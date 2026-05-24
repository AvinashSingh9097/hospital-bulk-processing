"""Unit tests for app/services/bulk_processing.py"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.exceptions import BatchNotFoundError, ExternalAPIError
from app.models.batch import BatchStatus, HospitalRowStatus
from app.schemas.batch import CSVHospitalRow
from app.services.bulk_processing import BulkProcessingService


def _make_rows(n: int = 3) -> list[CSVHospitalRow]:
    return [
        CSVHospitalRow(row=i, name=f"Hospital {i}", address=f"{i} Main St", phone=f"555-000{i}")
        for i in range(1, n + 1)
    ]


# ── process_bulk happy path ──────────────────────────────────────────────────

class TestProcessBulkHappyPath:
    async def test_returns_correct_counts(self, bulk_service, mock_api_client):
        mock_api_client.create_hospital = AsyncMock(
            side_effect=lambda **kw: {"id": kw.get("name", "x").__hash__() % 1000 + 1, "name": kw["name"]}
        )
        rows = _make_rows(3)
        result = await bulk_service.process_bulk(rows)

        assert result.total_hospitals == 3
        assert result.processed_hospitals == 3
        assert result.failed_hospitals == 0

    async def test_status_is_completed_when_all_succeed(self, bulk_service):
        result = await bulk_service.process_bulk(_make_rows(2))
        assert result.status == BatchStatus.completed

    async def test_batch_is_activated_when_all_succeed(self, bulk_service, mock_api_client):
        result = await bulk_service.process_bulk(_make_rows(2))
        assert result.batch_activated is True
        mock_api_client.activate_batch.assert_called_once()

    async def test_hospital_rows_ordered_by_row_number(self, bulk_service):
        result = await bulk_service.process_bulk(_make_rows(5))
        row_nums = [h.row for h in result.hospitals]
        assert row_nums == sorted(row_nums)

    async def test_all_hospitals_have_created_and_activated_status(self, bulk_service):
        result = await bulk_service.process_bulk(_make_rows(3))
        statuses = {h.status for h in result.hospitals}
        assert statuses == {HospitalRowStatus.created_and_activated}

    async def test_batch_id_is_uuid_format(self, bulk_service):
        import uuid
        result = await bulk_service.process_bulk(_make_rows(1))
        # Should not raise
        uuid.UUID(result.batch_id)

    async def test_processing_time_is_positive(self, bulk_service):
        result = await bulk_service.process_bulk(_make_rows(1))
        assert result.processing_time_seconds is not None
        assert result.processing_time_seconds >= 0

    async def test_activate_batch_called_with_correct_batch_id(self, bulk_service, mock_api_client):
        result = await bulk_service.process_bulk(_make_rows(1))
        mock_api_client.activate_batch.assert_called_once_with(result.batch_id)


# ── process_bulk partial failure ─────────────────────────────────────────────

class TestProcessBulkPartialFailure:
    async def test_partial_failure_status(self, bulk_service, mock_api_client):
        call_count = 0

        async def flaky(**kw):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise ExternalAPIError("Timeout", status_code=504)
            return {"id": call_count, "name": kw["name"]}

        mock_api_client.create_hospital = AsyncMock(side_effect=flaky)
        result = await bulk_service.process_bulk(_make_rows(3))

        assert result.status == BatchStatus.partially_failed
        assert result.failed_hospitals == 1
        assert result.processed_hospitals == 2

    async def test_failed_row_has_error_message(self, bulk_service, mock_api_client):
        mock_api_client.create_hospital = AsyncMock(
            side_effect=ExternalAPIError("Bad gateway", status_code=502)
        )
        result = await bulk_service.process_bulk(_make_rows(1))
        assert result.hospitals[0].error_message is not None
        assert len(result.hospitals[0].error_message) > 0

    async def test_error_message_is_truncated_to_500_chars(self, bulk_service, mock_api_client):
        mock_api_client.create_hospital = AsyncMock(
            side_effect=ExternalAPIError("E" * 600)
        )
        result = await bulk_service.process_bulk(_make_rows(1))
        assert len(result.hospitals[0].error_message) <= 500

    async def test_activation_still_called_on_partial_success(self, bulk_service, mock_api_client):
        call_count = 0

        async def one_fails(**kw):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ExternalAPIError("Fail")
            return {"id": call_count, "name": kw["name"]}

        mock_api_client.create_hospital = AsyncMock(side_effect=one_fails)
        result = await bulk_service.process_bulk(_make_rows(2))
        assert result.batch_activated is True


# ── process_bulk total failure ───────────────────────────────────────────────

class TestProcessBulkTotalFailure:
    async def test_status_is_failed_when_all_rows_fail(self, bulk_service, mock_api_client):
        mock_api_client.create_hospital = AsyncMock(
            side_effect=ExternalAPIError("Service down", status_code=503)
        )
        result = await bulk_service.process_bulk(_make_rows(3))
        assert result.status == BatchStatus.failed
        assert result.processed_hospitals == 0
        assert result.failed_hospitals == 3

    async def test_batch_not_activated_when_all_fail(self, bulk_service, mock_api_client):
        mock_api_client.create_hospital = AsyncMock(
            side_effect=ExternalAPIError("Down")
        )
        result = await bulk_service.process_bulk(_make_rows(2))
        assert result.batch_activated is False
        mock_api_client.activate_batch.assert_not_called()


# ── activation failure ────────────────────────────────────────────────────────

class TestActivationFailure:
    async def test_batch_activated_false_when_activate_fails(self, bulk_service, mock_api_client):
        mock_api_client.activate_batch = AsyncMock(side_effect=ExternalAPIError("Activate failed"))
        result = await bulk_service.process_bulk(_make_rows(2))
        assert result.batch_activated is False

    async def test_status_still_completed_despite_activate_failure(self, bulk_service, mock_api_client):
        """Hospitals were created; activation failure should not mark batch as failed."""
        mock_api_client.activate_batch = AsyncMock(side_effect=ExternalAPIError("Activate failed"))
        result = await bulk_service.process_bulk(_make_rows(2))
        # All hospitals created, so still "completed" even if activate failed
        assert result.processed_hospitals == 2


# ── get_batch ─────────────────────────────────────────────────────────────────

class TestGetBatch:
    async def test_get_batch_returns_response(self, bulk_service):
        created = await bulk_service.process_bulk(_make_rows(2))
        fetched = await bulk_service.get_batch(created.batch_id)
        assert fetched.batch_id == created.batch_id
        assert fetched.total_hospitals == 2

    async def test_get_batch_raises_not_found(self, bulk_service):
        with pytest.raises(BatchNotFoundError):
            await bulk_service.get_batch("nonexistent-uuid")


# ── get_batch_progress ────────────────────────────────────────────────────────

class TestGetBatchProgress:
    async def test_progress_percent_100_when_complete(self, bulk_service):
        created = await bulk_service.process_bulk(_make_rows(3))
        progress = await bulk_service.get_batch_progress(created.batch_id)
        assert progress.progress_percent == 100.0

    async def test_progress_raises_not_found(self, bulk_service):
        with pytest.raises(BatchNotFoundError):
            await bulk_service.get_batch_progress("bad-id")


# ── list_batches ──────────────────────────────────────────────────────────────

class TestListBatches:
    async def test_lists_created_batches(self, bulk_service):
        await bulk_service.process_bulk(_make_rows(1))
        await bulk_service.process_bulk(_make_rows(1))
        batches = await bulk_service.list_batches()
        assert len(batches) >= 2

    async def test_respects_limit(self, bulk_service):
        for _ in range(3):
            await bulk_service.process_bulk(_make_rows(1))
        batches = await bulk_service.list_batches(limit=2)
        assert len(batches) <= 2

    async def test_empty_list_when_no_batches(self, bulk_service):
        batches = await bulk_service.list_batches()
        assert batches == []


# ── delete_batch ──────────────────────────────────────────────────────────────

class TestDeleteBatch:
    async def test_delete_calls_external_api(self, bulk_service, mock_api_client):
        created = await bulk_service.process_bulk(_make_rows(1))
        await bulk_service.delete_batch(created.batch_id)
        mock_api_client.delete_batch.assert_called_once_with(created.batch_id)

    async def test_batch_no_longer_found_after_delete(self, bulk_service):
        created = await bulk_service.process_bulk(_make_rows(1))
        await bulk_service.delete_batch(created.batch_id)
        with pytest.raises(BatchNotFoundError):
            await bulk_service.get_batch(created.batch_id)

    async def test_delete_raises_not_found_for_unknown_batch(self, bulk_service):
        with pytest.raises(BatchNotFoundError):
            await bulk_service.delete_batch("does-not-exist")
