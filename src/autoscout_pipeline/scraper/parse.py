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


_BASE_URL = "https://www.autoscout24.com"


def _parse_year(raw: str | int | None) -> int:
    """Parse a year from various AutoScout24 date formats."""
    if raw is None:
        return 2000
    if isinstance(raw, int):
        return raw
    s = str(raw).strip()
    # Handles "2020-06", "2020", "2020-06-01", "11/2021", etc.
    if not s:
        return 2000
    # MM/YYYY
    if "/" in s:
        last = s.split("/")[-1]
        if last.isdigit():
            return int(last)
    # ISO-like prefix
    head = s.split("-")[0]
    if head.isdigit():
        return int(head)
    # Trailing 4-digit year
    import re

    m = re.search(r"(19|20)\d{2}", s)
    if m:
        return int(m.group(0))
    return 2000


def _parse_int(raw: Any, default: int = 0) -> int:
    """Parse an int from int/float/str (e.g. ``"29,000 km"``, ``"€ 16,950"``)."""
    if raw is None:
        return default
    if isinstance(raw, bool):
        return int(raw)
    if isinstance(raw, (int, float)):
        return int(raw)
    s = str(raw)
    digits = "".join(ch for ch in s if ch.isdigit())
    if not digits:
        return default
    return int(digits)


def _listing_from_dict(raw: dict[str, Any]) -> Listing | None:
    """Build a ``Listing`` from a raw AutoScout24 listing dict.

    Tolerates two on-the-wire schemas:

    1. **Flat (legacy)** — top-level ``make``/``model``/``mileage``/``price``/``year``.
    2. **Nested (current)** — ``vehicle.{make,model,mileageInKm}`` plus
       ``price.priceFormatted`` (e.g. ``"€ 16,950"``) and
       ``vehicleDetails[*].ariaLabel == "First registration"`` carrying the date.

    Returns ``None`` only if no listing identifier can be found.
    """
    listing_id = raw.get("id") or raw.get("listing_id")
    if not listing_id:
        return None

    vehicle = raw.get("vehicle") or {}
    if not isinstance(vehicle, dict):
        vehicle = {}

    # URL: relative paths get prefixed with the AS24 base
    url = raw.get("url") or ""
    if isinstance(url, str) and url.startswith("/"):
        url = _BASE_URL + url

    brand = raw.get("make") or vehicle.get("make") or ""
    model = raw.get("model") or vehicle.get("model") or ""

    # Year — try several sources, including the iconified vehicleDetails list
    year_raw = (
        raw.get("firstRegistrationDate") or raw.get("year") or vehicle.get("firstRegistrationDate")
    )
    if not year_raw:
        for det in raw.get("vehicleDetails") or []:
            if isinstance(det, dict) and det.get("ariaLabel") == "First registration":
                year_raw = det.get("data")
                break
    year = _parse_year(year_raw)
    if year < 1980:
        year = 1980
    if year > 2030:
        year = 2030

    # Mileage — flat int or "29,000 km" string under vehicle / vehicleDetails
    mileage_raw = raw.get("mileage") or raw.get("mileage_km") or vehicle.get("mileageInKm")
    if not mileage_raw:
        for det in raw.get("vehicleDetails") or []:
            if isinstance(det, dict) and det.get("ariaLabel") == "Mileage":
                mileage_raw = det.get("data")
                break
    mileage_km = _parse_int(mileage_raw, 0)

    # Price — flat int or {"priceFormatted": "€ 16,950"}
    price_raw = raw.get("price") if not isinstance(raw.get("price"), dict) else None
    if price_raw is None:
        price_raw = raw.get("price_eur")
    if price_raw is None and isinstance(raw.get("price"), dict):
        price_raw = raw["price"].get("priceFormatted") or raw["price"].get("amount")
    price_eur = _parse_int(price_raw, 0)

    # Location / country — flat string OR {"city": ..., "countryCode": ...}
    loc = raw.get("location")
    country = raw.get("country")
    if isinstance(loc, dict):
        country = country or loc.get("countryCode")
        city = loc.get("city")
        zip_code = loc.get("zip")
        location = ", ".join(p for p in [zip_code, city] if p) or None
    else:
        location = loc

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
    except Exception as exc:
        logger.debug("Failed to construct Listing from dict: id=%s err=%s", listing_id, exc)
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


def _flatten_equipment(raw: Any) -> list[str]:
    """Flatten the AS24 equipment value to a plain ``list[str]``.

    AutoScout24 uses a **dict-of-categories** shape (as of 2026-05-05):

    .. code-block:: json

        {
          "comfortAndConvenience": [
            {"id": "Automatic climate control, 2 zones", "categoryName": "...", "categoryId": "..."},
            ...
          ],
          "entertainmentAndMedia": [...],
          "extras": [...],
          "safetyAndSecurity": [...]
        }

    Each category value is a list of dicts with an ``id`` key containing the
    human-readable feature name.

    Handled input shapes (robust to schema drift):

    * ``None`` or falsy → return ``[]``
    * ``dict`` (categories → list-of-dicts-with-id)  → flatten all ``.id`` values (primary)
    * ``dict`` (categories → list-of-str)             → flatten all strings (fallback)
    * ``list[str]``                                   → return as-is (pass-through)
    * ``list[dict]`` with ``"items"`` sub-key         → flatten ``.items[*].id`` values
    * ``list[dict]`` with ``"id"`` key                → collect ``.id`` values directly
    * any other shape                                 → return ``[]`` (log a warning)

    JSON path (detail page):
        ``props.pageProps.listingDetails.vehicle.equipment``
    """
    if not raw:
        return []

    # Primary shape: dict-of-categories → list-of-dicts-with-id
    if isinstance(raw, dict):
        result: list[str] = []
        for category_list in raw.values():
            if not isinstance(category_list, list):
                continue
            for item in category_list:
                if isinstance(item, dict):
                    # Preferred: item["id"] is the feature label string
                    id_val = item.get("id")
                    if id_val and isinstance(id_val, str):
                        result.append(id_val)
                elif isinstance(item, str):
                    # Fallback: plain string inside category list
                    if item:
                        result.append(item)
        return result

    # Flat list passthrough
    if isinstance(raw, list):
        # list[str] passthrough
        if all(isinstance(x, str) for x in raw):
            return [x for x in raw if x]

        # list[dict] — check for items sub-key (another possible AS24 shape)
        result = []
        for item in raw:
            if isinstance(item, dict):
                # Shape: {"items": [{"id": "..."}]}
                sub_items = item.get("items")
                if isinstance(sub_items, list):
                    for sub in sub_items:
                        if isinstance(sub, dict):
                            id_val = sub.get("id")
                            if id_val and isinstance(id_val, str):
                                result.append(id_val)
                        elif isinstance(sub, str) and sub:
                            result.append(sub)
                else:
                    # Shape: {"id": "..."}
                    id_val = item.get("id")
                    if id_val and isinstance(id_val, str):
                        result.append(id_val)
        if result:
            return result

        # Unknown list shape — log and return empty
        logger.debug("_flatten_equipment: unrecognised list shape, returning empty")
        return []

    logger.debug(
        "_flatten_equipment: unrecognised raw type %s, returning empty", type(raw).__name__
    )
    return []


def parse_listing_detail(data: dict[str, Any]) -> Listing:
    """Parse a single ``Listing`` from a detail-page ``__NEXT_DATA__`` dict.

    Reads from ``props.pageProps.listingDetails``.  Enrichment fields
    (``equipment``, ``exterior_color``, ``interior_color``, ``upholstery``)
    are populated from the ``vehicle`` sub-object using the schema captured on
    2026-05-05 (see recon-notes.md).

    JSON paths for enrichment fields:
        - equipment:       ``listingDetails.vehicle.equipment``  (dict-of-categories)
        - exterior_color:  ``listingDetails.vehicle.bodyColor``  (string)
        - interior_color:  ``listingDetails.vehicle.upholsteryColor``  (string, NOT interiorColor)
        - upholstery:      ``listingDetails.vehicle.upholstery``  (string, e.g. "Cloth")

    Parameters
    ----------
    data:
        Parsed ``__NEXT_DATA__`` dict from a listing detail page.

    Returns
    -------
    Listing
        The parsed listing.  Missing enrichment fields default to ``[]`` / ``None``.

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

    # Enrich with detail-page-only fields from vehicle sub-object
    vehicle: dict[str, Any] = raw.get("vehicle") or {}
    if not isinstance(vehicle, dict):
        vehicle = {}

    # URL: the detail page stores the canonical URL at listingDetails.webPage
    # (the "url" key is absent in the live detail schema).
    # Fall back to webPage if _listing_from_dict left url empty.
    url = listing.url
    if not url:
        web_page = raw.get("webPage") or ""
        if isinstance(web_page, str) and web_page:
            url = web_page

    # equipment: vehicle.equipment (dict-of-categories shape)
    equipment = _flatten_equipment(vehicle.get("equipment"))

    # exterior_color: vehicle.bodyColor (normalised colour string)
    exterior_color_raw = vehicle.get("bodyColor")
    exterior_color = str(exterior_color_raw) if exterior_color_raw is not None else None

    # interior_color: vehicle.upholsteryColor (NOTE: not interiorColor / interior)
    interior_color_raw = vehicle.get("upholsteryColor")
    interior_color = str(interior_color_raw) if interior_color_raw is not None else None

    # upholstery: vehicle.upholstery (material type, e.g. "Cloth", "Leather")
    upholstery_raw = vehicle.get("upholstery")
    upholstery = str(upholstery_raw) if upholstery_raw is not None else None

    return listing.model_copy(
        update={
            "url": url,
            "equipment": equipment,
            "exterior_color": exterior_color,
            "interior_color": interior_color,
            "upholstery": upholstery,
        }
    )
