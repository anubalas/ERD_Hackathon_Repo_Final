from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import TelemetryLog


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
