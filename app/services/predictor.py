from app.ml.inference import predict as ml_predict
from app.schemas.pitch import PredictRequest, PredictResponse


def run_prediction(req: PredictRequest) -> PredictResponse:
    result = ml_predict(
        pitcher_key=req.pitcher_key,
        balls=req.balls,
        strikes=req.strikes,
        outs=req.outs,
        on_1b=req.on_1b,
        on_2b=req.on_2b,
        on_3b=req.on_3b,
        batter_id=req.batter_id,
    )
    return PredictResponse(
        pitcher_key=req.pitcher_key,
        pitch_type=result["pitch_type"],
        zone=result["zone"],
        action=result["action"],
        batter_cluster=result["batter_cluster"],
        confidence=result["confidence"],
    )
