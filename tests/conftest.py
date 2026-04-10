"""Pytest configuration and shared fixtures."""
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.api.main import app
from src.core.config import settings
from src.data.models.base import Base

TEST_DB_URL = settings.database_url.replace("/tradingfloor", "/tradingfloor_test")


@pytest_asyncio.fixture(scope="session")
async def engine():  # type: ignore[misc]
    e = create_async_engine(TEST_DB_URL, echo=False)
    async with e.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield e
    async with e.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await e.dispose()


@pytest_asyncio.fixture
async def session(engine):  # type: ignore[misc]
    async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as s:
        yield s


@pytest_asyncio.fixture
async def client() -> AsyncClient:
    """Async HTTP client wired directly to the FastAPI app (no network)."""
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac
