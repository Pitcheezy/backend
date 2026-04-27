from datetime import datetime
from typing import Optional
from pydantic import BaseModel, field_validator


# ---------------------------------------------------------------------------
# 공통 서브 모델
# ---------------------------------------------------------------------------

class TeamInfo(BaseModel):
    id: int
    name: str
    code: str  # abbreviation (e.g. "NYY")


class LastPitch(BaseModel):
    pitch_type: Optional[str] = None
    zone: Optional[int] = None
    velocity: Optional[float] = None   # mph
    result: Optional[str] = None       # "ball" | "strike" | "foul" | "in_play" ...


class InningLine(BaseModel):
    away: list[Optional[int]]  # index = inning - 1, None = 아직 미플레이
    home: list[Optional[int]]


# ---------------------------------------------------------------------------
# 예측 요청 / 응답
# ---------------------------------------------------------------------------

class PredictRequest(BaseModel):
    # pitcher_key 또는 pitcher_id 중 하나 필수
    pitcher_key: Optional[str] = None   # "cease" | "gallen" | "cole"
    pitcher_id: Optional[int] = None    # MLB pitcher ID (pitcher_key 없을 때 사용)
    batter_id: int
    balls: int
    strikes: int
    outs: int
    on_1b: bool = False
    on_2b: bool = False
    on_3b: bool = False

    @field_validator("balls")
    @classmethod
    def balls_range(cls, v: int) -> int:
        assert 0 <= v <= 3, "balls must be 0-3"
        return v

    @field_validator("strikes")
    @classmethod
    def strikes_range(cls, v: int) -> int:
        assert 0 <= v <= 2, "strikes must be 0-2"
        return v

    @field_validator("outs")
    @classmethod
    def outs_range(cls, v: int) -> int:
        assert 0 <= v <= 2, "outs must be 0-2"
        return v


class PredictResponse(BaseModel):
    pitcher_key: str
    pitch_type: str
    zone: int
    batter_cluster: int
    action: int
    confidence: Optional[float] = None  # Q-value softmax 확률 (0~1)


# ---------------------------------------------------------------------------
# WebSocket 브로드캐스트 메시지
# ---------------------------------------------------------------------------

class GameStateMessage(BaseModel):
    game_pk: int

    # 경기 상황
    inning: Optional[int] = None
    half: Optional[str] = None          # "top" | "bottom"
    away_score: Optional[int] = None
    home_score: Optional[int] = None
    away_team: Optional[TeamInfo] = None
    home_team: Optional[TeamInfo] = None
    inning_line: Optional[InningLine] = None

    # 현재 타석
    batter_id: Optional[int] = None
    batter_name: Optional[str] = None
    pitcher_id: Optional[int] = None
    pitcher_name: Optional[str] = None
    pitcher_key: Optional[str] = None   # 모델 키 ("cease" | "gallen" | "cole" | null)

    # 카운트
    balls: int = 0
    strikes: int = 0
    outs: int = 0

    # 루상황
    on_1b: bool = False
    on_2b: bool = False
    on_3b: bool = False

    # 직전 투구
    last_pitch: Optional[LastPitch] = None

    # 현재 타석 전체 투구 시퀀스 (oldest first)
    pitch_sequence: list[LastPitch] = []

    # ML 예측
    prediction: Optional[PredictResponse] = None


# ---------------------------------------------------------------------------
# DB 조회용
# ---------------------------------------------------------------------------

class PitchRecord(BaseModel):
    id: int
    game_pk: int
    at_bat_index: int
    pitch_number: int
    inning: Optional[int] = None
    pitcher_id: Optional[int] = None
    batter_id: Optional[int] = None
    balls: Optional[int] = None
    strikes: Optional[int] = None
    outs: Optional[int] = None
    pitch_type: Optional[str] = None
    zone: Optional[int] = None
    result: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}
