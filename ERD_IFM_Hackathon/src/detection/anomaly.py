"""
IsolationForest anomaly scorer and offline training script.

Runtime usage (scorer):
    from src.detection.anomaly import AnomalyScorer
    scorer = AnomalyScorer()
    scorer.load_models("src/detection/models")
    score, is_anomaly = scorer.score("boiler", {"temperature": 160.0, "pressure": 5.5})

Training (offline only):
    python -m src.detection.anomaly --fit
"""
import argparse
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest

logger = logging.getLogger(__name__)

DEVICE_FEATURES: dict[str, list[str]] = {
    "boiler":       ["temperature", "pressure"],
    "pasteurizer":  ["temperature", "ph", "flow_rate"],
    "dryer":        ["temperature", "humidity"],
}

ANOMALY_THRESHOLD = float(os.getenv("ANOMALY_THRESHOLD", "0.0"))


class AnomalyScorer:
    def __init__(self) -> None:
        self._models: dict[str, dict] = {}

    def load_models(self, models_dir: str | Path) -> None:
        models_dir = Path(models_dir)
        missing = []
        for device_type in DEVICE_FEATURES:
            pkl_path = models_dir / f"{device_type}.pkl"
            if not pkl_path.exists():
                missing.append(str(pkl_path))
            else:
                self._models[device_type] = joblib.load(pkl_path)
                logger.info("Loaded model: %s (trained_at=%s, version=%s)",
                            device_type,
                            self._models[device_type].get("trained_at"),
                            self._models[device_type].get("version"))
        if missing:
            raise FileNotFoundError(
                f"Missing model files — run `python -m src.detection.anomaly --fit` first:\n"
                + "\n".join(missing)
            )

    def score(self, device_type: str, payload: dict) -> tuple[float | None, bool]:
        if device_type not in DEVICE_FEATURES:
            logger.warning("Unknown device_type '%s' — skipping scoring", device_type)
            return None, False

        artifact = self._models.get(device_type)
        if artifact is None:
            logger.error("Model for '%s' not loaded — call load_models() first", device_type)
            return None, False

        features = DEVICE_FEATURES[device_type]
        try:
            values = [float(payload.get(f) or 0.0) for f in features]
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Feature extraction failed for {device_type}: {exc}") from exc

        X = np.array(values).reshape(1, -1)
        # decision_function: >0 = inlier, <0 = outlier; threshold 0.0 = anything negative is anomaly
        raw_score: float = float(artifact["model"].decision_function(X)[0])
        is_anomaly = raw_score < ANOMALY_THRESHOLD
        return raw_score, is_anomaly


def train(data_path: str, output_dir: str, version: str = "1.0.0") -> None:
    GREEN = "\033[92m"
    RESET = "\033[0m"

    print(f"[TRAIN] Loading baseline: {data_path}")
    try:
        df = pd.read_csv(data_path)
    except FileNotFoundError:
        print(f"[ERROR] Baseline CSV not found: {data_path}", file=sys.stderr)
        sys.exit(1)
    except Exception as exc:
        print(f"[ERROR] Could not read baseline CSV: {exc}", file=sys.stderr)
        sys.exit(1)

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    trained_at = datetime.now(timezone.utc).isoformat()
    saved = []

    for device_type, features in DEVICE_FEATURES.items():
        subset = df[df["device_type"] == device_type][features].dropna()
        if subset.empty:
            print(f"[WARN ] {device_type:<12} — no rows in baseline CSV; skipping", file=sys.stderr)
            continue

        clf = IsolationForest(contamination=0.05, random_state=42)
        clf.fit(subset.values)

        artifact = {
            "model": clf,
            "trained_at": trained_at,
            "version": version,
            "features": features,
        }
        pkl_path = output_path / f"{device_type}.pkl"
        joblib.dump(artifact, pkl_path)
        saved.append(device_type)
        print(f"{GREEN}[TRAIN] {device_type:<12} - {len(subset):>4} rows -> saved {pkl_path}{RESET}")

    if not saved:
        print("[ERROR] No models trained — check baseline CSV device_type values.", file=sys.stderr)
        sys.exit(2)

    print(f"[TRAIN] Training complete. {len(saved)} model(s) saved.")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="IFM Anomaly Detector — training script")
    parser.add_argument("--fit", action="store_true", required=True, help="Fit and save models")
    parser.add_argument("--data-path", default="data/telemetry_baseline.csv",
                        help="Path to baseline CSV (default: data/telemetry_baseline.csv)")
    parser.add_argument("--output-dir", default="src/detection/models",
                        help="Directory to write .pkl files (default: src/detection/models)")
    parser.add_argument("--version", default="1.0.0", help="Model version string (default: 1.0.0)")
    args = parser.parse_args()

    if args.fit:
        train(args.data_path, args.output_dir, args.version)
