"""Unit tests for AnomalyScorer — T024."""
import logging
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from src.detection.anomaly import ANOMALY_THRESHOLD, DEVICE_FEATURES, AnomalyScorer


def _make_mock_model(score: float) -> dict:
    """Return a fake model artifact dict whose decision_function returns `score`."""
    model = MagicMock()
    model.decision_function.return_value = np.array([score])
    return {"model": model, "trained_at": "2026-06-09T00:00:00", "version": "1.0.0",
            "features": ["temperature", "pressure"]}


class TestDeviceFeaturesRegistry:
    def test_all_three_devices_present(self):
        assert "boiler" in DEVICE_FEATURES
        assert "pasteurizer" in DEVICE_FEATURES
        assert "dryer" in DEVICE_FEATURES

    def test_boiler_features(self):
        assert DEVICE_FEATURES["boiler"] == ["temperature", "pressure"]

    def test_pasteurizer_features(self):
        assert DEVICE_FEATURES["pasteurizer"] == ["temperature", "ph", "flow_rate"]

    def test_dryer_features(self):
        assert DEVICE_FEATURES["dryer"] == ["temperature", "humidity"]


class TestAnomalyScorerScore:
    def _scorer_with_model(self, device_type: str, score: float) -> AnomalyScorer:
        scorer = AnomalyScorer()
        features = DEVICE_FEATURES[device_type]
        model = MagicMock()
        model.decision_function.return_value = np.array([score])
        scorer._models[device_type] = {"model": model, "features": features}
        return scorer

    def test_above_threshold_returns_ok(self):
        scorer = self._scorer_with_model("boiler", 0.05)
        raw, is_anomaly = scorer.score("boiler", {"temperature": 160.0, "pressure": 5.5})
        assert raw == pytest.approx(0.05)
        assert is_anomaly is False

    def test_below_threshold_returns_anomaly(self):
        scorer = self._scorer_with_model("boiler", -0.15)
        raw, is_anomaly = scorer.score("boiler", {"temperature": 210.0, "pressure": 13.0})
        assert raw == pytest.approx(-0.15)
        assert is_anomaly is True

    def test_equal_to_threshold_not_anomaly(self):
        scorer = self._scorer_with_model("dryer", ANOMALY_THRESHOLD)
        _, is_anomaly = scorer.score("dryer", {"temperature": 111.0, "humidity": 30.0})
        assert is_anomaly is False

    def test_unknown_device_type_returns_none_false(self, caplog):
        scorer = AnomalyScorer()
        with caplog.at_level(logging.WARNING):
            raw, is_anomaly = scorer.score("mixer", {"temperature": 100.0})
        assert raw is None
        assert is_anomaly is False
        assert "Unknown device_type" in caplog.text

    def test_pasteurizer_uses_only_pasteurizer_features(self):
        scorer = AnomalyScorer()
        model = MagicMock()
        model.decision_function.return_value = np.array([0.1])
        scorer._models["pasteurizer"] = {
            "model": model,
            "features": ["temperature", "ph", "flow_rate"],
        }
        scorer.score("pasteurizer", {
            "temperature": 82.0, "ph": 6.2, "flow_rate": 96.0, "pressure": 5.5
        })
        call_args = model.decision_function.call_args[0][0]
        assert call_args.shape == (1, 3)


class TestAnomalyScorerLoadModels:
    def test_missing_model_raises(self, tmp_path):
        scorer = AnomalyScorer()
        with pytest.raises(FileNotFoundError) as exc_info:
            scorer.load_models(tmp_path)
        assert "run" in str(exc_info.value).lower()

    def test_loads_valid_pkl(self, tmp_path):
        import joblib
        from sklearn.ensemble import IsolationForest
        clf = IsolationForest(random_state=42)
        clf.fit([[160.0, 5.5], [158.0, 5.3], [162.0, 5.7]])
        for dt in DEVICE_FEATURES:
            artifact = {"model": clf, "trained_at": "2026-06-09T00:00:00",
                        "version": "1.0.0", "features": DEVICE_FEATURES[dt]}
            joblib.dump(artifact, tmp_path / f"{dt}.pkl")
        scorer = AnomalyScorer()
        scorer.load_models(tmp_path)
        assert "boiler" in scorer._models
        assert "pasteurizer" in scorer._models
        assert "dryer" in scorer._models
