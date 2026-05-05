"""camoufox-backed HTML fetcher for AutoScout24.

Why ``networkidle`` + explicit ``wait_for_selector`` is required
----------------------------------------------------------------
AutoScout24 uses Next.js SSR with client-side hydration. The ``<script
id="__NEXT_DATA__" type="application/json">`` tag that contains the full
structured listing data is injected into the DOM **after** Next.js hydrates
on the client side. The ``domcontentloaded`` event fires before hydration
completes, so relying on it alone would result in pages that appear loaded but
lack the ``__NEXT_DATA__`` payload.

Using ``wait_until="networkidle"`` ensures the browser has finished all
in-flight network requests (Next.js chunk loading, data fetching), and
``page.wait_for_selector("script#__NEXT_DATA__", timeout=15000)`` provides
an explicit confirmation that the injected script tag is present in the DOM
before we capture the HTML. Verified 2026-05-01: a raw HTTP fetch of
autoscout24.com returned no ``__NEXT_DATA__`` tag; only a fully-hydrated
browser session produces it.
"""

from __future__ import annotations

from types import TracebackType

from camoufox.async_api import AsyncCamoufox
from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=2, max=15),
    retry=retry_if_exception_type((PlaywrightTimeoutError,)),
)
async def fetch_page_html(url: str) -> str:
    """Fetch a fully-hydrated HTML page from *url* using camoufox.

    Parameters
    ----------
    url:
        The fully-qualified URL to fetch (AutoScout24 search or detail page).

    Returns
    -------
    str
        The full HTML content of the page after Next.js hydration.

    Raises
    ------
    PlaywrightTimeoutError
        If the page or selector does not load within the configured timeouts.
        Tenacity will retry up to 3 times with exponential backoff (2-15 s).
    """
    async with AsyncCamoufox(headless=True, geoip=True, locale="de-DE") as browser:
        page = await browser.new_page()
        try:
            await page.goto(url, wait_until="networkidle", timeout=45000)
            await page.wait_for_selector("script#__NEXT_DATA__", state="attached", timeout=15000)
            html: str = await page.content()
        finally:
            await page.close()
    return html


class BrowserSession:
    """Async context manager that holds a single Camoufox browser for sequential fetches.

    Usage::

        async with BrowserSession() as session:
            html1 = await session.fetch(url1)
            html2 = await session.fetch(url2)

    The browser is started once on ``__aenter__`` and shut down on ``__aexit__``.
    Each call to :meth:`fetch` opens a new page, navigates to the URL, waits for
    ``script#__NEXT_DATA__`` to appear (mirroring :func:`fetch_page_html`), captures
    the HTML, and closes the page before returning.

    .. warning:: **Sequential use only.**
        Do NOT call :meth:`fetch` concurrently on a single ``BrowserSession`` instance
        (e.g. via ``asyncio.gather``). Camoufox issue #279 documents that opening
        multiple pages concurrently on the same browser instance can freeze the event
        loop. Sequential page-open/navigate/close cycles are the documented-safe
        pattern for re-using a single browser across many requests.
    """

    def __init__(self) -> None:
        self._browser_cm: object | None = None
        self._browser: object | None = None

    async def __aenter__(self) -> BrowserSession:
        self._browser_cm = AsyncCamoufox(headless=True, geoip=True, locale="de-DE")
        self._browser = await self._browser_cm.__aenter__()  # type: ignore[union-attr]
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> bool:
        if self._browser_cm is not None:
            await self._browser_cm.__aexit__(exc_type, exc_val, exc_tb)  # type: ignore[union-attr]
        return False

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=2, max=15),
        retry=retry_if_exception_type((PlaywrightTimeoutError,)),
    )
    async def fetch(self, url: str) -> str:
        """Fetch a fully-hydrated HTML page from *url* using the shared browser.

        Opens a new page on the existing Camoufox browser instance, navigates to
        *url* with ``wait_until="networkidle"``, waits for ``script#__NEXT_DATA__``
        to be attached (``state="attached"``, timeout 15 s), captures the page HTML,
        and closes the page.

        Tenacity retries up to 3 times with exponential backoff (2-15 s) on
        :class:`~playwright.async_api.TimeoutError`.

        Parameters
        ----------
        url:
            Fully-qualified URL of the AutoScout24 detail page to fetch.

        Returns
        -------
        str
            Full HTML of the page after Next.js hydration.

        Raises
        ------
        PlaywrightTimeoutError
            After 3 failed attempts (tenacity exhausted).
        RuntimeError
            If called outside an ``async with BrowserSession()`` block (browser
            not initialised).
        """
        if self._browser is None:
            raise RuntimeError(
                "BrowserSession.fetch() called outside 'async with BrowserSession()' block."
            )
        page = await self._browser.new_page()  # type: ignore[union-attr]
        try:
            await page.goto(url, wait_until="networkidle", timeout=45000)
            await page.wait_for_selector("script#__NEXT_DATA__", state="attached", timeout=15000)
            html: str = await page.content()
        finally:
            await page.close()
        return html
