import logging
from pathlib import Path

import pandas as pd
from stable_baselines3 import DQN

from app.config import settings

logger = logging.getLogger(__name__)

# Pitcher-specific pitch name ordering (must match MODEL_USAGE.md exactly)
PITCHER_PITCHES: dict[str, list[str]] = {
    "cole": ["Fastball", "Slider", "Curveball", "Changeup"],
    "cease": ["Fastball", "Slider", "Changeup"],
    "gallen": ["Fastball", "Slider", "Changeup", "Curveball"],
}

PITCHER_MODEL_FILES: dict[str, str] = {
    "cole": "smartpitch_dqn_final.zip",
    "cease": "dqn_cease_2024_2025.zip",
    "gallen": "dqn_gallen_2024_2025.zip",
}

# 13 zones: 1-9 (strike zone grid) + 11-14 (outer zones)
ZONES: list[int] = [1, 2, 3, 4, 5, 6, 7, 8, 9, 11, 12, 13, 14]

# Runtime state (populated by load_all)
loaded_models: dict[str, DQN] = {}
batter_clusters: dict[int, int] = {}


def load_all() -> None:
    models_dir = Path(settings.ML_MODELS_DIR)
    data_dir = models_dir / "data"

    _load_batter_clusters(data_dir)
    _load_dqn_models(models_dir)


def _load_batter_clusters(data_dir: Path) -> None:
    csv_path = data_dir / "batter_clusters_2023.csv"
    if not csv_path.exists():
        logger.warning("batter_clusters_2023.csv not found at %s", csv_path)
        return

    df = pd.read_csv(csv_path)
    for _, row in df.iterrows():
        batter_clusters[int(row["batter_id"])] = int(row["cluster"])

    logger.info("Loaded %d batter clusters", len(batter_clusters))


def _load_dqn_models(models_dir: Path) -> None:
    for key, filename in PITCHER_MODEL_FILES.items():
        model_path = models_dir / filename
        if not model_path.exists():
            logger.warning("DQN model not found: %s (pitcher=%s)", model_path, key)
            continue
        try:
            loaded_models[key] = DQN.load(str(model_path))
            logger.info("Loaded DQN model: %s", key)
        except Exception:
            logger.exception("Failed to load DQN model: %s", key)
