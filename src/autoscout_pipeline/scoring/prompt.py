"""Prompt assembly for the LLM scoring module.

Reads the user-configurable brief.md once per process via lru_cache,
then renders a Listing into a human-readable text block for the user
message (the raw field is intentionally excluded to avoid leaking internal
scrape state to the model).
"""

import functools
from pathlib import Path

from autoscout_pipeline.models import Listing


@functools.cache
def _read_brief_cached(path_str: str) -> str:
    """Read and cache brief file by its string path (one read per process)."""
    return Path(path_str).read_text(encoding="utf-8")


def load_brief(brief_path: Path) -> str:
    """Return the contents of brief_path, cached for the lifetime of the process."""
    return _read_brief_cached(str(brief_path))


def build_system_prompt(brief: str) -> str:
    """Build the full system message from the brief text."""
    return (
        "You are an automotive expert. Score the listing 1-10 according to this brief.\n\n"
        f"BRIEF:\n{brief}\n\n"
        "Return pros, cons, integer score 1-10, and 1-3 sentence reasoning."
    )


def render_listing(listing: Listing) -> str:
    """Produce a human-readable text representation of a Listing.

    The ``raw`` field is intentionally excluded — it contains scraper
    internals and should never be sent to the model.
    """
    lines = [
        f"brand: {listing.brand}",
        f"model: {listing.model}",
        f"year: {listing.year}",
        f"mileage_km: {listing.mileage_km}",
        f"price_eur: {listing.price_eur}",
        f"location: {listing.location}",
        f"country: {listing.country}",
        f"url: {listing.url}",
    ]
    return "\n".join(lines)
