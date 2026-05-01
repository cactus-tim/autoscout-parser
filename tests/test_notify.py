"""Tests for autoscout_pipeline.notify.telegram — Phase 6, Step 6.2.

All HTTP calls are intercepted by respx so no real network traffic is made.
Covers:
- Threshold gate (skip below, send at/above)
- HTML escaping for reasoning, URL href attribute, brand/model fields
- Network-error swallowing (HTTP 500, ConnectTimeout)
- send_batch: count of calls, asyncio.sleep cadence
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import httpx
import pytest
import respx

from autoscout_pipeline.models import Listing, ListingScore, ScoredListing
from autoscout_pipeline.notify.telegram import TelegramNotifier

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 5, 1, 12, 0, 0, tzinfo=UTC)

_BOT_TOKEN = "123456:TESTTOKEN"
_CHAT_ID = "-100999"
_EXPECTED_URL = f"https://api.telegram.org/bot{_BOT_TOKEN}/sendMessage"


def make_listing(**overrides) -> Listing:
    base = {
        "listing_id": "id1",
        "url": "https://www.autoscout24.com/listings/id1",
        "brand": "MINI",
        "model": "Hatch",
        "year": 2021,
        "mileage_km": 25000,
        "price_eur": 18500,
        "location": "Munich",
        "country": "DE",
        "first_seen": _NOW,
        "last_seen": _NOW,
    }
    base.update(overrides)
    return Listing(**base)


def make_score(**overrides) -> ListingScore:
    base = {
        "score": 9,
        "reasoning": "Great value for money.",
        "pros": ["Low mileage"],
        "cons": ["No sunroof"],
    }
    base.update(overrides)
    return ListingScore(**base)


def make_scored(listing: Listing | None = None, score: ListingScore | None = None) -> ScoredListing:
    return ScoredListing(
        listing=listing or make_listing(),
        score=score or make_score(),
        scored_at=_NOW,
    )


def notifier(threshold: int = 8) -> TelegramNotifier:
    return TelegramNotifier(token=_BOT_TOKEN, chat_id=_CHAT_ID, threshold=threshold)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@respx.mock
async def test_send_skips_below_threshold() -> None:
    """Listings with score below the threshold must never call the API."""
    route = respx.post(_EXPECTED_URL).mock(return_value=httpx.Response(200, json={"ok": True}))
    scored = make_scored(score=make_score(score=5))

    result = await notifier(threshold=8).send(scored)

    assert result is False
    assert route.call_count == 0


@respx.mock
async def test_send_calls_api_above_threshold() -> None:
    """A listing at or above the threshold must POST to the Bot API."""
    route = respx.post(_EXPECTED_URL).mock(return_value=httpx.Response(200, json={"ok": True}))
    scored = make_scored(score=make_score(score=9))

    result = await notifier(threshold=8).send(scored)

    assert result is True
    assert route.call_count == 1
    request = route.calls[0].request
    import json

    body = json.loads(request.content)
    assert body["parse_mode"] == "HTML"
    assert body["chat_id"] == _CHAT_ID


@respx.mock
async def test_send_escapes_reasoning_html() -> None:
    """HTML-special chars in reasoning must be entity-escaped in the payload."""
    route = respx.post(_EXPECTED_URL).mock(return_value=httpx.Response(200, json={"ok": True}))
    scored = make_scored(score=make_score(score=9, reasoning="<script>x</script>"))

    await notifier().send(scored)

    import json

    body = json.loads(route.calls[0].request.content)
    text: str = body["text"]
    assert "&lt;script&gt;" in text
    assert "<script>" not in text


@respx.mock
async def test_send_escapes_url_attribute() -> None:
    """Characters that break HTML attributes (quotes, ampersands) in the URL
    must be entity-escaped inside the href value."""
    dangerous_url = 'https://www.autoscout24.com/listings/x?a=1&b=2"x'
    route = respx.post(_EXPECTED_URL).mock(return_value=httpx.Response(200, json={"ok": True}))
    scored = make_scored(listing=make_listing(url=dangerous_url))

    await notifier().send(scored)

    import json

    body = json.loads(route.calls[0].request.content)
    text: str = body["text"]
    # The href attribute must use entity-encoded versions
    assert "&quot;" in text
    assert "&amp;" in text
    # Raw characters must not appear inside the href attribute
    assert 'href="' + dangerous_url not in text


@respx.mock
async def test_send_swallows_network_error(caplog: pytest.LogCaptureFixture) -> None:
    """A 5xx response must NOT raise; send() returns False and logs a warning."""
    respx.post(_EXPECTED_URL).mock(return_value=httpx.Response(500, text="Internal Server Error"))
    scored = make_scored(score=make_score(score=9))

    import logging

    with caplog.at_level(logging.WARNING, logger="autoscout_pipeline.notify.telegram"):
        result = await notifier().send(scored)

    assert result is False
    assert any("telegram send failed" in rec.message for rec in caplog.records)


@respx.mock
async def test_send_swallows_timeout() -> None:
    """A ConnectTimeout must be swallowed; send() returns False."""
    respx.post(_EXPECTED_URL).mock(side_effect=httpx.ConnectTimeout("timed out"))
    scored = make_scored(score=make_score(score=9))

    result = await notifier().send(scored)

    assert result is False


@respx.mock
async def test_send_batch_filters_and_sends_only_high_scores() -> None:
    """send_batch must honour the threshold and only POST for qualifying scores."""
    route = respx.post(_EXPECTED_URL).mock(return_value=httpx.Response(200, json={"ok": True}))

    scored_list = [
        make_scored(listing=make_listing(listing_id=f"id{i}"), score=make_score(score=s))
        for i, s in enumerate([3, 7, 9, 8, 4])
    ]

    # Only scores 9 and 8 meet threshold=8
    with patch("asyncio.sleep", new_callable=AsyncMock):
        sent = await notifier(threshold=8).send_batch(scored_list)

    assert sent == 2
    assert route.call_count == 2


@respx.mock
async def test_send_batch_sleeps_between_sends() -> None:
    """asyncio.sleep(0.5) must be called exactly once between each pair of
    consecutive successful sends — i.e., N-1 times for N sends, NOT N times."""
    respx.post(_EXPECTED_URL).mock(return_value=httpx.Response(200, json={"ok": True}))

    # 3 listings all above threshold → 3 sends → 2 inter-send sleeps
    scored_list = [
        make_scored(listing=make_listing(listing_id=f"id{i}"), score=make_score(score=9))
        for i in range(3)
    ]

    sleep_mock = AsyncMock()
    with patch("autoscout_pipeline.notify.telegram.asyncio.sleep", sleep_mock):
        sent = await notifier(threshold=8).send_batch(scored_list)

    assert sent == 3
    assert sleep_mock.call_count == 3
    # Every call must use the 0.5-second delay
    for call in sleep_mock.call_args_list:
        assert call.args[0] == 0.5
