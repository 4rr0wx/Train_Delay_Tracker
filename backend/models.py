"""
V2 SQLAlchemy models for Train Delay Tracker.

Table dependency order (matches Alembic migration 0001):
  1.  stations
  2.  lines
  3.  service_days
  4.  routes           (→ lines)
  5.  route_legs       (→ routes, stations)
  6.  trips            (→ lines, routes, service_days)
  7.  trip_stops       (→ trips, stations)
  8.  commute_slots    (→ routes, stations)
  9.  connections      (→ trips, service_days, commute_slots, stations)
  10. remarks          (polymorphic: trip or trip_stop)
  11. collection_runs
  12. api_errors        (→ collection_runs, stations)
"""

from __future__ import annotations

import enum

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    Date,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    TIMESTAMP,
    Text,
    Time,
    UniqueConstraint,
)

TIMESTAMPTZ = TIMESTAMP(timezone=True)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from database import Base


# ---------------------------------------------------------------------------
# Python-side enums (mirrored as PostgreSQL ENUMs in the migration)
# ---------------------------------------------------------------------------

class TripStatus(enum.Enum):
    scheduled           = "scheduled"
    active              = "active"
    delayed             = "delayed"
    cancelled           = "cancelled"
    partially_cancelled = "partially_cancelled"
    completed           = "completed"
    unknown             = "unknown"


class TripDirection(enum.Enum):
    to_wien    = "to_wien"
    to_ternitz = "to_ternitz"


class CollectionRunStatus(enum.Enum):
    running   = "running"
    completed = "completed"
    partial   = "partial"
    failed    = "failed"


# ---------------------------------------------------------------------------
# 1. stations
# ---------------------------------------------------------------------------

class Station(Base):
    __tablename__ = "stations"

    id           = Column(String(20), primary_key=True)
    name         = Column(String(200), nullable=False)
    short_name   = Column(String(50))
    station_type = Column(
        String(30),
        nullable=False,
        default="train",
        # CHECK enforced in DB via migration
    )
    latitude     = Column(Numeric(9, 6))
    longitude    = Column(Numeric(9, 6))
    timezone     = Column(String(50), nullable=False, default="Europe/Vienna")
    is_active    = Column(Boolean, nullable=False, default=True)
    created_at   = Column(TIMESTAMPTZ, nullable=False, server_default=func.now())
    updated_at   = Column(TIMESTAMPTZ, nullable=False, server_default=func.now(),
                          onupdate=func.now())

    # Relationships
    trip_stops        = relationship("TripStop", back_populates="station")
    route_legs        = relationship("RouteLeg", back_populates="station")
    api_errors        = relationship("ApiError", back_populates="station")

    __table_args__ = (
        CheckConstraint(
            "station_type IN ('train', 'subway', 'tram', 'bus', 'mixed')",
            name="ck_station_type",
        ),
    )


# ---------------------------------------------------------------------------
# 2. lines
# ---------------------------------------------------------------------------

class Line(Base):
    __tablename__ = "lines"

    id           = Column(Integer, primary_key=True, autoincrement=True)
    code         = Column(String(20), nullable=False, unique=True)
    display_name = Column(String(100), nullable=False)
    operator     = Column(String(100), nullable=False)
    product_type = Column(String(30), nullable=False)
    color_hex    = Column(String(7))
    is_active    = Column(Boolean, nullable=False, default=True)
    notes        = Column(Text)
    created_at   = Column(TIMESTAMPTZ, nullable=False, server_default=func.now())
    updated_at   = Column(TIMESTAMPTZ, nullable=False, server_default=func.now(),
                          onupdate=func.now())

    # Relationships
    trips  = relationship("Trip", back_populates="line")
    routes = relationship("Route", back_populates="line")

    __table_args__ = (
        CheckConstraint(
            "product_type IN ('regional', 'suburban', 'subway', 'tram', 'bus', "
            "'nationalExpress', 'national', 'ferry')",
            name="ck_line_product_type",
        ),
    )


# ---------------------------------------------------------------------------
# 3. service_days
# ---------------------------------------------------------------------------

class ServiceDay(Base):
    __tablename__ = "service_days"

    service_date        = Column(Date, primary_key=True)
    is_weekday          = Column(Boolean, nullable=False)
    day_of_week         = Column(SmallInteger, nullable=False)  # 0=Mon … 6=Sun (ISO)
    is_austrian_holiday = Column(Boolean, nullable=False, default=False)
    holiday_name        = Column(String(200))
    is_school_day       = Column(Boolean)  # NULL = unknown
    notes               = Column(Text)
    created_at          = Column(TIMESTAMPTZ, nullable=False, server_default=func.now())

    # Relationships
    trips = relationship("Trip", back_populates="service_day_ref")

    __table_args__ = (
        CheckConstraint("day_of_week BETWEEN 0 AND 6", name="ck_service_day_dow"),
    )


# ---------------------------------------------------------------------------
# 4. routes
# ---------------------------------------------------------------------------

class Route(Base):
    __tablename__ = "routes"

    id          = Column(Integer, primary_key=True, autoincrement=True)
    name        = Column(String(200), nullable=False, unique=True)
    line_id     = Column(Integer, ForeignKey("lines.id"), nullable=False)
    direction   = Column(String(20), nullable=False)
    description = Column(Text)
    is_active   = Column(Boolean, nullable=False, default=True)
    created_at  = Column(TIMESTAMPTZ, nullable=False, server_default=func.now())
    updated_at  = Column(TIMESTAMPTZ, nullable=False, server_default=func.now(),
                         onupdate=func.now())

    # Relationships
    line          = relationship("Line", back_populates="routes")
    route_legs    = relationship("RouteLeg", back_populates="route",
                                 order_by="RouteLeg.stop_sequence",
                                 cascade="all, delete-orphan")
    commute_slots = relationship("CommuteSlot", back_populates="route")

    __table_args__ = (
        UniqueConstraint("line_id", "direction", name="uq_route_line_direction"),
        CheckConstraint(
            "direction IN ('to_wien', 'to_ternitz', 'inbound', 'outbound', "
            "'northbound', 'southbound')",
            name="ck_route_direction",
        ),
    )


# ---------------------------------------------------------------------------
# 5. route_legs
# ---------------------------------------------------------------------------

class RouteLeg(Base):
    __tablename__ = "route_legs"

    id                               = Column(Integer, primary_key=True, autoincrement=True)
    route_id                         = Column(Integer, ForeignKey("routes.id", ondelete="CASCADE"),
                                              nullable=False)
    stop_sequence                    = Column(Integer, nullable=False)
    station_id                       = Column(String(20), ForeignKey("stations.id"), nullable=False)
    is_origin                        = Column(Boolean, nullable=False, default=False)
    is_destination                   = Column(Boolean, nullable=False, default=False)
    typical_travel_minutes_from_prev = Column(Integer)
    poll_window_before_minutes       = Column(Integer, nullable=False, default=10)
    poll_window_after_minutes        = Column(Integer, nullable=False, default=30)

    # Relationships
    route   = relationship("Route", back_populates="route_legs")
    station = relationship("Station", back_populates="route_legs")

    __table_args__ = (
        UniqueConstraint("route_id", "stop_sequence", name="uq_route_leg_sequence"),
        UniqueConstraint("route_id", "station_id", name="uq_route_leg_station"),
    )


# ---------------------------------------------------------------------------
# 6. trips
# ---------------------------------------------------------------------------

class Trip(Base):
    __tablename__ = "trips"

    id                       = Column(BigInteger, primary_key=True, autoincrement=True)
    api_trip_id              = Column(String(255), nullable=False)
    service_date             = Column(Date, ForeignKey("service_days.service_date"), nullable=False)
    line_id                  = Column(Integer, ForeignKey("lines.id"), nullable=False)
    route_id                 = Column(Integer, ForeignKey("routes.id"), nullable=True)
    direction                = Column(Enum(TripDirection, name="trip_direction"), nullable=False)
    train_number             = Column(String(50))
    destination_name         = Column(String(200))
    origin_name              = Column(String(200))
    status                   = Column(
        Enum(TripStatus, name="trip_status"),
        nullable=False,
        default=TripStatus.unknown,
    )
    is_diverted              = Column(Boolean, nullable=False, default=False)
    first_seen_at            = Column(TIMESTAMPTZ, nullable=False, server_default=func.now())
    last_updated_at          = Column(TIMESTAMPTZ, nullable=False, server_default=func.now(),
                                      onupdate=func.now())
    completed_at             = Column(TIMESTAMPTZ)
    planned_origin_departure = Column(TIMESTAMPTZ)

    # Relationships
    line            = relationship("Line", back_populates="trips")
    route           = relationship("Route")
    service_day_ref = relationship("ServiceDay", back_populates="trips")
    trip_stops      = relationship("TripStop", back_populates="trip",
                                   order_by="TripStop.stop_sequence",
                                   cascade="all, delete-orphan")
    connections_as_leg1 = relationship(
        "Connection",
        foreign_keys="Connection.leg1_trip_id",
        back_populates="leg1_trip",
    )
    connections_as_leg2 = relationship(
        "Connection",
        foreign_keys="Connection.leg2_trip_id",
        back_populates="leg2_trip",
    )

    __table_args__ = (
        UniqueConstraint("api_trip_id", "service_date", name="uq_trip_api_id_date"),
        Index("idx_trips_service_date", "service_date"),
        Index("idx_trips_line_id", "line_id"),
        Index("idx_trips_direction", "direction"),
        Index("idx_trips_status", "status"),
        Index("idx_trips_api_trip_id", "api_trip_id"),
        Index("idx_trips_line_direction_date", "line_id", "direction", "service_date"),
    )


# ---------------------------------------------------------------------------
# 7. trip_stops
# ---------------------------------------------------------------------------

class TripStop(Base):
    __tablename__ = "trip_stops"

    id                      = Column(BigInteger, primary_key=True, autoincrement=True)
    trip_id                 = Column(BigInteger, ForeignKey("trips.id", ondelete="CASCADE"),
                                     nullable=False)
    station_id              = Column(String(20), ForeignKey("stations.id"), nullable=False)
    stop_sequence           = Column(Integer)
    planned_arrival         = Column(TIMESTAMPTZ)
    planned_departure       = Column(TIMESTAMPTZ)
    actual_arrival          = Column(TIMESTAMPTZ)
    actual_departure        = Column(TIMESTAMPTZ)
    arrival_delay_seconds   = Column(Integer)
    departure_delay_seconds = Column(Integer)
    cancelled_at_stop       = Column(Boolean, nullable=False, default=False)
    platform                = Column(String(20))
    platform_changed        = Column(Boolean, nullable=False, default=False)
    first_seen_at           = Column(TIMESTAMPTZ, nullable=False, server_default=func.now())
    last_updated_at         = Column(TIMESTAMPTZ, nullable=False, server_default=func.now(),
                                     onupdate=func.now())

    # Relationships
    trip    = relationship("Trip", back_populates="trip_stops")
    station = relationship("Station", back_populates="trip_stops")
    remarks = relationship(
        "Remark",
        primaryjoin="and_(Remark.entity_type=='trip_stop', foreign(Remark.entity_id)==TripStop.id)",
        viewonly=True,
    )

    __table_args__ = (
        UniqueConstraint("trip_id", "station_id", name="uq_trip_stop"),
        Index("idx_trip_stops_trip_id", "trip_id"),
        Index("idx_trip_stops_station_id", "station_id"),
        Index("idx_trip_stops_planned_dep", "planned_departure"),
        Index("idx_trip_stops_station_planned_dep", "station_id", "planned_departure"),
    )

    @property
    def effective_delay_seconds(self) -> int | None:
        """Prefer departure delay (origin/intermediate), fall back to arrival (destination)."""
        if self.departure_delay_seconds is not None:
            return self.departure_delay_seconds
        return self.arrival_delay_seconds


# ---------------------------------------------------------------------------
# 8. commute_slots
# ---------------------------------------------------------------------------

class CommuteSlot(Base):
    __tablename__ = "commute_slots"

    id                     = Column(Integer, primary_key=True, autoincrement=True)
    name                   = Column(String(100), nullable=False, unique=True)
    route_id               = Column(Integer, ForeignKey("routes.id"), nullable=False)
    direction              = Column(Enum(TripDirection, name="trip_direction"), nullable=False)
    anchor_time_local      = Column(Time, nullable=False)
    anchor_station_id      = Column(String(20), ForeignKey("stations.id"), nullable=False)
    time_tolerance_minutes = Column(Integer, nullable=False, default=2)
    applies_monday         = Column(Boolean, nullable=False, default=True)
    applies_tuesday        = Column(Boolean, nullable=False, default=True)
    applies_wednesday      = Column(Boolean, nullable=False, default=True)
    applies_thursday       = Column(Boolean, nullable=False, default=True)
    applies_friday         = Column(Boolean, nullable=False, default=True)
    applies_saturday       = Column(Boolean, nullable=False, default=False)
    applies_sunday         = Column(Boolean, nullable=False, default=False)
    is_active              = Column(Boolean, nullable=False, default=True)
    notes                  = Column(Text)
    created_at             = Column(TIMESTAMPTZ, nullable=False, server_default=func.now())

    # Relationships
    route          = relationship("Route", back_populates="commute_slots")
    anchor_station = relationship("Station", foreign_keys=[anchor_station_id])
    connections    = relationship("Connection", back_populates="commute_slot")


# ---------------------------------------------------------------------------
# 9. connections
# ---------------------------------------------------------------------------

class Connection(Base):
    __tablename__ = "connections"

    id                     = Column(BigInteger, primary_key=True, autoincrement=True)
    service_date           = Column(Date, ForeignKey("service_days.service_date"), nullable=False)
    commute_slot_id        = Column(Integer, ForeignKey("commute_slots.id"))
    leg1_trip_id           = Column(BigInteger, ForeignKey("trips.id"))
    leg2_trip_id           = Column(BigInteger, ForeignKey("trips.id"))
    interchange_station_id = Column(String(20), ForeignKey("stations.id"), nullable=False,
                                    default="1191201")  # Wien Meidling
    leg1_planned_arrival   = Column(TIMESTAMPTZ)
    leg1_actual_arrival    = Column(TIMESTAMPTZ)
    leg2_planned_departure = Column(TIMESTAMPTZ)
    leg2_actual_departure  = Column(TIMESTAMPTZ)
    planned_buffer_seconds = Column(Integer)
    actual_buffer_seconds  = Column(Integer)
    connection_made        = Column(Boolean)   # NULL = not yet determined
    missed_by_seconds      = Column(Integer)   # positive = too late by N seconds
    fallback_trip_id       = Column(BigInteger, ForeignKey("trips.id"))
    fallback_wait_seconds  = Column(Integer)
    calculated_at          = Column(TIMESTAMPTZ, nullable=False, server_default=func.now())
    notes                  = Column(Text)

    # Relationships
    leg1_trip           = relationship("Trip", foreign_keys=[leg1_trip_id],
                                        back_populates="connections_as_leg1")
    leg2_trip           = relationship("Trip", foreign_keys=[leg2_trip_id],
                                        back_populates="connections_as_leg2")
    fallback_trip       = relationship("Trip", foreign_keys=[fallback_trip_id])
    commute_slot        = relationship("CommuteSlot", back_populates="connections")
    interchange_station = relationship("Station", foreign_keys=[interchange_station_id])

    __table_args__ = (
        UniqueConstraint("service_date", "leg1_trip_id", "leg2_trip_id",
                         name="uq_connection"),
        Index("idx_connections_service_date", "service_date"),
        Index("idx_connections_commute_slot", "commute_slot_id"),
        Index("idx_connections_leg1", "leg1_trip_id"),
        Index("idx_connections_leg2", "leg2_trip_id"),
    )


# ---------------------------------------------------------------------------
# 10. remarks  (polymorphic: entity_type = 'trip' | 'trip_stop')
# ---------------------------------------------------------------------------

class Remark(Base):
    __tablename__ = "remarks"

    id             = Column(BigInteger, primary_key=True, autoincrement=True)
    entity_type    = Column(String(20), nullable=False)  # 'trip' or 'trip_stop'
    entity_id      = Column(BigInteger, nullable=False)
    remark_type    = Column(String(50))    # 'warning', 'hint', 'status', …
    remark_code    = Column(String(100))   # machine-readable code if present
    remark_text    = Column(Text)
    remark_summary = Column(String(500))
    valid_from     = Column(TIMESTAMPTZ)
    valid_until    = Column(TIMESTAMPTZ)
    first_seen_at  = Column(TIMESTAMPTZ, nullable=False, server_default=func.now())
    last_seen_at   = Column(TIMESTAMPTZ, nullable=False, server_default=func.now(),
                            onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("entity_type", "entity_id", "remark_type", "remark_code",
                         "remark_text", name="uq_remark_dedup"),
        Index("idx_remarks_entity", "entity_type", "entity_id"),
        Index("idx_remarks_type", "remark_type"),
        CheckConstraint("entity_type IN ('trip', 'trip_stop')", name="ck_remark_entity_type"),
    )


# ---------------------------------------------------------------------------
# 11. collection_runs
# ---------------------------------------------------------------------------

class CollectionRun(Base):
    __tablename__ = "collection_runs"

    id                 = Column(BigInteger, primary_key=True, autoincrement=True)
    started_at         = Column(TIMESTAMPTZ, nullable=False, server_default=func.now())
    completed_at       = Column(TIMESTAMPTZ)
    status             = Column(
        Enum(CollectionRunStatus, name="collection_run_status"),
        nullable=False,
        default=CollectionRunStatus.running,
    )
    api_calls_made     = Column(Integer, nullable=False, default=0)
    api_calls_failed   = Column(Integer, nullable=False, default=0)
    trips_new          = Column(Integer, nullable=False, default=0)
    trips_updated      = Column(Integer, nullable=False, default=0)
    trip_stops_new     = Column(Integer, nullable=False, default=0)
    trip_stops_updated = Column(Integer, nullable=False, default=0)
    duration_ms        = Column(Integer)
    error_summary      = Column(Text)
    triggered_by       = Column(String(50), nullable=False, default="scheduler")
    poll_interval_used = Column(Integer)

    # Relationships
    api_errors = relationship("ApiError", back_populates="collection_run",
                              cascade="all, delete-orphan")

    __table_args__ = (
        Index("idx_collection_runs_started_at", "started_at"),
        Index("idx_collection_runs_status", "status"),
    )


# ---------------------------------------------------------------------------
# 12. api_errors
# ---------------------------------------------------------------------------

class ApiError(Base):
    __tablename__ = "api_errors"

    id                = Column(BigInteger, primary_key=True, autoincrement=True)
    collection_run_id = Column(BigInteger,
                               ForeignKey("collection_runs.id", ondelete="CASCADE"),
                               nullable=False)
    occurred_at       = Column(TIMESTAMPTZ, nullable=False, server_default=func.now())
    station_id        = Column(String(20), ForeignKey("stations.id"))
    endpoint          = Column(String(20), nullable=False)
    url               = Column(Text)
    http_status_code  = Column(Integer)
    error_type        = Column(String(100))
    error_message     = Column(Text)
    is_hafas_error    = Column(Boolean, nullable=False, default=False)
    response_body     = Column(Text)  # truncated to first 2000 chars in collector

    # Relationships
    collection_run = relationship("CollectionRun", back_populates="api_errors")
    station        = relationship("Station", back_populates="api_errors")

    __table_args__ = (
        CheckConstraint("endpoint IN ('departures', 'arrivals')", name="ck_api_error_endpoint"),
        Index("idx_api_errors_run_id", "collection_run_id"),
        Index("idx_api_errors_occurred_at", "occurred_at"),
        Index("idx_api_errors_station", "station_id"),
    )
