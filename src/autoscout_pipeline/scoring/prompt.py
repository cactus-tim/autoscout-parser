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
        "You are an automotive expert evaluating a MINI Hatch listing against a "
        "specific buyer wishlist. Apply the brief's hard dealbreakers FIRST. "
        "Then look for the listed option keywords in the `model_text` field — "
        "German listings often abbreviate features (SHZ, Pano, HK, Leder). "
        "Cite the exact substring you found in your reasoning. Treat absence of "
        "a keyword as 'unknown', not 'absent', except for the hard dealbreakers "
        "which are based on dedicated fields (body_variant, fuel).\n\n"
        "HARD RULE: score=1 is ONLY allowed when at least one of the hard "
        "dealbreakers in the brief is concretely present (5-door body, "
        "electric fuel, manual transmission, or non-base Cooper variant). "
        "You MUST quote the exact field value that triggered the dealbreaker "
        "in your reasoning. If no dealbreaker applies, the score MUST be at "
        "least 4 (baseline). Never output score=1 'just to be safe' or for "
        "missing wishlist items.\n\n"
        "ROUNDING RULE: the final integer score is the FLOOR of (baseline + "
        "bonuses). NEVER round up. NEVER 'round to nearest'. Always truncate "
        "downward. Examples: 6.5 → 6 (NOT 7), 7.9 → 7 (NOT 8), 4.5 → 4 "
        "(NOT 5). Show the arithmetic in your reasoning so the floor step "
        "is visible (e.g. '4 + 2 + 0.5 = 6.5, floor → 6').\n\n"
        f"BRIEF:\n{brief}\n\n"
        "Return pros, cons, integer score 1-10, and 1-3 sentence reasoning.\n\n"
        "OUTPUT LANGUAGE: write reasoning, pros, and cons IN RUSSIAN. "
        "Keep the cited German/English substrings verbatim (e.g. 'PSD', 'Black', "
        "'Hellblau', 'SHZ') — quote them as-is inside the Russian sentences."
    )


def render_listing(listing: Listing) -> str:
    """Produce a human-readable text representation of a Listing for the LLM.

    Includes structured fields plus a few high-signal raw fields from the
    AutoScout24 search payload (``vehicle.variant``, ``vehicle.fuel``,
    ``vehicle.transmission``, ``vehicle.modelVersionInput``) that the brief
    relies on for dealbreaker detection and option keyword search.
    The full ``raw`` payload is NOT sent to the model.
    """
    raw = listing.raw or {}
    vehicle = raw.get("vehicle") if isinstance(raw.get("vehicle"), dict) else {}
    seller = raw.get("seller") if isinstance(raw.get("seller"), dict) else {}

    body_variant = vehicle.get("variant") or "unknown"
    fuel = vehicle.get("fuel") or "unknown"
    transmission = vehicle.get("transmission") or "unknown"
    # modelVersionInput is the free-text title the seller writes — it usually
    # contains German option abbreviations (SHZ, Pano, HK, Leder, Navi, …)
    model_text = vehicle.get("modelVersionInput") or vehicle.get("subtitle") or ""
    seller_type = seller.get("type") or "unknown"

    exterior_color = listing.exterior_color or "unknown"
    interior_color = listing.interior_color or "unknown"
    upholstery = listing.upholstery or "unknown"
    equipment_list = "; ".join(listing.equipment) if listing.equipment else "unknown"

    lines = [
        f"brand: {listing.brand}",
        f"model: {listing.model}",
        f"body_variant: {body_variant}",
        f"fuel: {fuel}",
        f"transmission: {transmission}",
        f"year: {listing.year}",
        f"mileage_km: {listing.mileage_km}",
        f"price_eur: {listing.price_eur}",
        f"location: {listing.location}",
        f"country: {listing.country}",
        f"seller_type: {seller_type}",
        f"exterior_color: {exterior_color}",
        f"interior_color: {interior_color}",
        f"upholstery: {upholstery}",
        f"equipment_list: {equipment_list}",
        f"model_text: {model_text}",
        f"url: {listing.url}",
    ]
    return "\n".join(lines)
