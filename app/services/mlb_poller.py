"""
Background task: polls MLB Stats API every N seconds for live game state,
runs DQN prediction, then publishes the result to Redis Pub-Sub so WebSocket
clients receive real-time updates.
"""

import asyncio
import logging
from datetime import date

import httpx
import redis.asyncio as aioredis

from app.config import settings
from app.ml.inference import predict as ml_predict
from app.ml.loader import PITCHER_ID_MAP, loaded_models
from app.schemas.pitch import (
    GameStateMessage,
    InningLine,
    LastPitch,
    PredictResponse,
    TeamInfo,
)

logger = logging.getLogger(__name__)

MLB_BASE = "https://statsapi.mlb.com/api/v1"


# ---------------------------------------------------------------------------
# 투수 키 해석
# ---------------------------------------------------------------------------

def resolve_pitcher_key(pitcher_id: int | None, pitcher_name: str | None) -> str | None:
    """pitcher_id 우선, 없으면 이름 포함 여부로 fallback."""
    if pitcher_id and pitcher_id in PITCHER_ID_MAP:
        key = PITCHER_ID_MAP[pitcher_id]
        return key if key in loaded_models else None
    if pitcher_name:
        for key in loaded_models:
            if key in pitcher_name.lower():
                return key
    return None


# ---------------------------------------------------------------------------
# 데이터 파싱 헬퍼
# ---------------------------------------------------------------------------

def _parse_team(team_data: dict) -> TeamInfo:
    return TeamInfo(
        id=team_data.get("id", 0),
        name=team_data.get("name", ""),
        code=team_data.get("abbreviation", ""),
    )


def _parse_inning_line(innings: list[dict]) -> InningLine:
    away: list[int | None] = []
    home: list[int | None] = []
    for inn in innings:
        away.append(inn.get("away", {}).get("runs"))
        home.append(inn.get("home", {}).get("runs"))
    return InningLine(away=away, home=home)


def _parse_pitch_sequence(play_events: list[dict]) -> list[LastPitch]:
    """현재 타석의 전체 투구 시퀀스를 오래된 순서로 반환."""
    result = []
    for event in play_events:
        if not event.get("isPitch"):
            continue
        details = event.get("details", {})
        pitch_data = event.get("pitchData", {})
        result.append(LastPitch(
            pitch_type=details.get("type", {}).get("description"),
            zone=pitch_data.get("zone"),
            velocity=pitch_data.get("startSpeed"),
            result=details.get("call", {}).get("description"),
        ))
    return result


def _make_prediction(
    pitcher_key: str, pitch: dict, batter_id: int
) -> PredictResponse | None:
    try:
        result = ml_predict(
            pitcher_key=pitcher_key,
            balls=min(pitch["balls"], 3),
            strikes=min(pitch["strikes"], 2),
            outs=min(pitch["outs"], 2),
            on_1b=pitch["on_1b"],
            on_2b=pitch["on_2b"],
            on_3b=pitch["on_3b"],
            batter_id=batter_id,
        )
        return PredictResponse(
            pitcher_key=pitcher_key,
            pitch_type=result["pitch_type"],
            zone=result["zone"],
            action=result["action"],
            batter_cluster=result["batter_cluster"],
            confidence=result["confidence"],
        )
    except Exception:
        logger.exception("예측 실패: pitcher_key=%s", pitcher_key)
        return None


# ---------------------------------------------------------------------------
# 경기 목록 조회
# ---------------------------------------------------------------------------

async def get_live_games(client: httpx.AsyncClient) -> list[dict]:
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


# ---------------------------------------------------------------------------
# 경기 폴링
# ---------------------------------------------------------------------------

async def _poll_game(
    game_pk: int, client: httpx.AsyncClient, redis_client: aioredis.Redis
) -> None:
    resp = await client.get(
        f"https://statsapi.mlb.com/api/v1.1/game/{game_pk}/feed/live"
    )
    resp.raise_for_status()
    data = resp.json()

    game_data = data.get("gameData", {})
    live_data = data.get("liveData", {})
    linescore = live_data.get("linescore", {})
    current_play = live_data.get("plays", {}).get("currentPlay", {})

    if not current_play:
        return

    about = current_play.get("about", {})
    matchup = current_play.get("matchup", {})
    count = current_play.get("count", {})
    offense = linescore.get("offense", {})
    teams_score = linescore.get("teams", {})
    innings = linescore.get("innings", [])

    batter_id: int | None = matchup.get("batter", {}).get("id")
    pitcher_id: int | None = matchup.get("pitcher", {}).get("id")
    pitcher_name: str | None = matchup.get("pitcher", {}).get("fullName")
    balls = count.get("balls", 0)
    strikes = count.get("strikes", 0)
    outs = count.get("outs", 0)
    on_1b = "first" in offense
    on_2b = "second" in offense
    on_3b = "third" in offense

    pitcher_key = resolve_pitcher_key(pitcher_id, pitcher_name)
    prediction: PredictResponse | None = None
    if pitcher_key and batter_id is not None:
        prediction = _make_prediction(
            pitcher_key,
            {"balls": balls, "strikes": strikes, "outs": outs,
             "on_1b": on_1b, "on_2b": on_2b, "on_3b": on_3b},
            batter_id,
        )

    # 팀 정보
    away_team: TeamInfo | None = None
    home_team: TeamInfo | None = None
    gd_teams = game_data.get("teams", {})
    if gd_teams.get("away"):
        away_team = _parse_team(gd_teams["away"])
    if gd_teams.get("home"):
        home_team = _parse_team(gd_teams["home"])

    play_events = current_play.get("playEvents", [])
    pitch_sequence = _parse_pitch_sequence(play_events)

    state = GameStateMessage(
        game_pk=game_pk,
        inning=about.get("inning"),
        half=about.get("halfInning"),
        away_score=teams_score.get("away", {}).get("runs"),
        home_score=teams_score.get("home", {}).get("runs"),
        away_team=away_team,
        home_team=home_team,
        inning_line=_parse_inning_line(innings) if innings else None,
        batter_id=batter_id,
        batter_name=matchup.get("batter", {}).get("fullName"),
        pitcher_id=pitcher_id,
        pitcher_name=pitcher_name,
        pitcher_key=pitcher_key,
        balls=balls,
        strikes=strikes,
        outs=outs,
        on_1b=on_1b,
        on_2b=on_2b,
        on_3b=on_3b,
        last_pitch=pitch_sequence[-1] if pitch_sequence else None,
        pitch_sequence=pitch_sequence,
        prediction=prediction,
    )

    json_data = state.model_dump_json()
    await redis_client.publish(f"game:{game_pk}", json_data)
    # 최신 상태를 캐싱해 두어 신규 WS 연결 시 즉시 전송
    await redis_client.set(f"game:snapshot:{game_pk}", json_data, ex=300)


# ---------------------------------------------------------------------------
# 폴러 루프
# ---------------------------------------------------------------------------

async def run_poller() -> None:
    redis_client = aioredis.from_url(settings.REDIS_URL)
    interval = settings.MLB_POLL_INTERVAL

    async with httpx.AsyncClient(timeout=10.0) as client:
        while True:
            try:
                games = await get_live_games(client)
                if not games:
                    logger.debug("Live 경기 없음")
                for game in games:
                    await _poll_game(game["gamePk"], client, redis_client)
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("MLB poller 오류")
            await asyncio.sleep(interval)

    await redis_client.aclose()
