from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, CheckConstraint, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func

from database import Base


class Station(Base):
    __tablename__ = "stations"

    id = Column(String(20), primary_key=True)
    name = Column(String(200), nullable=False)


class TrainObservation(Base):
    __tablename__ = "train_observations"
    __table_args__ = (
        UniqueConstraint("trip_id", "station_id", name="train_observations_trip_id_station_id_key"),
        CheckConstraint("direction IN ('to_wien', 'to_ternitz')", name="train_observations_direction_check"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    trip_id = Column(String(255), nullable=False)
    station_id = Column(String(20), ForeignKey("stations.id"), nullable=False)
    direction = Column(String(10), nullable=False)
    train_number = Column(String(50))
    line_name = Column(String(100))
    line_product = Column(String(50))
    destination = Column(String(200))
    planned_time = Column(DateTime(timezone=True), nullable=False)
    actual_time = Column(DateTime(timezone=True))
    delay_seconds = Column(Integer)
    cancelled = Column(Boolean, default=False)
    platform = Column(String(20))
    remarks = Column(JSONB)
    first_seen_at = Column(DateTime(timezone=True), server_default=func.now())
    last_updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
