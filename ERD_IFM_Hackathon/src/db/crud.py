from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import Alert, TelemetryLog


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
) -> Alert:
    alert = Alert(
        device_id=device_id,
        device_type=device_type,
        reading_id=reading_id,
        batch_id=batch_id,
        anomaly_score=anomaly_score,
        alert_type=alert_type,
        sensor_values=sensor_values,
        error_detail=error_detail,
        detected_at=detected_at,
    )
    session.add(alert)
    await session.commit()
    await session.refresh(alert)
    return alert
