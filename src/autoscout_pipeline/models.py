"""Canonical data models for the AutoScout24 pipeline.

All models use Pydantic v2. Datetimes are always timezone-aware UTC.
ScoredListing uses NESTED composition: s.listing (Listing), s.score (ListingScore),
s.scored_at (datetime). Access pattern: s.listing.price_eur, s.score.score.
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def _require_tz_aware(dt: datetime) -> datetime:
    """Raise ValueError if dt has no tzinfo (naive datetime)."""
    if dt.tzinfo is None:
        raise ValueError("datetime must be timezone-aware (UTC required)")
    return dt


class Listing(BaseModel):
    """A single AutoScout24 car listing parsed from __NEXT_DATA__."""

    model_config = ConfigDict(extra="ignore")

    listing_id: str
    url: str
    brand: str
    model: str
    year: int = Field(..., ge=1980, le=2030)
    mileage_km: int = Field(..., ge=0)
    price_eur: int = Field(..., ge=0)
    location: str | None = None
    country: str | None = None
    first_seen: datetime
    last_seen: datetime
    raw: dict[str, Any] | None = None

    # Optional enrichment fields populated from the detail page (Step 2).
    # transmission is intentionally absent — it is read from raw["vehicle"]["transmission"].
    equipment: list[str] = Field(default_factory=list)
    exterior_color: str | None = None
    interior_color: str | None = None
    upholstery: str | None = None

    @field_validator("first_seen", "last_seen", mode="after")
    @classmethod
    def _first_last_seen_tz_aware(cls, v: datetime) -> datetime:
        return _require_tz_aware(v)


class ListingScore(BaseModel):
    """LLM-generated quality score for a single listing."""

    model_config = ConfigDict(extra="ignore")

    score: int = Field(..., ge=1, le=10)
    reasoning: str = Field(..., min_length=1)
    pros: list[str] = Field(default_factory=list)
    cons: list[str] = Field(default_factory=list)


class ScoredListing(BaseModel):
    """NESTED composition of a Listing and its ListingScore.

    Access pattern:
        s.listing.price_eur
        s.score.score
        s.scored_at
    """

    model_config = ConfigDict(extra="ignore")

    listing: Listing
    score: ListingScore
    scored_at: datetime

    @field_validator("scored_at", mode="after")
    @classmethod
    def _scored_at_tz_aware(cls, v: datetime) -> datetime:
        return _require_tz_aware(v)


class PriceChange(BaseModel):
    """Records a price change event for a listing."""

    model_config = ConfigDict(extra="ignore")

    listing_id: str
    changed_at: datetime
    old_price: int
    new_price: int

    @field_validator("changed_at", mode="after")
    @classmethod
    def _changed_at_tz_aware(cls, v: datetime) -> datetime:
        return _require_tz_aware(v)

    @model_validator(mode="after")
    def _prices_must_differ(self) -> "PriceChange":
        if self.old_price == self.new_price:
            raise ValueError(f"old_price and new_price must differ (both are {self.old_price})")
        return self


class RunRecord(BaseModel):
    """Summary record written after each pipeline run."""

    model_config = ConfigDict(extra="ignore")

    run_at: datetime
    new_count: int
    updated_count: int
    removed_count: int
    errors: int
    notes: str

    @field_validator("run_at", mode="after")
    @classmethod
    def _run_at_tz_aware(cls, v: datetime) -> datetime:
        return _require_tz_aware(v)

    @field_validator("notes", mode="before")
    @classmethod
    def _truncate_notes(cls, v: str) -> str:
        if isinstance(v, str) and len(v) > 500:
            return v[:500]
        return v


__all__ = [
    "Listing",
    "ListingScore",
    "PriceChange",
    "RunRecord",
    "ScoredListing",
]
