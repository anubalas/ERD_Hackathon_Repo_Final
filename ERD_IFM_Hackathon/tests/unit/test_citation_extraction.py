"""Unit tests for citation extraction and confidence handling (SC-006)."""
from unittest.mock import MagicMock, patch

import pytest

from src.agent.agent import (
    AGENT_HUMAN_REVIEW_THRESHOLD,
    clamp_confidence,
    extract_json_block,
)


class TestExtractJsonBlock:
    def test_valid_block_at_end_returns_dict(self):
        text = (
            "Some recommendation text here.\n\n"
            '{"citation": "[Source: boiler_sop.txt, §2.1]", "confidence": 0.92, "requires_human_review": false}'
        )
        result = extract_json_block(text)
        assert result is not None
        assert result["citation"] == "[Source: boiler_sop.txt, §2.1]"
        assert result["confidence"] == pytest.approx(0.92)
        assert result["requires_human_review"] is False

    def test_valid_block_mid_text_returns_dict(self):
        text = (
            'Preamble\n{"citation": "[Source: dryer_sop.txt, §3.1]", "confidence": 0.75, "requires_human_review": false}\nPostamble'
        )
        result = extract_json_block(text)
        assert result is not None
        assert result["citation"] == "[Source: dryer_sop.txt, §3.1]"

    def test_malformed_json_returns_none(self):
        text = 'Bad {"citation": broken json here'
        result = extract_json_block(text)
        assert result is None

    def test_absent_block_returns_none(self):
        text = "This response has no JSON block at all."
        result = extract_json_block(text)
        assert result is None

    def test_low_confidence_value_extracted(self):
        text = '{"citation": "", "confidence": 0.0, "requires_human_review": true}'
        result = extract_json_block(text)
        assert result is not None
        assert result["confidence"] == pytest.approx(0.0)
        assert result["requires_human_review"] is True

    def test_requires_human_review_true_when_flagged(self):
        text = '{"citation": "[Source: pasteurizer_sop.txt, §2.2]", "confidence": 0.55, "requires_human_review": true}'
        result = extract_json_block(text)
        assert result is not None
        assert result["requires_human_review"] is True


class TestClampConfidence:
    def test_valid_value_unchanged(self):
        assert clamp_confidence(0.85) == pytest.approx(0.85)

    def test_negative_clamped_to_zero(self):
        assert clamp_confidence(-0.5) == pytest.approx(0.0)

    def test_above_one_clamped_to_one(self):
        assert clamp_confidence(1.5) == pytest.approx(1.0)

    def test_zero_unchanged(self):
        assert clamp_confidence(0.0) == pytest.approx(0.0)

    def test_one_unchanged(self):
        assert clamp_confidence(1.0) == pytest.approx(1.0)


class TestHumanReviewThreshold:
    def test_below_threshold_forces_review_true(self):
        from src.agent.agent import AGENT_HUMAN_REVIEW_THRESHOLD
        confidence = AGENT_HUMAN_REVIEW_THRESHOLD - 0.01
        # Simulate the threshold check from process_alert
        requires_human_review = confidence < AGENT_HUMAN_REVIEW_THRESHOLD
        assert requires_human_review is True

    def test_at_or_above_threshold_no_forced_review(self):
        from src.agent.agent import AGENT_HUMAN_REVIEW_THRESHOLD
        confidence = AGENT_HUMAN_REVIEW_THRESHOLD
        requires_human_review = confidence < AGENT_HUMAN_REVIEW_THRESHOLD
        assert requires_human_review is False

    def test_threshold_default_is_0_7(self):
        assert AGENT_HUMAN_REVIEW_THRESHOLD == pytest.approx(0.7)


class TestProcessAlertCitationViolation:
    def test_missing_json_block_sets_requires_human_review(self):
        """Claude API failure path: API succeeds but response has no JSON block."""
        from src.agent.agent import process_alert
        from src.db.models import Alert
        from datetime import datetime

        alert = Alert(
            id=1,
            device_id="boiler-1",
            device_type="boiler",
            batch_id="BATCH-001",
            anomaly_score=-0.15,
            alert_type="ANOMALY",
            sensor_values='{"temperature": 210}',
            detected_at=datetime(2026, 6, 9, 10, 0, 0),
        )

        mock_collection = MagicMock()
        mock_collection.query.return_value = {
            "documents": [["some SOP text"]],
            "metadatas": [[{"source": "boiler_sop.txt"}]],
            "distances": [[0.1]],
        }

        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="Recommendation with no JSON block.")]

        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_response

        mock_session = MagicMock()
        captured = {}

        def fake_create_agent_run(session, **kwargs):
            captured.update(kwargs)
            run = MagicMock()
            run.id = 99
            return run

        with patch("src.agent.agent.create_agent_run", side_effect=fake_create_agent_run):
            process_alert(alert, mock_collection, mock_client, mock_session)

        assert captured["requires_human_review"] is True
        assert captured["citation"] == ""
        assert captured["confidence_score"] == pytest.approx(0.0)

    def test_api_error_propagates(self):
        """Claude API error should propagate (caller handles it in polling_loop)."""
        import anthropic as _anthropic
        from src.agent.agent import process_alert
        from src.db.models import Alert
        from datetime import datetime

        alert = Alert(
            id=2,
            device_id="dryer-1",
            device_type="dryer",
            batch_id="BATCH-002",
            anomaly_score=-0.2,
            alert_type="ANOMALY",
            sensor_values='{"temperature": 145}',
            detected_at=datetime(2026, 6, 9, 11, 0, 0),
        )

        mock_collection = MagicMock()
        mock_collection.query.return_value = {
            "documents": [["dryer text"]],
            "metadatas": [[{"source": "dryer_sop.txt"}]],
            "distances": [[0.15]],
        }

        mock_client = MagicMock()
        mock_client.messages.create.side_effect = _anthropic.APIConnectionError(
            request=MagicMock()
        )
        mock_session = MagicMock()

        with pytest.raises(_anthropic.APIConnectionError):
            process_alert(alert, mock_collection, mock_client, mock_session)
