from fastapi import APIRouter, HTTPException

from app.ml.loader import PITCHER_ID_MAP
from app.schemas.pitch import PredictRequest, PredictResponse
from app.services.predictor import run_prediction

router = APIRouter(prefix="/api", tags=["predict"])


@router.post("/predict", response_model=PredictResponse)
async def predict(req: PredictRequest):
    # pitcher_key 없으면 pitcher_id로 resolve
    if not req.pitcher_key:
        if req.pitcher_id is None:
            raise HTTPException(
                status_code=400, detail="pitcher_key 또는 pitcher_id 중 하나는 필수입니다"
            )
        key = PITCHER_ID_MAP.get(req.pitcher_id)
        if key is None:
            raise HTTPException(
                status_code=400,
                detail=f"pitcher_id={req.pitcher_id} 에 매핑된 모델이 없습니다",
            )
        req = req.model_copy(update={"pitcher_key": key})

    try:
        return run_prediction(req)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception:
        raise HTTPException(status_code=500, detail="Prediction failed")
