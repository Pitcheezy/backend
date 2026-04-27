from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services import replay as replay_service

router = APIRouter(prefix="/api/replay", tags=["replay"])


class ReplayStartRequest(BaseModel):
    game_pk: int
    interval: float = 5.0  # 투구 간격 (초)


@router.post("/start")
async def start_replay(req: ReplayStartRequest):
    """
    완료된 경기 데이터를 실시간처럼 재생합니다.
    WebSocket /ws/{game_pk} 로 연결하면 투구마다 데이터를 수신합니다.
    """
    if replay_service.is_running():
        raise HTTPException(status_code=409, detail="이미 replay가 실행 중입니다. /stop 을 먼저 호출하세요.")
    try:
        await replay_service.start(req.game_pk, req.interval)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return {
        "status": "started",
        "game_pk": req.game_pk,
        "interval": req.interval,
        "ws_url": f"/ws/{req.game_pk}",
    }


@router.post("/stop")
async def stop_replay():
    """실행 중인 replay를 중단합니다."""
    if not replay_service.is_running():
        raise HTTPException(status_code=404, detail="실행 중인 replay가 없습니다.")
    replay_service.stop()
    return {"status": "stopped"}


@router.get("/status")
async def replay_status():
    """replay 실행 여부를 반환합니다."""
    return {"running": replay_service.is_running()}
