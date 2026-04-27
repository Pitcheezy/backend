import logging

import numpy as np
import torch

from app.ml.loader import PITCHER_PITCHES, ZONES, batter_clusters, loaded_models

logger = logging.getLogger(__name__)

DEFAULT_BATTER_CLUSTER = 4  # median cluster used when batter not in lookup


def get_batter_cluster(batter_id: int) -> int:
    return batter_clusters.get(batter_id, DEFAULT_BATTER_CLUSTER)


def predict(
    pitcher_key: str,
    balls: int,
    strikes: int,
    outs: int,
    on_1b: bool,
    on_2b: bool,
    on_3b: bool,
    batter_id: int,
) -> dict:
    model = loaded_models.get(pitcher_key)
    if model is None:
        raise ValueError(f"Model for pitcher '{pitcher_key}' not loaded")

    batter_cluster = get_batter_cluster(batter_id)

    # 8-dim observation: [balls, strikes, outs, 1b, 2b, 3b, batter_cluster, pitcher_cluster]
    # pitcher_cluster is always 0 per MODEL_USAGE.md
    obs = np.array(
        [balls, strikes, outs, int(on_1b), int(on_2b), int(on_3b), batter_cluster, 0],
        dtype=np.float32,
    )

    action, _ = model.predict(obs, deterministic=True)
    action = int(action)

    pitch_names = PITCHER_PITCHES[pitcher_key]
    pitch_idx = action // 13
    zone_idx = action % 13

    pitch_type = pitch_names[pitch_idx] if pitch_idx < len(pitch_names) else "Unknown"
    zone = ZONES[zone_idx] if zone_idx < len(ZONES) else 0

    # Q-value 기반 신뢰도: 선택 액션 확률 / 상위 3개 확률 합
    # (전체 액션 softmax 대비 비율 대신 상위 후보 내 상대 신뢰도로 표현)
    confidence: float | None = None
    try:
        obs_th, _ = model.policy.obs_to_tensor(obs[np.newaxis, :])
        with torch.no_grad():
            q_values = model.policy.q_net(obs_th)
            probs = torch.softmax(q_values, dim=-1)
            chosen_prob = float(probs[0, action].item())
            top3_sum = float(probs[0].topk(3).values.sum().item())
            confidence = round(chosen_prob / top3_sum if top3_sum > 0 else 0.0, 4)
    except Exception:
        logger.debug("confidence 계산 실패", exc_info=True)

    return {
        "pitch_type": pitch_type,
        "zone": zone,
        "action": action,
        "batter_cluster": batter_cluster,
        "confidence": confidence,
    }
