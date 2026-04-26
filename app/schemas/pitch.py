from datetime import datetime
from typing import Optional
from pydantic import BaseModel, field_validator


class PredictRequest(BaseModel):
    pitcher_key: str  # "cease" | "gallen" | "cole"
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


class GameStateMessage(BaseModel):
    """Payload broadcast via WebSocket / Redis Pub-Sub."""
    game_pk: int
    inning: Optional[int] = None
    inning_half: Optional[str] = None
    batter_id: Optional[int] = None
    batter_name: Optional[str] = None
    pitcher_id: Optional[int] = None
    pitcher_name: Optional[str] = None
    balls: int = 0
    strikes: int = 0
    outs: int = 0
    on_1b: bool = False
    on_2b: bool = False
    on_3b: bool = False
    prediction: Optional[PredictResponse] = None


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
