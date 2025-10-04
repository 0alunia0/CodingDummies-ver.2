"""
SQLAlchemy/Pydantic - Data models and schemas

Satellite Orbit Tracking System - Data Layer
Author: Aleks Czarnecki

Contains:
- Database models (SQLAlchemy)
- Validation schemas (Pydantic)
- Dataclasses for orbital calculations
- Physical constants and configuration
"""

import logging
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Tuple, List

from pydantic import BaseModel, Field, validator
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from sqlalchemy.pool import StaticPool

# ===========================================================================================
# CONFIGURATION AND CONSTANTS
# ===========================================================================================

logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
log = logging.getLogger(__name__)

# Planetary and orbital constants
EARTH_GRAV_PARAMETER = 398600.4418  # km³/s² - standard gravitational parameter
EARTH_BASE_RADIUS = 6371.0  # km
PROXIMITY_TOLERANCE = 0.01  # km - event detection threshold
NUMERICAL_EPSILON = 1e-9  # for floating-point comparisons

# System operational limits
MAX_ITEMS_PER_PAGE = 100
DEFAULT_PAGE_SIZE = 10
MINIMUM_ORBIT_ALTITUDE = 160.0  # km above sea level
MAXIMUM_ORBIT_ALTITUDE = 40000.0  # km


# ===========================================================================================
# ENUMERATION TYPES
# ===========================================================================================

class ObjectType(str, Enum):
    """Classification of orbital objects"""
    ACTIVE = "active"
    INACTIVE = "inactive"
    DEORBITED = "deorbited"


class PrecisionCategory(str, Enum):
    """Time precision categories for calculations"""
    MILLISECONDS = "ms"
    SECONDS = "s"
    MINUTES = "m"
    HOURS = "h"
    DAYS = "d"


# ===========================================================================================
# DATACLASSES - Domain data structures
# ===========================================================================================

@dataclass
class GeodeticCoordinates:
    """Geodetic coordinates of an object in space"""
    latitude: float  # latitude [-90, 90]
    longitude: float  # longitude [-180, 180]
    altitude_asl: float  # altitude above sea level [km]
    
    def to_cartesian(self) -> Tuple[float, float, float]:
        """Conversion to Cartesian ECEF coordinates"""
        total_radius = EARTH_BASE_RADIUS + self.altitude_asl
        
        lat_rad = math.radians(self.latitude)
        lon_rad = math.radians(self.longitude)
        
        x_ecef = total_radius * math.cos(lat_rad) * math.cos(lon_rad)
        y_ecef = total_radius * math.cos(lat_rad) * math.sin(lon_rad)
        z_ecef = total_radius * math.sin(lat_rad)
        
        return x_ecef, y_ecef, z_ecef
    
    def distance_to(self, other: 'GeodeticCoordinates') -> float:
        """Calculates 3D distance to other coordinates"""
        x1, y1, z1 = self.to_cartesian()
        x2, y2, z2 = other.to_cartesian()
        
        return math.sqrt((x2 - x1)**2 + (y2 - y1)**2 + (z2 - z1)**2)


@dataclass
class OrbitalParameters:
    """Keplerian parameters describing an orbit"""
    semi_major_axis: float  # semi-major axis [km]
    inclination_deg: float  # inclination [degrees]
    ascending_node: float  # RAAN - Right Ascension of Ascending Node [degrees]
    
    def calculate_orbital_period(self) -> float:
        """Calculates orbital period T = 2Pi*sqrt(a3/μ)"""
        return 2 * math.pi * math.sqrt(
            self.semi_major_axis**3 / EARTH_GRAV_PARAMETER
        )
    
    def calculate_angular_velocity(self) -> float:
        """Calculates angular velocity omega = 2Pi/T"""
        T = self.calculate_orbital_period()
        return 2 * math.pi / T if T > NUMERICAL_EPSILON else 0.0


@dataclass
class SpaceEvent:
    """Space event - e.g. object proximity"""
    object_id_a: int
    object_id_b: int
    time_moment: datetime
    location: GeodeticCoordinates
    min_distance: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        """Export to dictionary"""
        return {
            "satellite1": self.object_id_a,
            "satellite2": self.object_id_b,
            "time": self.time_moment.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "position": {
                "latitude": self.location.latitude,
                "longitude": self.location.longitude,
                "altitude": self.location.altitude_asl
            },
            "distance": self.min_distance
        }


# ===========================================================================================
# DATABASE MODELS - SQLAlchemy
# ===========================================================================================

# Database engine
db_engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool
)

SessionFactory = sessionmaker(autocommit=False, autoflush=False, bind=db_engine)
Base = declarative_base()


class OrbitDBModel(Base):
    """Database model for orbits"""
    __tablename__ = "orb_catalog"
    
    record_id = Column(Integer, primary_key=True, index=True)
    orbit_identifier = Column(String(100), unique=True, nullable=False, index=True)
    altitude_km = Column(Float, nullable=False)
    inclination_angle = Column(Float, nullable=False)
    ascending_node = Column(Float, nullable=False)
    
    # Relationships
    associated_objects = relationship("ObjectDBModel", back_populates="orbit_ref")


class ObjectDBModel(Base):
    """Database model for orbital objects"""
    __tablename__ = "obj_catalog"
    
    record_id = Column(Integer, primary_key=True, index=True)
    object_name = Column(String(100), unique=True, nullable=False, index=True)
    system_operator = Column(String(50), nullable=False)
    introduction_date = Column(DateTime, nullable=False)
    operational_state = Column(String(20), nullable=False, default="active")
    starting_lon_position = Column(Float, nullable=False)
    associated_orbit_id = Column(Integer, ForeignKey("orb_catalog.record_id"), nullable=False)
    creation_timestamp = Column(DateTime, nullable=False, default=datetime.utcnow)
    
    # Relationships
    orbit_ref = relationship("OrbitDBModel", back_populates="associated_objects")


# Create tables
Base.metadata.create_all(bind=db_engine)


def get_db_session():
    """Dependency injection for database session"""
    session = SessionFactory()
    try:
        yield session
    finally:
        session.close()


# ===========================================================================================
# PYDANTIC SCHEMAS - API data validation
# ===========================================================================================

class OrbitInputSchema(BaseModel):
    """Input schema for creating an orbit"""
    name: str = Field(..., min_length=1, max_length=100)
    altitude: float = Field(..., gt=MINIMUM_ORBIT_ALTITUDE, le=MAXIMUM_ORBIT_ALTITUDE)
    inclination: float = Field(..., ge=0, le=180)
    raan: float = Field(..., ge=0, lt=360)
    
    class Config:
        """Pydantic schema configuration"""
        populate_by_name = True


class OrbitOutputSchema(BaseModel):
    """Output schema for orbit"""
    id: int
    name: str
    altitude: float
    inclination: float
    node: float
    
    class Config:
        """Pydantic schema configuration"""
        from_attributes = True
        populate_by_name = True
    
    @classmethod
    def from_model(cls, model: OrbitDBModel):
        """Conversion from DB model"""
        return cls(
            id=model.record_id,
            name=model.orbit_identifier,
            altitude=model.altitude_km,
            inclination=model.inclination_angle,
            node=model.ascending_node
        )


class ObjectInputSchema(BaseModel):
    """Input schema for orbital object"""
    name: str = Field(..., min_length=1, max_length=100)
    operator: str = Field(..., min_length=1, max_length=50)
    launch_date: datetime
    status: ObjectType = Field(default=ObjectType.ACTIVE)
    starting_lon_position: float = Field(..., ge=-180, le=180)
    associated_orbit_id: int
    
    class Config:
        """Pydantic schema configuration"""
        populate_by_name = True
    
    @validator('launch_date', pre=True)
    @classmethod
    def validate_launch_date(cls, value):
        """Validates launch date"""
        import dateutil.parser as dp
        
        if isinstance(value, str):
            dt = dp.isoparse(value)
        elif isinstance(value, datetime):
            dt = value
        else:
            raise ValueError(f"Invalid date type: {type(value)}")
        
        # Ensure UTC
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        
        if dt >= datetime.now(timezone.utc):
            raise ValueError('Introduction date must be in the past')
        
        return dt


class ObjectOutputSchema(BaseModel):
    """Output schema for object"""
    id: int
    name: str
    operator: str
    launch_date: str
    status: str
    initial_longitude: float
    orbit_id: int
    
    class Config:
        """Pydantic schema configuration"""
        from_attributes = True
    
    @classmethod
    def from_model(cls, model: ObjectDBModel):
        """Conversion from DB model"""
        return cls(
            id=model.record_id,
            name=model.object_name,
            operator=model.system_operator,
            launch_date=model.introduction_date.strftime("%Y-%m-%dT%H:%M:%SZ"),
            status=model.operational_state,
            initial_longitude=model.starting_lon_position,
            orbit_id=model.associated_orbit_id
        )


class PositionOutputSchema(BaseModel):
    """Schema for object position"""
    latitude: float
    longitude: float
    altitude: float


class OrbitListSchema(BaseModel):
    """List of orbits with pagination metadata"""
    orbits: List[OrbitOutputSchema]
    total: int
    skip: int
    limit: int


class ObjectListSchema(BaseModel):
    """List of objects with pagination metadata"""
    satellites: List[ObjectOutputSchema]
    total: int
    skip: int
    limit: int


class CollisionEventSchema(BaseModel):
    """Schema for satellite proximity event (orbit encounter)"""
    satellite1: int = Field(description="ID of first object in proximity")
    satellite2: int = Field(description="ID of second object in proximity")
    time: str = Field(description="Moment of proximity (ISO-8601)")
    position: PositionOutputSchema = Field(description="Coordinates of proximity location")
    distance: float = Field(description="Distance between objects in kilometers")


class CollisionListSchema(BaseModel):
    """List of detected proximities between satellites"""
    proximities: List[CollisionEventSchema] = Field(description="Detected orbit proximities")
