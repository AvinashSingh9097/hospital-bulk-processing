from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from app.models.batch import BatchStatus, HospitalRowStatus


# ── CSV row (internal) ──────────────────────────────────────────────────────
class CSVHospitalRow(BaseModel):
    row: int
    name: str
    address: str
    phone: Optional[str] = None


# ── Response sub-models ─────────────────────────────────────────────────────
class HospitalResult(BaseModel):
    row: int
    hospital_id: Optional[int]
    name: str
    status: HospitalRowStatus
    error_message: Optional[str] = None

    model_config = {"from_attributes": True}


class BatchResponse(BaseModel):
    batch_id: str = Field(alias="id")
    status: BatchStatus
    total_hospitals: int
    processed_hospitals: int
    failed_hospitals: int
    processing_time_seconds: Optional[float]
    batch_activated: bool
    hospitals: list[HospitalResult]
    created_at: datetime

    model_config = {"from_attributes": True, "populate_by_name": True}  # ← add populate_by_name


class BatchSummary(BaseModel):
    batch_id: str = Field(alias="id")   # ← add alias
    status: BatchStatus
    total_hospitals: int
    processed_hospitals: int
    failed_hospitals: int
    batch_activated: bool
    created_at: datetime

    model_config = {"from_attributes": True, "populate_by_name": True}  # ← add populate_by_name


class BatchListResponse(BaseModel):
    batches: list[BatchSummary]
    total: int


# ── CSV Validation ──────────────────────────────────────────────────────────
class CSVValidationResult(BaseModel):
    valid: bool
    row_count: int
    errors: list[str] = Field(default_factory=list)
    preview: list[CSVHospitalRow] = Field(default_factory=list)


# ── Progress (polling) ──────────────────────────────────────────────────────
class BatchProgress(BaseModel):
    batch_id: str
    status: BatchStatus
    total_hospitals: int
    processed_hospitals: int
    failed_hospitals: int
    progress_percent: float
    batch_activated: bool
