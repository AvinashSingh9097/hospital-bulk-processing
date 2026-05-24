"""Unit tests for app/utils/csv_parser.py"""
import io

import pytest

from app.core.config import Settings
from app.core.exceptions import CSVTooLargeError, CSVValidationError
from app.utils.csv_parser import parse_csv, validate_csv
from tests.conftest import make_csv, make_valid_csv


@pytest.fixture()
def settings() -> Settings:
    return Settings(max_csv_rows=5, database_url="sqlite+aiosqlite:///:memory:")


# ── parse_csv happy path ─────────────────────────────────────────────────────

class TestParseCsvHappyPath:
    def test_parses_all_three_columns(self, settings):
        csv = make_csv([{"name": "St Mary", "address": "1 Church Ln", "phone": "555-0001"}])
        rows = parse_csv(csv, settings)
        assert len(rows) == 1
        assert rows[0].name == "St Mary"
        assert rows[0].address == "1 Church Ln"
        assert rows[0].phone == "555-0001"

    def test_phone_is_optional(self, settings):
        csv = make_csv([{"name": "City Clinic", "address": "2 Park Ave", "phone": ""}])
        rows = parse_csv(csv, settings)
        assert rows[0].phone is None

    def test_row_numbers_start_at_one(self, settings):
        csv = make_valid_csv(3)
        rows = parse_csv(csv, settings)
        assert [r.row for r in rows] == [1, 2, 3]

    def test_multiple_rows(self, settings):
        csv = make_valid_csv(5)
        rows = parse_csv(csv, settings)
        assert len(rows) == 5

    def test_strips_whitespace_from_values(self, settings):
        csv = io.BytesIO(b"name,address,phone\n  General Hospital ,  42 Oak St  ,  555-9999  ")
        rows = parse_csv(csv, settings)
        assert rows[0].name == "General Hospital"
        assert rows[0].address == "42 Oak St"
        assert rows[0].phone == "555-9999"

    def test_header_case_insensitive(self, settings):
        csv = io.BytesIO(b"NAME,ADDRESS,PHONE\nHosp A,1 St,")
        rows = parse_csv(csv, settings)
        assert rows[0].name == "Hosp A"


# ── parse_csv validation errors ──────────────────────────────────────────────

class TestParseCsvValidationErrors:
    def test_raises_on_empty_file(self, settings):
        with pytest.raises(CSVValidationError, match="empty"):
            parse_csv(io.BytesIO(b""), settings)

    def test_raises_on_missing_name_column(self, settings):
        csv = io.BytesIO(b"address,phone\n1 Main St,555")
        with pytest.raises(CSVValidationError, match="name"):
            parse_csv(csv, settings)

    def test_raises_on_missing_address_column(self, settings):
        csv = io.BytesIO(b"name,phone\nHosp A,555")
        with pytest.raises(CSVValidationError, match="address"):
            parse_csv(csv, settings)

    def test_raises_on_unknown_column(self, settings):
        csv = io.BytesIO(b"name,address,email\nHosp A,1 St,x@y.com")
        with pytest.raises(CSVValidationError, match="Unknown"):
            parse_csv(csv, settings)

    def test_raises_on_empty_name_value(self, settings):
        csv = make_csv([{"name": "", "address": "1 St", "phone": ""}])
        with pytest.raises(CSVValidationError, match="name"):
            parse_csv(csv, settings)

    def test_raises_on_empty_address_value(self, settings):
        csv = make_csv([{"name": "Hosp", "address": "", "phone": ""}])
        with pytest.raises(CSVValidationError, match="address"):
            parse_csv(csv, settings)

    def test_raises_when_no_data_rows(self, settings):
        csv = io.BytesIO(b"name,address,phone\n")
        with pytest.raises(CSVValidationError, match="no data"):
            parse_csv(csv, settings)

    def test_raises_on_non_utf8(self, settings):
        csv = io.BytesIO(b"name,address\n\xff\xfe bad,1 St")
        with pytest.raises(CSVValidationError, match="UTF-8"):
            parse_csv(csv, settings)

    def test_raises_when_name_too_long(self, settings):
        long_name = "A" * 256
        csv = make_csv([{"name": long_name, "address": "1 St"}])
        with pytest.raises(CSVValidationError, match="name"):
            parse_csv(csv, settings)

    def test_raises_when_address_too_long(self, settings):
        long_addr = "A" * 501
        csv = make_csv([{"name": "Hosp", "address": long_addr}])
        with pytest.raises(CSVValidationError, match="address"):
            parse_csv(csv, settings)

    def test_raises_when_phone_too_long(self, settings):
        csv = make_csv([{"name": "Hosp", "address": "1 St", "phone": "5" * 51}])
        with pytest.raises(CSVValidationError, match="phone"):
            parse_csv(csv, settings)

    def test_raises_csv_too_large(self, settings):
        csv = make_valid_csv(6)  # limit is 5
        with pytest.raises(CSVTooLargeError):
            parse_csv(csv, settings)

    def test_error_message_includes_row_number(self, settings):
        csv = io.BytesIO(b"name,address\nOK Hosp,1 St\n,missing name")
        with pytest.raises(CSVValidationError, match="Row 3"):
            parse_csv(csv, settings)


# ── validate_csv (non-raising version) ──────────────────────────────────────

class TestValidateCsv:
    def test_returns_valid_true_for_good_file(self, settings):
        result = validate_csv(make_valid_csv(2), settings)
        assert result.valid is True
        assert result.row_count == 2
        assert result.errors == []

    def test_returns_valid_false_for_bad_file(self, settings):
        result = validate_csv(io.BytesIO(b"wrong,cols\na,b"), settings)
        assert result.valid is False
        assert len(result.errors) > 0

    def test_preview_capped_at_five_rows(self, settings):
        # settings.max_csv_rows = 5, so send exactly 5
        result = validate_csv(make_valid_csv(5), settings)
        assert len(result.preview) == 5

    def test_returns_errors_list_not_raises(self, settings):
        """validate_csv must never raise — it should capture and return errors."""
        result = validate_csv(io.BytesIO(b""), settings)
        assert result.valid is False
        assert result.errors
