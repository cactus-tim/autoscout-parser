"""Tests for scraper/enrich.py — enrich_with_details function.

All tests are pure unit tests: BrowserSession, extract_next_data, and
parse_listing_detail are mocked so no live network or browser is required.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from autoscout_pipeline.models import Listing
from autoscout_pipeline.scraper.errors import NextDataMissingError

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_listing(listing_id: str = "listing-1", url: str = "https://example.com/1") -> Listing:
    """Return a minimal valid Listing with empty enrichment fields."""
    now = datetime.now(tz=UTC)
    return Listing(
        listing_id=listing_id,
        url=url,
        brand="MINI",
        model="Cooper",
        year=2020,
        mileage_km=30000,
        price_eur=18000,
        first_seen=now,
        last_seen=now,
        raw={"vehicle": {"transmission": "Automatik"}},
    )


def _make_enriched_listing(listing_id: str = "listing-1") -> Listing:
    """Return a Listing with all four enrichment fields populated."""
    now = datetime.now(tz=UTC)
    return Listing(
        listing_id=listing_id,
        url="https://example.com/1",
        brand="MINI",
        model="Cooper",
        year=2020,
        mileage_km=30000,
        price_eur=18000,
        first_seen=now,
        last_seen=now,
        raw={"vehicle": {"transmission": "Automatik"}},
        equipment=["Klimaanlage", "Sitzheizung"],
        exterior_color="Hellblau",
        interior_color="Black",
        upholstery="Cloth",
    )


# ---------------------------------------------------------------------------
# Test: empty list returns immediately without opening BrowserSession
# ---------------------------------------------------------------------------


class TestEnrichEmptyList:
    """enrich_with_details returns immediately when given an empty list."""

    @pytest.mark.asyncio
    async def test_empty_list_returns_immediately_no_browser_opened(self) -> None:
        """Empty list → return [] without constructing BrowserSession."""
        with patch("autoscout_pipeline.scraper.enrich.BrowserSession") as mock_browser_session_cls:
            from autoscout_pipeline.scraper.enrich import enrich_with_details

            result = await enrich_with_details([], throttle_min=0.0, throttle_max=0.0)

        assert result == []
        mock_browser_session_cls.assert_not_called()

    @pytest.mark.asyncio
    async def test_empty_list_returns_same_list_object(self) -> None:
        """enrich_with_details returns the exact same list object (in-place semantics)."""
        with patch("autoscout_pipeline.scraper.enrich.BrowserSession"):
            from autoscout_pipeline.scraper.enrich import enrich_with_details

            empty: list[Listing] = []
            result = await enrich_with_details(empty, throttle_min=0.0, throttle_max=0.0)

        assert result is empty


# ---------------------------------------------------------------------------
# Test: logger.info expected-duration line is emitted at startup
# ---------------------------------------------------------------------------


class TestEnrichStartupLog:
    """enrich_with_details emits an INFO log with expected duration before fetching."""

    @pytest.mark.asyncio
    async def test_startup_info_log_emitted(self, caplog: pytest.LogCaptureFixture) -> None:
        """logger.info expected-duration line is logged before any fetch."""
        listings = [_make_listing("L1"), _make_listing("L2")]
        enriched = _make_enriched_listing("L1")

        mock_session = AsyncMock()
        mock_session.fetch = AsyncMock(return_value="<html>ok</html>")

        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("autoscout_pipeline.scraper.enrich.BrowserSession", return_value=mock_cm),
            patch("autoscout_pipeline.scraper.enrich.extract_next_data", return_value={}),
            patch(
                "autoscout_pipeline.scraper.enrich.parse_listing_detail",
                return_value=enriched,
            ),
            patch("asyncio.sleep"),
            caplog.at_level(logging.INFO, logger="autoscout_pipeline.scraper.enrich"),
        ):
            from autoscout_pipeline.scraper.enrich import enrich_with_details

            await enrich_with_details(listings, throttle_min=2.0, throttle_max=6.0)

        info_messages = [r.message for r in caplog.records if r.levelno == logging.INFO]
        assert any("Enriching" in msg for msg in info_messages), (
            f"Expected startup INFO log with 'Enriching', got: {info_messages}"
        )
        # Also check the numeric context is present
        assert any("2" in msg for msg in info_messages), (
            f"Expected listing count in INFO log, got: {info_messages}"
        )


# ---------------------------------------------------------------------------
# Test: N listings enriched in place with all 4 fields
# ---------------------------------------------------------------------------


class TestEnrichSuccessPath:
    """enrich_with_details populates all four enrichment fields on each listing."""

    @pytest.mark.asyncio
    async def test_single_listing_enriched_in_place(self) -> None:
        """A single listing has all four fields populated from parse_listing_detail."""
        listing = _make_listing("L1")
        enriched_result = _make_enriched_listing("L1")

        mock_session = AsyncMock()
        mock_session.fetch = AsyncMock(return_value="<html>detail</html>")

        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("autoscout_pipeline.scraper.enrich.BrowserSession", return_value=mock_cm),
            patch("autoscout_pipeline.scraper.enrich.extract_next_data", return_value={}),
            patch(
                "autoscout_pipeline.scraper.enrich.parse_listing_detail",
                return_value=enriched_result,
            ),
            patch("asyncio.sleep"),
        ):
            from autoscout_pipeline.scraper.enrich import enrich_with_details

            result = await enrich_with_details([listing], throttle_min=0.0, throttle_max=0.0)

        assert result[0].equipment == ["Klimaanlage", "Sitzheizung"]
        assert result[0].exterior_color == "Hellblau"
        assert result[0].interior_color == "Black"
        assert result[0].upholstery == "Cloth"

    @pytest.mark.asyncio
    async def test_multiple_listings_all_enriched_in_place(self) -> None:
        """All N listings get enrichment fields populated from parse_listing_detail."""
        listings = [
            _make_listing("L1", "https://example.com/1"),
            _make_listing("L2", "https://example.com/2"),
            _make_listing("L3", "https://example.com/3"),
        ]

        def make_enriched(id_: str) -> Listing:
            now = datetime.now(tz=UTC)
            return Listing(
                listing_id=id_,
                url=f"https://example.com/{id_}",
                brand="MINI",
                model="Cooper",
                year=2020,
                mileage_km=30000,
                price_eur=18000,
                first_seen=now,
                last_seen=now,
                equipment=["Klimaanlage"],
                exterior_color="Schwarz",
                interior_color="Grey",
                upholstery="Leather",
            )

        enriched_side_effects = [make_enriched("L1"), make_enriched("L2"), make_enriched("L3")]

        mock_session = AsyncMock()
        mock_session.fetch = AsyncMock(return_value="<html>ok</html>")

        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        call_count = 0

        def parse_side_effect(data: Any) -> Listing:
            nonlocal call_count
            result = enriched_side_effects[call_count]
            call_count += 1
            return result

        with (
            patch("autoscout_pipeline.scraper.enrich.BrowserSession", return_value=mock_cm),
            patch("autoscout_pipeline.scraper.enrich.extract_next_data", return_value={}),
            patch(
                "autoscout_pipeline.scraper.enrich.parse_listing_detail",
                side_effect=parse_side_effect,
            ),
            patch("asyncio.sleep"),
        ):
            from autoscout_pipeline.scraper.enrich import enrich_with_details

            result = await enrich_with_details(listings, throttle_min=0.0, throttle_max=0.0)

        assert len(result) == 3
        for lst in result:
            assert lst.equipment == ["Klimaanlage"]
            assert lst.exterior_color == "Schwarz"
            assert lst.interior_color == "Grey"
            assert lst.upholstery == "Leather"

    @pytest.mark.asyncio
    async def test_returns_same_list_object(self) -> None:
        """enrich_with_details returns the exact same list object (in-place semantics)."""
        listing = _make_listing("L1")
        enriched_result = _make_enriched_listing("L1")

        mock_session = AsyncMock()
        mock_session.fetch = AsyncMock(return_value="<html>ok</html>")

        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("autoscout_pipeline.scraper.enrich.BrowserSession", return_value=mock_cm),
            patch("autoscout_pipeline.scraper.enrich.extract_next_data", return_value={}),
            patch(
                "autoscout_pipeline.scraper.enrich.parse_listing_detail",
                return_value=enriched_result,
            ),
            patch("asyncio.sleep"),
        ):
            from autoscout_pipeline.scraper.enrich import enrich_with_details

            listings = [listing]
            result = await enrich_with_details(listings, throttle_min=0.0, throttle_max=0.0)

        assert result is listings

    @pytest.mark.asyncio
    async def test_one_browser_session_opened_for_n_listings(self) -> None:
        """Only ONE BrowserSession is opened regardless of how many listings there are."""
        listings = [_make_listing(f"L{i}") for i in range(5)]
        enriched_result = _make_enriched_listing("L0")

        mock_session = AsyncMock()
        mock_session.fetch = AsyncMock(return_value="<html>ok</html>")

        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with (
            patch(
                "autoscout_pipeline.scraper.enrich.BrowserSession", return_value=mock_cm
            ) as mock_browser_cls,
            patch("autoscout_pipeline.scraper.enrich.extract_next_data", return_value={}),
            patch(
                "autoscout_pipeline.scraper.enrich.parse_listing_detail",
                return_value=enriched_result,
            ),
            patch("asyncio.sleep"),
        ):
            from autoscout_pipeline.scraper.enrich import enrich_with_details

            await enrich_with_details(listings, throttle_min=0.0, throttle_max=0.0)

        mock_browser_cls.assert_called_once()
        mock_cm.__aenter__.assert_awaited_once()
        mock_cm.__aexit__.assert_awaited_once()


# ---------------------------------------------------------------------------
# Test: per-listing exception is logged and skipped; subsequent listings enriched
# ---------------------------------------------------------------------------


class TestEnrichPerListingExceptionHandling:
    """Per-listing exceptions are caught, logged as WARNING, and the loop continues."""

    @pytest.mark.asyncio
    async def test_failing_listing_is_skipped_and_subsequent_still_enriched(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """If listing[0] raises NextDataMissingError, listing[1] still gets enriched."""
        listing_fail = _make_listing("L-fail", "https://example.com/fail")
        listing_ok = _make_listing("L-ok", "https://example.com/ok")
        enriched_ok = _make_enriched_listing("L-ok")
        enriched_ok = Listing(
            listing_id="L-ok",
            url="https://example.com/ok",
            brand="MINI",
            model="Cooper",
            year=2020,
            mileage_km=30000,
            price_eur=18000,
            first_seen=datetime.now(tz=UTC),
            last_seen=datetime.now(tz=UTC),
            equipment=["Klimaanlage"],
            exterior_color="Weiss",
            interior_color="Black",
            upholstery="Cloth",
        )

        mock_session = AsyncMock()
        mock_session.fetch = AsyncMock(return_value="<html>page</html>")

        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        call_n = 0

        def parse_side_effect(data: Any) -> Listing:
            nonlocal call_n
            call_n += 1
            if call_n == 1:
                raise NextDataMissingError("missing __NEXT_DATA__")
            return enriched_ok

        with (
            patch("autoscout_pipeline.scraper.enrich.BrowserSession", return_value=mock_cm),
            patch("autoscout_pipeline.scraper.enrich.extract_next_data", return_value={}),
            patch(
                "autoscout_pipeline.scraper.enrich.parse_listing_detail",
                side_effect=parse_side_effect,
            ),
            patch("asyncio.sleep"),
            caplog.at_level(logging.WARNING, logger="autoscout_pipeline.scraper.enrich"),
        ):
            from autoscout_pipeline.scraper.enrich import enrich_with_details

            result = await enrich_with_details(
                [listing_fail, listing_ok],
                throttle_min=0.0,
                throttle_max=0.0,
            )

        # listing_fail stays un-enriched
        assert result[0].equipment == []
        assert result[0].exterior_color is None

        # listing_ok gets enriched
        assert result[1].equipment == ["Klimaanlage"]
        assert result[1].exterior_color == "Weiss"

        # WARNING was logged for the failure
        warn_messages = [r.message for r in caplog.records if r.levelno == logging.WARNING]
        assert any("L-fail" in msg for msg in warn_messages), (
            f"Expected WARNING with listing_id 'L-fail', got: {warn_messages}"
        )

    @pytest.mark.asyncio
    async def test_generic_exception_is_caught_and_skipped(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A generic ValueError from parse_listing_detail is caught and loop continues."""
        listing = _make_listing("L-err")
        enriched_result = _make_enriched_listing("L-err")

        mock_session = AsyncMock()
        mock_session.fetch = AsyncMock(return_value="<html>page</html>")

        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("autoscout_pipeline.scraper.enrich.BrowserSession", return_value=mock_cm),
            patch(
                "autoscout_pipeline.scraper.enrich.extract_next_data",
                side_effect=ValueError("parse error"),
            ),
            patch(
                "autoscout_pipeline.scraper.enrich.parse_listing_detail",
                return_value=enriched_result,
            ),
            patch("asyncio.sleep"),
            caplog.at_level(logging.WARNING, logger="autoscout_pipeline.scraper.enrich"),
        ):
            from autoscout_pipeline.scraper.enrich import enrich_with_details

            result = await enrich_with_details([listing], throttle_min=0.0, throttle_max=0.0)

        # listing remains un-enriched (exception was in extract_next_data)
        assert result[0].equipment == []
        assert result[0].exterior_color is None

        # WARNING should be logged
        warn_messages = [r.message for r in caplog.records if r.levelno == logging.WARNING]
        assert any("L-err" in msg for msg in warn_messages)


# ---------------------------------------------------------------------------
# Test: throttle sleep called between listings
# ---------------------------------------------------------------------------


class TestEnrichThrottle:
    """asyncio.sleep is called after each listing fetch with a value in [throttle_min, throttle_max]."""

    @pytest.mark.asyncio
    async def test_sleep_called_after_each_listing(self) -> None:
        """asyncio.sleep is called at least N-1 times for N listings."""
        n = 4
        listings = [_make_listing(f"L{i}") for i in range(n)]
        enriched_result = _make_enriched_listing("L0")

        mock_session = AsyncMock()
        mock_session.fetch = AsyncMock(return_value="<html>ok</html>")

        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("autoscout_pipeline.scraper.enrich.BrowserSession", return_value=mock_cm),
            patch("autoscout_pipeline.scraper.enrich.extract_next_data", return_value={}),
            patch(
                "autoscout_pipeline.scraper.enrich.parse_listing_detail",
                return_value=enriched_result,
            ),
            patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
        ):
            from autoscout_pipeline.scraper.enrich import enrich_with_details

            await enrich_with_details(listings, throttle_min=1.0, throttle_max=3.0)

        # sleep must be called at least N-1 times (may also be called N times — after last)
        assert mock_sleep.await_count >= n - 1, (
            f"Expected >= {n - 1} sleep calls for {n} listings, got {mock_sleep.await_count}"
        )

    @pytest.mark.asyncio
    async def test_sleep_called_with_value_in_throttle_range(self) -> None:
        """Each asyncio.sleep call receives a value between throttle_min and throttle_max."""
        listings = [_make_listing("L1"), _make_listing("L2")]
        enriched_result = _make_enriched_listing("L1")

        throttle_min = 1.0
        throttle_max = 5.0

        mock_session = AsyncMock()
        mock_session.fetch = AsyncMock(return_value="<html>ok</html>")

        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("autoscout_pipeline.scraper.enrich.BrowserSession", return_value=mock_cm),
            patch("autoscout_pipeline.scraper.enrich.extract_next_data", return_value={}),
            patch(
                "autoscout_pipeline.scraper.enrich.parse_listing_detail",
                return_value=enriched_result,
            ),
            patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
        ):
            from autoscout_pipeline.scraper.enrich import enrich_with_details

            await enrich_with_details(
                listings,
                throttle_min=throttle_min,
                throttle_max=throttle_max,
            )

        for c in mock_sleep.call_args_list:
            sleep_val = c.args[0]
            assert throttle_min <= sleep_val <= throttle_max, (
                f"sleep({sleep_val}) not in [{throttle_min}, {throttle_max}]"
            )


# ---------------------------------------------------------------------------
# Test: circuit breaker — 5 consecutive failures trip the breaker
# ---------------------------------------------------------------------------


class TestCircuitBreakerTrips:
    """After 5 consecutive outer failures the loop is aborted and ERROR is logged."""

    @pytest.mark.asyncio
    async def test_five_consecutive_failures_trip_circuit_breaker(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """5 consecutive NextDataMissingError → circuit breaker trips, remaining listings skipped."""
        # 7 listings; only 5 needed to trip the breaker
        listings = [_make_listing(f"L{i}") for i in range(7)]

        mock_session = AsyncMock()
        mock_session.fetch = AsyncMock(return_value="<html>challenge</html>")

        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("autoscout_pipeline.scraper.enrich.BrowserSession", return_value=mock_cm),
            patch(
                "autoscout_pipeline.scraper.enrich.extract_next_data",
                side_effect=NextDataMissingError("no __NEXT_DATA__"),
            ),
            patch("asyncio.sleep"),
            caplog.at_level(logging.ERROR, logger="autoscout_pipeline.scraper.enrich"),
        ):
            from autoscout_pipeline.scraper.enrich import enrich_with_details

            result = await enrich_with_details(listings, throttle_min=0.0, throttle_max=0.0)

        # Should return all listings (some un-enriched) — NOT raise
        assert len(result) == 7

        # All listings remain un-enriched (every fetch failed)
        for lst in result:
            assert lst.equipment == []
            assert lst.exterior_color is None

        # session.fetch was called at most 5 times (breaker trips after 5)
        assert mock_session.fetch.await_count <= 5, (
            f"Expected <= 5 fetch calls before breaker, got {mock_session.fetch.await_count}"
        )

        # ERROR was logged once
        error_messages = [r.message for r in caplog.records if r.levelno == logging.ERROR]
        assert len(error_messages) >= 1
        assert any(
            "Circuit breaker" in msg or "circuit" in msg.lower() for msg in error_messages
        ), f"Expected circuit breaker ERROR log, got: {error_messages}"

    @pytest.mark.asyncio
    async def test_circuit_breaker_aborts_remaining_listings(self) -> None:
        """After circuit breaker trips, remaining listings are not fetched."""
        # 10 listings; breaker trips after 5
        n_listings = 10
        listings = [_make_listing(f"L{i}") for i in range(n_listings)]

        mock_session = AsyncMock()
        mock_session.fetch = AsyncMock(return_value="<html>challenge</html>")

        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("autoscout_pipeline.scraper.enrich.BrowserSession", return_value=mock_cm),
            patch(
                "autoscout_pipeline.scraper.enrich.extract_next_data",
                side_effect=NextDataMissingError("no data"),
            ),
            patch("asyncio.sleep"),
        ):
            from autoscout_pipeline.scraper.enrich import enrich_with_details

            result = await enrich_with_details(listings, throttle_min=0.0, throttle_max=0.0)

        # The fetch count should be 5, not 10 — remaining 5 listings were skipped
        assert mock_session.fetch.await_count == 5, (
            f"Expected exactly 5 fetch calls (breaker threshold), got {mock_session.fetch.await_count}"
        )
        assert len(result) == n_listings  # all listings still returned, just un-enriched


# ---------------------------------------------------------------------------
# Test: circuit breaker RESETS on success
# ---------------------------------------------------------------------------


class TestCircuitBreakerResetsOnSuccess:
    """The consecutive-failure counter resets to 0 after each successful enrichment."""

    @pytest.mark.asyncio
    async def test_breaker_resets_after_success(self, caplog: pytest.LogCaptureFixture) -> None:
        """Pattern fail-fail-success-fail-fail-fail does not trip the breaker.

        fail-fail resets on success, then fail-fail-fail = 3 consecutive, which is
        below the threshold of 5.  Breaker must NOT be tripped.
        """
        # 6 listings: [fail, fail, success, fail, fail, fail]
        # After success on index 2, counter resets.  Final run of 3 fails < 5 threshold.
        listings = [_make_listing(f"L{i}") for i in range(6)]
        enriched_ok = _make_enriched_listing("ok")

        mock_session = AsyncMock()
        mock_session.fetch = AsyncMock(return_value="<html>page</html>")

        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        call_n = 0

        def parse_side_effect(data: Any) -> Listing:
            nonlocal call_n
            i = call_n
            call_n += 1
            if i in (0, 1, 3, 4, 5):
                raise NextDataMissingError("no data")
            return enriched_ok

        with (
            patch("autoscout_pipeline.scraper.enrich.BrowserSession", return_value=mock_cm),
            patch("autoscout_pipeline.scraper.enrich.extract_next_data", return_value={}),
            patch(
                "autoscout_pipeline.scraper.enrich.parse_listing_detail",
                side_effect=parse_side_effect,
            ),
            patch("asyncio.sleep"),
            caplog.at_level(logging.ERROR, logger="autoscout_pipeline.scraper.enrich"),
        ):
            from autoscout_pipeline.scraper.enrich import enrich_with_details

            result = await enrich_with_details(listings, throttle_min=0.0, throttle_max=0.0)

        # All 6 listings should have been attempted (breaker not tripped)
        assert mock_session.fetch.await_count == 6, (
            f"Expected all 6 listings fetched (breaker not tripped), got {mock_session.fetch.await_count}"
        )

        # listing[2] (index 2) should be enriched (the success)
        assert result[2].equipment == enriched_ok.equipment
        assert result[2].exterior_color == enriched_ok.exterior_color

        # No ERROR log for circuit breaker
        error_messages = [r.message for r in caplog.records if r.levelno == logging.ERROR]
        assert not any(
            "Circuit breaker" in msg or "circuit" in msg.lower() for msg in error_messages
        ), f"Expected NO circuit breaker ERROR, got: {error_messages}"

    @pytest.mark.asyncio
    async def test_five_consecutive_after_reset_trips_breaker(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Pattern success-fail x5 trips the breaker (reset then 5 consecutive)."""
        # 7 listings: [success, fail, fail, fail, fail, fail, success (unreached)]
        listings = [_make_listing(f"L{i}") for i in range(7)]
        enriched_ok = _make_enriched_listing("ok")

        mock_session = AsyncMock()
        mock_session.fetch = AsyncMock(return_value="<html>page</html>")

        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        call_n = 0

        def parse_side_effect(data: Any) -> Listing:
            nonlocal call_n
            i = call_n
            call_n += 1
            if i == 0:
                return enriched_ok  # success
            raise NextDataMissingError("no data")

        with (
            patch("autoscout_pipeline.scraper.enrich.BrowserSession", return_value=mock_cm),
            patch("autoscout_pipeline.scraper.enrich.extract_next_data", return_value={}),
            patch(
                "autoscout_pipeline.scraper.enrich.parse_listing_detail",
                side_effect=parse_side_effect,
            ),
            patch("asyncio.sleep"),
            caplog.at_level(logging.ERROR, logger="autoscout_pipeline.scraper.enrich"),
        ):
            from autoscout_pipeline.scraper.enrich import enrich_with_details

            result = await enrich_with_details(listings, throttle_min=0.0, throttle_max=0.0)

        # listing[0] enriched, then 5 consecutive failures trip breaker at attempt 6
        assert result[0].equipment == enriched_ok.equipment

        # Fetch count: 1 success + 5 failures = 6 total (last listing unreached)
        assert mock_session.fetch.await_count == 6, (
            f"Expected 6 fetch calls (1 ok + 5 fails), got {mock_session.fetch.await_count}"
        )

        # ERROR logged
        error_messages = [r.message for r in caplog.records if r.levelno == logging.ERROR]
        assert any("Circuit breaker" in msg or "circuit" in msg.lower() for msg in error_messages)
