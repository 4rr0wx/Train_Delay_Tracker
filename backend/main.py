import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from scheduler import scheduler
from collector import collect_data
from database import ensure_stations
from routes import health, stats, departures, commute, journeys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Ensure all known stations exist in DB (idempotent, safe on every restart)
    ensure_stations()
    logger.info("Starting scheduler...")
    scheduler.start()
    # Run an initial collection on startup
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
