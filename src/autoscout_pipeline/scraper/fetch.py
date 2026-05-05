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
            await page.wait_for_selector(
                "script#__NEXT_DATA__", state="attached", timeout=15000
            )
            html: str = await page.content()
        finally:
            await page.close()
    return html
