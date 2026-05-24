class HospitalBulkError(Exception):
    """Base error for this service."""


class CSVValidationError(HospitalBulkError):
    def __init__(self, message: str, row: int | None = None):
        self.row = row
        super().__init__(f"Row {row}: {message}" if row else message)


class CSVTooLargeError(HospitalBulkError):
    def __init__(self, found: int, limit: int):
        super().__init__(
            f"CSV contains {found} rows; maximum allowed is {limit}."
        )


class ExternalAPIError(HospitalBulkError):
    def __init__(self, message: str, status_code: int | None = None):
        self.status_code = status_code
        super().__init__(message)


class BatchNotFoundError(HospitalBulkError):
    def __init__(self, batch_id: str):
        super().__init__(f"Batch '{batch_id}' not found.")
