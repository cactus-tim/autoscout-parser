"""Live integration tests against a real Google Spreadsheet.

These tests verify the full Sheets contract end-to-end.  They are skipped by
default — see conftest.py for the skip conditions and how to enable them.

All tests depend on the ``live_client`` session-scoped fixture which pre- and
post-cleans the three pipeline tabs (listings, price_history, runs).
"""

from __future__ import annotations

from datetime import UTC, datetime

from gspread_formatting import get_conditional_format_rules

from autoscout_pipeline.models import Listing, ListingScore, RunRecord, ScoredListing
from autoscout_pipeline.sheets.schema import (
    LISTINGS_HEADERS,
    LISTINGS_TAB,
    PRICE_HISTORY_HEADERS,
    PRICE_HISTORY_TAB,
    RUNS_HEADERS,
    RUNS_TAB,
    SCORE_COLUMN_LETTER,
)

# ---------------------------------------------------------------------------
# Helper factories
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 5, 1, 12, 0, 0, tzinfo=UTC)


def _make_scored(
    listing_id: str,
    price_eur: int,
    score: int = 7,
) -> ScoredListing:
    """Build a minimal ScoredListing suitable for upsert tests."""
    listing = Listing(
        listing_id=listing_id,
        url=f"https://www.autoscout24.com/lst/{listing_id}",
        brand="MINI",
        model="Hatch",
        year=2020,
        mileage_km=25000,
        price_eur=price_eur,
        location="Munich",
        country="DE",
        first_seen=_NOW,
        last_seen=_NOW,
    )
    ls = ListingScore(
        score=score,
        reasoning="Test reasoning",
        pros=["low mileage", "good price"],
        cons=["no navigation"],
    )
    return ScoredListing(listing=listing, score=ls, scored_at=_NOW)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_bootstrap_creates_three_tabs_on_real_sheet(live_client):
    """bootstrap() creates all three tabs with correct headers on a blank sheet."""
    live_client.bootstrap()

    spreadsheet = live_client._spreadsheet
    existing_titles = {ws.title for ws in spreadsheet.worksheets()}

    assert LISTINGS_TAB in existing_titles, "listings tab missing"
    assert PRICE_HISTORY_TAB in existing_titles, "price_history tab missing"
    assert RUNS_TAB in existing_titles, "runs tab missing"

    # Verify headers match the schema constants
    listings_ws = spreadsheet.worksheet(LISTINGS_TAB)
    assert listings_ws.row_values(1) == LISTINGS_HEADERS

    ph_ws = spreadsheet.worksheet(PRICE_HISTORY_TAB)
    assert ph_ws.row_values(1) == PRICE_HISTORY_HEADERS

    runs_ws = spreadsheet.worksheet(RUNS_TAB)
    assert runs_ws.row_values(1) == RUNS_HEADERS


def test_bootstrap_idempotent(live_client):
    """Calling bootstrap() twice raises no error and tabs remain correct."""
    # First call was done in test_bootstrap_creates_three_tabs_on_real_sheet,
    # but live_client is session-scoped so we can call again here.
    live_client.bootstrap()
    live_client.bootstrap()

    spreadsheet = live_client._spreadsheet
    existing_titles = {ws.title for ws in spreadsheet.worksheets()}

    assert LISTINGS_TAB in existing_titles
    assert PRICE_HISTORY_TAB in existing_titles
    assert RUNS_TAB in existing_titles

    # Headers must still be correct after double bootstrap
    listings_ws = spreadsheet.worksheet(LISTINGS_TAB)
    assert listings_ws.row_values(1) == LISTINGS_HEADERS


def test_upsert_inserts_then_updates(live_client):
    """upsert_listings inserts new rows then updates on second call, recording price changes."""
    live_client.bootstrap()

    scored = [
        _make_scored("id-001", price_eur=15000, score=7),
        _make_scored("id-002", price_eur=18000, score=8),
    ]

    # First upsert: insert both listings
    live_client.upsert_listings(scored, today="2026-05-01")

    existing = live_client.get_existing_ids()
    assert "id-001" in existing, "id-001 should be present after first upsert"
    assert "id-002" in existing, "id-002 should be present after first upsert"

    # Modify id-001's price and upsert again
    scored_updated = [
        _make_scored("id-001", price_eur=14000, score=7),  # price dropped
        _make_scored("id-002", price_eur=18000, score=8),  # unchanged
    ]
    live_client.upsert_listings(scored_updated, today="2026-05-02")

    # Listings tab: id-001 should now show new price
    spreadsheet = live_client._spreadsheet
    listings_ws = spreadsheet.worksheet(LISTINGS_TAB)
    records = listings_ws.get_all_records()

    price_by_id = {str(r["listing_id"]): int(r["price_eur"]) for r in records}
    assert price_by_id["id-001"] == 14000, f"Expected 14000, got {price_by_id['id-001']}"
    assert price_by_id["id-002"] == 18000, f"Expected 18000, got {price_by_id['id-002']}"

    # price_history tab: exactly 1 row recording the price change for id-001
    ph_ws = spreadsheet.worksheet(PRICE_HISTORY_TAB)
    ph_records = ph_ws.get_all_records()
    assert len(ph_records) == 1, f"Expected 1 price history row, got {len(ph_records)}"

    ph = ph_records[0]
    assert str(ph["listing_id"]) == "id-001"
    assert int(ph["old_price"]) == 15000
    assert int(ph["new_price"]) == 14000


def test_record_run_appends_to_runs_tab(live_client):
    """record_run() appends a summary row to the runs tab."""
    live_client.bootstrap()

    record = RunRecord(
        run_at=_NOW,
        new_count=5,
        updated_count=2,
        removed_count=1,
        errors=0,
        notes="Integration test run",
    )
    live_client.record_run(record)

    spreadsheet = live_client._spreadsheet
    runs_ws = spreadsheet.worksheet(RUNS_TAB)
    data_rows = runs_ws.get_all_records()

    # There should be at least 1 row (may be more if previous tests also wrote)
    assert len(data_rows) >= 1, "Runs tab should have at least 1 data row after record_run"

    # Find the row we just wrote by matching new_count=5
    matching = [r for r in data_rows if int(r.get("new_count", -1)) == 5]
    assert len(matching) >= 1, "No run record with new_count=5 found in runs tab"
    assert int(matching[0]["updated_count"]) == 2
    assert int(matching[0]["removed_count"]) == 1
    assert int(matching[0]["errors"]) == 0


def test_conditional_formatting_applied_once_to_column_l(live_client):
    """bootstrap() applies at least one conditional format rule covering column L (score)."""
    live_client.bootstrap()

    spreadsheet = live_client._spreadsheet
    listings_ws = spreadsheet.worksheet(LISTINGS_TAB)

    rules = get_conditional_format_rules(listings_ws)

    # Collect all ranges across all rules
    all_range_strings: list[str] = []
    for rule in rules:
        for r in rule.ranges:
            # gspread_formatting GridRange objects expose startColumnIndex (0-based)
            # Column L is 0-based index 11 (A=0, B=1, …, L=11)
            start_col = getattr(r, "startColumnIndex", None)
            if start_col is not None:
                all_range_strings.append(f"col:{start_col}")
            # Also accept string representation that includes "L"
            r_str = str(r)
            all_range_strings.append(r_str)

    # Verify at least one rule targets column L (0-based index 11)
    col_l_rules = [
        r for r in rules if any(getattr(rng, "startColumnIndex", None) == 11 for rng in r.ranges)
    ]

    assert col_l_rules, (
        f"Expected at least one conditional format rule covering column {SCORE_COLUMN_LETTER} "
        f"(0-based index 11). Ranges found: {all_range_strings}"
    )

    # Confirm the range extends to approximately row 10000 (L2:L10000)
    for rule in col_l_rules:
        for rng in rule.ranges:
            end_row = getattr(rng, "endRowIndex", None)
            if end_row is not None:
                assert end_row >= 9999, (
                    f"Expected range to extend to at least row 10000, got endRowIndex={end_row}"
                )
