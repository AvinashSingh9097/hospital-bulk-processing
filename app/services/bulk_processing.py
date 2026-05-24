import asyncio
import time
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import Settings
from app.core.exceptions import BatchNotFoundError
from app.models.batch import Batch, BatchStatus, HospitalRow, HospitalRowStatus
from app.schemas.batch import BatchProgress, BatchResponse, BatchSummary, CSVHospitalRow
from app.services.hospital_api_client import HospitalAPIClient
from sqlalchemy import delete, select


class BulkProcessingService:
    """
    Orchestrates: CSV rows → external API calls → DB persistence → batch activation.
    All dependencies injected; no global state.
    """

    def __init__(
        self,
        db: AsyncSession,
        api_client: HospitalAPIClient,
        settings: Settings,
    ) -> None:
        self._db = db
        self._api = api_client
        self._semaphore = asyncio.Semaphore(settings.http_concurrency_limit)

    # ── Public interface ────────────────────────────────────────────────────

    async def process_bulk(self, rows: list[CSVHospitalRow]) -> BatchResponse:
        batch_id = str(uuid.uuid4())
        batch = Batch(
            id=batch_id,
            status=BatchStatus.processing,
            total_hospitals=len(rows),
        )
        self._db.add(batch)
        await self._db.flush()  # persist so FK constraints hold

        start = time.monotonic()

        hospital_rows = await self._create_hospitals_concurrently(batch_id, rows)

        for hr in hospital_rows:
            self._db.add(hr)
        await self._db.flush()

        processed = sum(1 for hr in hospital_rows if hr.status == HospitalRowStatus.created_and_activated)
        failed = len(hospital_rows) - processed

        activated = False
        if processed > 0:
            activated = await self._activate_batch(batch_id)

        elapsed = round(time.monotonic() - start, 3)

        if failed == 0:
            final_status = BatchStatus.completed
        elif processed == 0:
            final_status = BatchStatus.failed
        else:
            final_status = BatchStatus.partially_failed

        batch.status = final_status
        batch.processed_hospitals = processed
        batch.failed_hospitals = failed
        batch.processing_time_seconds = elapsed
        batch.batch_activated = activated
        await self._db.flush()

        return self._to_response(batch, hospital_rows)

    async def get_batch(self, batch_id: str) -> BatchResponse:
        batch = await self._load_batch(batch_id)
        return self._to_response(batch, batch.hospitals)

    async def get_batch_progress(self, batch_id: str) -> BatchProgress:
        batch = await self._load_batch(batch_id)
        total = batch.total_hospitals or 1  # avoid /0
        done = batch.processed_hospitals + batch.failed_hospitals
        return BatchProgress(
            batch_id=batch.id,
            status=batch.status,
            total_hospitals=batch.total_hospitals,
            processed_hospitals=batch.processed_hospitals,
            failed_hospitals=batch.failed_hospitals,
            progress_percent=round(done / total * 100, 1),
            batch_activated=batch.batch_activated,
        )

    async def list_batches(self, skip: int = 0, limit: int = 50) -> list[BatchSummary]:
        result = await self._db.execute(
            select(Batch).order_by(Batch.created_at.desc()).offset(skip).limit(limit)
        )
        return [BatchSummary.model_validate(b) for b in result.scalars()]

    async def delete_batch(self, batch_id: str) -> None:
        batch = await self._load_batch(batch_id)
        
        await self._db.execute(
            delete(HospitalRow).where(HospitalRow.batch_id == batch_id)
        )
        
        await self._api.delete_batch(batch_id)
        await self._db.delete(batch)
        await self._db.flush()

    # ── Internal helpers ────────────────────────────────────────────────────

    async def _create_hospitals_concurrently(
        self, batch_id: str, rows: list[CSVHospitalRow]
    ) -> list[HospitalRow]:
        tasks = [self._create_one(batch_id, row) for row in rows]
        return list(await asyncio.gather(*tasks))

    async def _create_one(self, batch_id: str, row: CSVHospitalRow) -> HospitalRow:
        async with self._semaphore:
            try:
                data: dict[str, Any] = await self._api.create_hospital(
                    name=row.name,
                    address=row.address,
                    phone=row.phone,
                    batch_id=batch_id,
                )
                return HospitalRow(
                    batch_id=batch_id,
                    row_number=row.row,
                    hospital_id=data.get("id"),
                    name=row.name,
                    address=row.address,
                    phone=row.phone,
                    status=HospitalRowStatus.created_and_activated,
                )
            except Exception as exc:
                return HospitalRow(
                    batch_id=batch_id,
                    row_number=row.row,
                    hospital_id=None,
                    name=row.name,
                    address=row.address,
                    phone=row.phone,
                    status=HospitalRowStatus.failed,
                    error_message=str(exc)[:500],
                )

    async def _activate_batch(self, batch_id: str) -> bool:
        try:
            await self._api.activate_batch(batch_id)
            return True
        except Exception:
            return False

    async def _load_batch(self, batch_id: str) -> Batch:
        result = await self._db.execute(
            select(Batch)
            .where(Batch.id == batch_id)
            .options(selectinload(Batch.hospitals))
        )
        batch = result.scalar_one_or_none()
        if batch is None:
            raise BatchNotFoundError(batch_id)
        return batch

    @staticmethod
    def _to_response(batch: Batch, rows: list[HospitalRow]) -> BatchResponse:
        from app.schemas.batch import HospitalResult

        return BatchResponse(
            batch_id=batch.id,
            status=batch.status,
            total_hospitals=batch.total_hospitals,
            processed_hospitals=batch.processed_hospitals,
            failed_hospitals=batch.failed_hospitals,
            processing_time_seconds=batch.processing_time_seconds,
            batch_activated=batch.batch_activated,
            created_at=batch.created_at,
            hospitals=[
                HospitalResult(
                    row=hr.row_number,
                    hospital_id=hr.hospital_id,
                    name=hr.name,
                    status=hr.status,
                    error_message=hr.error_message,
                )
                for hr in sorted(rows, key=lambda r: r.row_number)
            ],
        )
