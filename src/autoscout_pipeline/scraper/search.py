"""AutoScout24 search URL builder and async listing iterator.

URL Template (discovered 2026-05-01)
-------------------------------------
AutoScout24 search pages use the following URL structure::

    https://www.autoscout24.com/lst/{make}/{model}?{params}

Where ``{make}`` and ``{model}`` are lowercase slugs (e.g. ``mini/mini``),
and ``{params}`` is a query string with the following documented parameters:

    atype   - Asset type. Use ``C`` for cars.
    cy      - Country codes (comma-separated). E.g. ``D,A,CH`` for Germany,
              Austria, Switzerland.
    sort    - Sort order. ``age`` = newest first; ``standard`` = relevance.
    desc    - Sort direction. ``0`` = ascending, ``1`` = descending.
    ustate  - Vehicle state. ``N,U`` = new and used.
    page    - Page number (1-based; AutoScout24 returns up to 20 results/page,
              max 20 pages = 400 listings per query).
    priceto - Maximum price in EUR (raw integer, e.g. ``23000``).
    kmfrom  - Minimum mileage in km (raw integer, e.g. ``20000``).
    kmto    - Maximum mileage in km (raw integer, e.g. ``30000``).
    fregfrom- Minimum first registration year (integer, e.g. ``2018``).
    fregto  - Maximum first registration year (integer, e.g. ``2023``).

Note on bucket codes
~~~~~~~~~~~~~~~~~~~~~
Unlike some older AutoScout24 API endpoints where ``miles`` and ``price``
used coded bucket identifiers (e.g. ``miles=2,3``), the current /lst search
endpoint (verified 2026-05-01) accepts **raw integer values** for ``kmfrom``,
``kmto``, and ``priceto``. If the site is updated to use bucket codes again,
the URL builder will need to be updated accordingly and ``EmptyResultsError``
will surface the issue at runtime (no listings returned silently).

MINI Hatch model codes
~~~~~~~~~~~~~~~~~~~~~~~~
MINI Hatch 3-door and 5-door are both listed under make=``mini`` model=``mini``
on autoscout24.com (path: /lst/mini/mini). There is no separate model code
for the 3-door vs 5-door variant in the URL path; the body type filter
(``body=3`` for hatchback) can be added to further narrow results.
Discovery date: 2026-05-01.
"""

from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import AsyncGenerator
from urllib.parse import urlencode, urljoin

from autoscout_pipeline.models import Listing
from autoscout_pipeline.scraper.errors import EmptyResultsError
from autoscout_pipeline.scraper.fetch import fetch_page_html
from autoscout_pipeline.scraper.parse import extract_next_data, parse_listings_page

logger = logging.getLogger(__name__)

_BASE_URL = "https://www.autoscout24.com"
_SEARCH_PATH = "/lst/{make}/{model}"


def build_search_url(criteria: dict, page: int = 1) -> str:
    """Build an AutoScout24 search URL from *criteria* and a page number.

    Parameters
    ----------
    criteria:
        A dict of search parameters. Recognised keys:

        - ``make`` (str): Car make slug, e.g. ``"mini"``.
        - ``model`` (str): Car model slug, e.g. ``"mini"``.
        - ``priceto`` (int): Maximum price in EUR.
        - ``kmfrom`` (int): Minimum mileage in km.
        - ``kmto`` (int): Maximum mileage in km.
        - ``cy`` (str): Comma-separated country codes, e.g. ``"D,A,CH"``.
        - ``atype`` (str): Asset type (default ``"C"`` for cars).
        - ``fregfrom`` (int): Minimum first registration year.
        - ``fregto`` (int): Maximum first registration year.
        - ``sort`` (str): Sort field (default ``"standard"``).
        - ``desc`` (int): Sort direction; ``0`` = asc, ``1`` = desc.
        - ``ustate`` (str): Vehicle state (default ``"N,U"``).

    page:
        1-based page number.

    Returns
    -------
    str
        The fully-qualified search URL including query string.
    """
    make = criteria.get("make", "mini").lower()
    model = criteria.get("model", "mini").lower()

    path = _SEARCH_PATH.format(make=make, model=model)

    params: dict[str, str | int] = {}

    # Fixed defaults
    params["atype"] = criteria.get("atype", "C")
    params["sort"] = criteria.get("sort", "standard")
    params["desc"] = criteria.get("desc", 0)
    params["ustate"] = criteria.get("ustate", "N,U")

    # Country
    if "cy" in criteria:
        params["cy"] = criteria["cy"]

    # Price filter
    if "priceto" in criteria:
        params["priceto"] = criteria["priceto"]
    if "pricefrom" in criteria:
        params["pricefrom"] = criteria["pricefrom"]

    # Mileage filter
    if "kmfrom" in criteria:
        params["kmfrom"] = criteria["kmfrom"]
    if "kmto" in criteria:
        params["kmto"] = criteria["kmto"]

    # Year filter
    if "fregfrom" in criteria:
        params["fregfrom"] = criteria["fregfrom"]
    if "fregto" in criteria:
        params["fregto"] = criteria["fregto"]

    # Pagination — always last for readability
    params["page"] = page

    query = urlencode(params)
    return urljoin(_BASE_URL, path) + "?" + query


async def iter_listings(
    criteria: dict,
    max_pages: int = 20,
    throttle_min: float = 2.0,
    throttle_max: float = 6.0,
) -> AsyncGenerator[Listing, None]:
    """Async generator that yields ``Listing`` objects from AutoScout24 search pages.

    Iterates through pages 1..``max_pages``, stopping early when a page returns
    an empty listings array. A polite random sleep between pages uses
    ``AS24_THROTTLE_MIN`` / ``AS24_THROTTLE_MAX`` from config (or the parameters
    passed directly here for testability).

    Parameters
    ----------
    criteria:
        Search criteria dict passed to :func:`build_search_url`.
    max_pages:
        Maximum number of pages to fetch (default 20, i.e. up to 400 listings).
    throttle_min:
        Minimum sleep seconds between page requests.
    throttle_max:
        Maximum sleep seconds between page requests.

    Yields
    ------
    Listing
        Individual parsed listings.

    Raises
    ------
    EmptyResultsError
        If the very first page returns an empty listings array.
    """
    for page_num in range(1, max_pages + 1):
        url = build_search_url(criteria, page=page_num)
        logger.info("Fetching page %d: %s", page_num, url)

        html = await fetch_page_html(url)
        data = extract_next_data(html)
        listings = parse_listings_page(data)

        if not listings:
            if page_num == 1:
                raise EmptyResultsError(
                    f"No listings returned on page 1 for URL: {url}. "
                    "Check that the search criteria and URL parameters are correct."
                )
            logger.info("Page %d returned no listings — stopping iteration", page_num)
            break

        logger.info("Page %d: %d listings", page_num, len(listings))
        for listing in listings:
            yield listing

        if page_num < max_pages:
            sleep_secs = random.uniform(throttle_min, throttle_max)
            logger.debug("Throttle: sleeping %.1f s before page %d", sleep_secs, page_num + 1)
            await asyncio.sleep(sleep_secs)
