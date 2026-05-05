"""Conditional formatting rules for the Google Sheets listings tab.

Applied to the score column (L) to colour-code listing quality at a glance:
  - score >= 8  → green background  (good deal)
  - score >= 6  → yellow background (worth reviewing)
  - score >= 4  → no format         (neutral)
  - score <  4  → light-red background (poor deal)

The function is idempotent: it clears any existing conditional format rules on
the score range before adding the four rules, so re-running bootstrap() never
accumulates duplicate rules.
"""

from __future__ import annotations

from gspread import Worksheet
from gspread_formatting import (
    BooleanCondition,
    BooleanRule,
    CellFormat,
    Color,
    ConditionalFormatRule,
    ConditionalFormatRules,
    GridRange,
    TextFormat,
    format_cell_range,
    get_conditional_format_rules,
    set_column_width,
    set_frozen,
)

from autoscout_pipeline.sheets.schema import SCORE_COLUMN_LETTER

_SCORE_RANGE = f"{SCORE_COLUMN_LETTER}2:{SCORE_COLUMN_LETTER}10000"


def _color(r: float, g: float, b: float) -> Color:
    return Color(red=r, green=g, blue=b)


def apply_score_conditional_formatting(worksheet: Worksheet) -> None:
    """Apply four conditional format rules to the score column (L2:L10000).

    Rules (evaluated in priority order — first match wins):
      1. >= 8  → green background
      2. >= 6  → yellow background
      3. >= 4  → no special format (transparent / default)
      4. <  4  → light-red background

    Idempotent: clears all existing rules on *this worksheet* before applying.
    """
    rules: ConditionalFormatRules = get_conditional_format_rules(worksheet)
    rules.clear()

    score_range = GridRange.from_a1_range(_SCORE_RANGE, worksheet)

    green = CellFormat(backgroundColor=_color(0.7, 1.0, 0.7))
    yellow = CellFormat(backgroundColor=_color(1.0, 1.0, 0.7))
    light_red = CellFormat(backgroundColor=_color(1.0, 0.7, 0.7))

    new_rules = [
        # Rule 1: score >= 8 → green
        ConditionalFormatRule(
            ranges=[score_range],
            booleanRule=BooleanRule(
                condition=BooleanCondition("NUMBER_GREATER_THAN_EQ", ["8"]),
                format=green,
            ),
        ),
        # Rule 2: score >= 6 → yellow
        ConditionalFormatRule(
            ranges=[score_range],
            booleanRule=BooleanRule(
                condition=BooleanCondition("NUMBER_GREATER_THAN_EQ", ["6"]),
                format=yellow,
            ),
        ),
        # Rule 3: score >= 4 → no format (neutral; explicit rule keeps priority ordering)
        ConditionalFormatRule(
            ranges=[score_range],
            booleanRule=BooleanRule(
                condition=BooleanCondition("NUMBER_GREATER_THAN_EQ", ["4"]),
                format=CellFormat(),  # empty = transparent / default
            ),
        ),
        # Rule 4: score < 4 → light red
        ConditionalFormatRule(
            ranges=[score_range],
            booleanRule=BooleanRule(
                condition=BooleanCondition("NUMBER_LESS", ["4"]),
                format=light_red,
            ),
        ),
    ]

    rules.extend(new_rules)
    rules.save()


# ---------------------------------------------------------------------------
# Layout / readability formatting for the listings tab
# ---------------------------------------------------------------------------
#
# Pixel widths chosen to fit the schema in src/autoscout_pipeline/sheets/schema.py.
# The "wide text" columns (reasoning M, pros N, cons O) get the bulk of the
# horizontal space and have wrap=WRAP + vertical=TOP so multi-line Russian text
# stays readable without manual resizing.

_COLUMN_WIDTHS_PX: dict[str, int] = {
    "A": 110,  # listing_id (truncated UUID prefix is enough at a glance)
    "B": 240,  # url
    "C": 90,   # first_seen
    "D": 90,   # last_seen
    "E": 60,   # brand
    "F": 110,  # model
    "G": 60,   # year
    "H": 90,   # mileage_km
    "I": 90,   # price_eur
    "J": 130,  # location
    "K": 70,   # country
    "L": 60,   # score
    "M": 480,  # reasoning  (wide)
    "N": 320,  # pros       (wide)
    "O": 280,  # cons       (wide)
    "P": 80,   # status
}

def apply_listings_layout(worksheet: Worksheet) -> None:
    """Apply column widths, header bold, frozen header row, and text-wrap on
    the wide text columns of the listings tab.

    Idempotent — Sheets-side property writes overwrite previous values.
    """
    # Header: bold + freeze first row.
    bold_header = CellFormat(
        textFormat=TextFormat(bold=True),
        verticalAlignment="MIDDLE",
        wrapStrategy="CLIP",
    )
    format_cell_range(worksheet, "A1:P1", bold_header)
    set_frozen(worksheet, rows=1)

    # Column widths.
    for letter, width in _COLUMN_WIDTHS_PX.items():
        set_column_width(worksheet, letter, width)

    # Wrap + top-align the wide text columns so long Russian reasoning is readable.
    wrap_top = CellFormat(wrapStrategy="WRAP", verticalAlignment="TOP")
    format_cell_range(worksheet, "M2:O10000", wrap_top)

    # The url column also benefits from CLIP (don't wrap, just hide overflow).
    format_cell_range(worksheet, "B2:B10000", CellFormat(wrapStrategy="CLIP"))
