"""Initial V2 schema

Revision ID: 0001
Revises:
Create Date: 2026-03-23

Creates all 12 tables of the V2 data model from scratch.
This migration does NOT attempt to migrate V1 data.
V1-to-V2 data migration belongs in migration 0002 (future).
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # PostgreSQL ENUM types
    # ------------------------------------------------------------------
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE trip_direction AS ENUM ('to_wien', 'to_ternitz');
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE trip_status AS ENUM (
                'scheduled', 'active', 'delayed', 'cancelled',
                'partially_cancelled', 'completed', 'unknown'
            );
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE collection_run_status AS ENUM (
                'running', 'completed', 'partial', 'failed'
            );
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
    """)

    # ------------------------------------------------------------------
    # 1. stations
    # ------------------------------------------------------------------
    op.execute("""
        CREATE TABLE IF NOT EXISTS stations (
            id           VARCHAR(20)  PRIMARY KEY,
            name         VARCHAR(200) NOT NULL,
            short_name   VARCHAR(50),
            station_type VARCHAR(30)  NOT NULL DEFAULT 'train'
                CONSTRAINT ck_station_type
                CHECK (station_type IN ('train', 'subway', 'tram', 'bus', 'mixed')),
            latitude     NUMERIC(9, 6),
            longitude    NUMERIC(9, 6),
            timezone     VARCHAR(50)  NOT NULL DEFAULT 'Europe/Vienna',
            is_active    BOOLEAN      NOT NULL DEFAULT TRUE,
            created_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            updated_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_stations_active
            ON stations (is_active) WHERE is_active = TRUE
    """)

    # ------------------------------------------------------------------
    # 2. lines
    # ------------------------------------------------------------------
    op.execute("""
        CREATE TABLE IF NOT EXISTS lines (
            id           SERIAL       PRIMARY KEY,
            code         VARCHAR(20)  NOT NULL UNIQUE,
            display_name VARCHAR(100) NOT NULL,
            operator     VARCHAR(100) NOT NULL,
            product_type VARCHAR(30)  NOT NULL
                CONSTRAINT ck_line_product_type
                CHECK (product_type IN (
                    'regional', 'suburban', 'subway', 'tram', 'bus',
                    'nationalExpress', 'national', 'ferry'
                )),
            color_hex    VARCHAR(7),
            is_active    BOOLEAN      NOT NULL DEFAULT TRUE,
            notes        TEXT,
            created_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            updated_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW()
        )
    """)

    # ------------------------------------------------------------------
    # 3. service_days
    # ------------------------------------------------------------------
    op.execute("""
        CREATE TABLE IF NOT EXISTS service_days (
            service_date        DATE        PRIMARY KEY,
            is_weekday          BOOLEAN     NOT NULL,
            day_of_week         SMALLINT    NOT NULL
                CONSTRAINT ck_service_day_dow CHECK (day_of_week BETWEEN 0 AND 6),
            is_austrian_holiday BOOLEAN     NOT NULL DEFAULT FALSE,
            holiday_name        VARCHAR(200),
            is_school_day       BOOLEAN,
            notes               TEXT,
            created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_service_days_weekday
            ON service_days (is_weekday)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_service_days_holiday
            ON service_days (is_austrian_holiday) WHERE is_austrian_holiday = TRUE
    """)

    # ------------------------------------------------------------------
    # 4. routes
    # ------------------------------------------------------------------
    op.execute("""
        CREATE TABLE IF NOT EXISTS routes (
            id          SERIAL       PRIMARY KEY,
            name        VARCHAR(200) NOT NULL UNIQUE,
            line_id     INTEGER      NOT NULL REFERENCES lines (id),
            direction   VARCHAR(20)  NOT NULL
                CONSTRAINT ck_route_direction
                CHECK (direction IN (
                    'to_wien', 'to_ternitz', 'inbound', 'outbound',
                    'northbound', 'southbound'
                )),
            description TEXT,
            is_active   BOOLEAN      NOT NULL DEFAULT TRUE,
            created_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            updated_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_route_line_direction UNIQUE (line_id, direction)
        )
    """)

    # ------------------------------------------------------------------
    # 5. route_legs
    # ------------------------------------------------------------------
    op.execute("""
        CREATE TABLE IF NOT EXISTS route_legs (
            id                               SERIAL      PRIMARY KEY,
            route_id                         INTEGER     NOT NULL
                REFERENCES routes (id) ON DELETE CASCADE,
            stop_sequence                    INTEGER     NOT NULL,
            station_id                       VARCHAR(20) NOT NULL REFERENCES stations (id),
            is_origin                        BOOLEAN     NOT NULL DEFAULT FALSE,
            is_destination                   BOOLEAN     NOT NULL DEFAULT FALSE,
            typical_travel_minutes_from_prev INTEGER,
            poll_window_before_minutes       INTEGER     NOT NULL DEFAULT 10,
            poll_window_after_minutes        INTEGER     NOT NULL DEFAULT 30,
            CONSTRAINT uq_route_leg_sequence UNIQUE (route_id, stop_sequence),
            CONSTRAINT uq_route_leg_station  UNIQUE (route_id, station_id)
        )
    """)

    # ------------------------------------------------------------------
    # 6. trips
    # ------------------------------------------------------------------
    op.execute("""
        CREATE TABLE IF NOT EXISTS trips (
            id                       BIGSERIAL        PRIMARY KEY,
            api_trip_id              VARCHAR(255)     NOT NULL,
            service_date             DATE             NOT NULL
                REFERENCES service_days (service_date),
            line_id                  INTEGER          NOT NULL REFERENCES lines (id),
            route_id                 INTEGER          REFERENCES routes (id),
            direction                trip_direction   NOT NULL,
            train_number             VARCHAR(50),
            destination_name         VARCHAR(200),
            origin_name              VARCHAR(200),
            status                   trip_status      NOT NULL DEFAULT 'unknown',
            is_diverted              BOOLEAN          NOT NULL DEFAULT FALSE,
            first_seen_at            TIMESTAMPTZ      NOT NULL DEFAULT NOW(),
            last_updated_at          TIMESTAMPTZ      NOT NULL DEFAULT NOW(),
            completed_at             TIMESTAMPTZ,
            planned_origin_departure TIMESTAMPTZ,
            CONSTRAINT uq_trip_api_id_date UNIQUE (api_trip_id, service_date)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_trips_service_date ON trips (service_date)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_trips_line_id ON trips (line_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_trips_direction ON trips (direction)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_trips_status ON trips (status)")
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_trips_diverted
            ON trips (is_diverted) WHERE is_diverted = TRUE
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_trips_api_trip_id ON trips (api_trip_id)")
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_trips_line_direction_date
            ON trips (line_id, direction, service_date)
    """)

    # ------------------------------------------------------------------
    # 7. trip_stops
    # ------------------------------------------------------------------
    op.execute("""
        CREATE TABLE IF NOT EXISTS trip_stops (
            id                      BIGSERIAL   PRIMARY KEY,
            trip_id                 BIGINT      NOT NULL
                REFERENCES trips (id) ON DELETE CASCADE,
            station_id              VARCHAR(20) NOT NULL REFERENCES stations (id),
            stop_sequence           INTEGER,
            planned_arrival         TIMESTAMPTZ,
            planned_departure       TIMESTAMPTZ,
            actual_arrival          TIMESTAMPTZ,
            actual_departure        TIMESTAMPTZ,
            arrival_delay_seconds   INTEGER,
            departure_delay_seconds INTEGER,
            cancelled_at_stop       BOOLEAN     NOT NULL DEFAULT FALSE,
            platform                VARCHAR(20),
            platform_changed        BOOLEAN     NOT NULL DEFAULT FALSE,
            first_seen_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            last_updated_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_trip_stop UNIQUE (trip_id, station_id)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_trip_stops_trip_id ON trip_stops (trip_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_trip_stops_station_id ON trip_stops (station_id)")
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_trip_stops_planned_dep
            ON trip_stops (planned_departure)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_trip_stops_station_planned_dep
            ON trip_stops (station_id, planned_departure)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_trip_stops_cancelled
            ON trip_stops (cancelled_at_stop) WHERE cancelled_at_stop = TRUE
    """)

    # ------------------------------------------------------------------
    # 8. commute_slots
    # ------------------------------------------------------------------
    op.execute("""
        CREATE TABLE IF NOT EXISTS commute_slots (
            id                     SERIAL         PRIMARY KEY,
            name                   VARCHAR(100)   NOT NULL UNIQUE,
            route_id               INTEGER        NOT NULL REFERENCES routes (id),
            direction              trip_direction NOT NULL,
            anchor_time_local      TIME           NOT NULL,
            anchor_station_id      VARCHAR(20)    NOT NULL REFERENCES stations (id),
            time_tolerance_minutes INTEGER        NOT NULL DEFAULT 2,
            applies_monday         BOOLEAN        NOT NULL DEFAULT TRUE,
            applies_tuesday        BOOLEAN        NOT NULL DEFAULT TRUE,
            applies_wednesday      BOOLEAN        NOT NULL DEFAULT TRUE,
            applies_thursday       BOOLEAN        NOT NULL DEFAULT TRUE,
            applies_friday         BOOLEAN        NOT NULL DEFAULT TRUE,
            applies_saturday       BOOLEAN        NOT NULL DEFAULT FALSE,
            applies_sunday         BOOLEAN        NOT NULL DEFAULT FALSE,
            is_active              BOOLEAN        NOT NULL DEFAULT TRUE,
            notes                  TEXT,
            created_at             TIMESTAMPTZ    NOT NULL DEFAULT NOW()
        )
    """)

    # ------------------------------------------------------------------
    # 9. connections
    # ------------------------------------------------------------------
    op.execute("""
        CREATE TABLE IF NOT EXISTS connections (
            id                     BIGSERIAL   PRIMARY KEY,
            service_date           DATE        NOT NULL
                REFERENCES service_days (service_date),
            commute_slot_id        INTEGER     REFERENCES commute_slots (id),
            leg1_trip_id           BIGINT      REFERENCES trips (id),
            leg2_trip_id           BIGINT      REFERENCES trips (id),
            interchange_station_id VARCHAR(20) NOT NULL
                REFERENCES stations (id) DEFAULT '1191201',
            leg1_planned_arrival   TIMESTAMPTZ,
            leg1_actual_arrival    TIMESTAMPTZ,
            leg2_planned_departure TIMESTAMPTZ,
            leg2_actual_departure  TIMESTAMPTZ,
            planned_buffer_seconds INTEGER,
            actual_buffer_seconds  INTEGER,
            connection_made        BOOLEAN,
            missed_by_seconds      INTEGER,
            fallback_trip_id       BIGINT      REFERENCES trips (id),
            fallback_wait_seconds  INTEGER,
            calculated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            notes                  TEXT,
            CONSTRAINT uq_connection UNIQUE (service_date, leg1_trip_id, leg2_trip_id)
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_connections_service_date
            ON connections (service_date)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_connections_commute_slot
            ON connections (commute_slot_id)
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_connections_leg1 ON connections (leg1_trip_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_connections_leg2 ON connections (leg2_trip_id)")

    # ------------------------------------------------------------------
    # 10. remarks
    # ------------------------------------------------------------------
    op.execute("""
        CREATE TABLE IF NOT EXISTS remarks (
            id             BIGSERIAL    PRIMARY KEY,
            entity_type    VARCHAR(20)  NOT NULL
                CONSTRAINT ck_remark_entity_type
                CHECK (entity_type IN ('trip', 'trip_stop')),
            entity_id      BIGINT       NOT NULL,
            remark_type    VARCHAR(50),
            remark_code    VARCHAR(100),
            remark_text    TEXT,
            remark_summary VARCHAR(500),
            valid_from     TIMESTAMPTZ,
            valid_until    TIMESTAMPTZ,
            first_seen_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            last_seen_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_remark_dedup
                UNIQUE (entity_type, entity_id, remark_type, remark_code, remark_text)
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_remarks_entity
            ON remarks (entity_type, entity_id)
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_remarks_type ON remarks (remark_type)")
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_remarks_code
            ON remarks (remark_code) WHERE remark_code IS NOT NULL
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_remarks_text_gin
            ON remarks USING GIN (to_tsvector('german', remark_text))
            WHERE remark_text IS NOT NULL
    """)

    # ------------------------------------------------------------------
    # 11. collection_runs
    # ------------------------------------------------------------------
    op.execute("""
        CREATE TABLE IF NOT EXISTS collection_runs (
            id                 BIGSERIAL              PRIMARY KEY,
            started_at         TIMESTAMPTZ            NOT NULL DEFAULT NOW(),
            completed_at       TIMESTAMPTZ,
            status             collection_run_status  NOT NULL DEFAULT 'running',
            api_calls_made     INTEGER                NOT NULL DEFAULT 0,
            api_calls_failed   INTEGER                NOT NULL DEFAULT 0,
            trips_new          INTEGER                NOT NULL DEFAULT 0,
            trips_updated      INTEGER                NOT NULL DEFAULT 0,
            trip_stops_new     INTEGER                NOT NULL DEFAULT 0,
            trip_stops_updated INTEGER                NOT NULL DEFAULT 0,
            duration_ms        INTEGER,
            error_summary      TEXT,
            triggered_by       VARCHAR(50)            NOT NULL DEFAULT 'scheduler',
            poll_interval_used INTEGER
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_collection_runs_started_at
            ON collection_runs (started_at DESC)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_collection_runs_status
            ON collection_runs (status)
    """)

    # ------------------------------------------------------------------
    # 12. api_errors
    # ------------------------------------------------------------------
    op.execute("""
        CREATE TABLE IF NOT EXISTS api_errors (
            id                BIGSERIAL   PRIMARY KEY,
            collection_run_id BIGINT      NOT NULL
                REFERENCES collection_runs (id) ON DELETE CASCADE,
            occurred_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            station_id        VARCHAR(20) REFERENCES stations (id),
            endpoint          VARCHAR(20) NOT NULL
                CONSTRAINT ck_api_error_endpoint
                CHECK (endpoint IN ('departures', 'arrivals')),
            url               TEXT,
            http_status_code  INTEGER,
            error_type        VARCHAR(100),
            error_message     TEXT,
            is_hafas_error    BOOLEAN     NOT NULL DEFAULT FALSE,
            response_body     TEXT
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_api_errors_run_id
            ON api_errors (collection_run_id)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_api_errors_occurred_at
            ON api_errors (occurred_at DESC)
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_api_errors_station ON api_errors (station_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_api_errors_type ON api_errors (error_type)")


def downgrade() -> None:
    # Drop in reverse dependency order
    op.execute("DROP TABLE IF EXISTS api_errors CASCADE")
    op.execute("DROP TABLE IF EXISTS collection_runs CASCADE")
    op.execute("DROP TABLE IF EXISTS remarks CASCADE")
    op.execute("DROP TABLE IF EXISTS connections CASCADE")
    op.execute("DROP TABLE IF EXISTS commute_slots CASCADE")
    op.execute("DROP TABLE IF EXISTS trip_stops CASCADE")
    op.execute("DROP TABLE IF EXISTS trips CASCADE")
    op.execute("DROP TABLE IF EXISTS route_legs CASCADE")
    op.execute("DROP TABLE IF EXISTS routes CASCADE")
    op.execute("DROP TABLE IF EXISTS service_days CASCADE")
    op.execute("DROP TABLE IF EXISTS lines CASCADE")
    op.execute("DROP TABLE IF EXISTS stations CASCADE")
    op.execute("DROP TYPE IF EXISTS collection_run_status")
    op.execute("DROP TYPE IF EXISTS trip_status")
    op.execute("DROP TYPE IF EXISTS trip_direction")
