import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.ml.loader import load_all
from app.routers import games, health, predict, replay, ws
from app.services.mlb_poller import run_poller

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Loading ML models...")
    load_all()
    logger.info("Starting MLB poller...")
    poller_task = asyncio.create_task(run_poller())
    yield
    poller_task.cancel()
    try:
        await poller_task
    except asyncio.CancelledError:
        pass


app = FastAPI(title="SmartPitch API", version="0.1.0", lifespan=lifespan)

app.include_router(health.router)
app.include_router(games.router)
app.include_router(predict.router)
app.include_router(replay.router)
app.include_router(ws.router)
