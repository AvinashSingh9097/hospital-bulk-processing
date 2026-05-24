"""Unit tests for app/services/hospital_api_client.py"""
import json
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from app.core.config import Settings
from app.core.exceptions import ExternalAPIError
from app.services.hospital_api_client import HospitalAPIClient


@pytest.fixture()
def settings() -> Settings:
    return Settings(
        hospital_api_base_url="https://fake-api.test",
        database_url="sqlite+aiosqlite:///:memory:",
    )


def _mock_response(status_code: int, body: dict | list | None = None) -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.text = json.dumps(body or {})
    resp.content = json.dumps(body or {}).encode()
    resp.json = MagicMock(return_value=body or {})
    return resp


@pytest.fixture()
def mock_http(settings) -> tuple[HospitalAPIClient, MagicMock]:
    http = MagicMock(spec=httpx.AsyncClient)
    client = HospitalAPIClient(settings=settings, client=http)
    return client, http


class TestCreateHospital:
    async def test_returns_hospital_data_on_201(self, mock_http):
        client, http = mock_http
        expected = {"id": 42, "name": "General"}
        http.post = AsyncMock(return_value=_mock_response(201, expected))

        result = await client.create_hospital(
            name="General", address="1 St", phone="555", batch_id="batch-1"
        )
        assert result["id"] == 42

    async def test_accepts_200_status(self, mock_http):
        client, http = mock_http
        http.post = AsyncMock(return_value=_mock_response(200, {"id": 7, "name": "City"}))
        result = await client.create_hospital(name="City", address="2 Ave", phone=None, batch_id="b")
        assert result["id"] == 7

    async def test_raises_on_4xx(self, mock_http):
        client, http = mock_http
        http.post = AsyncMock(return_value=_mock_response(422, {"detail": "Invalid"}))
        with pytest.raises(ExternalAPIError) as exc_info:
            await client.create_hospital(name="X", address="Y", phone=None, batch_id="b")
        assert exc_info.value.status_code == 422

    async def test_raises_on_5xx(self, mock_http):
        client, http = mock_http
        http.post = AsyncMock(return_value=_mock_response(503))
        with pytest.raises(ExternalAPIError) as exc_info:
            await client.create_hospital(name="X", address="Y", phone=None, batch_id="b")
        assert exc_info.value.status_code == 503

    async def test_phone_omitted_from_payload_when_none(self, mock_http):
        client, http = mock_http
        http.post = AsyncMock(return_value=_mock_response(201, {"id": 1}))
        await client.create_hospital(name="X", address="Y", phone=None, batch_id="b")

        _, kwargs = http.post.call_args
        payload = kwargs["json"]
        assert "phone" not in payload

    async def test_phone_included_in_payload_when_provided(self, mock_http):
        client, http = mock_http
        http.post = AsyncMock(return_value=_mock_response(201, {"id": 1}))
        await client.create_hospital(name="X", address="Y", phone="999", batch_id="b")

        _, kwargs = http.post.call_args
        assert kwargs["json"]["phone"] == "999"

    async def test_batch_id_in_payload(self, mock_http):
        client, http = mock_http
        http.post = AsyncMock(return_value=_mock_response(201, {"id": 1}))
        await client.create_hospital(name="X", address="Y", phone=None, batch_id="my-batch")

        _, kwargs = http.post.call_args
        assert kwargs["json"]["creation_batch_id"] == "my-batch"


class TestActivateBatch:
    async def test_returns_dict_on_200(self, mock_http):
        client, http = mock_http
        http.patch = AsyncMock(return_value=_mock_response(200, {"activated": True}))
        result = await client.activate_batch("batch-123")
        assert result == {"activated": True}

    async def test_returns_empty_dict_on_204(self, mock_http):
        client, http = mock_http
        resp = _mock_response(204)
        resp.content = b""
        http.patch = AsyncMock(return_value=resp)
        result = await client.activate_batch("batch-123")
        assert result == {}

    async def test_raises_on_error_status(self, mock_http):
        client, http = mock_http
        http.patch = AsyncMock(return_value=_mock_response(500))
        with pytest.raises(ExternalAPIError):
            await client.activate_batch("batch-123")


class TestDeleteBatch:
    async def test_succeeds_on_204(self, mock_http):
        client, http = mock_http
        http.delete = AsyncMock(return_value=_mock_response(204))
        await client.delete_batch("batch-abc")  # should not raise

    async def test_succeeds_on_404(self, mock_http):
        """Deleting an already-gone batch should be idempotent."""
        client, http = mock_http
        http.delete = AsyncMock(return_value=_mock_response(404))
        await client.delete_batch("ghost-batch")

    async def test_raises_on_500(self, mock_http):
        client, http = mock_http
        http.delete = AsyncMock(return_value=_mock_response(500))
        with pytest.raises(ExternalAPIError):
            await client.delete_batch("batch-abc")


class TestGetBatch:
    async def test_returns_list_on_200(self, mock_http):
        client, http = mock_http
        data = [{"id": 1}, {"id": 2}]
        http.get = AsyncMock(return_value=_mock_response(200, data))
        result = await client.get_batch("batch-xyz")
        assert len(result) == 2

    async def test_returns_empty_list_on_404(self, mock_http):
        client, http = mock_http
        http.get = AsyncMock(return_value=_mock_response(404))
        result = await client.get_batch("missing")
        assert result == []

    async def test_raises_on_error(self, mock_http):
        client, http = mock_http
        http.get = AsyncMock(return_value=_mock_response(500))
        with pytest.raises(ExternalAPIError):
            await client.get_batch("batch-xyz")
