"""Pure functions for extracting and parsing AutoScout24 __NEXT_DATA__ JSON.

All functions in this module are side-effect-free except for:
- ``extract_next_data``, which writes a raw HTML dump to /tmp when the
  __NEXT_DATA__ script tag is absent (error-path only).

No network access is performed here; this module operates on pre-fetched HTML.
"""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime
from typing import Any

import orjson
from selectolax.parser import HTMLParser

from autoscout_pipeline.models import Listing
from autoscout_pipeline.scraper.errors import NextDataMissingError

logger = logging.getLogger(__name__)


def extract_next_data(html: str) -> dict[str, Any]:
    """Extract and parse the ``__NEXT_DATA__`` JSON embedded in *html*.

    AutoScout24 pages contain a ``<script id="__NEXT_DATA__" type="application/json">``
    tag with the full structured data payload injected by Next.js after hydration.

    Parameters
    ----------
    html:
        Raw HTML content from a fully-hydrated AutoScout24 page.

    Returns
    -------
    dict
        The parsed ``__NEXT_DATA__`` JSON object.

    Raises
    ------
    NextDataMissingError
        If the ``script#__NEXT_DATA__`` tag is absent. The raw HTML is written
        to ``/tmp/as24_dump_<unix-ts>.html`` for offline debugging and the
        dump path is included in the exception message.
    """
    tree = HTMLParser(html)
    node = tree.css_first("script#__NEXT_DATA__")

    if node is None:
        ts = int(time.time())
        dump_path = f"/tmp/as24_dump_{ts}.html"
        try:
            with open(dump_path, "w", encoding="utf-8") as fh:
                fh.write(html)
        except OSError:
            dump_path = "<unable to write dump>"
        raise NextDataMissingError(
            f"__NEXT_DATA__ script tag not found in HTML. Raw HTML saved to: {dump_path}"
        )

    raw_json = node.text(strip=True)
    return orjson.loads(raw_json)


def _parse_year(raw: str | int | None) -> int:
    """Parse a year from various AutoScout24 date formats."""
    if raw is None:
        return 2000
    if isinstance(raw, int):
        return raw
    s = str(raw).strip()
    # Handles "2020-06", "2020", "2020-06-01", etc.
    if s:
        return int(s.split("-")[0])
    return 2000


def _listing_from_dict(raw: dict[str, Any]) -> Listing | None:
    """Build a ``Listing`` from a raw AutoScout24 listing dict.

    Returns ``None`` if required fields are missing or invalid.
    Uses ``.get()`` throughout to handle schema variance gracefully.
    """
    listing_id = raw.get("id") or raw.get("listing_id")
    if not listing_id:
        return None

    url = raw.get("url") or ""
    brand = raw.get("make") or ""
    model = raw.get("model") or ""

    year_raw = raw.get("firstRegistrationDate") or raw.get("year")
    year = _parse_year(year_raw)
    if year < 1980:
        year = 1980
    if year > 2030:
        year = 2030

    mileage_km = raw.get("mileage") or raw.get("mileage_km") or 0
    price_eur = raw.get("price") or raw.get("price_eur") or 0

    # Normalise to int — prices can arrive as strings in some schema variants
    try:
        mileage_km = int(mileage_km)
    except (TypeError, ValueError):
        mileage_km = 0
    try:
        price_eur = int(price_eur)
    except (TypeError, ValueError):
        price_eur = 0

    location = raw.get("location")
    country = raw.get("country")

    now = datetime.now(tz=UTC)

    try:
        return Listing(
            listing_id=str(listing_id),
            url=str(url),
            brand=str(brand),
            model=str(model),
            year=year,
            mileage_km=mileage_km,
            price_eur=price_eur,
            location=location,
            country=country,
            first_seen=now,
            last_seen=now,
            raw=raw,
        )
    except Exception:
        logger.debug("Failed to construct Listing from dict: id=%s", listing_id)
        return None


def parse_listings_page(data: dict[str, Any]) -> list[Listing]:
    """Parse a list of ``Listing`` objects from a search-page ``__NEXT_DATA__`` dict.

    Tries two known JSON paths in order:
    1. ``props.pageProps.listings``  (primary — used by the main search page layout)
    2. ``props.pageProps.initialState.search.results``  (fallback — older or A/B-tested layout)

    Parameters
    ----------
    data:
        Parsed ``__NEXT_DATA__`` dict from a search results page.

    Returns
    -------
    list[Listing]
        Parsed listings (may be empty if no path matched or listings array is empty).
    """
    page_props: dict[str, Any] = data.get("props", {}).get("pageProps", {})

    raw_listings: list[dict[str, Any]] | None = None
    matched_path: str = "<none>"

    # Path 1: direct listings array
    if "listings" in page_props and isinstance(page_props["listings"], list):
        raw_listings = page_props["listings"]
        matched_path = "props.pageProps.listings"

    # Path 2: initialState fallback
    if raw_listings is None:
        try:
            results = page_props.get("initialState", {}).get("search", {}).get("results")
            if isinstance(results, list):
                raw_listings = results
                matched_path = "props.pageProps.initialState.search.results"
        except (AttributeError, TypeError):
            pass

    if raw_listings is None:
        logger.warning("No listings path matched in __NEXT_DATA__")
        return []

    logger.debug("Listings found via path: %s (%d items)", matched_path, len(raw_listings))

    listings: list[Listing] = []
    for raw in raw_listings:
        listing = _listing_from_dict(raw)
        if listing is not None:
            listings.append(listing)

    return listings


def parse_listing_detail(data: dict[str, Any]) -> Listing:
    """Parse a single ``Listing`` from a detail-page ``__NEXT_DATA__`` dict.

    Reads from ``props.pageProps.listingDetails``.

    Parameters
    ----------
    data:
        Parsed ``__NEXT_DATA__`` dict from a listing detail page.

    Returns
    -------
    Listing
        The parsed listing.

    Raises
    ------
    KeyError
        If the ``listingDetails`` key is missing from the data.
    ValueError
        If required fields cannot be parsed.
    """
    page_props: dict[str, Any] = data.get("props", {}).get("pageProps", {})
    raw = page_props.get("listingDetails")
    if raw is None:
        raise KeyError("'listingDetails' not found in props.pageProps")

    listing = _listing_from_dict(raw)
    if listing is None:
        raise ValueError("Unable to construct Listing from listingDetails dict")
    return listing
