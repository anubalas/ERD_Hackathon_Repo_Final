"""Unit tests for create_alert() — T019 and T020."""
import inspect
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

import src.db.crud as crud_module
from src.db.models import Alert


@pytest.fixture
def mock_session():
    """Minimal async session mock that captures the added object."""
    added = []

    class _Session:
        async def commit(self): pass

        async def refresh(self, obj):
            obj.id = 1

        def add(self, obj):
            added.append(obj)

    session = _Session()
    session._added = added
    return session


@pytest.mark.asyncio
async def test_create_alert_anomaly_writes_correct_fields(mock_session):
    detected = datetime(2026, 6, 9, 12, 0, 0, tzinfo=timezone.utc)
    result = await crud_module.create_alert(
        mock_session,
        device_id="boiler-line-1",
        device_type="boiler",
        batch_id="BATCH-001",
        alert_type="ANOMALY",
        detected_at=detected,
        reading_id="abc123",
        anomaly_score=-0.15,
        sensor_values='{"temperature": 210.0, "pressure": 13.0}',
    )
    assert result.device_id == "boiler-line-1"
    assert result.device_type == "boiler"
    assert result.batch_id == "BATCH-001"
    assert result.alert_type == "ANOMALY"
    assert result.reading_id == "abc123"
    assert result.anomaly_score == pytest.approx(-0.15)
    assert result.sensor_values == '{"temperature": 210.0, "pressure": 13.0}'
    assert result.error_detail is None
    assert result.detected_at == detected


@pytest.mark.asyncio
async def test_create_alert_pipeline_error_writes_correct_fields(mock_session):
    detected = datetime(2026, 6, 9, 12, 5, 0, tzinfo=timezone.utc)
    result = await crud_module.create_alert(
        mock_session,
        device_id="dryer-01",
        device_type="dryer",
        batch_id="BATCH-002",
        alert_type="PIPELINE_ERROR",
        detected_at=detected,
        anomaly_score=None,
        error_detail="ValueError: feature extraction failed",
    )
    assert result.alert_type == "PIPELINE_ERROR"
    assert result.anomaly_score is None
    assert result.error_detail == "ValueError: feature extraction failed"
    assert result.reading_id is None


@pytest.mark.asyncio
async def test_create_alert_adds_to_session(mock_session):
    await crud_module.create_alert(
        mock_session,
        device_id="past-01",
        device_type="pasteurizer",
        batch_id="BATCH-003",
        alert_type="ANOMALY",
        detected_at=datetime.now(timezone.utc),
        anomaly_score=-0.12,
    )
    assert len(mock_session._added) == 1
    assert isinstance(mock_session._added[0], Alert)


def test_append_only_contract_no_update_alert():
    """T020: assert no update_alert function exists in crud.py."""
    assert not hasattr(crud_module, "update_alert"), (
        "update_alert must not exist in crud.py — Constitution Principle II (Immutable Audit Log)"
    )


def test_append_only_contract_no_delete_alert():
    """T020: assert no delete_alert function exists in crud.py."""
    assert not hasattr(crud_module, "delete_alert"), (
        "delete_alert must not exist in crud.py — Constitution Principle II (Immutable Audit Log)"
    )
