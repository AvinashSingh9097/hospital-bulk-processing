from typing import Annotated

from fastapi import APIRouter, File, HTTPException, Query, UploadFile, status

from app.api.deps import BulkServiceDep, SettingsDep
from app.schemas.batch import (
    BatchListResponse,
    BatchProgress,
    BatchResponse,
    CSVValidationResult,
)
from app.utils.csv_parser import parse_csv, validate_csv

router = APIRouter(prefix="/hospitals", tags=["Hospitals Bulk"])


@router.post(
    "/bulk",
    response_model=BatchResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Bulk-create hospitals from a CSV file",
)
async def bulk_create_hospitals(
    service: BulkServiceDep,
    settings: SettingsDep,
    file: Annotated[UploadFile, File(description="CSV with columns: name, address, phone(optional)")],
) -> BatchResponse:
    """
    Upload a CSV file to create hospitals in bulk.

    - Validates the CSV structure and row limits.
    - Creates each hospital via the Hospital Directory API.
    - Activates the batch once all hospitals are created.
    - Returns full processing results including per-row status.
    """
    if not file.filename or not file.filename.endswith(".csv"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="File must be a .csv file.",
        )

    rows = parse_csv(file.file, settings)
    return await service.process_bulk(rows)


@router.post(
    "/bulk/validate",
    response_model=CSVValidationResult,
    summary="Validate a CSV file without processing it",
)
async def validate_csv_file(
    settings: SettingsDep,
    file: Annotated[UploadFile, File(description="CSV file to validate")],
) -> CSVValidationResult:
    """Dry-run CSV validation — no hospitals are created."""
    return validate_csv(file.file, settings)


@router.get(
    "/bulk",
    response_model=BatchListResponse,
    summary="List all bulk processing batches",
)
async def list_batches(
    service: BulkServiceDep,
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> BatchListResponse:
    batches = await service.list_batches(skip=skip, limit=limit)
    return BatchListResponse(batches=batches, total=len(batches))


@router.get(
    "/bulk/{batch_id}",
    response_model=BatchResponse,
    summary="Get full details of a batch",
)
async def get_batch(batch_id: str, service: BulkServiceDep) -> BatchResponse:
    return await service.get_batch(batch_id)


@router.get(
    "/bulk/{batch_id}/progress",
    response_model=BatchProgress,
    summary="Poll real-time progress of a running batch",
)
async def get_batch_progress(batch_id: str, service: BulkServiceDep) -> BatchProgress:
    return await service.get_batch_progress(batch_id)


@router.delete(
    "/bulk/{batch_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a batch and all its hospitals from the directory",
)
async def delete_batch(batch_id: str, service: BulkServiceDep) -> None:
    await service.delete_batch(batch_id)
