"""Tests for scraper/fetch.py — BrowserSession async context manager.

All tests are pure unit tests: AsyncCamoufox is mocked so no live network or
browser is required.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest
from playwright.async_api import TimeoutError as PlaywrightTimeoutError


class TestBrowserSessionLifecycle:
    """BrowserSession opens the browser once and closes it when the CM exits."""

    @pytest.mark.asyncio
    async def test_context_manager_opens_and_closes_browser_exactly_once(self) -> None:
        """Browser is opened on __aenter__ and closed on __aexit__ exactly once."""
        mock_browser = AsyncMock()
        mock_page = AsyncMock()
        mock_page.content = AsyncMock(return_value="<html>test</html>")
        mock_browser.new_page = AsyncMock(return_value=mock_page)

        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_browser)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "autoscout_pipeline.scraper.fetch.AsyncCamoufox", return_value=mock_cm
        ):
            from autoscout_pipeline.scraper.fetch import BrowserSession

            async with BrowserSession() as session:
                await session.fetch("https://example.com")

        # AsyncCamoufox constructed exactly once
        mock_cm.__aenter__.assert_awaited_once()
        mock_cm.__aexit__.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_context_manager_shares_browser_across_multiple_fetches(
        self,
    ) -> None:
        """A single BrowserSession reuses one browser for N sequential fetches."""
        mock_browser = AsyncMock()
        mock_page = AsyncMock()
        mock_page.content = AsyncMock(return_value="<html>page</html>")
        mock_browser.new_page = AsyncMock(return_value=mock_page)

        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_browser)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "autoscout_pipeline.scraper.fetch.AsyncCamoufox", return_value=mock_cm
        ):
            from autoscout_pipeline.scraper.fetch import BrowserSession

            async with BrowserSession() as session:
                await session.fetch("https://example.com/1")
                await session.fetch("https://example.com/2")
                await session.fetch("https://example.com/3")

        # Browser opened once, closed once — not per-fetch
        mock_cm.__aenter__.assert_awaited_once()
        mock_cm.__aexit__.assert_awaited_once()
        # But new_page was called once per fetch
        assert mock_browser.new_page.await_count == 3


class TestBrowserSessionFetch:
    """BrowserSession.fetch returns HTML content and uses the correct wait strategy."""

    @pytest.mark.asyncio
    async def test_fetch_returns_page_html(self) -> None:
        """fetch() returns the content of the fully-hydrated page."""
        expected_html = "<html><body>listing data</body></html>"

        mock_browser = AsyncMock()
        mock_page = AsyncMock()
        mock_page.content = AsyncMock(return_value=expected_html)
        mock_browser.new_page = AsyncMock(return_value=mock_page)

        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_browser)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "autoscout_pipeline.scraper.fetch.AsyncCamoufox", return_value=mock_cm
        ):
            from autoscout_pipeline.scraper.fetch import BrowserSession

            async with BrowserSession() as session:
                result = await session.fetch("https://example.com/listing/1")

        assert result == expected_html

    @pytest.mark.asyncio
    async def test_fetch_waits_for_next_data_selector_with_state_attached(
        self,
    ) -> None:
        """fetch() calls wait_for_selector with state='attached' for __NEXT_DATA__."""
        mock_browser = AsyncMock()
        mock_page = AsyncMock()
        mock_page.content = AsyncMock(return_value="<html>ok</html>")
        mock_browser.new_page = AsyncMock(return_value=mock_page)

        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_browser)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "autoscout_pipeline.scraper.fetch.AsyncCamoufox", return_value=mock_cm
        ):
            from autoscout_pipeline.scraper.fetch import BrowserSession

            async with BrowserSession() as session:
                await session.fetch("https://example.com/listing/2")

        # Verify wait_for_selector was called with state="attached"
        mock_page.wait_for_selector.assert_awaited_once_with(
            "script#__NEXT_DATA__", state="attached", timeout=15000
        )

    @pytest.mark.asyncio
    async def test_fetch_closes_page_after_content_captured(self) -> None:
        """Each fetch() call opens a page and closes it before returning."""
        mock_browser = AsyncMock()
        mock_page = AsyncMock()
        mock_page.content = AsyncMock(return_value="<html>content</html>")
        mock_browser.new_page = AsyncMock(return_value=mock_page)

        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_browser)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "autoscout_pipeline.scraper.fetch.AsyncCamoufox", return_value=mock_cm
        ):
            from autoscout_pipeline.scraper.fetch import BrowserSession

            async with BrowserSession() as session:
                await session.fetch("https://example.com/listing/3")

        mock_page.close.assert_awaited_once()


class TestBrowserSessionRetry:
    """BrowserSession.fetch retries on PlaywrightTimeoutError via tenacity."""

    @pytest.mark.asyncio
    async def test_fetch_retries_on_playwright_timeout_error(self) -> None:
        """fetch() retries 3 times on PlaywrightTimeoutError, then raises RetryError.

        Tenacity wraps the final exception in RetryError after stop_after_attempt(3)
        is exhausted. We verify new_page was called exactly 3 times (3 attempts).
        """
        import tenacity

        mock_browser = AsyncMock()
        mock_page = AsyncMock()
        # Simulate timeout on every attempt
        mock_page.goto = AsyncMock(side_effect=PlaywrightTimeoutError("timeout"))
        mock_browser.new_page = AsyncMock(return_value=mock_page)

        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_browser)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "autoscout_pipeline.scraper.fetch.AsyncCamoufox", return_value=mock_cm
        ):
            from autoscout_pipeline.scraper.fetch import BrowserSession

            # Patch asyncio.sleep to skip actual backoff waits in tests
            with patch("asyncio.sleep"):
                async with BrowserSession() as session:
                    with pytest.raises((PlaywrightTimeoutError, tenacity.RetryError)):
                        # tenacity must exhaust retries and re-raise
                        await session.fetch("https://example.com/listing/timeout")

        # 3 attempts = 3 new_page opens
        assert mock_browser.new_page.await_count == 3

    @pytest.mark.asyncio
    async def test_fetch_succeeds_after_transient_timeout(self) -> None:
        """fetch() succeeds when the first attempt times out but second succeeds."""
        mock_browser = AsyncMock()
        mock_page_fail = AsyncMock()
        mock_page_fail.goto = AsyncMock(side_effect=PlaywrightTimeoutError("timeout"))
        mock_page_ok = AsyncMock()
        mock_page_ok.content = AsyncMock(return_value="<html>recovered</html>")

        # First call returns fail page, subsequent calls return ok page
        mock_browser.new_page = AsyncMock(
            side_effect=[mock_page_fail, mock_page_ok]
        )

        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_browser)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "autoscout_pipeline.scraper.fetch.AsyncCamoufox", return_value=mock_cm
        ):
            from autoscout_pipeline.scraper.fetch import BrowserSession

            # Patch asyncio.sleep to skip tenacity backoff waits in tests
            with patch("asyncio.sleep"):
                async with BrowserSession() as session:
                    result = await session.fetch("https://example.com/transient")

        assert result == "<html>recovered</html>"
