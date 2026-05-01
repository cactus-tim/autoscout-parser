"""Schema constants for Google Sheets tabs used by the pipeline.

Three tabs:
  - listings: current view of all tracked car listings (16 columns)
  - price_history: log of price change events
  - runs: one row per pipeline run summary
"""

LISTINGS_TAB = "listings"
PRICE_HISTORY_TAB = "price_history"
RUNS_TAB = "runs"

# 16 columns; score is at 0-based index 11 → column letter L.
LISTINGS_HEADERS = [
    "listing_id",  # 0  A
    "url",  # 1  B
    "first_seen",  # 2  C
    "last_seen",  # 3  D
    "brand",  # 4  E
    "model",  # 5  F
    "year",  # 6  G
    "mileage_km",  # 7  H
    "price_eur",  # 8  I
    "location",  # 9  J
    "country",  # 10 K
    "score",  # 11 L  ← SCORE_COLUMN_LETTER
    "reasoning",  # 12 M
    "pros",  # 13 N
    "cons",  # 14 O
    "status",  # 15 P
]

PRICE_HISTORY_HEADERS = ["listing_id", "changed_at", "old_price", "new_price"]

RUNS_HEADERS = ["run_at", "new_count", "updated_count", "removed_count", "errors", "notes"]

# 1-based column index of "score" → A=1, …, L=12
SCORE_COLUMN_LETTER = "L"


class SheetSchemaError(Exception):
    """Raised when an existing sheet tab has headers that don't match the expected schema.

    Operator must manually reconcile the sheet before re-running bootstrap.
    """
