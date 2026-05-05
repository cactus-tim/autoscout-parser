"""Detail-page enrichment for AutoScout24 listings.

This module provides :func:`enrich_with_details`, which fetches the detail page
for each listing in sequence, parses the enrichment fields (equipment, colours,
upholstery), and mutates the input listings in place.

Features:
- Reuses a single :class:`~autoscout_pipeline.scraper.fetch.BrowserSession`
  across all listings to avoid per-listing browser startup cost.
- Per-listing exception handling: a single listing failure is logged as WARNING
  and the loop continues.
- Circuit breaker: 5 consecutive outer failures (each after tenacity's 3x
  internal retries) trigger an ERROR log and early loop exit.  Remaining
  listings keep their default empty ``equipment``/``None`` colour fields so
  scoring can still run on ``model_text`` fallback.
- Throttle: ``asyncio.sleep(random.uniform(throttle_min, throttle_max))`` after
  each listing, matching the search-page flow.
"""

from __future__ import annotations

import asyncio
import logging
import random

from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from autoscout_pipeline.models import Listing
from autoscout_pipeline.scraper.errors import NextDataMissingError
from autoscout_pipeline.scraper.fetch import BrowserSession
from autoscout_pipeline.scraper.parse import extract_next_data, parse_listing_detail

logger = logging.getLogger(__name__)

_CIRCUIT_BREAKER_THRESHOLD = 5

# Exception types that indicate a network/bot-block failure and therefore
# increment the circuit-breaker consecutive-failure counter.
_NETWORK_EXCEPTIONS = (NextDataMissingError, PlaywrightTimeoutError)


async def enrich_with_details(
    listings: list[Listing],
    throttle_min: float,
    throttle_max: float,
) -> list[Listing]:
    """Enrich a list of listings with detail-page fields (in place).

    Fetches the detail page for each listing, extracts ``__NEXT_DATA__``,
    parses enrichment fields (``equipment``, ``exterior_color``,
    ``interior_color``, ``upholstery``), and assigns them directly onto the
    input :class:`~autoscout_pipeline.models.Listing` objects.

    Parameters
    ----------
    listings:
        The list of listings to enrich.  Modified in place.  May be empty.
    throttle_min:
        Minimum seconds for the random throttle sleep between fetches.
    throttle_max:
        Maximum seconds for the random throttle sleep between fetches.

    Returns
    -------
    list[Listing]
        The **same** list object passed in (for call chaining), with
        enrichment fields mutated in place.

    Notes
    -----
    *Circuit breaker*: after :data:`_CIRCUIT_BREAKER_THRESHOLD` consecutive
    outer failures (i.e. network/bot-block exceptions after tenacity's
    internal retries are exhausted), the loop exits early and an ERROR is
    logged.  Listings not yet enriched keep default empty/``None`` fields so
    scoring still works via ``model_text`` fallback.

    *Non-network exceptions* (``ValueError``, ``KeyError``, etc.) are also
    caught and logged as WARNING but do **not** increment the consecutive
    failure counter.
    """
    if not listings:
        return listings

    n = len(listings)
    logger.info(
        "Enriching %d listings; expected ~%.0f-%.0fs at throttle %.1f-%.1fs",
        n,
        n * throttle_min,
        n * (throttle_max + 15),
        throttle_min,
        throttle_max,
    )

    consecutive_failures = 0

    async with BrowserSession() as session:
        for listing in listings:
            try:
                html = await session.fetch(listing.url)
                data = extract_next_data(html)
                enriched = parse_listing_detail(data)

                # Mutate in place: assign the four enrichment fields
                listing.equipment = enriched.equipment
                listing.exterior_color = enriched.exterior_color
                listing.interior_color = enriched.interior_color
                listing.upholstery = enriched.upholstery

                # Success — reset consecutive failure counter
                consecutive_failures = 0

            except _NETWORK_EXCEPTIONS as exc:
                # Network/bot-block failure — increment circuit breaker counter
                consecutive_failures += 1
                logger.warning(
                    "Enrichment failed for listing %s (%s: %s); consecutive_failures=%d",
                    listing.listing_id,
                    type(exc).__name__,
                    exc,
                    consecutive_failures,
                )

                if consecutive_failures >= _CIRCUIT_BREAKER_THRESHOLD:
                    logger.error(
                        "Circuit breaker tripped after %d consecutive enrichment failures; "
                        "aborting enrichment, scoring will run on un-enriched listings",
                        _CIRCUIT_BREAKER_THRESHOLD,
                    )
                    break

            except Exception as exc:
                # Non-network error (parse bug, KeyError, etc.) — log and skip
                # but do NOT increment the consecutive failure counter
                logger.warning(
                    "Enrichment failed for listing %s (%s: %s); skipping",
                    listing.listing_id,
                    type(exc).__name__,
                    exc,
                )

            finally:
                # Throttle between listings regardless of success/failure
                await asyncio.sleep(random.uniform(throttle_min, throttle_max))

    return listings
