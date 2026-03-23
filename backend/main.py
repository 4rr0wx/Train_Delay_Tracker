import logging
import subprocess
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from scheduler import scheduler
from collector import collect_data
from database import SessionLocal
from seed import seed_reference_data
from routes import health, stats, departures, commute, journeys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def run_alembic_upgrade() -> None:
    """Run `alembic upgrade head` as a subprocess from the backend directory."""
    logger.info("Running Alembic migrations...")
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        capture_output=True,
        text=True,
    )
    if result.stdout:
        logger.info("Alembic: %s", result.stdout.strip())
    if result.returncode != 0:
        logger.error("Alembic migration failed: %s", result.stderr.strip())
        raise RuntimeError(f"Alembic upgrade failed: {result.stderr}")
    logger.info("Alembic migrations complete.")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 1. Run any pending DB migrations
    run_alembic_upgrade()

    # 2. Seed reference data (idempotent)
    with SessionLocal() as db:
        seed_reference_data(db)

    # 3. Start the background scheduler
    logger.info("Starting scheduler...")
    scheduler.start()

    # 4. Run an initial data collection on startup
    try:
        collect_data()
    except Exception as e:
        logger.error("Initial collection failed: %s", e)

    yield

    logger.info("Shutting down scheduler...")
    scheduler.shutdown()


app = FastAPI(title="Pendler Verspätungsstatistik", lifespan=lifespan)

app.include_router(health.router, prefix="/api")
app.include_router(stats.router, prefix="/api")
app.include_router(departures.router, prefix="/api")
app.include_router(commute.router, prefix="/api")
app.include_router(journeys.router, prefix="/api")

app.mount("/", StaticFiles(directory="static", html=True), name="static")
