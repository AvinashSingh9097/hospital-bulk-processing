import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Enum, Float, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class BatchStatus(str, enum.Enum):
    pending = "pending"
    processing = "processing"
    completed = "completed"
    failed = "failed"
    partially_failed = "partially_failed"


class HospitalRowStatus(str, enum.Enum):
    created_and_activated = "created_and_activated"
    failed = "failed"


class Batch(Base):
    __tablename__ = "batches"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    status: Mapped[BatchStatus] = mapped_column(Enum(BatchStatus), default=BatchStatus.pending)
    total_hospitals: Mapped[int] = mapped_column(Integer, default=0)
    processed_hospitals: Mapped[int] = mapped_column(Integer, default=0)
    failed_hospitals: Mapped[int] = mapped_column(Integer, default=0)
    processing_time_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    batch_activated: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )

    hospitals: Mapped[list["HospitalRow"]] = relationship(
        back_populates="batch", cascade="all, delete-orphan",
        passive_deletes=True
    )


class HospitalRow(Base):
    __tablename__ = "hospital_rows"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    batch_id: Mapped[str] = mapped_column(String(36), ForeignKey("batches.id", ondelete="CASCADE"))
    row_number: Mapped[int] = mapped_column(Integer)
    hospital_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    name: Mapped[str] = mapped_column(String(255))
    address: Mapped[str] = mapped_column(String(500))
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    status: Mapped[HospitalRowStatus] = mapped_column(Enum(HospitalRowStatus))
    error_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    batch: Mapped["Batch"] = relationship(back_populates="hospitals")
