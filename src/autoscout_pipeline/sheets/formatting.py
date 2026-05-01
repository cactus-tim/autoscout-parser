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
    get_conditional_format_rules,
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

    green = CellFormat(backgroundColor=_color(0.7, 1.0, 0.7))
    yellow = CellFormat(backgroundColor=_color(1.0, 1.0, 0.7))
    light_red = CellFormat(backgroundColor=_color(1.0, 0.7, 0.7))

    new_rules = [
        # Rule 1: score >= 8 → green
        ConditionalFormatRule(
            ranges=[_SCORE_RANGE],
            booleanRule=BooleanRule(
                condition=BooleanCondition("NUMBER_GREATER_THAN_EQ", ["8"]),
                format=green,
            ),
        ),
        # Rule 2: score >= 6 → yellow
        ConditionalFormatRule(
            ranges=[_SCORE_RANGE],
            booleanRule=BooleanRule(
                condition=BooleanCondition("NUMBER_GREATER_THAN_EQ", ["6"]),
                format=yellow,
            ),
        ),
        # Rule 3: score >= 4 → no format (neutral; explicit rule keeps priority ordering)
        ConditionalFormatRule(
            ranges=[_SCORE_RANGE],
            booleanRule=BooleanRule(
                condition=BooleanCondition("NUMBER_GREATER_THAN_EQ", ["4"]),
                format=CellFormat(),  # empty = transparent / default
            ),
        ),
        # Rule 4: score < 4 → light red
        ConditionalFormatRule(
            ranges=[_SCORE_RANGE],
            booleanRule=BooleanRule(
                condition=BooleanCondition("NUMBER_LESS_THAN", ["4"]),
                format=light_red,
            ),
        ),
    ]

    rules.extend(new_rules)
    rules.save()
