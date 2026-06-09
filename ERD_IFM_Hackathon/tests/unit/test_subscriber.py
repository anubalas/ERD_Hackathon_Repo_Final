"""Unit tests for subscriber.process_message() — T025."""
import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.detection.subscriber import process_message


def _make_scorer(score: float = 0.05, is_anomaly: bool = False):
    scorer = MagicMock()
    scorer.score.return_value = (score, is_anomaly)
    return scorer


def _make_session():
    session = AsyncMock()
    session.add = MagicMock()
    return session


def _make_payload(**kwargs) -> str:
    base = {
        "device_id": "boiler-line-1",
        "device_type": "boiler",
        "batch_id": "BATCH-TEST-001",
        "reading_id": "abc123",
        "temperature": 160.0,
        "pressure": 5.5,
    }
    base.update(kwargs)
    return json.dumps(base)


@pytest.mark.asyncio
async def test_normal_reading_no_alert_written():
    scorer = _make_scorer(score=0.05, is_anomaly=False)
    session = _make_session()
    with patch("src.detection.subscriber.create_alert") as mock_alert:
        await process_message(_make_payload(), scorer, session)
    mock_alert.assert_not_called()


@pytest.mark.asyncio
async def test_anomalous_reading_writes_anomaly_alert():
    scorer = _make_scorer(score=-0.15, is_anomaly=True)
    session = _make_session()
    with patch("src.detection.subscriber.create_alert", new_callable=AsyncMock) as mock_alert:
        await process_message(_make_payload(), scorer, session)
    mock_alert.assert_called_once()
    kwargs = mock_alert.call_args.kwargs
    assert kwargs["alert_type"] == "ANOMALY"
    assert kwargs["device_id"] == "boiler-line-1"
    assert kwargs["anomaly_score"] == pytest.approx(-0.15)


@pytest.mark.asyncio
async def test_malformed_json_writes_pipeline_error():
    scorer = _make_scorer()
    session = _make_session()
    with patch("src.detection.subscriber.create_alert", new_callable=AsyncMock) as mock_alert:
        await process_message("{not valid json", scorer, session)
    mock_alert.assert_called_once()
    kwargs = mock_alert.call_args.kwargs
    assert kwargs["alert_type"] == "PIPELINE_ERROR"
    scorer.score.assert_not_called()


@pytest.mark.asyncio
async def test_scoring_exception_writes_pipeline_error():
    scorer = MagicMock()
    scorer.score.side_effect = ValueError("feature extraction failed")
    session = _make_session()
    with patch("src.detection.subscriber.create_alert", new_callable=AsyncMock) as mock_alert:
        await process_message(_make_payload(), scorer, session)
    mock_alert.assert_called_once()
    kwargs = mock_alert.call_args.kwargs
    assert kwargs["alert_type"] == "PIPELINE_ERROR"
    assert "feature extraction failed" in kwargs["error_detail"]


@pytest.mark.asyncio
async def test_unknown_device_type_no_alert():
    scorer = _make_scorer(score=None, is_anomaly=False)
    scorer.score.return_value = (None, False)
    session = _make_session()
    payload = _make_payload(device_type="mixer")
    with patch("src.detection.subscriber.create_alert") as mock_alert:
        await process_message(payload, scorer, session)
    mock_alert.assert_not_called()
