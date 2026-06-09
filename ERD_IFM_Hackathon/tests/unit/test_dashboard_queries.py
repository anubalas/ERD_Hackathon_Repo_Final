from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import pandas as pd

from src.dashboard.app import get_alerts, get_batch_audit, get_live_feed


def _make_log(**kwargs) -> SimpleNamespace:
    defaults = dict(
        id=1,
        reading_id="r-001",
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
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


# ---------------------------------------------------------------------------
# get_live_feed (T006)
# ---------------------------------------------------------------------------

class TestGetLiveFeed:
    def test_returns_dataframe_with_correct_columns(self):
        session = MagicMock()
        session.query.return_value.order_by.return_value.limit.return_value.all.return_value = []
        df = get_live_feed(session)
        assert isinstance(df, pd.DataFrame)
        assert "status" in df.columns
        assert "stream_published" in df.columns

    def test_three_rows_returned(self):
        rows = [
            _make_log(id=1, status="ACCEPTED", stream_published=True),
            _make_log(id=2, status="ACCEPTED", stream_published=False),
            _make_log(id=3, status="REJECTED", stream_published=False),
        ]
        session = MagicMock()
        session.query.return_value.order_by.return_value.limit.return_value.all.return_value = rows
        df = get_live_feed(session)
        assert len(df) == 3
        assert list(df["status"]) == ["ACCEPTED", "ACCEPTED", "REJECTED"]

    def test_empty_db_returns_empty_dataframe(self):
        session = MagicMock()
        session.query.return_value.order_by.return_value.limit.return_value.all.return_value = []
        df = get_live_feed(session)
        assert df.empty
        assert "server_received_at" in df.columns


# ---------------------------------------------------------------------------
# get_alerts (T011)
# ---------------------------------------------------------------------------

class TestGetAlerts:
    def test_returns_rejected_rows_and_total_count(self):
        rejected_rows = [
            _make_log(id=1, status="REJECTED", rejection_reason="temp too low"),
            _make_log(id=2, status="REJECTED", rejection_reason="pressure too high"),
        ]
        session = MagicMock()
        session.query.return_value.filter.return_value.scalar.return_value = 2
        session.query.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = rejected_rows
        df, total = get_alerts(session)
        assert total == 2
        assert len(df) == 2

    def test_empty_returns_empty_dataframe_and_zero(self):
        session = MagicMock()
        session.query.return_value.filter.return_value.scalar.return_value = 0
        session.query.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = []
        df, total = get_alerts(session)
        assert total == 0
        assert df.empty

    def test_rejection_reason_truncated_to_120_chars(self):
        long_reason = "x" * 200
        rows = [_make_log(id=1, status="REJECTED", rejection_reason=long_reason)]
        session = MagicMock()
        session.query.return_value.filter.return_value.scalar.return_value = 1
        session.query.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = rows
        df, _ = get_alerts(session)
        assert len(df["rejection_reason"].iloc[0]) == 120


# ---------------------------------------------------------------------------
# get_batch_audit (T011)
# ---------------------------------------------------------------------------

class TestGetBatchAudit:
    def test_returns_rows_for_matching_batch(self):
        rows = [
            _make_log(id=1, batch_id="B001", device_timestamp=datetime(2026, 6, 9, 10, 0, 0)),
            _make_log(id=2, batch_id="B001", device_timestamp=datetime(2026, 6, 9, 10, 1, 0)),
        ]
        session = MagicMock()
        session.query.return_value.filter.return_value.order_by.return_value.all.return_value = rows
        df = get_batch_audit(session, "B001")
        assert len(df) == 2
        assert "device_timestamp" in df.columns

    def test_unknown_batch_returns_empty_dataframe(self):
        session = MagicMock()
        session.query.return_value.filter.return_value.order_by.return_value.all.return_value = []
        df = get_batch_audit(session, "UNKNOWN")
        assert df.empty
        assert "status" in df.columns

    def test_results_contain_rejection_reason_column(self):
        rows = [_make_log(id=1, batch_id="B001", status="REJECTED", rejection_reason="ph too high")]
        session = MagicMock()
        session.query.return_value.filter.return_value.order_by.return_value.all.return_value = rows
        df = get_batch_audit(session, "B001")
        assert df["rejection_reason"].iloc[0] == "ph too high"
