from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

from src.streaming.redis_client import RedisPublishError

VALID_BOILER_PAYLOAD = {
    "device_id": "boiler-01",
    "device_type": "boiler",
    "temperature": 150.0,
    "pressure": 6.0,
    "batch_id": "B001",
    "timestamp": "2026-06-09T10:00:00Z",
}


# ---------------------------------------------------------------------------
# Happy path (T013)
# ---------------------------------------------------------------------------

class TestTelemetryHappyPath:
    async def test_accepted_response_shape(self, async_test_client: AsyncClient):
        with patch("src.api.routes.telemetry.create_telemetry_log", new_callable=AsyncMock):
            resp = await async_test_client.post("/telemetry", json=VALID_BOILER_PAYLOAD)
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ACCEPTED"
        assert "reading_id" in body
        assert "server_received_at" in body
        assert body["stream_published"] is True

    async def test_pasteurizer_accepted(self, async_test_client: AsyncClient):
        payload = {
            "device_id": "past-01",
            "device_type": "pasteurizer",
            "temperature": 80.0,
            "ph": 5.5,
            "flow_rate": 100.0,
            "batch_id": "B002",
            "timestamp": "2026-06-09T10:00:00Z",
        }
        with patch("src.api.routes.telemetry.create_telemetry_log", new_callable=AsyncMock):
            resp = await async_test_client.post("/telemetry", json=payload)
        assert resp.status_code == 200

    async def test_structural_validation_error_returns_422(self, async_test_client: AsyncClient):
        payload = {**VALID_BOILER_PAYLOAD, "device_id": ""}
        resp = await async_test_client.post("/telemetry", json=payload)
        assert resp.status_code == 422

    async def test_unknown_device_type_returns_422(self, async_test_client: AsyncClient):
        payload = {**VALID_BOILER_PAYLOAD, "device_type": "oven"}
        resp = await async_test_client.post("/telemetry", json=payload)
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# CCP rejection path (T017)
# ---------------------------------------------------------------------------

class TestCCPRejection:
    async def test_ccp_violation_returns_422(self, async_test_client: AsyncClient):
        payload = {**VALID_BOILER_PAYLOAD, "temperature": 50.0}
        with patch("src.api.routes.telemetry.create_telemetry_log", new_callable=AsyncMock):
            resp = await async_test_client.post("/telemetry", json=payload)
        assert resp.status_code == 422

    async def test_ccp_violation_detail_contains_field(self, async_test_client: AsyncClient):
        payload = {**VALID_BOILER_PAYLOAD, "temperature": 50.0}
        with patch("src.api.routes.telemetry.create_telemetry_log", new_callable=AsyncMock):
            resp = await async_test_client.post("/telemetry", json=payload)
        detail = resp.json()["detail"]
        assert any(v["field"] == "temperature" for v in detail)

    async def test_ccp_rejection_writes_rejected_record(self, async_test_client: AsyncClient):
        payload = {**VALID_BOILER_PAYLOAD, "temperature": 50.0}
        with patch("src.api.routes.telemetry.create_telemetry_log", new_callable=AsyncMock) as mock_crud:
            await async_test_client.post("/telemetry", json=payload)
        mock_crud.assert_awaited_once()
        _, kwargs = mock_crud.call_args
        assert kwargs["status"] == "REJECTED"
        assert kwargs["stream_published"] is False


# ---------------------------------------------------------------------------
# Redis failure (T021)
# ---------------------------------------------------------------------------

class TestRedisFailure:
    async def test_redis_failure_still_returns_accepted(
        self, async_test_client: AsyncClient, mock_redis_client
    ):
        mock_redis_client.publish_telemetry.side_effect = RedisPublishError("conn failed")
        with patch("src.api.routes.telemetry.create_telemetry_log", new_callable=AsyncMock):
            resp = await async_test_client.post("/telemetry", json=VALID_BOILER_PAYLOAD)
        assert resp.status_code == 200
        body = resp.json()
        assert body["stream_published"] is False
        assert any("Stream publish failed" in w for w in body["warnings"])

    async def test_redis_failure_db_record_has_stream_published_false(
        self, async_test_client: AsyncClient, mock_redis_client
    ):
        mock_redis_client.publish_telemetry.side_effect = RedisPublishError("conn failed")
        with patch("src.api.routes.telemetry.create_telemetry_log", new_callable=AsyncMock) as mock_crud:
            await async_test_client.post("/telemetry", json=VALID_BOILER_PAYLOAD)
        _, kwargs = mock_crud.call_args
        assert kwargs["stream_published"] is False


# ---------------------------------------------------------------------------
# DB failure (T022)
# ---------------------------------------------------------------------------

class TestDBFailure:
    async def test_db_failure_returns_503(self, async_test_client: AsyncClient):
        with patch(
            "src.api.routes.telemetry.create_telemetry_log",
            new_callable=AsyncMock,
            side_effect=Exception("db down"),
        ):
            resp = await async_test_client.post("/telemetry", json=VALID_BOILER_PAYLOAD)
        assert resp.status_code == 503

    async def test_db_failure_detail_message(self, async_test_client: AsyncClient):
        with patch(
            "src.api.routes.telemetry.create_telemetry_log",
            new_callable=AsyncMock,
            side_effect=Exception("db down"),
        ):
            resp = await async_test_client.post("/telemetry", json=VALID_BOILER_PAYLOAD)
        assert "Database unavailable" in resp.json()["detail"]
