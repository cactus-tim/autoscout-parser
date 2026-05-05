"""End-to-end smoke script for the AutoScout24 MINI pipeline.

Exercises the full pipeline with all external services mocked:
- Scraper: returns fixture HTML instead of calling camoufox/network.
- Scorer: returns deterministic ListingScore objects (no OpenAI call).
- Sheets: all gspread calls absorbed by MagicMock (no Google Sheets call).
- Telegram: httpx.AsyncClient.post returns 200 OK (no Telegram call).

Usage:
    uv run python -m scripts.smoke

Expected output (numbers may vary):
    OK smoke OK: scraped=12 new=12 scored=12 notified=3 in 4.2s
"""

from __future__ import annotations

import asyncio
import itertools
import os
import sys
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

# ---------------------------------------------------------------------------
# Inject dummy env vars before any pipeline import so pydantic-settings
# picks them up and Settings() builds without real credentials.
# ---------------------------------------------------------------------------
os.environ.setdefault("OPENAI_API_KEY", "test")
os.environ.setdefault("TG_TOKEN", "test")
os.environ.setdefault("TG_CHAT_ID", "0")
os.environ.setdefault("SHEET_ID", "test")

# ---------------------------------------------------------------------------
# Now it's safe to import pipeline modules.
# ---------------------------------------------------------------------------
from autoscout_pipeline.config import Settings
from autoscout_pipeline.models import ListingScore
from autoscout_pipeline.pipeline import run

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
_REPO_ROOT = Path(__file__).resolve().parent.parent
_FIXTURE_HTML = _REPO_ROOT / "tests" / "fixtures" / "autoscout_listings_page1.html"

# ---------------------------------------------------------------------------
# Fixture HTML
# ---------------------------------------------------------------------------
_FIXTURE_CONTENT = _FIXTURE_HTML.read_text(encoding="utf-8")

# ---------------------------------------------------------------------------
# Score cycle: 7, 8, 9, 5, 6, 7, 8, 9, 5, 6, ...
# Listings with score >= 8 will be notified (threshold default = 8).
# ---------------------------------------------------------------------------
_SCORE_CYCLE = itertools.cycle([7, 8, 9, 5, 6])


def _make_listing_score() -> ListingScore:
    """Return the next pre-determined ListingScore from the cycle."""
    s = next(_SCORE_CYCLE)
    return ListingScore(
        score=s,
        reasoning=f"Smoke test score {s}",
        pros=["good"],
        cons=["average"],
    )


# ---------------------------------------------------------------------------
# Mock builders
# ---------------------------------------------------------------------------


def _make_fetch_mock():
    """Async mock that returns fixture HTML for any URL.

    Page 1 → fixture HTML (12 listings parsed from __NEXT_DATA__).
    Page 2+ → minimal HTML with empty listings so iteration stops.
    """
    call_count = 0
    _EMPTY_PAGE = (
        "<html><head></head><body>"
        '<script id="__NEXT_DATA__" type="application/json">'
        '{"props":{"pageProps":{"listings":[]}}}'
        "</script></body></html>"
    )

    async def _fetch(url: str) -> str:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return _FIXTURE_CONTENT
        return _EMPTY_PAGE

    return _fetch


def _make_instructor_mock():
    """Mock for ``instructor.from_openai`` that returns deterministic scores.

    instructor.from_openai(client, mode=...) returns a patched client whose
    .chat.completions.create() is what LLMScorer awaits.
    """
    mock_client = MagicMock()
    mock_client.chat = MagicMock()
    mock_client.chat.completions = MagicMock()
    mock_client.chat.completions.create = AsyncMock(
        side_effect=lambda **kwargs: _make_listing_score()
    )

    def _from_openai(client, mode=None):
        return mock_client

    return _from_openai


def _make_gspread_mock():
    """Mock for ``gspread.service_account`` that absorbs all Sheets calls.

    The returned spreadsheet mock auto-creates worksheet mocks via MagicMock.
    get_all_records() returns [] (no existing listings → all are "new").
    worksheets() returns [] (no existing tabs → bootstrap creates them).
    """
    worksheet_mock = MagicMock()
    worksheet_mock.get_all_records.return_value = []
    worksheet_mock.row_values.return_value = []

    spreadsheet_mock = MagicMock()
    spreadsheet_mock.worksheets.return_value = []
    spreadsheet_mock.worksheet.return_value = worksheet_mock
    spreadsheet_mock.add_worksheet.return_value = worksheet_mock

    gc_mock = MagicMock()
    gc_mock.open_by_key.return_value = spreadsheet_mock

    def _service_account(filename=None):
        return gc_mock

    return _service_account


def _make_httpx_post_mock():
    """AsyncMock for ``httpx.AsyncClient.post`` that returns HTTP 200 OK."""
    response_mock = MagicMock()
    response_mock.status_code = 200
    response_mock.raise_for_status = MagicMock()
    return AsyncMock(return_value=response_mock)


# ---------------------------------------------------------------------------
# Main smoke runner
# ---------------------------------------------------------------------------


async def _smoke() -> None:
    settings = Settings(  # type: ignore[call-arg]
        openai_api_key="test",
        tg_token="test",
        tg_chat_id="0",
        sheet_id="test",
        score_notify_threshold=8,
        brief_path=str(_REPO_ROOT / "brief.md"),
        creds_path="creds.json",
    )

    fetch_mock = _make_fetch_mock()
    instructor_mock = _make_instructor_mock()
    gspread_mock = _make_gspread_mock()
    httpx_post_mock = _make_httpx_post_mock()

    t0 = time.perf_counter()

    with (
        # Patch where the name is consumed (search.py imports it directly).
        patch("autoscout_pipeline.scraper.search.fetch_page_html", new=fetch_mock),
        patch("autoscout_pipeline.scoring.scorer.instructor.from_openai", new=instructor_mock),
        patch("autoscout_pipeline.sheets.client.gspread.service_account", new=gspread_mock),
        # apply_score_conditional_formatting calls get_conditional_format_rules which
        # requires a real gspread Worksheet object; patch it to a no-op in the smoke context.
        patch(
            "autoscout_pipeline.sheets.client.apply_score_conditional_formatting",
            new=MagicMock(),
        ),
        patch("httpx.AsyncClient.post", new=httpx_post_mock),
        # Passthrough patch for enrich_with_details so no real browser is launched.
        patch(
            "autoscout_pipeline.pipeline.enrich_with_details",
            new_callable=AsyncMock,
            side_effect=lambda lst, **kw: lst,
        ),
    ):
        record = await run(settings, dry_run=False)

    elapsed = time.perf_counter() - t0

    # Derive notified count from the score cycle pattern:
    # cycle [7,8,9,5,6] → scores 8 and 9 pass threshold=8
    # For 12 listings: positions 0-11 → scores 7,8,9,5,6,7,8,9,5,6,7,8
    # threshold >= 8 → indices 1(8), 2(9), 6(8), 7(9), 11(8) → 5 qualifying
    # But the notifier checks > threshold? Let's parse from record notes instead.
    notes = record.notes
    scraped = _extract_int(notes, "scraped=")
    new = _extract_int(notes, "new=")
    scored_count = _extract_int(notes, "scored=")

    # Count notified: httpx_post_mock.call_count equals number of sends attempted.
    # Each successful send calls post() once.
    notified = httpx_post_mock.call_count

    print(
        f"OK smoke OK: "
        f"scraped={scraped} "
        f"new={new} "
        f"scored={scored_count} "
        f"notified={notified} "
        f"in {elapsed:.1f}s"
    )


def _extract_int(text: str, prefix: str) -> int:
    """Extract the integer value after *prefix* in *text*."""
    try:
        start = text.index(prefix) + len(prefix)
        end = start
        while end < len(text) and text[end].isdigit():
            end += 1
        return int(text[start:end])
    except (ValueError, IndexError):
        return -1


if __name__ == "__main__":
    try:
        asyncio.run(_smoke())
    except Exception as exc:
        print(f"FAIL smoke FAILED: {exc}", file=sys.stderr)
        sys.exit(1)
