import logging

import redis.asyncio as aioredis
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(tags=["websocket"])


@router.websocket("/ws/{game_pk}")
async def websocket_game(websocket: WebSocket, game_pk: int):
    await websocket.accept()

    redis_client = aioredis.from_url(settings.REDIS_URL)
    pubsub = redis_client.pubsub()
    await pubsub.subscribe(f"game:{game_pk}")
    logger.info("WS client connected: game_pk=%d", game_pk)

    try:
        async for message in pubsub.listen():
            if message["type"] == "message":
                data = message["data"]
                text = data.decode() if isinstance(data, bytes) else data
                await websocket.send_text(text)
    except WebSocketDisconnect:
        logger.info("WS client disconnected: game_pk=%d", game_pk)
    finally:
        await pubsub.unsubscribe(f"game:{game_pk}")
        await redis_client.aclose()
