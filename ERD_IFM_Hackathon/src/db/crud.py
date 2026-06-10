from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from src.db.models import AgentRun, Alert, TelemetryLog


async def create_telemetry_log(
    session: AsyncSession,
    *,
    reading_id: str,
    device_id: str,
    device_type: str,
    temperature: float | None,
    pressure: float | None,
    humidity: float | None,
    ph: float | None,
    flow_rate: float | None,
    batch_id: str,
    device_timestamp: datetime,
    server_received_at: datetime,
    status: str,
    rejection_reason: str | None,
    stream_published: bool,
    stale_timestamp: bool,
) -> TelemetryLog:
    log = TelemetryLog(
        reading_id=reading_id,
        device_id=device_id,
        device_type=device_type,
        temperature=temperature,
        pressure=pressure,
        humidity=humidity,
        ph=ph,
        flow_rate=flow_rate,
        batch_id=batch_id,
        device_timestamp=device_timestamp,
        server_received_at=server_received_at,
        status=status,
        rejection_reason=rejection_reason,
        stream_published=stream_published,
        stale_timestamp=stale_timestamp,
    )
    session.add(log)
    await session.commit()
    await session.refresh(log)
    return log


async def create_alert(
    session: AsyncSession,
    *,
    device_id: str,
    device_type: str,
    batch_id: str,
    alert_type: str,
    detected_at: datetime,
    reading_id: str | None = None,
    anomaly_score: float | None = None,
    sensor_values: str | None = None,
    error_detail: str | None = None,
    severity: str | None = None,
) -> Alert:
    alert = Alert(
        device_id=device_id,
        device_type=device_type,
        reading_id=reading_id,
        batch_id=batch_id,
        anomaly_score=anomaly_score,
        alert_type=alert_type,
        severity=severity,
        sensor_values=sensor_values,
        error_detail=error_detail,
        detected_at=detected_at,
    )
    session.add(alert)
    await session.commit()
    await session.refresh(alert)
    return alert


# ---------------------------------------------------------------------------
# Sync functions — used by the AI agent polling loop (not async FastAPI)
# ---------------------------------------------------------------------------

def create_agent_run(
    session: Session,
    *,
    alert_id: int,
    recommendation: str,
    citation: str,
    confidence_score: float,
    requires_human_review: bool,
    model_name: str,
    raw_response: str,
    created_at: datetime,
) -> AgentRun:
    run = AgentRun(
        alert_id=alert_id,
        recommendation=recommendation,
        citation=citation,
        confidence_score=confidence_score,
        requires_human_review=requires_human_review,
        model_name=model_name,
        raw_response=raw_response,
        created_at=created_at,
    )
    session.add(run)
    session.commit()
    session.refresh(run)
    return run


def get_unprocessed_alerts(session: Session) -> list[Alert]:
    processed_ids = session.query(AgentRun.alert_id).scalar_subquery()
    return (
        session.query(Alert)
        .filter(Alert.id.notin_(processed_ids))
        .filter(Alert.alert_type.in_(["ANOMALY", "TREND_ANOMALY"]))
        .order_by(Alert.detected_at.asc())
        .all()
    )


# ---------------------------------------------------------------------------
# Operator alert management (sync) — used by dashboard
# ---------------------------------------------------------------------------

def get_pending_alerts(session: Session) -> list[Alert]:
    """Return unacknowledged, undismissed ANOMALY/TREND_ANOMALY alerts, oldest first."""
    return (
        session.query(Alert)
        .filter(Alert.acknowledged == False)  # noqa: E712
        .filter(Alert.dismissed == False)     # noqa: E712
        .filter(Alert.alert_type.in_(["ANOMALY", "TREND_ANOMALY", "CCP_BREACH"]))
        .order_by(Alert.detected_at.asc())
        .all()
    )


def dismiss_alert(session: Session, alert_id: int) -> None:
    alert = session.query(Alert).filter(Alert.id == alert_id).first()
    if alert:
        alert.dismissed = True
        session.commit()


def acknowledge_alert(session: Session, alert_id: int) -> None:
    alert = session.query(Alert).filter(Alert.id == alert_id).first()
    if alert:
        alert.acknowledged = True
        alert.acknowledged_at = datetime.utcnow()
        session.commit()


def create_alert_sync(
    session: Session,
    *,
    device_id: str,
    device_type: str,
    batch_id: str,
    alert_type: str,
    detected_at: datetime,
    reading_id: str | None = None,
    anomaly_score: float | None = None,
    sensor_values: str | None = None,
    error_detail: str | None = None,
    severity: str | None = None,
) -> Alert:
    alert = Alert(
        device_id=device_id,
        device_type=device_type,
        reading_id=reading_id,
        batch_id=batch_id,
        anomaly_score=anomaly_score,
        alert_type=alert_type,
        severity=severity,
        sensor_values=sensor_values,
        error_detail=error_detail,
        detected_at=detected_at,
    )
    session.add(alert)
    session.commit()
    session.refresh(alert)
    return alert


def get_agent_run_for_alert(session: Session, alert_id: int) -> AgentRun | None:
    return (
        session.query(AgentRun)
        .filter(AgentRun.alert_id == alert_id)
        .order_by(AgentRun.created_at.desc())
        .first()
    )
