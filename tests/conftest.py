"""Pytest configuration and shared fixtures."""
import pytest
from httpx import AsyncClient, ASGITransport

from src.api.main import app
from src.core.config import Settings


@pytest.fixture(scope="session")
def test_settings() -> Settings:
    """Override settings for the test environment."""
    return Settings(
        environment="test",
        database_url="postgresql+asyncpg://tradingfloor:tradingfloor_dev@localhost:5432/tradingfloor_test",
        redis_url="redis://localhost:6379/1",
    )


@pytest.fixture
async def client() -> AsyncClient:
    """Async HTTP client wired directly to the FastAPI app (no network)."""
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac
