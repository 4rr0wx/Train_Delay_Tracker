from sqlalchemy import Column, Integer, String, Boolean, DateTime, JSON, ForeignKey
from sqlalchemy.sql import func

from database import Base


class Station(Base):
    __tablename__ = "stations"

    id = Column(String(20), primary_key=True)
    name = Column(String(200), nullable=False)


class TrainObservation(Base):
    __tablename__ = "train_observations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    trip_id = Column(String(255), nullable=False)
    station_id = Column(String(20), ForeignKey("stations.id"))
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
    remarks = Column(JSON)
    first_seen_at = Column(DateTime(timezone=True), server_default=func.now())
    last_updated_at = Column(DateTime(timezone=True), server_default=func.now())
