CREATE TABLE stations (
    id VARCHAR(20) PRIMARY KEY,
    name VARCHAR(200) NOT NULL
);

INSERT INTO stations (id, name) VALUES
    ('1131839', 'Ternitz'),
    ('1130165', 'Baden bei Wien'),
    ('1191201', 'Wien Meidling'),
    ('915006',  'Wien Westbahnhof (U6)');

CREATE TABLE train_observations (
    id SERIAL PRIMARY KEY,
    trip_id VARCHAR(255) NOT NULL,
    station_id VARCHAR(20) REFERENCES stations(id),
    direction VARCHAR(10) NOT NULL CHECK (direction IN ('to_wien', 'to_ternitz')),
    line_name VARCHAR(100),
    line_product VARCHAR(50),
    destination VARCHAR(200),
    planned_time TIMESTAMPTZ NOT NULL,
    actual_time TIMESTAMPTZ,
    delay_seconds INTEGER,
    cancelled BOOLEAN DEFAULT FALSE,
    platform VARCHAR(20),
    remarks JSONB,
    first_seen_at TIMESTAMPTZ DEFAULT NOW(),
    last_updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (trip_id, planned_time)
);

CREATE INDEX idx_obs_direction ON train_observations(direction);
CREATE INDEX idx_obs_planned_time ON train_observations(planned_time);
CREATE INDEX idx_obs_direction_time ON train_observations(direction, planned_time);
CREATE INDEX idx_obs_cancelled ON train_observations(cancelled);
CREATE INDEX idx_obs_line_product ON train_observations(line_product);
