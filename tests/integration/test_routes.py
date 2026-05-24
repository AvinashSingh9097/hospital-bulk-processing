"""
Integration tests for HTTP routes.

Uses httpx.AsyncClient with ASGITransport so FastAPI middleware,
exception handlers, and request parsing are all exercised.
The external Hospital Directory API is replaced by a mock client.
"""
import io
from typing import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api import deps
from app.core.config import Settings
from app.core.exceptions import ExternalAPIError
from app.db.session import Base, get_db
from app.main import create_app
from app.services.hospital_api_client import HospitalAPIClient
from tests.conftest import make_csv, make_valid_csv


# ── Test-scoped fixtures ─────────────────────────────────────────────────────

@pytest.fixture()
def test_settings() -> Settings:
    return Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        hospital_api_base_url="https://fake.test",
        max_csv_rows=20,
        http_concurrency_limit=5,
    )


@pytest_asyncio.fixture()
async def db_engine(test_settings):
    engine = create_async_engine(
        test_settings.database_url, connect_args={"check_same_thread": False}
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture()
async def db_session_factory(db_engine):
    return async_sessionmaker(db_engine, expire_on_commit=False, autoflush=False)


@pytest.fixture()
def mock_api_client() -> MagicMock:
    client = MagicMock(spec=HospitalAPIClient)
    client.create_hospital = AsyncMock(return_value={"id": 99, "name": "Test"})
    client.activate_batch = AsyncMock(return_value={})
    client.delete_batch = AsyncMock(return_value=None)
    client.get_batch = AsyncMock(return_value=[])
    return client


@pytest_asyncio.fixture()
async def api_client(
    test_settings, db_session_factory, mock_api_client
) -> AsyncGenerator[AsyncClient, None]:
    """
    Stand-up the FastAPI app with all DI overridden:
    - DB: in-memory SQLite
    - External API: mock
    - Settings: test settings
    """
    app = create_app()

    async def override_db() -> AsyncGenerator[AsyncSession, None]:
        async with db_session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[deps.get_settings] = lambda: test_settings
    app.dependency_overrides[deps.get_http_client] = lambda: MagicMock()
    app.dependency_overrides[deps.get_hospital_api_client] = lambda: mock_api_client

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client


def _csv_upload(content: bytes | io.BytesIO, filename: str = "hospitals.csv"):
    if isinstance(content, io.BytesIO):
        content = content.getvalue()
    return {"file": (filename, content, "text/csv")}


# ── Health check ─────────────────────────────────────────────────────────────

class TestHealth:
    async def test_health_returns_200(self, api_client):
        resp = await api_client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"


# ── POST /api/v1/hospitals/bulk ───────────────────────────────────────────────

class TestBulkCreate:
    async def test_happy_path_returns_201(self, api_client):
        resp = await api_client.post(
            "/api/v1/hospitals/bulk",
            files=_csv_upload(make_valid_csv(3)),
        )
        assert resp.status_code == 201

    async def test_response_shape(self, api_client):
        resp = await api_client.post(
            "/api/v1/hospitals/bulk",
            files=_csv_upload(make_valid_csv(2)),
        )
        body = resp.json()
        assert "batch_id" in body
        assert "total_hospitals" in body
        assert "processed_hospitals" in body
        assert "failed_hospitals" in body
        assert "batch_activated" in body
        assert "hospitals" in body

    async def test_total_hospitals_matches_csv_rows(self, api_client):
        resp = await api_client.post(
            "/api/v1/hospitals/bulk",
            files=_csv_upload(make_valid_csv(4)),
        )
        assert resp.json()["total_hospitals"] == 4

    async def test_returns_422_for_non_csv_file(self, api_client):
        resp = await api_client.post(
            "/api/v1/hospitals/bulk",
            files={"file": ("data.txt", b"name,address\na,b", "text/plain")},
        )
        assert resp.status_code == 422

    async def test_returns_422_for_missing_columns(self, api_client):
        csv = io.BytesIO(b"wrong,cols\na,b")
        resp = await api_client.post(
            "/api/v1/hospitals/bulk",
            files=_csv_upload(csv),
        )
        assert resp.status_code == 422

    async def test_returns_413_when_csv_exceeds_limit(self, api_client, test_settings):
        test_settings.max_csv_rows = 2
        csv = make_valid_csv(3)
        resp = await api_client.post(
            "/api/v1/hospitals/bulk",
            files=_csv_upload(csv),
        )
        assert resp.status_code == 413

    async def test_returns_422_for_empty_csv(self, api_client):
        resp = await api_client.post(
            "/api/v1/hospitals/bulk",
            files=_csv_upload(io.BytesIO(b"")),
        )
        assert resp.status_code == 422

    async def test_batch_activated_true_on_success(self, api_client):
        resp = await api_client.post(
            "/api/v1/hospitals/bulk",
            files=_csv_upload(make_valid_csv(2)),
        )
        assert resp.json()["batch_activated"] is True

    async def test_hospital_rows_in_response(self, api_client):
        resp = await api_client.post(
            "/api/v1/hospitals/bulk",
            files=_csv_upload(make_valid_csv(2)),
        )
        hospitals = resp.json()["hospitals"]
        assert len(hospitals) == 2
        assert all("row" in h for h in hospitals)
        assert all("status" in h for h in hospitals)

    async def test_api_client_failure_reflected_in_response(
        self, api_client, mock_api_client
    ):
        mock_api_client.create_hospital = AsyncMock(
            side_effect=ExternalAPIError("Upstream error")
        )
        resp = await api_client.post(
            "/api/v1/hospitals/bulk",
            files=_csv_upload(make_valid_csv(2)),
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["failed_hospitals"] == 2
        assert body["processed_hospitals"] == 0


# ── POST /api/v1/hospitals/bulk/validate ────────────────────────────────────

class TestValidateCSV:
    async def test_valid_csv_returns_valid_true(self, api_client):
        resp = await api_client.post(
            "/api/v1/hospitals/bulk/validate",
            files=_csv_upload(make_valid_csv(3)),
        )
        assert resp.status_code == 200
        assert resp.json()["valid"] is True

    async def test_invalid_csv_returns_valid_false(self, api_client):
        resp = await api_client.post(
            "/api/v1/hospitals/bulk/validate",
            files=_csv_upload(io.BytesIO(b"bad,columns\na,b")),
        )
        assert resp.json()["valid"] is False

    async def test_errors_list_populated_on_invalid(self, api_client):
        resp = await api_client.post(
            "/api/v1/hospitals/bulk/validate",
            files=_csv_upload(io.BytesIO(b"")),
        )
        assert len(resp.json()["errors"]) > 0

    async def test_preview_returned_for_valid_csv(self, api_client):
        resp = await api_client.post(
            "/api/v1/hospitals/bulk/validate",
            files=_csv_upload(make_valid_csv(3)),
        )
        assert len(resp.json()["preview"]) == 3

    async def test_no_hospitals_created_during_validation(
        self, api_client, mock_api_client
    ):
        await api_client.post(
            "/api/v1/hospitals/bulk/validate",
            files=_csv_upload(make_valid_csv(3)),
        )
        mock_api_client.create_hospital.assert_not_called()


# ── GET /api/v1/hospitals/bulk ───────────────────────────────────────────────

class TestListBatches:
    async def test_empty_list_initially(self, api_client):
        resp = await api_client.get("/api/v1/hospitals/bulk")
        assert resp.status_code == 200
        assert resp.json()["batches"] == []

    async def test_lists_created_batch(self, api_client):
        await api_client.post(
            "/api/v1/hospitals/bulk",
            files=_csv_upload(make_valid_csv(1)),
        )
        resp = await api_client.get("/api/v1/hospitals/bulk")
        assert resp.json()["total"] == 1

    async def test_respects_limit_param(self, api_client):
        for _ in range(3):
            await api_client.post(
                "/api/v1/hospitals/bulk",
                files=_csv_upload(make_valid_csv(1)),
            )
        resp = await api_client.get("/api/v1/hospitals/bulk?limit=2")
        assert len(resp.json()["batches"]) <= 2


# ── GET /api/v1/hospitals/bulk/{batch_id} ────────────────────────────────────

class TestGetBatch:
    async def test_get_existing_batch(self, api_client):
        create_resp = await api_client.post(
            "/api/v1/hospitals/bulk",
            files=_csv_upload(make_valid_csv(2)),
        )
        batch_id = create_resp.json()["batch_id"]
        resp = await api_client.get(f"/api/v1/hospitals/bulk/{batch_id}")
        assert resp.status_code == 200
        assert resp.json()["batch_id"] == batch_id

    async def test_returns_404_for_unknown_batch(self, api_client):
        resp = await api_client.get("/api/v1/hospitals/bulk/nonexistent-id")
        assert resp.status_code == 404


# ── GET /api/v1/hospitals/bulk/{batch_id}/progress ──────────────────────────

class TestGetBatchProgress:
    async def test_progress_for_completed_batch(self, api_client):
        create_resp = await api_client.post(
            "/api/v1/hospitals/bulk",
            files=_csv_upload(make_valid_csv(2)),
        )
        batch_id = create_resp.json()["batch_id"]
        resp = await api_client.get(f"/api/v1/hospitals/bulk/{batch_id}/progress")
        assert resp.status_code == 200
        assert resp.json()["progress_percent"] == 100.0

    async def test_progress_returns_404_for_unknown_batch(self, api_client):
        resp = await api_client.get("/api/v1/hospitals/bulk/bad-id/progress")
        assert resp.status_code == 404


# ── DELETE /api/v1/hospitals/bulk/{batch_id} ─────────────────────────────────

class TestDeleteBatch:
    async def test_delete_existing_batch_returns_204(self, api_client):
        create_resp = await api_client.post(
            "/api/v1/hospitals/bulk",
            files=_csv_upload(make_valid_csv(1)),
        )
        batch_id = create_resp.json()["batch_id"]
        resp = await api_client.delete(f"/api/v1/hospitals/bulk/{batch_id}")
        assert resp.status_code == 204

    async def test_batch_gone_after_delete(self, api_client):
        create_resp = await api_client.post(
            "/api/v1/hospitals/bulk",
            files=_csv_upload(make_valid_csv(1)),
        )
        batch_id = create_resp.json()["batch_id"]
        await api_client.delete(f"/api/v1/hospitals/bulk/{batch_id}")
        resp = await api_client.get(f"/api/v1/hospitals/bulk/{batch_id}")
        assert resp.status_code == 404

    async def test_delete_unknown_batch_returns_404(self, api_client):
        resp = await api_client.delete("/api/v1/hospitals/bulk/ghost-batch")
        assert resp.status_code == 404
