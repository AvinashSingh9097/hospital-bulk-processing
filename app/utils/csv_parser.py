import csv
import io
from typing import IO

from app.core.config import Settings
from app.core.exceptions import CSVTooLargeError, CSVValidationError
from app.schemas.batch import CSVHospitalRow, CSVValidationResult

REQUIRED_COLUMNS = {"name", "address"}
OPTIONAL_COLUMNS = {"phone"}
ALL_COLUMNS = REQUIRED_COLUMNS | OPTIONAL_COLUMNS


def _normalise_header(header: list[str]) -> list[str]:
    return [h.strip().lower() for h in header]


def parse_csv(file: IO[bytes], settings: Settings) -> list[CSVHospitalRow]:
    """
    Parse CSV bytes into a list of validated hospital rows.
    Raises CSVValidationError or CSVTooLargeError on problems.
    """
    content = file.read()
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        raise CSVValidationError("File must be UTF-8 encoded.")

    reader = csv.DictReader(io.StringIO(text))

    if reader.fieldnames is None:
        raise CSVValidationError("CSV file is empty or has no header row.")

    header = _normalise_header(list(reader.fieldnames))

    missing = REQUIRED_COLUMNS - set(header)
    if missing:
        raise CSVValidationError(f"Missing required columns: {', '.join(sorted(missing))}.")

    unknown = set(header) - ALL_COLUMNS
    if unknown:
        raise CSVValidationError(f"Unknown columns: {', '.join(sorted(unknown))}.")

    rows: list[CSVHospitalRow] = []

    for i, raw_row in enumerate(reader, start=2):  # row 1 = header
        # Normalise keys
        row = {k.strip().lower(): (v or "").strip() for k, v in raw_row.items() if k}

        name = row.get("name", "")
        address = row.get("address", "")
        phone = row.get("phone") or None

        if not name:
            raise CSVValidationError("'name' must not be empty.", row=i)
        if not address:
            raise CSVValidationError("'address' must not be empty.", row=i)
        if len(name) > 255:
            raise CSVValidationError("'name' exceeds 255 characters.", row=i)
        if len(address) > 500:
            raise CSVValidationError("'address' exceeds 500 characters.", row=i)
        if phone and len(phone) > 50:
            raise CSVValidationError("'phone' exceeds 50 characters.", row=i)

        rows.append(CSVHospitalRow(row=i - 1, name=name, address=address, phone=phone))

    if not rows:
        raise CSVValidationError("CSV contains no data rows.")

    if len(rows) > settings.max_csv_rows:
        raise CSVTooLargeError(found=len(rows), limit=settings.max_csv_rows)

    return rows


def validate_csv(file: IO[bytes], settings: Settings) -> CSVValidationResult:
    """
    Validate CSV without committing to processing.
    Returns a structured result instead of raising.
    """
    errors: list[str] = []
    rows: list[CSVHospitalRow] = []

    try:
        rows = parse_csv(file, settings)
    except (CSVValidationError, CSVTooLargeError) as exc:
        errors.append(str(exc))

    return CSVValidationResult(
        valid=not errors,
        row_count=len(rows),
        errors=errors,
        preview=rows[:5],
    )
