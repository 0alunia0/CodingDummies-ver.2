"""
FastAPI - Endpoints and presentation layer

Satellite Orbit Tracking System - API Layer
Author: Aleks Czarnecki

Endpoints:
- /status - system status check
- /orbits/ - orbit management
- /satellites/ - orbital object management
- /satellites/{id}/position - position calculation
- /proximities - satellite proximity detection
"""

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict

from fastapi import FastAPI, Depends, HTTPException, Query, Request, Response, Path
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from satellite_models import (
    OrbitDBModel,
    ObjectDBModel,
    OrbitInputSchema,
    OrbitOutputSchema,
    ObjectInputSchema,
    ObjectOutputSchema,
    PositionOutputSchema,
    OrbitListSchema,
    ObjectListSchema,
    CollisionListSchema,
    CollisionEventSchema,
    SpaceEvent,
    GeodeticCoordinates,
    OrbitalParameters,
    ObjectType,
    get_db_session,
    EARTH_BASE_RADIUS,
    DEFAULT_PAGE_SIZE,
    MAX_ITEMS_PER_PAGE,
    PROXIMITY_TOLERANCE,
)
from satellite_services import (
    KeplerianPropagator,
    ISO8601Validator,
    TimeValidationError,
)

log = logging.getLogger(__name__)


# ===========================================================================================
# SERVICES 
# ===========================================================================================

class OrbitalCalculationService:
    """Service for orbital position calculations"""
    
    def __init__(self, propagator):
        self.propagator = propagator
        self.validator = ISO8601Validator()
        log.info(f"Initialized calculation service with propagator: {propagator.__class__.__name__}")
    
    def calculate_position_at_time(
        self,
        object_model: ObjectDBModel,
        timestamp: datetime
    ) -> Optional[GeodeticCoordinates]:
        """
        Calculates object position at specified time
        
        Args:
            object_model: Object model from database
            timestamp: Time moment for calculations
            
        Returns:
            Coordinates or None if object was not yet introduced
        """
        # Check if object was already introduced
        introduction_date = object_model.introduction_date
        if introduction_date.tzinfo is None:
            introduction_date = introduction_date.replace(tzinfo=timezone.utc)
        
        if timestamp < introduction_date:
            return None  # Object did not exist yet
        
        # Prepare orbital parameters
        orbit = object_model.orbit_ref
        params = OrbitalParameters(
            semi_major_axis=EARTH_BASE_RADIUS + orbit.altitude_km,
            inclination_deg=orbit.inclination_angle,
            ascending_node=orbit.ascending_node
        )
        
        # Calculate time from introduction
        time_delta = (timestamp - introduction_date).total_seconds()
        
        # Propagate position
        coordinates = self.propagator.propagate_position(
            params,
            time_delta,
            object_model.starting_lon_position
        )
        
        return coordinates


class EventAnalysisService:
    """Service for orbital event analysis (collisions, proximities)"""
    
    def __init__(self, calculation_service: OrbitalCalculationService):
        self.calculation_service = calculation_service
        self.detection_threshold = PROXIMITY_TOLERANCE
        log.info(f"Initialized event service with threshold: {self.detection_threshold} km")
    
    def parse_precision(self, precision_text: str) -> timedelta:
        """Parses precision string to timedelta"""
        pattern = r'^(\d+)(ms|s|m|h|d)$'
        match = re.match(pattern, precision_text)
        
        if not match:
            raise ValueError(f"Invalid precision format: {precision_text}")
        
        value = int(match.group(1))
        unit = match.group(2)
        
        if value < 1:
            raise ValueError("Precision value must be >= 1")
        
        mapping = {
            'ms': lambda v: timedelta(milliseconds=v),
            's': lambda v: timedelta(seconds=v),
            'm': lambda v: timedelta(minutes=v),
            'h': lambda v: timedelta(hours=v),
            'd': lambda v: timedelta(days=v)
        }
        
        return mapping[unit](value)
    
    def round_to_grid(self, dt: datetime, delta: timedelta) -> datetime:
        """Rounds datetime to nearest time grid"""
        timestamp = dt.timestamp()
        delta_sekund = delta.total_seconds()
        
        rounded = round(timestamp / delta_sekund) * delta_sekund
        
        return datetime.fromtimestamp(rounded, tz=timezone.utc)
    
    def detect_events_in_interval(
        self,
        objects,
        start_time: datetime,
        end_time: datetime,
        time_delta: timedelta
    ):
        """
        Detects events in time interval
        
        Args:
            objects: List of objects to analyze
            start_time: Interval start
            end_time: Interval end
            time_delta: Analysis time step
            
        Returns:
            List of detected events
        """
        events = []
        
        # Round boundaries to grid
        start_time = self.round_to_grid(start_time, time_delta)
        end_time = self.round_to_grid(end_time, time_delta)
        
        log.info(f"Starting event analysis from {start_time} to {end_time}")
        
        # Iterate over time grid
        current_time = start_time
        step_counter = 0
        
        while current_time <= end_time:
            # Calculate positions of all active objects
            positions_map: Dict[int, GeodeticCoordinates] = {}
            
            for obj in objects:
                if obj.operational_state != ObjectType.ACTIVE.value:
                    continue
                
                position = self.calculation_service.calculate_position_at_time(
                    obj,
                    current_time
                )
                
                if position is not None:
                    positions_map[obj.record_id] = position
            
            # Analyze object pairs
            active_ids = sorted(positions_map.keys())
            
            for i, id_a in enumerate(active_ids):
                for id_b in active_ids[i+1:]:
                    pos_a = positions_map[id_a]
                    pos_b = positions_map[id_b]
                    
                    distance = pos_a.distance_to(pos_b)
                    
                    if distance < self.detection_threshold:
                        event = SpaceEvent(
                            object_id_a=min(id_a, id_b),
                            object_id_b=max(id_a, id_b),
                            time_moment=current_time,
                            location=pos_a,
                            min_distance=distance
                        )
                        events.append(event)
                        
                        log.warning(
                            f"Proximity detected: {id_a} <-> {id_b} "
                            f"distance={distance:.6f}km at {current_time}"
                        )
            
            current_time += time_delta
            step_counter += 1
        
        log.info(f"Analysis completed. Analyzed {step_counter} steps, detected {len(events)} events")
        
        return events


# ===========================================================================================
# VALIDATORS AND HELPERS
# ===========================================================================================

def validate_positive_id(id_str: str) -> int:
    """Validates positive integer identifier"""
    try:
        id_val = int(id_str)
        if id_val <= 0:
            raise ValueError()
        return id_val
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid identifier format")


def validate_pagination_parameters(skipped: int, limit: int):
    """Validates pagination parameters"""
    if skipped < 0 or limit < 1 or limit > MAX_ITEMS_PER_PAGE:
        raise HTTPException(status_code=400, detail="Invalid pagination parameters")


# ===========================================================================================
# FASTAPI APPLICATION - Presentation layer
# ===========================================================================================

system_api = FastAPI(
    title="Satellite Orbit Tracking System",
    version="2.0.0",
    description="Orbital object management and tracking system"
)

# Middleware CORS
system_api.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Service initialization
main_propagator = KeplerianPropagator()
global_calculation_service = OrbitalCalculationService(main_propagator)
serwis_zdarzen_globalny = EventAnalysisService(global_calculation_service)


# ===========================================================================================
# EXCEPTION HANDLING
# ===========================================================================================

@system_api.exception_handler(RequestValidationError)
async def handle_validation_error(request: Request, exception: RequestValidationError):
    """Handles validation errors"""
    try:
        errors = exception.errors()
        
        for err in errors:
            loc = err.get('loc', [])
            if len(loc) >= 2 and loc[0] == 'path' and loc[1] == 'id':
                return JSONResponse(status_code=400, content={"detail": "Invalid identifier format"})
        
        if "/position" in str(request.url.path):
            for err in errors:
                loc = err.get('loc', [])
                if len(loc) >= 2 and loc[0] == 'query' and loc[1] == 'timestamp':
                    return JSONResponse(status_code=400, content={"detail": "Invalid identifier or timestamp"})
        
        if request.url.path == "/proximities":
            return JSONResponse(status_code=400, content={"detail": "Invalid format or date range"})
        
        return JSONResponse(status_code=400, content={"detail": "Invalid input data"})
    
    except Exception:
        return JSONResponse(status_code=400, content={"detail": "Invalid input data"})


# ===========================================================================================
# ENDPOINTS - Main
# ===========================================================================================

@system_api.get("/")
async def main_endpoint():
    """Main endpoint with system information"""
    return {
        "message": "Orbit Tracking System - API v2.0",
        "tocs": "/tocs",
        "status": "operational"
    }


@system_api.get("/status")
async def check_status():
    """System health check"""
    return {"status": "running", "timestamp": datetime.now(timezone.utc).isoformat()}


# ===========================================================================================
# ENDPOINTS - Orbits (CRUD)
# ===========================================================================================

@system_api.post("/orbits/", status_code=201, response_model=OrbitOutputSchema)
async def create_orbit(
    input_data: OrbitInputSchema,
    session: Session = Depends(get_db_session)
):
    """Creates new orbit in catalog"""
    # Check uniqueness
    existing = session.query(OrbitDBModel).filter(
        OrbitDBModel.orbit_identifier == input_data.name
    ).first()
    
    if existing:
        raise HTTPException(status_code=409, detail="Orbit name already exists")
    
    # Create record
    new_orbit = OrbitDBModel(
        orbit_identifier=input_data.name,
        altitude_km=input_data.altitude,
        inclination_angle=input_data.inclination,
        ascending_node=input_data.raan
    )
    
    session.add(new_orbit)
    session.commit()
    session.refresh(new_orbit)
    
    log.info(f"Created orbit: {input_data.name}")
    
    return OrbitOutputSchema.from_model(new_orbit)


@system_api.get("/orbits/{id}", response_model=OrbitOutputSchema)
async def get_orbit(
    resource_id: str = Path(alias="id"),
    session: Session = Depends(get_db_session)
):
    """Gets orbit by ID"""
    id_val = validate_positive_id(resource_id)
    
    orbit = session.query(OrbitDBModel).filter(
        OrbitDBModel.record_id == id_val
    ).first()
    
    if not orbit:
        raise HTTPException(status_code=404, detail="Orbit not found")
    
    return OrbitOutputSchema.from_model(orbit)


@system_api.get("/orbits/", response_model=OrbitListSchema)
async def list_orbits(
    skip: int = Query(0, ge=0),
    limit: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_ITEMS_PER_PAGE),
    name: Optional[str] = None,
    session: Session = Depends(get_db_session)
):
    """Lists orbits with filtering and pagination"""
    validate_pagination_parameters(skip, limit)
    
    query = session.query(OrbitDBModel)
    
    if name:
        query = query.filter(
            OrbitDBModel.orbit_identifier.ilike(f"%{name}%")
        )
    
    total = query.count()
    orbits = query.offset(skip).limit(limit).all()
    
    return OrbitListSchema(
        orbits=[OrbitOutputSchema.from_model(o) for o in orbits],
        total=total,
        skip=skip,
        limit=limit
    )


@system_api.put("/orbits/{id}", response_model=OrbitOutputSchema)
async def update_orbit(
    input_data: OrbitInputSchema,
    resource_id: str = Path(alias="id"),
    session: Session = Depends(get_db_session)
):
    """Updates orbit parameters"""
    id_val = validate_positive_id(resource_id)
    
    orbit = session.query(OrbitDBModel).filter(
        OrbitDBModel.record_id == id_val
    ).first()
    
    if not orbit:
        raise HTTPException(status_code=404, detail="Orbit not found")
    
    # Check name conflict
    conflict = session.query(OrbitDBModel).filter(
        OrbitDBModel.orbit_identifier == input_data.name,
        OrbitDBModel.record_id != id_val
    ).first()
    
    if conflict:
        raise HTTPException(status_code=409, detail="Orbit name already exists")
    
    # Update
    orbit.orbit_identifier = input_data.name
    orbit.altitude_km = input_data.altitude
    orbit.inclination_angle = input_data.inclination
    orbit.ascending_node = input_data.raan
    
    session.commit()
    session.refresh(orbit)
    
    log.info(f"Updated orbit ID={id_val}")
    
    return OrbitOutputSchema.from_model(orbit)


@system_api.delete("/orbits/{id}", status_code=204)
async def delete_orbit(
    resource_id: str = Path(alias="id"),
    session: Session = Depends(get_db_session)
):
    """Removes orbit from catalog"""
    id_val = validate_positive_id(resource_id)
    
    orbit = session.query(OrbitDBModel).filter(
        OrbitDBModel.record_id == id_val
    ).first()
    
    if not orbit:
        raise HTTPException(status_code=404, detail="Orbit not found")
    
    # Check associations
    associated_count = session.query(ObjectDBModel).filter(
        ObjectDBModel.associated_orbit_id == id_val
    ).count()
    
    if associated_count > 0:
        raise HTTPException(status_code=409, detail="Orbit is used by objects")
    
    session.delete(orbit)
    session.commit()
    
    log.info(f"Deleted orbit ID={id_val}")
    
    return Response(status_code=204)


# ===========================================================================================
# ENDPOINTS - Satellites (CRUD)
# ===========================================================================================

@system_api.post("/satellites/", status_code=201, response_model=ObjectOutputSchema)
async def create_object(
    input_data: ObjectInputSchema,
    session: Session = Depends(get_db_session)
):
    """Adds new orbital object to catalog"""
    try:
        # Check name uniqueness
        existing = session.query(ObjectDBModel).filter(
            ObjectDBModel.object_name == input_data.name
        ).first()
        
        if existing:
            raise HTTPException(status_code=409, detail="Object name already exists")
        
        # Check orbit existence
        orbit = session.query(OrbitDBModel).filter(
            OrbitDBModel.record_id == input_data.associated_orbit_id
        ).first()
        
        if not orbit:
            raise HTTPException(status_code=400, detail="Invalid orbit identifier")
        
        # Create object
        new_object = ObjectDBModel(
            object_name=input_data.name,
            system_operator=input_data.operator,
            introduction_date=input_data.launch_date,
            operational_state=input_data.status.value,
            starting_lon_position=input_data.starting_lon_position,
            associated_orbit_id=input_data.associated_orbit_id
        )
        
        session.add(new_object)
        session.commit()
        session.refresh(new_object)
        
        log.info(f"Created object: {input_data.name}")
        
        return ObjectOutputSchema.from_model(new_object)
    
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid identifier format or data")


@system_api.get("/satellites/{id}", response_model=ObjectOutputSchema)
async def get_object(
    resource_id: str = Path(alias="id"),
    session: Session = Depends(get_db_session)
):
    """Gets object by ID"""
    id_val = validate_positive_id(resource_id)
    
    obj = session.query(ObjectDBModel).filter(
        ObjectDBModel.record_id == id_val
    ).first()
    
    if not obj:
        raise HTTPException(status_code=404, detail="Satellite not found")
    
    return ObjectOutputSchema.from_model(obj)


@system_api.get("/satellites/", response_model=ObjectListSchema)
async def list_objects(
    skip: int = Query(0, ge=0),
    limit: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_ITEMS_PER_PAGE),
    operator: Optional[str] = None,
    session: Session = Depends(get_db_session)
):
    """Lists orbital objects with filtering"""
    validate_pagination_parameters(skip, limit)
    
    query = session.query(ObjectDBModel)
    
    if operator:
        query = query.filter(
            ObjectDBModel.system_operator.ilike(f"%{operator}%")
        )
    
    total = query.count()
    objects = query.offset(skip).limit(limit).all()
    
    return ObjectListSchema(
        satellites=[ObjectOutputSchema.from_model(o) for o in objects],
        total=total,
        skip=skip,
        limit=limit
    )


@system_api.put("/satellites/{id}", response_model=ObjectOutputSchema)
async def update_object(
    input_data: ObjectInputSchema,
    resource_id: str = Path(alias="id"),
    session: Session = Depends(get_db_session)
):
    """Updates orbital object parameters"""
    id_val = validate_positive_id(resource_id)
    
    obj = session.query(ObjectDBModel).filter(
        ObjectDBModel.record_id == id_val
    ).first()
    
    if not obj:
        raise HTTPException(status_code=404, detail="Satellite not found")
    
    # Check name conflict
    conflict = session.query(ObjectDBModel).filter(
        ObjectDBModel.object_name == input_data.name,
        ObjectDBModel.record_id != id_val
    ).first()
    
    if conflict:
        raise HTTPException(status_code=409, detail="Object name already exists")
    
    # Check orbit
    orbit = session.query(OrbitDBModel).filter(
        OrbitDBModel.record_id == input_data.associated_orbit_id
    ).first()
    
    if not orbit:
        raise HTTPException(status_code=400, detail="Invalid identifier format or data")
    
    # Update
    obj.object_name = input_data.name
    obj.system_operator = input_data.operator
    obj.introduction_date = input_data.launch_date
    obj.operational_state = input_data.status.value
    obj.starting_lon_position = input_data.starting_lon_position
    obj.associated_orbit_id = input_data.associated_orbit_id
    
    session.commit()
    session.refresh(obj)
    
    log.info(f"Updated object ID={id_val}")
    
    return ObjectOutputSchema.from_model(obj)


@system_api.delete("/satellites/{id}", status_code=204)
async def delete_object(
    resource_id: str = Path(alias="id"),
    session: Session = Depends(get_db_session)
):
    """Removes object from catalog"""
    id_val = validate_positive_id(resource_id)
    
    obj = session.query(ObjectDBModel).filter(
        ObjectDBModel.record_id == id_val
    ).first()
    
    if not obj:
        raise HTTPException(status_code=404, detail="Satellite not found")
    
    session.delete(obj)
    session.commit()
    
    log.info(f"Deleted object ID={id_val}")
    
    return Response(status_code=204)


# ===========================================================================================
# ENDPOINTS - Position calculations
# ===========================================================================================

@system_api.get("/satellites/{id}/position", response_model=PositionOutputSchema)
async def calculate_object_position(
    resource_id: str = Path(alias="id"),
    timestamp: str = Query(..., description="ISO-8601 UTC datetime"),
    session: Session = Depends(get_db_session)
):
    """Calculates object position at specified time"""
    try:
        # Validate ID
        id_val = validate_positive_id(resource_id)
        
        # Fetch object
        obj = session.query(ObjectDBModel).filter(
            ObjectDBModel.record_id == id_val
        ).first()
        
        if not obj:
            raise HTTPException(status_code=404, detail="Satellite not found")
    except HTTPException as e:
        if e.status_code == 400:
            raise HTTPException(status_code=400, detail="Invalid identifier or timestamp")
        raise
    
    # Validate timestamp
    try:
        validator = ISO8601Validator()
        timestamp_dt = validator.validate_timestamp(timestamp)
    except TimeValidationError:
        raise HTTPException(status_code=400, detail="Invalid timestamp format")
    
    # Check if timestamp is not before introduction
    introduction_date = obj.introduction_date
    if introduction_date.tzinfo is None:
        introduction_date = introduction_date.replace(tzinfo=timezone.utc)
    
    if timestamp_dt < introduction_date:
        raise HTTPException(status_code=400, detail="Timestamp before introduction date")
    
    # Calculate position
    coordinates = global_calculation_service.calculate_position_at_time(obj, timestamp_dt)
    
    if coordinates is None:
        raise HTTPException(status_code=400, detail="Cannot calculate position")
    
    return PositionOutputSchema(
        latitude=coordinates.latitude,
        longitude=coordinates.longitude,
        altitude=coordinates.altitude_asl
    )


# ===========================================================================================
# ENDPOINTS - Event analysis
# ===========================================================================================

@system_api.get("/proximities", response_model=CollisionListSchema)
async def detect_proximities(
    start_date: str = Query(..., description="Analysis start date (ISO-8601)"),
    end_date: str = Query(..., description="Analysis end date (ISO-8601)"),
    precision: str = Query("1m", description="Time precision (e.g. 1m, 5s, 1h)"),
    session: Session = Depends(get_db_session)
):
    """Detects satellite proximity locations (encounters) in time interval"""
    try:
        validator = ISO8601Validator()
        
        # Parse dates
        try:
            dt_start = validator.validate_timestamp(start_date)
            dt_end = validator.validate_timestamp(end_date)
        except TimeValidationError:
            raise HTTPException(status_code=400, detail="Invalid timestamp format")
        
        # Validate range
        if dt_start >= dt_end:
            raise HTTPException(status_code=400, detail="Invalid timestamp format")
        
        # Parse precision
        try:
            time_delta = serwis_zdarzen_globalny.parse_precision(precision)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid timestamp format")
        
        # Get all objects
        objects = session.query(ObjectDBModel).join(OrbitDBModel).all()
        
        # Detect events
        events = serwis_zdarzen_globalny.detect_events_in_interval(
            objects,
            dt_start,
            dt_end,
            time_delta
        )
        
        # Sort
        events.sort(key=lambda evt: (evt.time_moment, evt.object_id_a, evt.object_id_b))
        
        # Convert to schemas
        collisions_out = [
            CollisionEventSchema(
                satellite1=evt.object_id_a,
                satellite2=evt.object_id_b,
                time=evt.time_moment.strftime("%Y-%m-%dT%H:%M:%SZ"),
                position=PositionOutputSchema(
                    latitude=evt.location.latitude,
                    longitude=evt.location.longitude,
                    altitude=evt.location.altitude_asl
                ),
                distance=evt.distance_km
            )
            for evt in events
        ]
        
        return CollisionListSchema(proximities=collisions_out)
    
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid timestamp format")


# ===========================================================================================
# ENTRY POINT
# ===========================================================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(system_api, host="0.0.0.0", port=8000)
