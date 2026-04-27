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
from collections import defaultdict

import httpx
import redis.asyncio as aioredis

from app.config import settings
from app.ml.inference import predict as ml_predict
from app.ml.loader import loaded_models
from app.schemas.pitch import (
    GameStateMessage, HitterLiveStats, InningLine, InningPitchCount,
    LastPitch, PitchMixEntry, PitcherLiveStats, PredictResponse, TeamInfo,
)
from app.services.mlb_poller import resolve_pitcher_key

logger = logging.getLogger(__name__)

_replay_task: asyncio.Task | None = None
_replay_game_pk: int | None = None


# ---------------------------------------------------------------------------
# 데이터 추출
# ---------------------------------------------------------------------------

def _parse_team_info(team_data: dict) -> TeamInfo:
    return TeamInfo(
        id=team_data.get("id", 0),
        name=team_data.get("name", ""),
        code=team_data.get("abbreviation", ""),
    )


def _build_inning_line(inning_runs: dict[int, dict], max_inning: int) -> InningLine:
    """현재 이닝까지의 득점 라인을 구성한다. 미플레이 이닝은 None."""
    away: list[int | None] = []
    home: list[int | None] = []
    for inn in range(1, max_inning + 1):
        runs = inning_runs.get(inn, {})
        away.append(runs.get("away"))
        home.append(runs.get("home"))
    return InningLine(away=away, home=home)


def _extract_pitches(all_plays: list[dict]) -> list[dict]:
    """allPlays에서 투구 단위 상태 목록을 추출한다.

    각 항목에 누적 점수, inning_line 스냅샷, last_pitch, pitch_sequence를 포함한다.
    점수는 해당 타석 시작 시점 기준(타석 종료 후 득점 반영).
    """
    pitches: list[dict] = []
    on_1b = on_2b = on_3b = False
    current_batter_id: int | None = None
    current_at_bat_sequence: list[dict] = []
    away_score = 0
    home_score = 0
    # inning_runs[inning] = {"away": int, "home": int}
    # None 값은 "아직 해당 이닝이 시작 안 됨"을 의미
    inning_runs: dict[int, dict] = {}

    for play in all_plays:
        matchup = play.get("matchup", {})
        about = play.get("about", {})
        batter_id: int | None = matchup.get("batter", {}).get("id")
        inning: int = about.get("inning", 1)
        half: str = about.get("halfInning", "top")

        # 이닝 첫 등장 시 초기화
        if inning not in inning_runs:
            inning_runs[inning] = {"away": None, "home": None}
        if half == "top" and inning_runs[inning]["away"] is None:
            inning_runs[inning]["away"] = 0
        if half == "bottom" and inning_runs[inning]["home"] is None:
            inning_runs[inning]["home"] = 0

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
                "inning": inning,
                "half": half,
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
                "away_score": away_score,
                "home_score": home_score,
                "inning_runs": {k: dict(v) for k, v in inning_runs.items()},
                "last_pitch": pitch_detail,
                "pitch_sequence": list(current_at_bat_sequence),
            })

        # 타석 종료 후 득점 및 주자 상황 업데이트
        on_1b = on_2b = on_3b = False
        for runner in play.get("runners", []):
            end = runner.get("movement", {}).get("end", "")
            if end == "score":
                if half == "top":
                    away_score += 1
                    inning_runs[inning]["away"] = (inning_runs[inning].get("away") or 0) + 1
                else:
                    home_score += 1
                    inning_runs[inning]["home"] = (inning_runs[inning].get("home") or 0) + 1
            elif end == "1B":
                on_1b = True
            elif end == "2B":
                on_2b = True
            elif end == "3B":
                on_3b = True

    return pitches


# ---------------------------------------------------------------------------
# 시즌 스탯 조회
# ---------------------------------------------------------------------------

async def _fetch_season_stats(
    pitcher_ids: list[int],
    batter_ids: list[int],
    season: int,
) -> tuple[dict[int, dict], dict[int, dict]]:
    """MLB Stats API에서 투수·타자 시즌 스탯을 병렬로 가져온다."""

    async def fetch_one(client: httpx.AsyncClient, pid: int, group: str) -> tuple[int, dict]:
        try:
            resp = await client.get(
                f"https://statsapi.mlb.com/api/v1/people/{pid}",
                params={"hydrate": f"stats(group=[{group}],type=season,season={season})"},
                timeout=10.0,
            )
            data = resp.json()
            splits = (
                data.get("people", [{}])[0]
                    .get("stats", [{}])[0]
                    .get("splits", [])
            )
            return pid, splits[0].get("stat", {}) if splits else {}
        except Exception:
            return pid, {}

    async with httpx.AsyncClient() as client:
        pitcher_results, batter_results = await asyncio.gather(
            asyncio.gather(*[fetch_one(client, pid, "pitching") for pid in pitcher_ids]),
            asyncio.gather(*[fetch_one(client, pid, "hitting") for pid in batter_ids]),
        )

    return dict(pitcher_results), dict(batter_results)


def _parse_pitcher_season(raw: dict) -> dict:
    def _f(key: str) -> float | None:
        v = raw.get(key)
        try:
            return float(v) if v is not None else None
        except (ValueError, TypeError):
            return None

    ip_str = raw.get("inningsPitched")
    ip: float | None = None
    if ip_str:
        try:
            parts = str(ip_str).split(".")
            ip = int(parts[0]) + (int(parts[1]) / 3 if len(parts) > 1 else 0)
        except Exception:
            pass

    return {
        "era": _f("era"),
        "whip": _f("whip"),
        "k9": _f("strikeoutsPer9Inn"),
        "ip": ip,
    }


def _parse_batter_season(raw: dict) -> dict:
    def _f(key: str) -> float | None:
        v = raw.get(key)
        try:
            return float(v) if v is not None else None
        except (ValueError, TypeError):
            return None

    def _i(key: str) -> int | None:
        v = raw.get(key)
        try:
            return int(v) if v is not None else None
        except (ValueError, TypeError):
            return None

    return {
        "avg": _f("avg"),
        "ops": _f("ops"),
        "hr": _i("homeRuns"),
        "rbi": _i("rbi"),
    }


# ---------------------------------------------------------------------------
# 투수 게임 내 누적 통계 추적
# ---------------------------------------------------------------------------

class _PitcherTracker:
    def __init__(self) -> None:
        self._pitches: list[dict] = []  # {pitch_type, velocity, inning}

    def record(self, pitch_type: str | None, velocity: float | None, inning: int) -> None:
        self._pitches.append({"pitch_type": pitch_type, "velocity": velocity, "inning": inning})

    def build_stats(self, season: dict) -> PitcherLiveStats:
        total = len(self._pitches)

        # 구종 믹스
        mix_counts: dict[str, list[float]] = defaultdict(list)
        for p in self._pitches:
            if p["pitch_type"]:
                if p["velocity"]:
                    mix_counts[p["pitch_type"]].append(p["velocity"])
                else:
                    mix_counts.setdefault(p["pitch_type"], [])

        pitch_mix = sorted(
            [
                PitchMixEntry(
                    pitch_type=pt,
                    count=len(vels) if vels else mix_counts[pt].__len__(),
                    share=len(mix_counts[pt]) / total if total else 0,
                    avg_velocity=sum(vels) / len(vels) if vels else None,
                )
                for pt, vels in mix_counts.items()
            ],
            key=lambda e: -e.count,
        )

        # 구속 추이 (최근 30구)
        all_vels = [p["velocity"] for p in self._pitches if p["velocity"]]
        velocity_trend = all_vels[-30:]
        current_velocity = all_vels[-1] if all_vels else None
        peak_velocity = max(all_vels) if all_vels else None

        # 이닝별 투구 수
        inning_map: dict[int, int] = defaultdict(int)
        for p in self._pitches:
            inning_map[p["inning"]] += 1
        inning_pitches = [
            InningPitchCount(inning=inn, count=cnt)
            for inn, cnt in sorted(inning_map.items())
        ]

        # 교체 지수: 투구수 + 구속 낙폭 반영
        velocity_drop = (peak_velocity - current_velocity) if (peak_velocity and current_velocity) else 0.0
        change_index = min(100.0, total * 0.25 + velocity_drop * 5.0)

        return PitcherLiveStats(
            era=season.get("era"),
            whip=season.get("whip"),
            k9=season.get("k9"),
            ip_season=season.get("ip"),
            pitches_today=total,
            pitch_mix=pitch_mix,
            velocity_trend=velocity_trend,
            current_velocity=current_velocity,
            peak_velocity=peak_velocity,
            inning_pitches=inning_pitches,
            change_index=change_index,
        )


async def _fetch_game_data(game_pk: int) -> tuple[list[dict], TeamInfo | None, TeamInfo | None]:
    """MLB Stats API에서 경기 피드를 가져와 (pitches, away_team, home_team)을 반환한다."""
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(
            f"https://statsapi.mlb.com/api/v1.1/game/{game_pk}/feed/live"
        )
        resp.raise_for_status()
        data = resp.json()

    all_plays = data.get("liveData", {}).get("plays", {}).get("allPlays", [])
    if not all_plays:
        raise ValueError(f"game_pk={game_pk} 에서 투구 데이터를 찾을 수 없습니다")

    gd_teams = data.get("gameData", {}).get("teams", {})
    away_team = _parse_team_info(gd_teams["away"]) if gd_teams.get("away") else None
    home_team = _parse_team_info(gd_teams["home"]) if gd_teams.get("home") else None

    pitches = _extract_pitches(all_plays)
    logger.info("game_pk=%d 에서 투구 %d개 로드 완료 (%s vs %s)",
                game_pk, len(pitches),
                away_team.code if away_team else "?",
                home_team.code if home_team else "?")
    return pitches, away_team, home_team


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
    pitches, away_team, home_team = await _fetch_game_data(game_pk)

    # 게임에 등장하는 전체 투수·타자 ID 추출 후 시즌 스탯 일괄 조회
    pitcher_ids = list({p["pitcher_id"] for p in pitches if p["pitcher_id"]})
    batter_ids = list({p["batter_id"] for p in pitches if p["batter_id"]})
    # 경기 날짜에서 시즌 연도 추출 (첫 투구 기준)
    season = 2026

    logger.info("시즌 스탯 조회 중: 투수 %d명, 타자 %d명 (season=%d)", len(pitcher_ids), len(batter_ids), season)
    raw_pitcher_stats, raw_batter_stats = await _fetch_season_stats(pitcher_ids, batter_ids, season)
    pitcher_season: dict[int, dict] = {pid: _parse_pitcher_season(s) for pid, s in raw_pitcher_stats.items()}
    batter_season: dict[int, dict] = {bid: _parse_batter_season(s) for bid, s in raw_batter_stats.items()}
    logger.info("시즌 스탯 조회 완료")

    redis_client = aioredis.from_url(settings.REDIS_URL)
    channel = f"game:{game_pk}"

    # 투수별 게임 내 누적 추적기
    pitcher_trackers: dict[int, _PitcherTracker] = defaultdict(_PitcherTracker)

    logger.info("replay 시작: game_pk=%d, 투구수=%d, interval=%.1fs", game_pk, len(pitches), interval)

    try:
        for i, pitch in enumerate(pitches):
            pitcher_id = pitch["pitcher_id"]
            lp_data = pitch.get("last_pitch", {})

            # 이번 투구를 먼저 기록한 뒤 통계 계산 (현재 투구 포함)
            if pitcher_id:
                pitcher_trackers[pitcher_id].record(
                    lp_data.get("pitch_type"),
                    lp_data.get("velocity"),
                    pitch["inning"],
                )

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

            inning_runs = pitch.get("inning_runs", {})
            max_inning = pitch["inning"]
            inning_line = _build_inning_line(inning_runs, max_inning)

            # 투수 라이브 스탯 (게임 내 누적 + 시즌)
            pitcher_stats: PitcherLiveStats | None = None
            if pitcher_id:
                pitcher_stats = pitcher_trackers[pitcher_id].build_stats(
                    pitcher_season.get(pitcher_id, {})
                )

            # 타자 라이브 스탯 (시즌)
            batter_id = pitch["batter_id"]
            batter_stats: HitterLiveStats | None = None
            if batter_id and batter_id in batter_season:
                bs = batter_season[batter_id]
                batter_stats = HitterLiveStats(
                    avg=bs.get("avg"),
                    ops=bs.get("ops"),
                    hr=bs.get("hr"),
                    rbi=bs.get("rbi"),
                )

            state = GameStateMessage(
                game_pk=game_pk,
                inning=pitch["inning"],
                half=pitch["half"],
                away_team=away_team,
                home_team=home_team,
                away_score=pitch["away_score"],
                home_score=pitch["home_score"],
                inning_line=inning_line,
                batter_id=batter_id,
                batter_name=pitch["batter_name"],
                pitcher_id=pitcher_id,
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
                pitcher_stats=pitcher_stats,
                batter_stats=batter_stats,
            )
            json_data = state.model_dump_json()
            await redis_client.publish(channel, json_data)
            await redis_client.set(f"game:snapshot:{game_pk}", json_data, ex=300)
            logger.debug("replay [%d/%d] inn=%s %s  %s vs %s  %d-%d",
                         i + 1, len(pitches),
                         pitch["inning"], pitch["half"],
                         pitch["pitcher_name"], pitch["batter_name"],
                         pitch["away_score"], pitch["home_score"])
            await asyncio.sleep(interval)

        logger.info("replay 완료: game_pk=%d", game_pk)

    except asyncio.CancelledError:
        logger.info("replay 중단: game_pk=%d", game_pk)
    except Exception:
        logger.exception("replay 루프 예외 발생: game_pk=%d", game_pk)
    finally:
        await redis_client.aclose()


# ---------------------------------------------------------------------------
# 공개 인터페이스
# ---------------------------------------------------------------------------

def is_running() -> bool:
    return _replay_task is not None and not _replay_task.done()


def current_game_pk() -> int | None:
    return _replay_game_pk if is_running() else None


async def start(game_pk: int, interval: float = 5.0) -> None:
    global _replay_task, _replay_game_pk
    if is_running():
        raise RuntimeError("이미 replay가 실행 중입니다. 먼저 중단하세요.")
    _replay_game_pk = game_pk
    _replay_task = asyncio.create_task(_replay_loop(game_pk, interval))


def stop() -> None:
    global _replay_task, _replay_game_pk
    if _replay_task and not _replay_task.done():
        _replay_task.cancel()
    _replay_task = None
    _replay_game_pk = None
