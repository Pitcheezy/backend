"""
Background task: polls MLB Stats API every N seconds for live game state,
runs DQN prediction, then publishes the result to Redis Pub-Sub so WebSocket
clients receive real-time updates.
"""

import asyncio
import json
import logging
from datetime import date

import httpx
import redis.asyncio as aioredis

from app.config import settings
from app.ml.inference import predict as ml_predict
from app.ml.loader import PITCHER_PITCHES, loaded_models
from app.schemas.pitch import GameStateMessage, PredictResponse

logger = logging.getLogger(__name__)

MLB_BASE = "https://statsapi.mlb.com/api/v1"


def _resolve_pitcher_key(pitcher_id: int | None, pitcher_name: str | None) -> str | None:
    """Best-effort mapping from MLB pitcher info to a loaded model key."""
    if pitcher_name is None:
        return None
    name_lower = pitcher_name.lower()
    for key in loaded_models:
        if key in name_lower:
            return key
    return None


async def _get_live_games(client: httpx.AsyncClient) -> list[dict]:
    today = date.today().strftime("%Y-%m-%d")
    resp = await client.get(
        f"{MLB_BASE}/schedule",
        params={"sportId": 1, "date": today, "hydrate": "linescore,team"},
    )
    resp.raise_for_status()
    data = resp.json()
    return [
        game
        for date_entry in data.get("dates", [])
        for game in date_entry.get("games", [])
        if game.get("status", {}).get("abstractGameState") == "Live"
    ]


async def _poll_game(
    game_pk: int, client: httpx.AsyncClient, redis_client: aioredis.Redis
) -> None:
    resp = await client.get(
        f"https://statsapi.mlb.com/api/v1.1/game/{game_pk}/feed/live"
    )
    resp.raise_for_status()
    data = resp.json()

    live_data = data.get("liveData", {})
    current_play = live_data.get("plays", {}).get("currentPlay", {})
    if not current_play:
        return

    about = current_play.get("about", {})
    matchup = current_play.get("matchup", {})
    count = current_play.get("count", {})
    offense = live_data.get("linescore", {}).get("offense", {})

    batter_id: int | None = matchup.get("batter", {}).get("id")
    pitcher_id: int | None = matchup.get("pitcher", {}).get("id")
    pitcher_name: str | None = matchup.get("pitcher", {}).get("fullName")
    balls = count.get("balls", 0)
    strikes = count.get("strikes", 0)
    outs = count.get("outs", 0)
    on_1b = "first" in offense
    on_2b = "second" in offense
    on_3b = "third" in offense

    prediction: PredictResponse | None = None
    pitcher_key = _resolve_pitcher_key(pitcher_id, pitcher_name)
    if pitcher_key and batter_id is not None:
        try:
            result = ml_predict(
                pitcher_key=pitcher_key,
                balls=min(balls, 3),
                strikes=min(strikes, 2),
                outs=min(outs, 2),
                on_1b=on_1b,
                on_2b=on_2b,
                on_3b=on_3b,
                batter_id=batter_id,
            )
            prediction = PredictResponse(
                pitcher_key=pitcher_key,
                pitch_type=result["pitch_type"],
                zone=result["zone"],
                action=result["action"],
                batter_cluster=result["batter_cluster"],
            )
        except Exception:
            logger.exception("Prediction failed for game %d", game_pk)

    state = GameStateMessage(
        game_pk=game_pk,
        inning=about.get("inning"),
        inning_half=about.get("halfInning"),
        batter_id=batter_id,
        batter_name=matchup.get("batter", {}).get("fullName"),
        pitcher_id=pitcher_id,
        pitcher_name=pitcher_name,
        balls=balls,
        strikes=strikes,
        outs=outs,
        on_1b=on_1b,
        on_2b=on_2b,
        on_3b=on_3b,
        prediction=prediction,
    )

    await redis_client.publish(f"game:{game_pk}", state.model_dump_json())


async def run_poller() -> None:
    redis_client = aioredis.from_url(settings.REDIS_URL)
    interval = settings.MLB_POLL_INTERVAL

    async with httpx.AsyncClient(timeout=10.0) as client:
        while True:
            try:
                games = await _get_live_games(client)
                if not games:
                    logger.debug("No live games found")
                for game in games:
                    await _poll_game(game["gamePk"], client, redis_client)
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("MLB poller error")
            await asyncio.sleep(interval)

    await redis_client.aclose()
