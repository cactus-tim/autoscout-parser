"""Tests for sheets/schema.py constants and invariants."""

from autoscout_pipeline.sheets.schema import (
    LISTINGS_HEADERS,
    SCORE_COLUMN_LETTER,
    SheetSchemaError,
)


def test_listings_has_16_headers() -> None:
    assert len(LISTINGS_HEADERS) == 16, (
        f"Expected 16 headers, got {len(LISTINGS_HEADERS)}: {LISTINGS_HEADERS}"
    )


def test_score_column_letter_matches_header_index() -> None:
    """SCORE_COLUMN_LETTER must equal chr(A + index_of_score) and must be 'L'."""
    idx = LISTINGS_HEADERS.index("score")
    derived = chr(ord("A") + idx)
    assert derived == "L", f"score is at index {idx} → column {derived}, expected L"
    assert SCORE_COLUMN_LETTER == "L", f"SCORE_COLUMN_LETTER={SCORE_COLUMN_LETTER!r}, expected 'L'"


def test_score_index_is_11() -> None:
    """score must be at 0-based index 11 (column L)."""
    assert LISTINGS_HEADERS.index("score") == 11


def test_sheet_schema_error_is_exception() -> None:
    """SheetSchemaError must be importable and subclass Exception."""
    assert issubclass(SheetSchemaError, Exception)


def test_all_header_names_are_unique() -> None:
    assert len(LISTINGS_HEADERS) == len(set(LISTINGS_HEADERS)), (
        "Duplicate header names found in LISTINGS_HEADERS"
    )
