"""
Replay service: fetches a completed game's pitch-by-pitch data from MLB StatsAPI
and re-publishes each pitch to Redis Pub-Sub at a fixed interval,
so WebSocket clients receive it exactly like a live game.

Usage:
  POST /api/replay/start  {"game_pk": 824202, "interval": 5.0}
  POST /api/replay/stop
"""

import asyncio
import logging

import httpx
import redis.asyncio as aioredis

from app.config import settings
from app.ml.inference import predict as ml_predict
from app.ml.loader import loaded_models
from app.schemas.pitch import GameStateMessage, LastPitch, PredictResponse
from app.services.mlb_poller import resolve_pitcher_key

logger = logging.getLogger(__name__)

# 현재 실행 중인 replay task (None이면 미실행)
_replay_task: asyncio.Task | None = None


# ---------------------------------------------------------------------------
# 데이터 추출
# ---------------------------------------------------------------------------

def _extract_pitches(all_plays: list[dict]) -> list[dict]:
    """allPlays에서 투구 단위 상태 목록을 추출한다.

    각 항목에 last_pitch(현재 투구 상세)와 pitch_sequence(타석 내 누적)를 포함.
    """
    pitches: list[dict] = []
    on_1b = on_2b = on_3b = False
    current_batter_id: int | None = None
    current_at_bat_sequence: list[dict] = []

    for play in all_plays:
        matchup = play.get("matchup", {})
        about = play.get("about", {})
        batter_id: int | None = matchup.get("batter", {}).get("id")

        # 타자가 바뀌면 타석 시퀀스 초기화
        if batter_id != current_batter_id:
            current_batter_id = batter_id
            current_at_bat_sequence = []

        for event in play.get("playEvents", []):
            if not event.get("isPitch"):
                continue

            count = event.get("count", {})
            details = event.get("details", {})
            pitch_data = event.get("pitchData", {})

            pitch_detail = {
                "pitch_type": details.get("type", {}).get("description"),
                "zone": pitch_data.get("zone"),
                "velocity": pitch_data.get("startSpeed"),
                "result": details.get("call", {}).get("description"),
            }
            current_at_bat_sequence.append(pitch_detail)

            pitches.append({
                "inning": about.get("inning"),
                "half": about.get("halfInning"),
                "batter_id": batter_id,
                "batter_name": matchup.get("batter", {}).get("fullName"),
                "pitcher_id": matchup.get("pitcher", {}).get("id"),
                "pitcher_name": matchup.get("pitcher", {}).get("fullName"),
                "balls": count.get("balls", 0),
                "strikes": count.get("strikes", 0),
                "outs": count.get("outs", 0),
                "on_1b": on_1b,
                "on_2b": on_2b,
                "on_3b": on_3b,
                "last_pitch": pitch_detail,
                "pitch_sequence": list(current_at_bat_sequence),
            })

        # 타석 종료 후 주자 상황 업데이트
        on_1b = on_2b = on_3b = False
        for runner in play.get("runners", []):
            end = runner.get("movement", {}).get("end", "")
            if end == "1B":
                on_1b = True
            elif end == "2B":
                on_2b = True
            elif end == "3B":
                on_3b = True

    return pitches


async def _fetch_pitches(game_pk: int) -> list[dict]:
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(
            f"https://statsapi.mlb.com/api/v1.1/game/{game_pk}/feed/live"
        )
        resp.raise_for_status()
        data = resp.json()

    all_plays = data.get("liveData", {}).get("plays", {}).get("allPlays", [])
    if not all_plays:
        raise ValueError(f"game_pk={game_pk} 에서 투구 데이터를 찾을 수 없습니다")

    pitches = _extract_pitches(all_plays)
    logger.info("game_pk=%d 에서 투구 %d개 로드 완료", game_pk, len(pitches))
    return pitches


# ---------------------------------------------------------------------------
# 예측
# ---------------------------------------------------------------------------

def _make_prediction(pitch: dict) -> PredictResponse | None:
    pitcher_key = resolve_pitcher_key(pitch["pitcher_id"], pitch["pitcher_name"])
    if not pitcher_key or pitch["batter_id"] is None:
        return None
    try:
        result = ml_predict(
            pitcher_key=pitcher_key,
            balls=min(pitch["balls"], 3),
            strikes=min(pitch["strikes"], 2),
            outs=min(pitch["outs"], 2),
            on_1b=pitch["on_1b"],
            on_2b=pitch["on_2b"],
            on_3b=pitch["on_3b"],
            batter_id=pitch["batter_id"],
        )
        return PredictResponse(
            pitcher_key=pitcher_key,
            pitch_type=result["pitch_type"],
            zone=result["zone"],
            action=result["action"],
            batter_cluster=result["batter_cluster"],
            confidence=result.get("confidence"),
        )
    except Exception:
        logger.exception("replay 예측 실패")
        return None


# ---------------------------------------------------------------------------
# replay 루프
# ---------------------------------------------------------------------------

async def _replay_loop(game_pk: int, interval: float) -> None:
    pitches = await _fetch_pitches(game_pk)
    redis_client = aioredis.from_url(settings.REDIS_URL)
    channel = f"game:{game_pk}"

    logger.info("replay 시작: game_pk=%d, 투구수=%d, interval=%.1fs", game_pk, len(pitches), interval)

    try:
        for i, pitch in enumerate(pitches):
            lp_data = pitch.get("last_pitch", {})
            last_pitch = LastPitch(
                pitch_type=lp_data.get("pitch_type"),
                zone=lp_data.get("zone"),
                velocity=lp_data.get("velocity"),
                result=lp_data.get("result"),
            ) if lp_data else None

            pitch_sequence = [
                LastPitch(
                    pitch_type=p.get("pitch_type"),
                    zone=p.get("zone"),
                    velocity=p.get("velocity"),
                    result=p.get("result"),
                )
                for p in pitch.get("pitch_sequence", [])
            ]

            state = GameStateMessage(
                game_pk=game_pk,
                inning=pitch["inning"],
                half=pitch["half"],
                batter_id=pitch["batter_id"],
                batter_name=pitch["batter_name"],
                pitcher_id=pitch["pitcher_id"],
                pitcher_name=pitch["pitcher_name"],
                balls=pitch["balls"],
                strikes=pitch["strikes"],
                outs=pitch["outs"],
                on_1b=pitch["on_1b"],
                on_2b=pitch["on_2b"],
                on_3b=pitch["on_3b"],
                last_pitch=last_pitch,
                pitch_sequence=pitch_sequence,
                prediction=_make_prediction(pitch),
            )
            json_data = state.model_dump_json()
            await redis_client.publish(channel, json_data)
            await redis_client.set(f"game:snapshot:{game_pk}", json_data, ex=300)
            logger.debug("replay [%d/%d] 전송: %s", i + 1, len(pitches), pitch["pitcher_name"])
            await asyncio.sleep(interval)

        logger.info("replay 완료: game_pk=%d", game_pk)

    except asyncio.CancelledError:
        logger.info("replay 중단: game_pk=%d", game_pk)
    finally:
        await redis_client.aclose()


# ---------------------------------------------------------------------------
# 공개 인터페이스
# ---------------------------------------------------------------------------

def is_running() -> bool:
    return _replay_task is not None and not _replay_task.done()


async def start(game_pk: int, interval: float = 5.0) -> None:
    global _replay_task
    if is_running():
        raise RuntimeError("이미 replay가 실행 중입니다. 먼저 중단하세요.")
    _replay_task = asyncio.create_task(_replay_loop(game_pk, interval))


def stop() -> None:
    global _replay_task
    if _replay_task and not _replay_task.done():
        _replay_task.cancel()
    _replay_task = None
