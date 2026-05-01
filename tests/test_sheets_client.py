"""Tests for sheets/client.py — all gspread interactions are mocked.

No real network or Google Sheets access is performed in this test module.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from autoscout_pipeline.models import Listing, ListingScore, PriceChange, RunRecord, ScoredListing
from autoscout_pipeline.sheets.client import SheetsClient
from autoscout_pipeline.sheets.schema import (
    LISTINGS_HEADERS,
    LISTINGS_TAB,
    PRICE_HISTORY_HEADERS,
    PRICE_HISTORY_TAB,
    RUNS_HEADERS,
    RUNS_TAB,
    SheetSchemaError,
)

# ---------------------------------------------------------------------------
# Shared test helpers
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 5, 1, 12, 0, 0, tzinfo=UTC)
_TODAY = "2026-05-01"


def _make_listing(
    listing_id: str = "abc123",
    price_eur: int = 15000,
    brand: str = "MINI",
    model: str = "Hatch",
    year: int = 2020,
    mileage_km: int = 25000,
    location: str | None = "Munich",
    country: str | None = "DE",
) -> Listing:
    return Listing(
        listing_id=listing_id,
        url=f"https://autoscout24.com/listing/{listing_id}",
        brand=brand,
        model=model,
        year=year,
        mileage_km=mileage_km,
        price_eur=price_eur,
        location=location,
        country=country,
        first_seen=_NOW,
        last_seen=_NOW,
    )


def _make_score(score: int = 8) -> ListingScore:
    return ListingScore(
        score=score,
        reasoning="Great deal",
        pros=["low mileage", "good price"],
        cons=["older model"],
    )


def _make_scored(
    listing_id: str = "abc123", price_eur: int = 15000, score: int = 8
) -> ScoredListing:
    return ScoredListing(
        listing=_make_listing(listing_id=listing_id, price_eur=price_eur),
        score=_make_score(score=score),
        scored_at=_NOW,
    )


def _make_ws_mock(tab_name: str, headers: list[str]) -> MagicMock:
    """Return a worksheet mock that has the correct title and header row."""
    ws = MagicMock()
    ws.title = tab_name
    ws.row_values.return_value = headers
    ws.get_all_records.return_value = []
    return ws


def _make_spreadsheet_mock(existing_tabs: list[str]) -> MagicMock:
    """Return a spreadsheet mock with the specified tabs pre-existing.

    Any tab not in existing_tabs will be returned as a fresh mock via add_worksheet.
    """
    tab_mocks: dict[str, MagicMock] = {}
    for tab in existing_tabs:
        if tab == LISTINGS_TAB:
            tab_mocks[tab] = _make_ws_mock(tab, LISTINGS_HEADERS)
        elif tab == PRICE_HISTORY_TAB:
            tab_mocks[tab] = _make_ws_mock(tab, PRICE_HISTORY_HEADERS)
        elif tab == RUNS_TAB:
            tab_mocks[tab] = _make_ws_mock(tab, RUNS_HEADERS)

    def _worksheet(name: str) -> MagicMock:
        if name in tab_mocks:
            return tab_mocks[name]
        raise Exception(f"Worksheet '{name}' not found")  # gspread raises on missing

    sp = MagicMock()
    sp.worksheets.return_value = [tab_mocks[t] for t in existing_tabs]
    sp.worksheet.side_effect = _worksheet

    new_ws = MagicMock()
    new_ws.row_values.return_value = []
    sp.add_worksheet.return_value = new_ws
    return sp


# ---------------------------------------------------------------------------
# Fixture: a SheetsClient with gspread.service_account mocked
# ---------------------------------------------------------------------------


@pytest.fixture()
def client_factory():
    """Return a factory that creates a SheetsClient with a given spreadsheet mock."""

    def _factory(spreadsheet_mock: MagicMock) -> tuple[SheetsClient, MagicMock]:
        with patch("autoscout_pipeline.sheets.client.gspread") as mock_gspread:
            mock_gspread.service_account.return_value.open_by_key.return_value = spreadsheet_mock
            client = SheetsClient(creds_path=Path("/fake/creds.json"), sheet_id="FAKE_ID")
            return client, mock_gspread

    return _factory


# ---------------------------------------------------------------------------
# bootstrap() tests
# ---------------------------------------------------------------------------


class TestBootstrap:
    def test_bootstrap_creates_missing_tabs(self, client_factory) -> None:
        """When only 'listings' exists, bootstrap() must create the other two tabs."""
        sp = _make_spreadsheet_mock([LISTINGS_TAB])
        with (
            patch("autoscout_pipeline.sheets.client.gspread") as mock_gspread,
            patch("autoscout_pipeline.sheets.client.apply_score_conditional_formatting"),
        ):
            mock_gspread.service_account.return_value.open_by_key.return_value = sp
            client = SheetsClient(creds_path=Path("/fake/creds.json"), sheet_id="FAKE_ID")
            client.bootstrap()

        # add_worksheet should have been called for exactly the two missing tabs
        assert sp.add_worksheet.call_count == 2
        added_titles = {c.kwargs.get("title") or c.args[0] for c in sp.add_worksheet.call_args_list}
        assert added_titles == {PRICE_HISTORY_TAB, RUNS_TAB}

    def test_bootstrap_raises_on_header_mismatch(self, client_factory) -> None:
        """If a tab exists with wrong headers, bootstrap() raises SheetSchemaError."""
        sp = _make_spreadsheet_mock([LISTINGS_TAB, PRICE_HISTORY_TAB, RUNS_TAB])
        # Corrupt the listings tab headers
        sp.worksheet(LISTINGS_TAB).row_values.return_value = ["wrong", "headers"]

        with (
            patch("autoscout_pipeline.sheets.client.gspread") as mock_gspread,
            patch("autoscout_pipeline.sheets.client.apply_score_conditional_formatting"),
        ):
            mock_gspread.service_account.return_value.open_by_key.return_value = sp
            client = SheetsClient(creds_path=Path("/fake/creds.json"), sheet_id="FAKE_ID")
            with pytest.raises(SheetSchemaError):
                client.bootstrap()

    def test_bootstrap_applies_conditional_format_to_column_L(self) -> None:
        """bootstrap() must call apply_score_conditional_formatting on listings worksheet."""
        sp = _make_spreadsheet_mock([LISTINGS_TAB, PRICE_HISTORY_TAB, RUNS_TAB])

        with (
            patch("autoscout_pipeline.sheets.client.gspread") as mock_gspread,
            patch(
                "autoscout_pipeline.sheets.client.apply_score_conditional_formatting"
            ) as mock_fmt,
        ):
            mock_gspread.service_account.return_value.open_by_key.return_value = sp
            client = SheetsClient(creds_path=Path("/fake/creds.json"), sheet_id="FAKE_ID")
            client.bootstrap()

        mock_fmt.assert_called_once()
        # The argument must be the listings worksheet
        ws_arg = mock_fmt.call_args[0][0]
        assert ws_arg.title == LISTINGS_TAB

    def test_bootstrap_writes_headers_to_blank_tab(self) -> None:
        """When a tab is freshly created (blank), bootstrap() writes the header row."""
        sp = _make_spreadsheet_mock([LISTINGS_TAB, PRICE_HISTORY_TAB, RUNS_TAB])
        # Simulate RUNS_TAB being blank (no existing headers)
        sp.worksheet(RUNS_TAB).row_values.return_value = []

        with (
            patch("autoscout_pipeline.sheets.client.gspread") as mock_gspread,
            patch("autoscout_pipeline.sheets.client.apply_score_conditional_formatting"),
        ):
            mock_gspread.service_account.return_value.open_by_key.return_value = sp
            client = SheetsClient(creds_path=Path("/fake/creds.json"), sheet_id="FAKE_ID")
            client.bootstrap()

        runs_ws = sp.worksheet(RUNS_TAB)
        runs_ws.append_row.assert_called_once_with(RUNS_HEADERS)


# ---------------------------------------------------------------------------
# upsert_listings() tests
# ---------------------------------------------------------------------------


class TestUpsertListings:
    def _client_with_empty_sheet(self) -> tuple[SheetsClient, MagicMock]:
        sp = _make_spreadsheet_mock([LISTINGS_TAB, PRICE_HISTORY_TAB, RUNS_TAB])
        listings_ws = sp.worksheet(LISTINGS_TAB)
        listings_ws.get_all_records.return_value = []

        with (
            patch("autoscout_pipeline.sheets.client.gspread") as mock_gspread,
            patch("autoscout_pipeline.sheets.client.apply_score_conditional_formatting"),
        ):
            mock_gspread.service_account.return_value.open_by_key.return_value = sp
            client = SheetsClient(creds_path=Path("/fake/creds.json"), sheet_id="FAKE_ID")
            client.bootstrap()

        return client, sp

    def test_upsert_uses_batch_append(self) -> None:
        """3 new listings → exactly one append_rows call with 3 rows."""
        client, sp = self._client_with_empty_sheet()
        listings_ws = sp.worksheet(LISTINGS_TAB)
        listings_ws.get_all_records.return_value = []

        scored = [_make_scored(f"id{i}") for i in range(3)]
        client.upsert_listings(scored, today=_TODAY)

        listings_ws.append_rows.assert_called_once()
        rows_arg = listings_ws.append_rows.call_args[0][0]
        assert len(rows_arg) == 3

    def test_upsert_updates_last_seen_on_existing(self) -> None:
        """Existing listing that reappears → last_seen updated via batch_update (not append)."""
        client, sp = self._client_with_empty_sheet()
        listings_ws = sp.worksheet(LISTINGS_TAB)

        # Simulate existing row for id0
        listings_ws.get_all_records.return_value = [
            {
                "listing_id": "id0",
                "price_eur": 15000,
                "status": "active",
                "first_seen": "2026-04-30",
                "last_seen": "2026-04-30",
                "_row": 2,
            }
        ]
        # Row 1 = headers; existing data is at row 2
        listings_ws.find.return_value = None

        scored = [_make_scored("id0")]
        client.upsert_listings(scored, today=_TODAY)

        # batch_update must be called for the update
        listings_ws.batch_update.assert_called()
        # append_rows should NOT be called (no new rows)
        listings_ws.append_rows.assert_not_called()

    def test_upsert_writes_price_history_on_price_change(self) -> None:
        """When price changes, a row is appended to price_history tab."""
        client, sp = self._client_with_empty_sheet()
        listings_ws = sp.worksheet(LISTINGS_TAB)
        ph_ws = sp.worksheet(PRICE_HISTORY_TAB)

        listings_ws.get_all_records.return_value = [
            {
                "listing_id": "id0",
                "price_eur": 14000,  # old price
                "status": "active",
                "first_seen": "2026-04-30",
                "last_seen": "2026-04-30",
                "_row": 2,
            }
        ]

        # New price is 15000 (changed)
        scored = [_make_scored("id0", price_eur=15000)]
        client.upsert_listings(scored, today=_TODAY)

        ph_ws.append_rows.assert_called()
        rows = ph_ws.append_rows.call_args[0][0]
        assert len(rows) == 1
        row = rows[0]
        assert row[0] == "id0"  # listing_id
        assert row[2] == 14000  # old_price
        assert row[3] == 15000  # new_price

    def test_upsert_resurrects_removed_listing(self) -> None:
        """A listing with status=removed that reappears gets status=active."""
        client, sp = self._client_with_empty_sheet()
        listings_ws = sp.worksheet(LISTINGS_TAB)

        listings_ws.get_all_records.return_value = [
            {
                "listing_id": "id0",
                "price_eur": 15000,
                "status": "removed",  # previously removed
                "first_seen": "2026-04-01",
                "last_seen": "2026-04-15",
                "_row": 2,
            }
        ]

        scored = [_make_scored("id0")]
        client.upsert_listings(scored, today=_TODAY)

        # batch_update must be called (to flip status to active)
        listings_ws.batch_update.assert_called()
        # The update must contain "active" for that listing
        update_data = listings_ws.batch_update.call_args[0][0]
        # values is a 2D list [[value]] in gspread batch_update format
        flat_values = [
            cell
            for item in update_data
            if isinstance(item.get("values"), list)
            for row in item["values"]
            for cell in row
        ]
        assert "active" in flat_values

    def test_upsert_marks_stale_as_removed(self) -> None:
        """Listings whose last_seen < today and absent from current run get status=removed."""
        client, sp = self._client_with_empty_sheet()
        listings_ws = sp.worksheet(LISTINGS_TAB)

        # "stale" listing not in current scored set
        listings_ws.get_all_records.return_value = [
            {
                "listing_id": "stale_id",
                "price_eur": 10000,
                "status": "active",
                "first_seen": "2026-04-01",
                "last_seen": "2026-04-30",  # yesterday — stale
                "_row": 2,
            }
        ]

        # Pass an empty scored set — no current listings
        client.upsert_listings([], today=_TODAY)

        listings_ws.batch_update.assert_called()
        update_data = listings_ws.batch_update.call_args[0][0]
        # values is a 2D list [[value]] in gspread batch_update format
        flat_values = [
            cell
            for item in update_data
            if isinstance(item.get("values"), list)
            for row in item["values"]
            for cell in row
        ]
        assert "removed" in flat_values


# ---------------------------------------------------------------------------
# _scored_to_row() helper tests
# ---------------------------------------------------------------------------


class TestScoredToRow:
    def _client(self) -> SheetsClient:
        sp = _make_spreadsheet_mock([LISTINGS_TAB, PRICE_HISTORY_TAB, RUNS_TAB])
        with (
            patch("autoscout_pipeline.sheets.client.gspread") as mock_gspread,
            patch("autoscout_pipeline.sheets.client.apply_score_conditional_formatting"),
        ):
            mock_gspread.service_account.return_value.open_by_key.return_value = sp
            return SheetsClient(creds_path=Path("/fake/creds.json"), sheet_id="FAKE_ID")

    def test_scored_to_row_builds_16_element_row(self) -> None:
        client = self._client()
        scored = _make_scored()
        row = client._scored_to_row(
            scored, first_seen="2026-04-01", last_seen="2026-05-01", status="active"
        )
        assert len(row) == 16

    def test_scored_to_row_field_positions(self) -> None:
        client = self._client()
        scored = _make_scored("myid", price_eur=12345, score=7)
        row = client._scored_to_row(
            scored, first_seen="2026-04-01", last_seen="2026-05-01", status="active"
        )

        assert row[LISTINGS_HEADERS.index("listing_id")] == "myid"
        assert row[LISTINGS_HEADERS.index("price_eur")] == 12345
        assert row[LISTINGS_HEADERS.index("score")] == 7
        assert row[LISTINGS_HEADERS.index("status")] == "active"
        assert row[LISTINGS_HEADERS.index("first_seen")] == "2026-04-01"
        assert row[LISTINGS_HEADERS.index("last_seen")] == "2026-05-01"

    def test_scored_to_row_joins_pros_cons(self) -> None:
        client = self._client()
        listing = _make_listing()
        score = ListingScore(
            score=5,
            reasoning="ok",
            pros=["a", "b", "c"],
            cons=["x", "y"],
        )
        scored = ScoredListing(listing=listing, score=score, scored_at=_NOW)
        row = client._scored_to_row(
            scored, first_seen="2026-04-01", last_seen="2026-05-01", status="active"
        )

        assert row[LISTINGS_HEADERS.index("pros")] == "a; b; c"
        assert row[LISTINGS_HEADERS.index("cons")] == "x; y"

    def test_scored_to_row_none_location_becomes_empty_string(self) -> None:
        client = self._client()
        listing = _make_listing(location=None, country=None)
        scored = ScoredListing(listing=listing, score=_make_score(), scored_at=_NOW)
        row = client._scored_to_row(
            scored, first_seen="2026-04-01", last_seen="2026-05-01", status="active"
        )

        assert row[LISTINGS_HEADERS.index("location")] == ""
        assert row[LISTINGS_HEADERS.index("country")] == ""


# ---------------------------------------------------------------------------
# record_run() / record_price_change() tests
# ---------------------------------------------------------------------------


class TestRecordRun:
    def _client_and_sp(self) -> tuple[SheetsClient, MagicMock]:
        sp = _make_spreadsheet_mock([LISTINGS_TAB, PRICE_HISTORY_TAB, RUNS_TAB])
        with (
            patch("autoscout_pipeline.sheets.client.gspread") as mock_gspread,
            patch("autoscout_pipeline.sheets.client.apply_score_conditional_formatting"),
        ):
            mock_gspread.service_account.return_value.open_by_key.return_value = sp
            client = SheetsClient(creds_path=Path("/fake/creds.json"), sheet_id="FAKE_ID")
            client.bootstrap()
        return client, sp

    def test_record_run_appends_row(self) -> None:
        client, sp = self._client_and_sp()
        runs_ws = sp.worksheet(RUNS_TAB)

        record = RunRecord(
            run_at=_NOW,
            new_count=5,
            updated_count=2,
            removed_count=1,
            errors=0,
            notes="all good",
        )
        client.record_run(record)

        runs_ws.append_row.assert_called()
        row = runs_ws.append_row.call_args[0][0]
        assert len(row) == len(RUNS_HEADERS)
        assert row[RUNS_HEADERS.index("new_count")] == 5
        assert row[RUNS_HEADERS.index("notes")] == "all good"

    def test_record_price_change_appends_row(self) -> None:
        client, sp = self._client_and_sp()
        ph_ws = sp.worksheet(PRICE_HISTORY_TAB)

        change = PriceChange(
            listing_id="abc",
            changed_at=_NOW,
            old_price=14000,
            new_price=15000,
        )
        client.record_price_change(change)

        ph_ws.append_row.assert_called()
        row = ph_ws.append_row.call_args[0][0]
        assert len(row) == len(PRICE_HISTORY_HEADERS)
        assert row[PRICE_HISTORY_HEADERS.index("listing_id")] == "abc"
        assert row[PRICE_HISTORY_HEADERS.index("old_price")] == 14000
        assert row[PRICE_HISTORY_HEADERS.index("new_price")] == 15000
