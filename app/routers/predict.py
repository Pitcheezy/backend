from fastapi import APIRouter, HTTPException

from app.schemas.pitch import PredictRequest, PredictResponse
from app.services.predictor import run_prediction

router = APIRouter(prefix="/api", tags=["predict"])


@router.post("/predict", response_model=PredictResponse)
async def predict(req: PredictRequest):
    try:
        return run_prediction(req)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Prediction failed")
