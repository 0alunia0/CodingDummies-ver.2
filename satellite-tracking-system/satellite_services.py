"""
Propagators/Validators - Business logic and calculations

Satellite Orbit Tracking System - Services Layer
Author: Aleks Czarnecki

Contains:
- Orbital propagators (Keplerian)
- Data validators (ISO8601, range)
- Satellite position calculation algorithms
- Patterns: Strategy Pattern, Service Layer
"""

import logging
import math
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import List, Optional

import dateutil.parser
from sqlalchemy.orm import Session

from satellite_models import (
    GeodeticCoordinates,
    OrbitalParameters,
    SpaceEvent,
    OrbitDBModel,
    ObjectDBModel,
    PrecisionCategory,
    EARTH_BASE_RADIUS,
    PROXIMITY_TOLERANCE,
    NUMERICAL_EPSILON
)

log = logging.getLogger(__name__)


# ===========================================================================================
# DOMAIN EXCEPTIONS
# ===========================================================================================

class TimeValidationError(ValueError):
    """Time format validation error"""


class OrbitalCalculationError(RuntimeError):
    """Error in orbital calculations"""


class ResourceNotFoundError(RuntimeError):
    """Resource not found in database"""



# ===========================================================================================
# ABSTRACT CLASSES - Strategy Pattern
# ===========================================================================================

class OrbitPropagator(ABC):
    """Abstract base class for orbit propagators"""
    
    @abstractmethod
    def calculate_position(
        self,
        orbit_params: OrbitalParameters,
        moment: datetime,
        initial_longitude: float,
        start_date: datetime
    ) -> GeodeticCoordinates:
        """Calculates object position at given moment"""


class TimeValidator(ABC):
    """Abstract base class for time validators"""
    
    @abstractmethod
    def validate_timestamp(self, timestamp: str) -> datetime:
        """Validates and parses timestamp"""


# ===========================================================================================
# PROPAGATOR IMPLEMENTATIONS
# ===========================================================================================

class KeplerianPropagator(OrbitPropagator):
    """Orbit propagator using simplified Keplerian model"""
    
    def __init__(self):
        self.name = "Keplerian Circular Propagator"
        log.debug(f"Initialized propagator: {self.name}")
    
    def propagate_position(
        self,
        parameters: OrbitalParameters,
        time_from_epoch: float,
        initial_longitude: float
    ) -> GeodeticCoordinates:
        """
        Position propagation using Keplerian method
        
        Args:
            parameters: Object orbital parameters
            time_from_epoch: Time from initial epoch [seconds]
            initial_longitude: Initial geographic longitude [degrees]
        
        Returns:
            Geodetic coordinates at given moment
        """
        # Convert angles to radians
        inclination_rad = math.radians(parameters.inclination_deg)
        raan_rad = math.radians(parameters.ascending_node)
        initial_lon_rad = math.radians(initial_longitude)
        
        # Calculate true anomaly
        angular_omega = parameters.calculate_angular_velocity()
        true_anomaly = (angular_omega * time_from_epoch + initial_lon_rad) % (2 * math.pi)
        
        # Calculate coordinates in orbital plane
        orbital_lat = math.asin(math.sin(inclination_rad) * math.sin(true_anomaly))
        
        # Calculate geographic longitude
        longitude_coord = math.atan2(
            math.cos(inclination_rad) * math.sin(true_anomaly),
            math.cos(true_anomaly)
        ) + raan_rad
        
        # Convert back to degrees and normalize
        geo_lat = math.degrees(orbital_lat)
        geo_lon = self._normalize_longitude(math.degrees(longitude_coord))
        
        # Altitude is orbit radius minus Earth radius
        altitude = parameters.semi_major_axis - EARTH_BASE_RADIUS
        
        return GeodeticCoordinates(
            latitude=geo_lat,
            longitude=geo_lon,
            altitude_asl=altitude
        )
    
    @staticmethod
    def _normalize_longitude(longitude_deg: float) -> float:
        """Normalizes longitude to range [-180, 180]"""
        normalized = ((longitude_deg + 180) % 360) - 180
        return normalized
    
    # Implementation of abstract method
    def calculate_position(
        self,
        orbit_params: OrbitalParameters,
        moment: datetime,
        initial_longitude: float,
        start_date: datetime
    ) -> GeodeticCoordinates:
        """Calculates object position at given moment"""
        
        if not isinstance(moment, datetime) or not isinstance(start_date, datetime):
            raise OrbitalCalculationError("Invalid date format")
        
        # Ensure timezone-aware datetime
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
        if start_date.tzinfo is None:
            start_date = start_date.replace(tzinfo=timezone.utc)
        
        # Time elapsed from start [seconds]
        delta_t = (moment - start_date).total_seconds()
        
        if delta_t < 0:
            raise OrbitalCalculationError(
                "Calculation moment cannot be earlier than start date"
            )
        
        # Angular velocity
        omega = orbit_params.calculate_angular_velocity()
        if abs(omega) < NUMERICAL_EPSILON:
            raise OrbitalCalculationError("Angular velocity too low")
        
        # Use propagate_position
        return self.propagate_position(orbit_params, delta_t, initial_longitude)




# ===========================================================================================
# VALIDATORS
# ===========================================================================================

class ISO8601Validator(TimeValidator):
    """ISO 8601 format validator"""
    
    def validate_timestamp(self, timestamp: str) -> datetime:
        """Parses and validates timestamp in ISO 8601 format"""
        try:
            dt = dateutil.parser.isoparse(timestamp)
            
            # Ensure timezone-aware datetime
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            
            return dt
            
        except (ValueError, TypeError) as e:
            raise TimeValidationError(
                f"Invalid time format: {timestamp}. "
                f"Expected ISO 8601 (e.g. '2024-01-15T10:30:00Z'). Error: {e}"
            ) from e


# ===========================================================================================
# BUSINESS SERVICES
# ===========================================================================================

class OrbitalCalculationService:
    """Service for orbital object position calculations"""
    
    def __init__(self, propagator: OrbitPropagator, validator: TimeValidator):
        """Initialize service with chosen propagation strategy"""
        self.propagator = propagator
        self.validator = validator
    
    def calculate_object_position(
        self,
        db_session: Session,
        object_id: int,
        timestamp: str
    ) -> GeodeticCoordinates:
        """Calculates object position at given time"""
        
        # Time validation
        moment = self.validator.validate_timestamp(timestamp)
        
        # Retrieve object and its orbit
        obj = db_session.query(ObjectDBModel).filter_by(record_id=object_id).first()
        if not obj:
            raise ResourceNotFoundError(f"Object with ID {object_id} does not exist")
        
        orbit = db_session.query(OrbitDBModel).filter_by(record_id=obj.associated_orbit_id).first()
        if not orbit:
            raise ResourceNotFoundError(f"Orbit of object {object_id} does not exist")
        
        # Convert to orbital parameters
        params = OrbitalParameters(
            semi_major_axis=orbit.altitude_km + EARTH_BASE_RADIUS,
            inclination_deg=orbit.inclination_angle,
            ascending_node=orbit.ascending_node
        )
        
        # Calculate position
        return self.propagator.calculate_position(
            orbit_params=params,
            moment=moment,
            initial_longitude=obj.starting_lon_position,
            start_date=obj.introduction_date
        )


class EventAnalysisService:
    """Service for detecting events in outer space"""
    
    def __init__(
        self,
        calculation_service: OrbitalCalculationService,
        proximity_threshold: float = PROXIMITY_TOLERANCE
    ):
        """Initialize analysis service"""
        self.calculation_service = calculation_service
        self.proximity_threshold = proximity_threshold
    
    def detect_collisions(
        self,
        db_session: Session,
        timestamp: str,
        orbit_filter: Optional[int] = None
    ) -> List[SpaceEvent]:
        """Detects potential collisions between objects"""
        
        # Get all active objects
        query = db_session.query(ObjectDBModel).filter_by(operational_state="active")
        
        if orbit_filter:
            query = query.filter_by(associated_orbit_id=orbit_filter)
        
        objects = query.all()
        
        if len(objects) < 2:
            return []
        
        # Calculate positions of all objects
        positions = {}
        for obj in objects:
            try:
                pos = self.calculation_service.calculate_object_position(
                    db_session=db_session,
                    object_id=obj.record_id,
                    timestamp=timestamp
                )
                positions[obj.record_id] = pos
            except Exception as e:
                log.warning(f"Error calculating position for object {obj.record_id}: {e}")
                continue
        
        # Detect proximities
        events = []
        ids = list(positions.keys())
        
        for i, id_a in enumerate(ids):
            for j in range(i + 1, len(ids)):
                id_b = ids[j]
                pos_a, pos_b = positions[id_a], positions[id_b]
                
                distance = pos_a.distance_to(pos_b)
                
                if distance <= self.proximity_threshold:
                    # Use midpoint between positions as event location
                    avg_lat = (pos_a.latitude + pos_b.latitude) / 2
                    avg_lon = (pos_a.longitude + pos_b.longitude) / 2
                    avg_alt = (pos_a.altitude_asl + pos_b.altitude_asl) / 2
                    
                    moment = self.calculation_service.validator.validate_timestamp(timestamp)
                    
                    event = SpaceEvent(
                        object_id_a=id_a,
                        object_id_b=id_b,
                        time_moment=moment,
                        location=GeodeticCoordinates(avg_lat, avg_lon, avg_alt),
                        min_distance=distance
                    )
                    events.append(event)
        
        return events


# ===========================================================================================
# HELPER FUNCTIONS
# ===========================================================================================

def calculate_time_difference(
    start_time: datetime,
    end_time: datetime,
    category: PrecisionCategory = PrecisionCategory.SECONDS
) -> float:
    """Calculates time difference in specified unit"""
    
    if start_time.tzinfo is None:
        start_time = start_time.replace(tzinfo=timezone.utc)
    if end_time.tzinfo is None:
        end_time = end_time.replace(tzinfo=timezone.utc)
    
    delta = end_time - start_time
    seconds = delta.total_seconds()
    
    conversions = {
        PrecisionCategory.MILLISECONDS: lambda s: s * 1000,
        PrecisionCategory.SECONDS: lambda s: s,
        PrecisionCategory.MINUTES: lambda s: s / 60,
        PrecisionCategory.HOURS: lambda s: s / 3600,
        PrecisionCategory.DAYS: lambda s: s / 86400
    }
    
    return conversions[category](seconds)


def validate_orbital_parameters(altitude: float, inclination: float, raan: float) -> bool:
    """Validates orbital parameters"""
    from satellite_models import MINIMUM_ORBIT_ALTITUDE, MAXIMUM_ORBIT_ALTITUDE
    
    if not (MINIMUM_ORBIT_ALTITUDE <= altitude <= MAXIMUM_ORBIT_ALTITUDE):
        return False
    
    if not (0 <= inclination <= 180):
        return False
    
    if not (0 <= raan < 360):
        return False
    
    return True
