-- V2 bootstrap: extensions only.
-- All table creation is managed by Alembic (runs `alembic upgrade head` on app startup).
-- This file runs exactly once when the PostgreSQL Docker volume is first initialized.

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";   -- available for future UUID primary keys
CREATE EXTENSION IF NOT EXISTS "pg_trgm";     -- enables trigram indexes for fuzzy text search
CREATE EXTENSION IF NOT EXISTS "btree_gin";   -- enables GIN indexes on scalar types
