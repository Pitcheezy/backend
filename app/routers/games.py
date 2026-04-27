from datetime import date
from typing import Optional

import httpx
from fastapi import APIRouter, HTTPException, Query

from app.schemas.common import err, ok

router = APIRouter(prefix="/api/games", tags=["games"])

MLB_BASE = "https://statsapi.mlb.com/api/v1"

_STATUS_MAP = {
    "Live": "live",
    "Final": "final",
    "Preview": "scheduled",
    "Cancelled": "cancelled",
    "Postponed": "postponed",
}


def _format_game(game: dict) -> dict:
    status_raw = game.get("status", {}).get("abstractGameState", "")
    linescore = game.get("linescore", {})
    teams_score = linescore.get("teams", {})
    away = game["teams"]["away"]["team"]
    home = game["teams"]["home"]["team"]

    return {
        "game_pk": game["gamePk"],
        "status": _STATUS_MAP.get(status_raw, status_raw.lower()),
        "inning": linescore.get("currentInning"),
        "half": (linescore.get("inningHalf") or "").lower() or None,
        "away_team": {
            "id": away["id"],
            "name": away["name"],
            "code": away.get("abbreviation", ""),
        },
        "home_team": {
            "id": home["id"],
            "name": home["name"],
            "code": home.get("abbreviation", ""),
        },
        "away_score": teams_score.get("away", {}).get("runs"),
        "home_score": teams_score.get("home", {}).get("runs"),
        "starts_at": game.get("gameDate"),
        "venue": game.get("venue", {}).get("name"),
    }


@router.get("")
async def list_games(
    status: Optional[str] = Query(None, description="live | scheduled | final"),
    date: Optional[str] = Query(None, description="YYYY-MM-DD (기본값: 오늘)"),
):
    """오늘(또는 지정일) 경기 목록 반환."""
    target_date = date or __import__("datetime").date.today().strftime("%Y-%m-%d")
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(
            f"{MLB_BASE}/schedule",
            params={"sportId": 1, "date": target_date, "hydrate": "linescore,team"},
        )
        if resp.status_code != 200:
            return err("MLB_API_ERROR", "MLB Schedule API 호출 실패")
        data = resp.json()

    games = [
        _format_game(g)
        for d in data.get("dates", [])
        for g in d.get("games", [])
    ]

    if status:
        games = [g for g in games if g["status"] == status]

    return ok(games)


@router.get("/{game_pk}")
async def get_game(game_pk: int):
    """단건 경기 정보 반환."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(
            f"{MLB_BASE}/schedule",
            params={"gamePks": game_pk, "hydrate": "linescore,team"},
        )
        if resp.status_code != 200:
            return err("MLB_API_ERROR", "MLB Schedule API 호출 실패")
        data = resp.json()

    games = [
        g
        for d in data.get("dates", [])
        for g in d.get("games", [])
        if g["gamePk"] == game_pk
    ]
    if not games:
        raise HTTPException(status_code=404, detail=f"game_pk={game_pk} 를 찾을 수 없습니다")

    return ok(_format_game(games[0]))
