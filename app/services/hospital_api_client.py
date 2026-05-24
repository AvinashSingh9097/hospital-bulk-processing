from typing import Any

import httpx

from app.core.config import Settings
from app.core.exceptions import ExternalAPIError


class HospitalAPIClient:
    """
    Thin async wrapper around the Hospital Directory REST API.
    Injected via FastAPI dependency — one shared instance per app lifetime.
    """

    def __init__(self, settings: Settings, client: httpx.AsyncClient) -> None:
        self._base = settings.hospital_api_base_url.rstrip("/")
        self._client = client

    async def create_hospital(
        self,
        *,
        name: str,
        address: str,
        phone: str | None,
        batch_id: str,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "name": name,
            "address": address,
            "creation_batch_id": batch_id,
        }
        if phone:
            payload["phone"] = phone

        resp = await self._client.post(f"{self._base}/hospitals/", json=payload)
        if resp.status_code not in (200, 201):
            raise ExternalAPIError(
                f"Failed to create hospital '{name}': {resp.text}",
                status_code=resp.status_code,
            )
        return resp.json()

    async def activate_batch(self, batch_id: str) -> dict[str, Any]:
        resp = await self._client.patch(
            f"{self._base}/hospitals/batch/{batch_id}/activate"
        )
        if resp.status_code not in (200, 204):
            raise ExternalAPIError(
                f"Failed to activate batch '{batch_id}': {resp.text}",
                status_code=resp.status_code,
            )
        return resp.json() if resp.content else {}

    async def get_batch(self, batch_id: str) -> list[dict[str, Any]]:
        resp = await self._client.get(f"{self._base}/hospitals/batch/{batch_id}")
        if resp.status_code == 404:
            return []
        if resp.status_code != 200:
            raise ExternalAPIError(
                f"Failed to fetch batch '{batch_id}': {resp.text}",
                status_code=resp.status_code,
            )
        return resp.json()

    async def delete_batch(self, batch_id: str) -> None:
        resp = await self._client.delete(f"{self._base}/hospitals/batch/{batch_id}")
        if resp.status_code not in (200, 204, 404):
            raise ExternalAPIError(
                f"Failed to delete batch '{batch_id}': {resp.text}",
                status_code=resp.status_code,
            )
