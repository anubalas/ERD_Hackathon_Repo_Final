import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.schemas import (
    SensorReading,
    TelemetryResponse,
    validate_ccp_ranges,
)
from src.db.crud import create_telemetry_log
from src.db.database import get_db_session
from src.streaming.redis_client import RedisClient, RedisPublishError, get_redis_client

logger = logging.getLogger(__name__)

router = APIRouter()

_STALE_THRESHOLD_SECONDS = 300


@router.post("/telemetry", response_model=TelemetryResponse)
async def ingest_telemetry(
    reading: SensorReading,
    db: AsyncSession = Depends(get_db_session),
    redis: RedisClient = Depends(get_redis_client),
) -> TelemetryResponse:
    reading_id = str(uuid.uuid4())
    server_received_at = datetime.now(timezone.utc)

    stale = (
        abs((server_received_at - reading.timestamp.astimezone(timezone.utc)).total_seconds())
        > _STALE_THRESHOLD_SECONDS
    )

    violations = validate_ccp_ranges(reading)
    if violations:
        rejection_reason = "; ".join(v.message for v in violations)
        try:
            await create_telemetry_log(
                db,
                reading_id=reading_id,
                device_id=reading.device_id,
                device_type=reading.device_type,
                temperature=reading.temperature,
                pressure=reading.pressure,
                humidity=reading.humidity,
                ph=reading.ph,
                flow_rate=reading.flow_rate,
                batch_id=reading.batch_id,
                device_timestamp=reading.timestamp.replace(tzinfo=None) if reading.timestamp.tzinfo else reading.timestamp,
                server_received_at=server_received_at.replace(tzinfo=None),
                status="REJECTED",
                rejection_reason=rejection_reason,
                stream_published=False,
                stale_timestamp=stale,
            )
        except Exception:
            logger.exception("DB write failed for REJECTED reading %s", reading_id)
        raise HTTPException(
            status_code=422,
            detail=[v.model_dump() for v in violations],
        )

    stream_published = False
    warnings: list[str] = []
    try:
        await redis.publish_telemetry(reading_id, reading, server_received_at)
        stream_published = True
    except RedisPublishError as exc:
        logger.error("Redis publish failed for reading %s: %s", reading_id, exc)
        warnings.append("Stream publish failed — reading saved to audit log only")

    try:
        await create_telemetry_log(
            db,
            reading_id=reading_id,
            device_id=reading.device_id,
            device_type=reading.device_type,
            temperature=reading.temperature,
            pressure=reading.pressure,
            humidity=reading.humidity,
            ph=reading.ph,
            flow_rate=reading.flow_rate,
            batch_id=reading.batch_id,
            device_timestamp=reading.timestamp.replace(tzinfo=None) if reading.timestamp.tzinfo else reading.timestamp,
            server_received_at=server_received_at.replace(tzinfo=None),
            status="ACCEPTED",
            rejection_reason=None,
            stream_published=stream_published,
            stale_timestamp=stale,
        )
    except Exception as exc:
        logger.exception("DB write failed for ACCEPTED reading %s", reading_id)
        raise HTTPException(status_code=503, detail="Database unavailable") from exc

    if stale:
        warnings.append("Timestamp is more than 5 minutes from server time")

    return TelemetryResponse(
        reading_id=reading_id,
        status="ACCEPTED",
        server_received_at=server_received_at,
        stream_published=stream_published,
        warnings=warnings,
    )
