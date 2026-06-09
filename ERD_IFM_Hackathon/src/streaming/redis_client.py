import json
import logging
import os
from datetime import datetime
from typing import AsyncGenerator

import redis.asyncio as aioredis

logger = logging.getLogger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
REDIS_CHANNEL = os.getenv("REDIS_CHANNEL", "telemetry")


class RedisPublishError(Exception):
    def __init__(self, message: str, cause: Exception | None = None) -> None:
        super().__init__(message)
        self.cause = cause


class RedisClient:
    def __init__(self, client: aioredis.Redis) -> None:
        self._client = client

    async def publish_telemetry(
        self,
        reading_id: str,
        reading,
        server_received_at: datetime,
    ) -> None:
        payload = json.dumps(
            {
                "reading_id": reading_id,
                "device_id": reading.device_id,
                "device_type": reading.device_type,
                "temperature": reading.temperature,
                "pressure": reading.pressure,
                "humidity": reading.humidity,
                "ph": reading.ph,
                "flow_rate": reading.flow_rate,
                "batch_id": reading.batch_id,
                "device_timestamp": reading.timestamp.isoformat(),
                "server_received_at": server_received_at.isoformat(),
            }
        )
        try:
            await self._client.publish(REDIS_CHANNEL, payload)
        except Exception as exc:
            raise RedisPublishError(
                f"Failed to publish reading {reading_id} to channel '{REDIS_CHANNEL}'",
                cause=exc,
            ) from exc

    async def close(self) -> None:
        await self._client.aclose()


async def get_redis_client() -> AsyncGenerator[RedisClient, None]:
    # protocol=2 forces RESP2, avoiding the HELLO 3 handshake that Redis <6 rejects
    client = aioredis.from_url(REDIS_URL, decode_responses=True, protocol=2)
    redis_client = RedisClient(client)
    try:
        yield redis_client
    finally:
        await redis_client.close()
