"""
Shared pytest fixtures.

Async DB uses an in-memory SQLite database so tests are fully isolated
and do not touch the filesystem or the real Hospital Directory API.
"""
import io
from typing import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import Settings
from app.db.session import Base
from app.models.batch import Batch, BatchStatus  # noqa: F401 – ensure models register
from app.services.bulk_processing import BulkProcessingService
from app.services.hospital_api_client import HospitalAPIClient

# ── Settings override ────────────────────────────────────────────────────────

@pytest.fixture()
def settings() -> Settings:
    return Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        hospital_api_base_url="https://fake-hospital-api.test",
        max_csv_rows=20,
        http_concurrency_limit=5,
    )


# ── In-memory async DB ───────────────────────────────────────────────────────

@pytest_asyncio.fixture()
async def db_session(settings: Settings) -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine(settings.database_url, connect_args={"check_same_thread": False})
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    async with session_factory() as session:
        yield session
        await session.rollback()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


# ── Mock API client ───────────────────────────────────────────────────────────

@pytest.fixture()
def mock_api_client() -> MagicMock:
    """Returns a MagicMock with async methods for the HospitalAPIClient."""
    client = MagicMock(spec=HospitalAPIClient)
    client.create_hospital = AsyncMock(return_value={"id": 1, "name": "Test Hospital"})
    client.activate_batch = AsyncMock(return_value={})
    client.delete_batch = AsyncMock(return_value=None)
    client.get_batch = AsyncMock(return_value=[])
    return client


# ── Service factory ───────────────────────────────────────────────────────────

@pytest.fixture()
def bulk_service(
    db_session: AsyncSession,
    mock_api_client: MagicMock,
    settings: Settings,
) -> BulkProcessingService:
    return BulkProcessingService(
        db=db_session,
        api_client=mock_api_client,
        settings=settings,
    )


# ── CSV helpers ───────────────────────────────────────────────────────────────

def make_csv(rows: list[dict], *, include_header: bool = True) -> io.BytesIO:
    """Build a CSV BytesIO from a list of dicts."""
    lines: list[str] = []
    if include_header:
        lines.append("name,address,phone")
    for r in rows:
        name = r.get("name", "")
        address = r.get("address", "")
        phone = r.get("phone", "")
        lines.append(f"{name},{address},{phone}")
    return io.BytesIO("\n".join(lines).encode())


def make_valid_csv(n: int = 3) -> io.BytesIO:
    return make_csv([
        {"name": f"Hospital {i}", "address": f"{i} Main St", "phone": f"555-000{i}"}
        for i in range(1, n + 1)
    ])
