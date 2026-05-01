"""Capture real AutoScout24 HTML fixtures for the test suite.

Usage
-----
    uv run python -m scripts.capture_fixtures

What it does
~~~~~~~~~~~~
1. Uses ``cloverlabs-camoufox`` (headless Firefox with anti-fingerprint patches)
   to fetch a live MINI Hatch search results page from autoscout24.com.
2. Navigates to the first detail page from the results.
3. Writes the raw HTML (post-Next.js hydration, containing __NEXT_DATA__) to:
   - ``tests/fixtures/autoscout_listings_page1.html``  (search results page)
   - ``tests/fixtures/autoscout_listing_detail.html``  (first listing detail)

Requirements
~~~~~~~~~~~~
- camoufox browser binary must be downloaded first::

      python -m camoufox fetch

- The ``[geoip]`` extra must be installed::

      pip install "cloverlabs-camoufox[geoip]"

- Live network access to autoscout24.com is required.

Note
~~~~
These fixtures contain real user-facing HTML from AutoScout24. They are
committed to the repository as reference snapshots. If the site's __NEXT_DATA__
schema changes, re-run this script and update the parse paths in
``src/autoscout_pipeline/scraper/parse.py`` accordingly.
"""

from __future__ import annotations

import asyncio
import pathlib
import sys

FIXTURES_DIR = pathlib.Path(__file__).parent.parent / "tests" / "fixtures"

# Search URL for MINI Hatch (3-door + 5-door) in DE/AT/CH
# Mileage: 20,000-30,000 km | Price: max 23,000 EUR
SEARCH_URL = (
    "https://www.autoscout24.com/lst/mini/mini"
    "?atype=C&cy=D%2CA%2CCH&sort=standard&desc=0&ustate=N%2CU"
    "&priceto=23000&kmfrom=20000&kmto=30000&page=1"
)


async def _capture() -> None:
    try:
        from camoufox.async_api import AsyncCamoufox
    except ImportError:
        print(
            "ERROR: cloverlabs-camoufox is not installed. "
            "Run: pip install 'cloverlabs-camoufox[geoip]'",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        from playwright.async_api import TimeoutError as PlaywrightTimeoutError
    except ImportError:
        print("ERROR: playwright is not installed.", file=sys.stderr)
        sys.exit(1)

    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)

    print(f"Fetching search page: {SEARCH_URL}")
    detail_url: str | None = None

    async with AsyncCamoufox(headless=True, geoip=True, locale="de-DE") as browser:
        # --- Capture search results page ---
        page = await browser.new_page()
        try:
            await page.goto(SEARCH_URL, wait_until="networkidle", timeout=45000)
            try:
                await page.wait_for_selector("script#__NEXT_DATA__", timeout=15000)
            except PlaywrightTimeoutError:
                print(
                    "WARNING: __NEXT_DATA__ not found on search page — "
                    "Akamai may have served a challenge page.",
                    file=sys.stderr,
                )

            html = await page.content()
            out_path = FIXTURES_DIR / "autoscout_listings_page1.html"
            out_path.write_text(html, encoding="utf-8")
            print(f"  Wrote {len(html):,} bytes to {out_path}")

            # Try to find a detail link from the __NEXT_DATA__
            import orjson
            from selectolax.parser import HTMLParser

            tree = HTMLParser(html)
            node = tree.css_first("script#__NEXT_DATA__")
            if node:
                data = orjson.loads(node.text(strip=True))
                listings = (
                    data.get("props", {})
                    .get("pageProps", {})
                    .get("listings", [])
                )
                if listings and isinstance(listings, list) and listings[0].get("url"):
                    detail_url = listings[0]["url"]
                    if not detail_url.startswith("http"):
                        detail_url = f"https://www.autoscout24.com{detail_url}"
        finally:
            await page.close()

        # --- Capture listing detail page ---
        if detail_url:
            print(f"Fetching detail page: {detail_url}")
            detail_page = await browser.new_page()
            try:
                await detail_page.goto(
                    detail_url, wait_until="networkidle", timeout=45000
                )
                try:
                    await detail_page.wait_for_selector(
                        "script#__NEXT_DATA__", timeout=15000
                    )
                except PlaywrightTimeoutError:
                    print(
                        "WARNING: __NEXT_DATA__ not found on detail page.",
                        file=sys.stderr,
                    )

                detail_html = await detail_page.content()
                detail_out = FIXTURES_DIR / "autoscout_listing_detail.html"
                detail_out.write_text(detail_html, encoding="utf-8")
                print(f"  Wrote {len(detail_html):,} bytes to {detail_out}")
            finally:
                await detail_page.close()
        else:
            print(
                "  Skipping detail capture — no listing URL found in __NEXT_DATA__",
                file=sys.stderr,
            )

    print("Done. Fixtures written to:", FIXTURES_DIR)
    print(
        "\nReminder: the autoscout_listings_no_next_data.html fixture is synthetic "
        "and does not need to be refreshed from the live site."
    )


def main() -> None:
    asyncio.run(_capture())


if __name__ == "__main__":
    main()
