from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient


@pytest.fixture
def mock_redis_client():
    client = MagicMock()
    client.publish_telemetry = AsyncMock(return_value=None)
    client.close = AsyncMock(return_value=None)
    return client


@pytest.fixture
def mock_db_session():
    session = AsyncMock()
    return session


@pytest_asyncio.fixture
async def async_test_client(mock_redis_client, mock_db_session):
    with patch("src.db.database.init_db", new_callable=AsyncMock):
        from src.api.main import app
        from src.db.database import get_db_session
        from src.streaming.redis_client import get_redis_client

        app.dependency_overrides[get_db_session] = lambda: mock_db_session
        app.dependency_overrides[get_redis_client] = lambda: mock_redis_client

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            yield client

        app.dependency_overrides.clear()
