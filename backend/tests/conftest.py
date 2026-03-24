"""Shared pytest configuration and fixtures.

Sets up a lightweight in-memory SQLite environment so that unit tests can
import the application modules (utils.py, routes/*.py) without a running
PostgreSQL instance.

Strategy:
  1. Stub ``psycopg2`` so SQLAlchemy never tries to load it.
  2. Patch ``sqlalchemy.create_engine`` to return a no-op mock **before**
     ``database.py`` is imported, so the module-level ``engine = create_engine(...)``
     call succeeds without a real DB connection.
  3. Ensure ``sys.path`` includes the backend root so all imports work.
"""

import os
import sys
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# 1. Ensure backend/ is on the path
# ---------------------------------------------------------------------------
_backend_dir = os.path.join(os.path.dirname(__file__), "..")
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

# ---------------------------------------------------------------------------
# 2. Stub out psycopg2 – must happen before any SQLAlchemy engine is created
# ---------------------------------------------------------------------------
_psycopg2_stub = MagicMock()
sys.modules.setdefault("psycopg2", _psycopg2_stub)
sys.modules.setdefault("psycopg2.extras", _psycopg2_stub.extras)
sys.modules.setdefault("psycopg2.extensions", _psycopg2_stub.extensions)

# ---------------------------------------------------------------------------
# 3. Import database.py with create_engine patched to a no-op mock.
#    We then replace the module-level engine/SessionLocal with real SQLite
#    equivalents so that models.py can inherit from Base correctly.
# ---------------------------------------------------------------------------
_mock_engine = MagicMock()

with patch("sqlalchemy.create_engine", return_value=_mock_engine):
    import database  # noqa: E402  (import after sys.path modification)

# Now give the database module a real SQLite engine + sessionmaker so that
# SQLAlchemy ORM classes (models.py) have a functional Base.
from sqlalchemy import create_engine as _real_create_engine
from sqlalchemy.orm import sessionmaker as _real_sessionmaker

_sqlite_engine = _real_create_engine("sqlite+pysqlite:///:memory:")
database.engine = _sqlite_engine
database.SessionLocal = _real_sessionmaker(bind=_sqlite_engine)
