"""Google Sheets adapter for the AutoScout24 pipeline.

Wraps gspread to provide:
  - Idempotent bootstrap (create tabs + headers + conditional formatting)
  - Batch dedup-aware upsert for ScoredListing objects
  - Price history tracking
  - Run-record appending

All writes use batch APIs (append_rows, batch_update) — never per-cell loops.
"""

from __future__ import annotations

import logging
from pathlib import Path

import gspread

from autoscout_pipeline.models import PriceChange, RunRecord, ScoredListing
from autoscout_pipeline.sheets.formatting import (
    apply_listings_layout,
    apply_score_conditional_formatting,
)
from autoscout_pipeline.sheets.schema import (
    LISTINGS_HEADERS,
    LISTINGS_TAB,
    PRICE_HISTORY_HEADERS,
    PRICE_HISTORY_TAB,
    RUNS_HEADERS,
    RUNS_TAB,
    SheetSchemaError,
)

logger = logging.getLogger(__name__)

# Map each tab to its expected header list
_TAB_HEADERS: dict[str, list[str]] = {
    LISTINGS_TAB: LISTINGS_HEADERS,
    PRICE_HISTORY_TAB: PRICE_HISTORY_HEADERS,
    RUNS_TAB: RUNS_HEADERS,
}

# Column indices (0-based) used in batch_update cell ranges
_COL_LISTING_ID = LISTINGS_HEADERS.index("listing_id")
_COL_LAST_SEEN = LISTINGS_HEADERS.index("last_seen")
_COL_PRICE_EUR = LISTINGS_HEADERS.index("price_eur")
_COL_STATUS = LISTINGS_HEADERS.index("status")


def _col_letter(zero_based_index: int) -> str:
    """Convert a 0-based column index to a spreadsheet column letter (A, B, … Z, AA, …)."""
    result = ""
    n = zero_based_index + 1  # 1-based
    while n > 0:
        n, remainder = divmod(n - 1, 26)
        result = chr(ord("A") + remainder) + result
    return result


class SheetsClient:
    """Synchronous Google Sheets client backed by gspread.

    Parameters
    ----------
    creds_path:
        Path to a Google service-account JSON credentials file.
    sheet_id:
        The Google Spreadsheet ID (from the URL).
    """

    def __init__(self, creds_path: Path, sheet_id: str) -> None:
        self._creds_path = creds_path
        self._sheet_id = sheet_id
        self._gc = gspread.service_account(filename=str(creds_path))
        self._spreadsheet = self._gc.open_by_key(sheet_id)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def bootstrap(self) -> None:
        """Ensure all three tabs exist with correct headers; apply conditional formatting.

        - Creates missing tabs.
        - Writes headers to blank tabs.
        - Raises SheetSchemaError if an existing tab has wrong headers.
        - Applies (or re-applies) conditional formatting to the score column on the
          listings tab.  Idempotent — safe to call on every pipeline run.
        """
        existing_titles = {ws.title for ws in self._spreadsheet.worksheets()}

        for tab_name, expected_headers in _TAB_HEADERS.items():
            if tab_name not in existing_titles:
                logger.info("Creating missing tab '%s'", tab_name)
                ws = self._spreadsheet.add_worksheet(
                    title=tab_name, rows=10000, cols=len(expected_headers)
                )
                ws.append_row(expected_headers)
            else:
                ws = self._spreadsheet.worksheet(tab_name)
                current = ws.row_values(1)
                if current == []:
                    # Blank tab — write headers
                    ws.append_row(expected_headers)
                elif current != expected_headers:
                    raise SheetSchemaError(
                        f"Tab '{tab_name}' has unexpected headers.\n"
                        f"  expected: {expected_headers}\n"
                        f"  found:    {current}\n"
                        "Manually reconcile the sheet before re-running bootstrap()."
                    )

        # Apply conditional formatting to the score column (idempotent — clears + reapplies)
        listings_ws = self._spreadsheet.worksheet(LISTINGS_TAB)
        apply_score_conditional_formatting(listings_ws)
        # Column widths, header bold, frozen header row, text-wrap on M/N/O.
        apply_listings_layout(listings_ws)

    def get_existing_ids(self) -> dict[str, dict]:
        """Return a mapping of listing_id → row metadata for the listings tab.

        The returned dict has the shape:
            {
                "<listing_id>": {
                    "row": <int>,        # 1-based sheet row number (row 1 = headers)
                    "price_eur": <int>,
                    "status": <str>,
                    "first_seen": <str>,
                    "last_seen": <str>,
                }
            }

        Uses get_all_records() which fetches the whole sheet in one API call.
        Row numbers are reconstructed from the record index (header row = 1,
        first data row = 2).
        """
        ws = self._spreadsheet.worksheet(LISTINGS_TAB)
        records = ws.get_all_records()
        result: dict[str, dict] = {}
        for i, rec in enumerate(records):
            lid = str(rec.get("listing_id", ""))
            if not lid:
                continue
            result[lid] = {
                "row": i + 2,  # header is row 1; first data row is 2
                "price_eur": int(rec.get("price_eur", 0)),
                "status": str(rec.get("status", "active")),
                "first_seen": str(rec.get("first_seen", "")),
                "last_seen": str(rec.get("last_seen", "")),
            }
        return result

    def upsert_listings(self, scored: list[ScoredListing], today: str) -> None:
        """Dedup-aware batch upsert of scored listings.

        Algorithm:
        1. Fetch existing rows once via get_all_records().
        2. Partition scored into new vs existing.
        3. Batch-append new rows.
        4. For existing rows: update last_seen; detect price changes; detect resurrection.
        5. Mark stale rows (last_seen < today and not in current scored set) as removed.
        All writes are batched (append_rows / batch_update).
        """
        listings_ws = self._spreadsheet.worksheet(LISTINGS_TAB)
        ph_ws = self._spreadsheet.worksheet(PRICE_HISTORY_TAB)

        existing = self.get_existing_ids()
        current_ids = {s.listing.listing_id for s in scored}

        new_rows: list[list] = []
        update_cells: list[dict] = []  # batch_update payload for listings tab
        price_history_rows: list[list] = []

        for s in scored:
            lid = s.listing.listing_id

            if lid not in existing:
                # Brand-new listing
                row = self._scored_to_row(s, first_seen=today, last_seen=today, status="active")
                new_rows.append(row)
            else:
                meta = existing[lid]
                sheet_row = meta["row"]
                old_price = meta["price_eur"]
                old_status = meta["status"]

                updates: list[tuple[str, object]] = []

                # Always update last_seen
                updates.append(("last_seen", today))

                # Detect price change
                if s.listing.price_eur != old_price:
                    updates.append(("price_eur", s.listing.price_eur))
                    price_history_rows.append([lid, today, old_price, s.listing.price_eur])

                # Resurrect removed listing
                if old_status == "removed":
                    updates.append(("status", "active"))

                for col_name, value in updates:
                    col_idx = LISTINGS_HEADERS.index(col_name)
                    col_letter = _col_letter(col_idx)
                    cell_range = f"{col_letter}{sheet_row}"
                    update_cells.append({"range": cell_range, "values": [[value]]})

        # Mark stale rows as removed (active rows not seen today)
        for lid, meta in existing.items():
            if (
                lid not in current_ids
                and meta["status"] == "active"
                and meta.get("last_seen", today) < today
            ):
                sheet_row = meta["row"]
                col_letter = _col_letter(_COL_STATUS)
                update_cells.append({"range": f"{col_letter}{sheet_row}", "values": [["removed"]]})

        # Batch writes
        if new_rows:
            listings_ws.append_rows(new_rows)

        if update_cells:
            listings_ws.batch_update(update_cells)

        if price_history_rows:
            ph_ws.append_rows(price_history_rows)

    def record_run(self, record: RunRecord) -> None:
        """Append a single run summary row to the runs tab."""
        ws = self._spreadsheet.worksheet(RUNS_TAB)
        row = [
            record.run_at.isoformat(),
            record.new_count,
            record.updated_count,
            record.removed_count,
            record.errors,
            record.notes,
        ]
        ws.append_row(row)

    def record_price_change(self, change: PriceChange) -> None:
        """Append a single price-change event to the price_history tab."""
        ws = self._spreadsheet.worksheet(PRICE_HISTORY_TAB)
        row = [
            change.listing_id,
            change.changed_at.isoformat(),
            change.old_price,
            change.new_price,
        ]
        ws.append_row(row)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _scored_to_row(
        self,
        s: ScoredListing,
        first_seen: str,
        last_seen: str,
        status: str,
    ) -> list:
        """Build a 16-element row in LISTINGS_HEADERS order from a ScoredListing.

        Returns
        -------
        list
            Elements in the same order as LISTINGS_HEADERS:
            [listing_id, url, first_seen, last_seen, brand, model, year,
             mileage_km, price_eur, location, country, score, reasoning,
             pros_joined, cons_joined, status]
        """
        return [
            s.listing.listing_id,  # 0  listing_id
            s.listing.url,  # 1  url
            first_seen,  # 2  first_seen
            last_seen,  # 3  last_seen
            s.listing.brand,  # 4  brand
            s.listing.model,  # 5  model
            s.listing.year,  # 6  year
            s.listing.mileage_km,  # 7  mileage_km
            s.listing.price_eur,  # 8  price_eur
            s.listing.location or "",  # 9  location
            s.listing.country or "",  # 10 country
            s.score.score,  # 11 score  ← column L
            s.score.reasoning,  # 12 reasoning
            "; ".join(s.score.pros),  # 13 pros
            "; ".join(s.score.cons),  # 14 cons
            status,  # 15 status
        ]
