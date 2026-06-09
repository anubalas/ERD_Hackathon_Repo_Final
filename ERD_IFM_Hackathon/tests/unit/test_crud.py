from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from src.db.crud import create_telemetry_log
from src.db.models import TelemetryLog


_BASE_KWARGS = dict(
    reading_id="rid-001",
    device_id="boiler-01",
    device_type="boiler",
    temperature=150.0,
    pressure=6.0,
    humidity=None,
    ph=None,
    flow_rate=None,
    batch_id="B001",
    device_timestamp=datetime(2026, 6, 9, 10, 0, 0),
    server_received_at=datetime(2026, 6, 9, 10, 0, 1),
    status="ACCEPTED",
    rejection_reason=None,
    stream_published=True,
    stale_timestamp=False,
)


class TestCreateTelemetryLog:
    async def test_creates_and_returns_log(self):
        session = AsyncMock()
        log = TelemetryLog(**{k: v for k, v in _BASE_KWARGS.items()})
        session.refresh = AsyncMock(return_value=None)

        with patch("src.db.crud.TelemetryLog", return_value=log):
            result = await create_telemetry_log(session, **_BASE_KWARGS)

        session.add.assert_called_once_with(log)
        session.commit.assert_awaited_once()
        session.refresh.assert_awaited_once_with(log)
        assert result is log

    async def test_rejected_reading_stored_with_reason(self):
        session = AsyncMock()
        kwargs = {**_BASE_KWARGS, "status": "REJECTED", "rejection_reason": "temp too low", "stream_published": False}
        log = TelemetryLog(**{k: v for k, v in kwargs.items()})
        session.refresh = AsyncMock(return_value=None)

        with patch("src.db.crud.TelemetryLog", return_value=log):
            result = await create_telemetry_log(session, **kwargs)

        assert result.status == "REJECTED"
        assert result.rejection_reason == "temp too low"


# ---------------------------------------------------------------------------
# Append-only contract (T025)
# ---------------------------------------------------------------------------

class TestAppendOnlyContract:
    def test_crud_module_has_no_update_function(self):
        import src.db.crud as crud_module
        public = [n for n in dir(crud_module) if not n.startswith("_")]
        update_like = [n for n in public if "update" in n.lower() or "delete" in n.lower()]
        assert update_like == [], f"Unexpected mutating functions found: {update_like}"

    def test_create_telemetry_log_is_only_write_function(self):
        import src.db.crud as crud_module
        import inspect
        write_fns = [
            n for n in dir(crud_module)
            if not n.startswith("_") and inspect.iscoroutinefunction(getattr(crud_module, n))
        ]
        # create_alert was added for anomaly detection; both are INSERT-only
        assert set(write_fns) == {"create_telemetry_log", "create_alert"}
