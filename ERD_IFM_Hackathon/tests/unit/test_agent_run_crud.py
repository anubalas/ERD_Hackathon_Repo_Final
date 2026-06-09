"""Unit tests for AgentRun CRUD operations and append-only contract (SC-006)."""
import inspect
from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.db.crud import create_agent_run, get_unprocessed_alerts
from src.db.models import AgentRun, Alert, Base


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()
    engine.dispose()


def _make_alert(session, alert_id_offset=0) -> Alert:
    alert = Alert(
        device_id=f"boiler-{alert_id_offset}",
        device_type="boiler",
        batch_id=f"BATCH-{alert_id_offset:03d}",
        anomaly_score=-0.15,
        alert_type="ANOMALY",
        sensor_values='{"temperature": 210}',
        detected_at=datetime(2026, 6, 9, 10, alert_id_offset, 0),
    )
    session.add(alert)
    session.commit()
    session.refresh(alert)
    return alert


class TestCreateAgentRun:
    def test_all_fields_written(self, db_session):
        alert = _make_alert(db_session)
        created_at = datetime(2026, 6, 9, 10, 1, 0)

        run = create_agent_run(
            db_session,
            alert_id=alert.id,
            recommendation="Reduce steam demand per §2.1",
            citation="[Source: boiler_sop.txt, §2.1]",
            confidence_score=0.92,
            requires_human_review=False,
            model_name="claude-sonnet-4-6",
            raw_response="Full response text here.",
            created_at=created_at,
        )

        assert run.id is not None
        assert run.alert_id == alert.id
        assert run.recommendation == "Reduce steam demand per §2.1"
        assert run.citation == "[Source: boiler_sop.txt, §2.1]"
        assert run.confidence_score == pytest.approx(0.92)
        assert run.requires_human_review is False
        assert run.model_name == "claude-sonnet-4-6"
        assert run.created_at == created_at

    def test_low_confidence_run_persisted(self, db_session):
        alert = _make_alert(db_session, 1)
        run = create_agent_run(
            db_session,
            alert_id=alert.id,
            recommendation="REQUIRES HUMAN REVIEW — no SOP match found.",
            citation="",
            confidence_score=0.0,
            requires_human_review=True,
            model_name="claude-sonnet-4-6",
            raw_response="Full response.",
            created_at=datetime(2026, 6, 9, 10, 2, 0),
        )
        assert run.requires_human_review is True
        assert run.citation == ""
        assert run.confidence_score == pytest.approx(0.0)


class TestGetUnprocessedAlerts:
    def test_returns_alert_with_no_agent_run(self, db_session):
        alert = _make_alert(db_session)
        unprocessed = get_unprocessed_alerts(db_session)
        assert len(unprocessed) == 1
        assert unprocessed[0].id == alert.id

    def test_skips_alert_with_existing_agent_run(self, db_session):
        alert = _make_alert(db_session)
        create_agent_run(
            db_session,
            alert_id=alert.id,
            recommendation="Already processed",
            citation="[Source: boiler_sop.txt, §2.1]",
            confidence_score=0.9,
            requires_human_review=False,
            model_name="claude-sonnet-4-6",
            raw_response="resp",
            created_at=datetime(2026, 6, 9, 10, 1, 0),
        )
        unprocessed = get_unprocessed_alerts(db_session)
        assert len(unprocessed) == 0

    def test_only_returns_anomaly_type(self, db_session):
        pipeline_alert = Alert(
            device_id="boiler-err",
            device_type="boiler",
            batch_id="BATCH-ERR",
            alert_type="PIPELINE_ERROR",
            error_detail="Scoring failed",
            detected_at=datetime(2026, 6, 9, 10, 0, 0),
        )
        db_session.add(pipeline_alert)
        db_session.commit()

        unprocessed = get_unprocessed_alerts(db_session)
        assert all(a.alert_type == "ANOMALY" for a in unprocessed)

    def test_ordered_by_detected_at_ascending(self, db_session):
        a1 = _make_alert(db_session, 0)
        a2 = _make_alert(db_session, 1)
        a3 = _make_alert(db_session, 2)
        unprocessed = get_unprocessed_alerts(db_session)
        ids = [a.id for a in unprocessed]
        assert ids == sorted(ids)


class TestAppendOnlyContract:
    def test_no_update_agent_run_function_in_crud(self):
        import src.db.crud as crud_module
        functions = [
            name for name, obj in inspect.getmembers(crud_module, inspect.isfunction)
        ]
        assert "update_agent_run" not in functions, (
            "update_agent_run must not exist — AgentRun is append-only (Constitution Principle II)"
        )

    def test_no_delete_agent_run_function_in_crud(self):
        import src.db.crud as crud_module
        functions = [
            name for name, obj in inspect.getmembers(crud_module, inspect.isfunction)
        ]
        assert "delete_agent_run" not in functions, (
            "delete_agent_run must not exist — AgentRun is append-only (Constitution Principle II)"
        )
