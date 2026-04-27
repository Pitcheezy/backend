import asyncio
import logging

import redis.asyncio as aioredis
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(tags=["websocket"])


@router.websocket("/ws/{game_pk}")
async def websocket_game(websocket: WebSocket, game_pk: int):
    await websocket.accept()
    logger.info("WS connected: game_pk=%d", game_pk)

    redis_client = aioredis.from_url(settings.REDIS_URL)

    # 연결 즉시 최신 상태 전송 (첫 폴링까지 빈 화면 방지)
    snapshot = await redis_client.get(f"game:snapshot:{game_pk}")
    if snapshot:
        text = snapshot.decode() if isinstance(snapshot, bytes) else snapshot
        await websocket.send_text(text)

    pubsub = redis_client.pubsub()
    await pubsub.subscribe(f"game:{game_pk}")

    try:
        while True:
            # 1초 안에 메시지 없으면 None 반환 → 루프 재진입
            message = await pubsub.get_message(
                ignore_subscribe_messages=True, timeout=1.0
            )
            if message and message["type"] == "message":
                data = message["data"]
                text = data.decode() if isinstance(data, bytes) else data
                await websocket.send_text(text)
            else:
                await asyncio.sleep(0.05)
    except WebSocketDisconnect:
        logger.info("WS disconnected: game_pk=%d", game_pk)
    except Exception:
        logger.exception("WS error: game_pk=%d", game_pk)
    finally:
        await pubsub.unsubscribe(f"game:{game_pk}")
        await redis_client.aclose()
