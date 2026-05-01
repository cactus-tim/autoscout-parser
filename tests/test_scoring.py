"""Tests for the LLM scoring module (scoring/prompt.py, scorer.py, batch.py).

All async tests run automatically because asyncio_mode = "auto" is set in
pyproject.toml.  AsyncMock is used for all instructor / OpenAI calls so that
no real network traffic is produced.
"""

import asyncio
import datetime as dt
from unittest.mock import AsyncMock, MagicMock

import instructor

from autoscout_pipeline.models import Listing, ListingScore, ScoredListing
from autoscout_pipeline.scoring.batch import score_many
from autoscout_pipeline.scoring.prompt import build_system_prompt, load_brief, render_listing
from autoscout_pipeline.scoring.scorer import LLMScorer

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NOW = dt.datetime(2026, 5, 1, 12, 0, 0, tzinfo=dt.UTC)


def _make_listing(**kwargs) -> Listing:
    defaults = {
        "listing_id": "test-001",
        "url": "https://www.autoscout24.com/lst/1",
        "brand": "MINI",
        "model": "Hatch",
        "year": 2020,
        "mileage_km": 25000,
        "price_eur": 18000,
        "location": "Berlin",
        "country": "DE",
        "first_seen": _NOW,
        "last_seen": _NOW,
    }
    defaults.update(kwargs)
    return Listing(**defaults)


def _make_score(**kwargs) -> ListingScore:
    defaults = {
        "score": 8,
        "reasoning": "Good value for money.",
        "pros": ["Low mileage"],
        "cons": ["High price"],
    }
    defaults.update(kwargs)
    return ListingScore(**defaults)


# ---------------------------------------------------------------------------
# 5.1  prompt.py tests
# ---------------------------------------------------------------------------


def test_build_system_prompt_contains_brief():
    brief = "Score cars strictly."
    prompt = build_system_prompt(brief)
    assert "Score cars strictly." in prompt
    assert "automotive expert" in prompt
    assert "1-10" in prompt
    assert "pros, cons" in prompt


def test_render_listing_excludes_raw_dict():
    listing = _make_listing(raw={"secret": "xyz", "internal_id": 42})
    output = render_listing(listing)
    assert "secret" not in output
    assert "xyz" not in output
    assert "internal_id" not in output
    assert "42" not in output


def test_render_listing_includes_key_fields():
    listing = _make_listing()
    output = render_listing(listing)
    assert "brand: MINI" in output
    assert "model: Hatch" in output
    assert "year: 2020" in output
    assert "mileage_km: 25000" in output
    assert "price_eur: 18000" in output
    assert "location: Berlin" in output
    assert "country: DE" in output
    assert "url: https://www.autoscout24.com/lst/1" in output


def test_render_listing_format_is_key_value_lines():
    """Each line must be 'key: value', not JSON."""
    listing = _make_listing()
    output = render_listing(listing)
    # Must NOT be JSON
    assert "{" not in output
    assert "}" not in output
    # Every non-empty line must contain a colon
    for line in output.splitlines():
        if line.strip():
            assert ": " in line, f"Line has no ': ': {line!r}"


def test_load_brief_reads_file(tmp_path):
    brief_file = tmp_path / "brief.md"
    brief_file.write_text("Rate this car.", encoding="utf-8")
    # Clear lru_cache so we pick up the new path
    from autoscout_pipeline.scoring.prompt import _read_brief_cached

    _read_brief_cached.cache_clear()
    result = load_brief(brief_file)
    assert result == "Rate this car."


# ---------------------------------------------------------------------------
# 5.2  scorer.py tests
# ---------------------------------------------------------------------------


def test_scorer_pins_mode_to_tools():
    """_mode must be the exact instructor.Mode.TOOLS enum member (identity check)."""
    scorer = LLMScorer(api_key="x")
    assert scorer._mode is instructor.Mode.TOOLS


def test_scorer_uses_async_openai_client():
    """The underlying OpenAI client wrapped by instructor must be AsyncOpenAI."""
    from openai import AsyncOpenAI

    scorer = LLMScorer(api_key="x")
    # instructor wraps the client; the raw client is accessible via .client
    assert isinstance(scorer._client.client, AsyncOpenAI)


async def test_score_returns_listing_score():
    """score() returns the ListingScore produced by the (mocked) LLM."""
    listing = _make_listing()
    expected = _make_score(score=7)

    scorer = LLMScorer(api_key="x")
    scorer._client = MagicMock()
    scorer._client.chat.completions.create = AsyncMock(return_value=expected)

    result = await scorer.score(listing)
    assert result is expected
    assert result.score == 7


async def test_score_returns_sentinel_on_api_error():
    """On any API error, score() returns ListingScore(score=1, reasoning starts with 'LLM scoring failed:')."""
    listing = _make_listing()

    scorer = LLMScorer(api_key="x")
    scorer._client = MagicMock()
    scorer._client.chat.completions.create = AsyncMock(side_effect=Exception("openai timeout"))

    result = await scorer.score(listing)
    assert isinstance(result, ListingScore)
    assert result.score == 1
    assert result.reasoning.startswith("LLM scoring failed:")
    assert "openai timeout" in result.reasoning
    assert result.pros == []
    assert result.cons == []


# ---------------------------------------------------------------------------
# 5.3  batch.py tests
# ---------------------------------------------------------------------------


async def test_score_many_returns_nested_scored_listing():
    """score_many() returns ScoredListing with NESTED layout and UTC scored_at."""
    listings = [_make_listing(listing_id="a")]
    expected_score = _make_score(score=9)

    scorer = LLMScorer(api_key="x")
    scorer._client = MagicMock()
    scorer._client.chat.completions.create = AsyncMock(return_value=expected_score)

    results = await score_many(scorer, listings)

    assert len(results) == 1
    r = results[0]
    # NESTED layout
    assert isinstance(r, ScoredListing)
    assert r.listing is listings[0]
    assert isinstance(r.score, ListingScore)
    assert r.score.score == 9
    # scored_at must be tz-aware
    assert r.scored_at.tzinfo is not None


async def test_score_many_respects_semaphore():
    """Peak concurrent in-flight scoring calls must never exceed concurrency=5."""
    concurrency = 5
    n_listings = 20

    listings = [_make_listing(listing_id=f"listing-{i}") for i in range(n_listings)]

    peak_inflight = 0
    current_inflight = 0
    lock = asyncio.Lock()

    async def fake_score(listing: Listing) -> ListingScore:
        nonlocal peak_inflight, current_inflight
        async with lock:
            current_inflight += 1
            if current_inflight > peak_inflight:
                peak_inflight = current_inflight
        # Yield control so other coroutines can run and potentially increase in-flight
        await asyncio.sleep(0)
        async with lock:
            current_inflight -= 1
        return _make_score()

    scorer = LLMScorer(api_key="x")
    scorer.score = fake_score  # type: ignore[method-assign]

    await score_many(scorer, listings, concurrency=concurrency)

    assert peak_inflight <= concurrency, (
        f"Peak in-flight ({peak_inflight}) exceeded semaphore limit ({concurrency})"
    )


async def test_score_many_returns_all_results():
    """score_many() returns exactly one ScoredListing per input Listing."""
    n = 8
    listings = [_make_listing(listing_id=f"x-{i}") for i in range(n)]
    expected_score = _make_score()

    scorer = LLMScorer(api_key="x")
    scorer._client = MagicMock()
    scorer._client.chat.completions.create = AsyncMock(return_value=expected_score)

    results = await score_many(scorer, listings, concurrency=3)
    assert len(results) == n
    assert all(isinstance(r, ScoredListing) for r in results)
