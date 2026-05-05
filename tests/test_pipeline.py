"""Tests for the pipeline orchestrator (pipeline.py).

All components are mocked — no real network, Sheets, or OpenAI calls are made.

Async tests run automatically because asyncio_mode = "auto" is set in
pyproject.toml.
"""

from __future__ import annotations

import datetime as dt
import inspect
from unittest.mock import AsyncMock, MagicMock, patch

import autoscout_pipeline.pipeline as pipeline_mod
from autoscout_pipeline.models import Listing, ListingScore, RunRecord, ScoredListing
from autoscout_pipeline.scraper.errors import EmptyResultsError

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NOW = dt.datetime(2026, 5, 1, 12, 0, 0, tzinfo=dt.UTC)
_TODAY = "2026-05-01"


def _make_listing(listing_id: str = "lid-1", price_eur: int = 18_000) -> Listing:
    return Listing(
        listing_id=listing_id,
        url=f"https://www.autoscout24.com/lst/{listing_id}",
        brand="MINI",
        model="Cooper",
        year=2021,
        mileage_km=25_000,
        price_eur=price_eur,
        location="Munich",
        country="DE",
        first_seen=_NOW,
        last_seen=_NOW,
    )


def _make_score(score: int = 7) -> ListingScore:
    return ListingScore(
        score=score,
        reasoning=f"Score {score} reasoning.",
        pros=["pro1"],
        cons=["con1"],
    )


def _make_scored(listing_id: str = "lid-1", score: int = 7) -> ScoredListing:
    return ScoredListing(
        listing=_make_listing(listing_id=listing_id),
        score=_make_score(score=score),
        scored_at=_NOW,
    )


def _make_settings(**overrides) -> MagicMock:
    """Build a Settings-like MagicMock with sensible defaults."""
    s = MagicMock()
    s.openai_api_key = "test-key"
    s.openai_model = "gpt-4.1-nano"
    s.brief_path = "brief.md"
    s.creds_path = "creds.json"
    s.sheet_id = "sheet-abc"
    s.tg_token = "tg-token"
    s.tg_chat_id = "-1001234"
    s.score_notify_threshold = 8
    for k, v in overrides.items():
        setattr(s, k, v)
    return s


# ---------------------------------------------------------------------------
# Shared patch targets
# ---------------------------------------------------------------------------

_PATCH_SHEETS = "autoscout_pipeline.pipeline.SheetsClient"
_PATCH_SCORER = "autoscout_pipeline.pipeline.LLMScorer"
_PATCH_SCORE_MANY = "autoscout_pipeline.pipeline.score_many"
_PATCH_ITER = "autoscout_pipeline.pipeline.iter_listings"
_PATCH_NOTIFIER = "autoscout_pipeline.pipeline.TelegramNotifier"
_PATCH_CONF_LOG = "autoscout_pipeline.pipeline.configure_logging"


def _make_async_gen(items):
    """Return a coroutine that when called returns an async generator of *items*."""

    async def _gen(*args, **kwargs):
        for item in items:
            yield item

    return _gen


# ---------------------------------------------------------------------------
# Test 1: dedup — only new listings are scored
# ---------------------------------------------------------------------------


async def test_pipeline_skips_listings_already_in_sheet():
    """iter_listings yields 3; get_existing_ids returns 1 of them; score_many called with 2."""
    listings = [_make_listing(f"lid-{i}") for i in range(3)]
    scored_results = [_make_scored(f"lid-{i}", score=7) for i in range(1, 3)]

    with (
        patch(_PATCH_CONF_LOG),
        patch(_PATCH_ITER, side_effect=_make_async_gen(listings)),
        patch(_PATCH_SHEETS) as MockSheets,
        patch(_PATCH_SCORER),
        patch(
            _PATCH_SCORE_MANY, new_callable=AsyncMock, return_value=scored_results
        ) as mock_score_many,
        patch(_PATCH_NOTIFIER),
    ):
        mock_client = MockSheets.return_value
        # lid-0 already exists in the sheet
        mock_client.get_existing_ids.return_value = {
            "lid-0": {
                "row": 2,
                "price_eur": 18000,
                "status": "active",
                "first_seen": _TODAY,
                "last_seen": _TODAY,
            }
        }
        mock_client.upsert_listings.return_value = None
        mock_client.record_run.return_value = None

        settings = _make_settings()
        record = await pipeline_mod.run(settings, dry_run=False)

    # score_many should only see lid-1 and lid-2
    call_args = mock_score_many.call_args
    scored_listings_arg = call_args[0][1]  # second positional arg is the listings list
    assert len(scored_listings_arg) == 2
    ids_scored = {lst.listing_id for lst in scored_listings_arg}
    assert "lid-0" not in ids_scored
    assert "lid-1" in ids_scored
    assert "lid-2" in ids_scored

    assert record.new_count == 2


# ---------------------------------------------------------------------------
# Test 2: scrape error — RunRecord.errors=1, new_count=0, no crash
# ---------------------------------------------------------------------------


async def test_pipeline_handles_scrape_error():
    """iter_listings raises EmptyResultsError; pipeline returns RunRecord with errors=1, new_count=0."""

    async def _failing_gen(*args, **kwargs):
        raise EmptyResultsError("No results")
        yield  # make it an async generator

    with (
        patch(_PATCH_CONF_LOG),
        patch(_PATCH_ITER, side_effect=_failing_gen),
        patch(_PATCH_SHEETS) as MockSheets,
        patch(_PATCH_SCORER),
        patch(_PATCH_SCORE_MANY, new_callable=AsyncMock, return_value=[]),
        patch(_PATCH_NOTIFIER),
    ):
        mock_client = MockSheets.return_value
        mock_client.get_existing_ids.return_value = {}
        mock_client.upsert_listings.return_value = None
        mock_client.record_run.return_value = None

        settings = _make_settings()
        record = await pipeline_mod.run(settings, dry_run=False)

    assert record.errors >= 1
    assert record.new_count == 0


# ---------------------------------------------------------------------------
# Test 3: orchestrator passes full scored list to notifier for threshold filtering
# ---------------------------------------------------------------------------


async def test_pipeline_passes_all_scored_to_notifier_for_threshold_filtering():
    """3 scored listings with scores [5, 7, 9]; TelegramNotifier.send_batch IS called
    with all 3 (the notifier's threshold gate is exercised inside send_batch itself,
    not in the pipeline).

    Threshold filtering happens INSIDE the notifier (see test_notify.py for coverage
    of which listings are actually sent).  This test only verifies that the orchestrator
    hands off the full scored list to the notifier without pre-filtering.
    """
    listings = [_make_listing(f"lid-{i}") for i in range(3)]
    scores = [5, 7, 9]
    scored_results = [_make_scored(f"lid-{i}", score=scores[i]) for i in range(3)]

    with (
        patch(_PATCH_CONF_LOG),
        patch(_PATCH_ITER, side_effect=_make_async_gen(listings)),
        patch(_PATCH_SHEETS) as MockSheets,
        patch(_PATCH_SCORER),
        patch(_PATCH_SCORE_MANY, new_callable=AsyncMock, return_value=scored_results),
        patch(_PATCH_NOTIFIER) as MockNotifier,
    ):
        mock_client = MockSheets.return_value
        mock_client.get_existing_ids.return_value = {}
        mock_client.upsert_listings.return_value = None
        mock_client.record_run.return_value = None

        mock_notifier_instance = MockNotifier.return_value
        mock_notifier_instance.send_batch = AsyncMock(return_value=1)

        settings = _make_settings(score_notify_threshold=8)
        await pipeline_mod.run(settings, dry_run=False)

    # send_batch MUST be called with all 3 scored listings
    mock_notifier_instance.send_batch.assert_called_once()
    sent_list = mock_notifier_instance.send_batch.call_args[0][0]
    assert len(sent_list) == 3


# ---------------------------------------------------------------------------
# Test 4: dry_run makes no writes and no Telegram calls
# ---------------------------------------------------------------------------


async def test_pipeline_dry_run_makes_no_writes():
    """dry_run=True: SheetsClient is NOT instantiated at all (no creds required);
    send_batch NOT called; score_many IS still called (preview)."""
    listings = [_make_listing(f"lid-{i}") for i in range(2)]
    scored_results = [_make_scored(f"lid-{i}", score=9) for i in range(2)]

    with (
        patch(_PATCH_CONF_LOG),
        patch(_PATCH_ITER, side_effect=_make_async_gen(listings)),
        patch(_PATCH_SHEETS) as MockSheets,
        patch(_PATCH_SCORER),
        patch(
            _PATCH_SCORE_MANY, new_callable=AsyncMock, return_value=scored_results
        ) as mock_score_many,
        patch(_PATCH_NOTIFIER) as MockNotifier,
    ):
        mock_notifier_instance = MockNotifier.return_value
        mock_notifier_instance.send_batch = AsyncMock(return_value=0)

        settings = _make_settings()
        record = await pipeline_mod.run(settings, dry_run=True)

    # SheetsClient must NOT be instantiated in dry-run (no GCP creds needed)
    MockSheets.assert_not_called()

    # Telegram MUST NOT fire
    mock_notifier_instance.send_batch.assert_not_called()

    # Scoring MUST still happen (preview)
    mock_score_many.assert_called_once()

    assert record.new_count == 2


# ---------------------------------------------------------------------------
# Test 5: record_run called with correct RunRecord
# ---------------------------------------------------------------------------


async def test_pipeline_records_run_summary():
    """sheets.record_run is called once with a RunRecord whose new_count matches the new list."""
    listings = [_make_listing(f"lid-{i}") for i in range(4)]
    # lid-0 already in sheet → 3 new
    scored_results = [_make_scored(f"lid-{i}", score=7) for i in range(1, 4)]

    with (
        patch(_PATCH_CONF_LOG),
        patch(_PATCH_ITER, side_effect=_make_async_gen(listings)),
        patch(_PATCH_SHEETS) as MockSheets,
        patch(_PATCH_SCORER),
        patch(_PATCH_SCORE_MANY, new_callable=AsyncMock, return_value=scored_results),
        patch(_PATCH_NOTIFIER) as MockNotifier,
    ):
        mock_client = MockSheets.return_value
        mock_client.get_existing_ids.return_value = {
            "lid-0": {
                "row": 2,
                "price_eur": 18000,
                "status": "active",
                "first_seen": _TODAY,
                "last_seen": _TODAY,
            }
        }
        mock_client.upsert_listings.return_value = None
        mock_client.record_run.return_value = None

        mock_notifier_instance = MockNotifier.return_value
        mock_notifier_instance.send_batch = AsyncMock(return_value=0)

        settings = _make_settings()
        await pipeline_mod.run(settings, dry_run=False)

    mock_client.record_run.assert_called_once()
    passed_record = mock_client.record_run.call_args[0][0]
    assert isinstance(passed_record, RunRecord)
    # 4 total - 1 existing = 3 new
    assert passed_record.new_count == 3


# ---------------------------------------------------------------------------
# Test 6: NESTED ScoredListing access — source-level check
# ---------------------------------------------------------------------------


def test_pipeline_uses_nested_scored_listing_access():
    """Verify that pipeline.run() accesses scored listings via NESTED layout.

    The source of pipeline.run must contain 's.listing.' and 's.score.'
    substrings, proving it uses the NESTED composition pattern.
    """
    source = inspect.getsource(pipeline_mod.run)
    assert "s.listing." in source, (
        "pipeline.run() must access scored listings via NESTED layout (s.listing.*)"
    )
    assert "s.score." in source, "pipeline.run() must access scores via NESTED layout (s.score.*)"


# ---------------------------------------------------------------------------
# Test 7: TelegramNotifier constructed only when token/chat_id present
# ---------------------------------------------------------------------------


async def test_pipeline_skips_telegram_when_no_token():
    """When tg_token is empty, TelegramNotifier should not be instantiated."""
    listings = [_make_listing("lid-1")]
    scored_results = [_make_scored("lid-1", score=9)]

    with (
        patch(_PATCH_CONF_LOG),
        patch(_PATCH_ITER, side_effect=_make_async_gen(listings)),
        patch(_PATCH_SHEETS) as MockSheets,
        patch(_PATCH_SCORER),
        patch(_PATCH_SCORE_MANY, new_callable=AsyncMock, return_value=scored_results),
        patch(_PATCH_NOTIFIER) as MockNotifier,
    ):
        mock_client = MockSheets.return_value
        mock_client.get_existing_ids.return_value = {}
        mock_client.upsert_listings.return_value = None
        mock_client.record_run.return_value = None

        # No token — notifier should not fire
        settings = _make_settings(tg_token="", tg_chat_id="")
        await pipeline_mod.run(settings, dry_run=False)

    MockNotifier.assert_not_called()
