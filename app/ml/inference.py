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

    # Q-value softmax → confidence
    confidence: float | None = None
    try:
        obs_th, _ = model.policy.obs_to_tensor(obs[np.newaxis, :])
        with torch.no_grad():
            q_values = model.policy.q_net(obs_th)
            probs = torch.softmax(q_values, dim=-1)
            confidence = round(float(probs[0, action].item()), 4)
    except Exception:
        logger.debug("confidence 계산 실패", exc_info=True)

    return {
        "pitch_type": pitch_type,
        "zone": zone,
        "action": action,
        "batter_cluster": batter_cluster,
        "confidence": confidence,
    }
