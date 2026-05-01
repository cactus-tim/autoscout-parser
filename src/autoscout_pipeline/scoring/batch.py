"""Concurrent scoring of multiple listings using asyncio.Semaphore."""

import asyncio
import datetime as dt

from autoscout_pipeline.models import Listing, ScoredListing
from autoscout_pipeline.scoring.scorer import LLMScorer


async def score_many(
    scorer: LLMScorer,
    listings: list[Listing],
    concurrency: int = 5,
) -> list[ScoredListing]:
    """Score *listings* in parallel, capping in-flight requests at *concurrency*.

    Returns a list of ScoredListing with NESTED layout:
        result[i].listing   — the original Listing
        result[i].score     — the LLM-produced ListingScore
        result[i].scored_at — UTC datetime of scoring
    """
    semaphore = asyncio.Semaphore(concurrency)

    async def _score_one(listing: Listing) -> ScoredListing:
        async with semaphore:
            listing_score = await scorer.score(listing)
        return ScoredListing(
            listing=listing,
            score=listing_score,
            scored_at=dt.datetime.now(dt.UTC),
        )

    return list(await asyncio.gather(*(_score_one(item) for item in listings)))
