"""
Central DI wiring.
All FastAPI route parameters that need a service/client pull from here.
"""
from typing import Annotated, AsyncGenerator

import httpx
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.services.bulk_processing import BulkProcessingService
from app.services.hospital_api_client import HospitalAPIClient

# ── Shared HTTP client (one per app lifetime) ────────────────────────────────
_http_client: httpx.AsyncClient | None = None


def get_http_client() -> httpx.AsyncClient:
    if _http_client is None:
        raise RuntimeError("HTTP client not initialised. Call init_http_client() on startup.")
    return _http_client


async def init_http_client(settings: Settings) -> None:
    global _http_client
    _http_client = httpx.AsyncClient(
        timeout=settings.hospital_api_timeout,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )


async def close_http_client() -> None:
    global _http_client
    if _http_client:
        await _http_client.aclose()
        _http_client = None


# ── Typed dependency aliases ─────────────────────────────────────────────────
SettingsDep = Annotated[Settings, Depends(get_settings)]
DBDep = Annotated[AsyncSession, Depends(get_db)]


def get_hospital_api_client(
    settings: SettingsDep,
    client: Annotated[httpx.AsyncClient, Depends(get_http_client)],
) -> HospitalAPIClient:
    return HospitalAPIClient(settings=settings, client=client)


HospitalAPIClientDep = Annotated[HospitalAPIClient, Depends(get_hospital_api_client)]


def get_bulk_service(
    db: DBDep,
    api_client: HospitalAPIClientDep,
    settings: SettingsDep,
) -> BulkProcessingService:
    return BulkProcessingService(db=db, api_client=api_client, settings=settings)


BulkServiceDep = Annotated[BulkProcessingService, Depends(get_bulk_service)]
