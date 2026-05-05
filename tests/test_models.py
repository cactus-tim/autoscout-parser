"""Tests for autoscout_pipeline.models — Phase 2, Step 2.2.

Covers:
- Listing round-trip from dict (raw preserved)
- ListingScore validators: score range 1..10, pros/cons lists, reasoning non-empty
- ScoredListing NESTED composition
- PriceChange rejects equal prices
- RunRecord truncates notes to 500 chars
- All datetimes are timezone-aware UTC
"""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from autoscout_pipeline.models import (
    Listing,
    ListingScore,
    PriceChange,
    RunRecord,
    ScoredListing,
)

# ---------------------------------------------------------------------------
# Shared helpers / fixtures
# ---------------------------------------------------------------------------

NOW_UTC = datetime(2026, 5, 1, 12, 0, 0, tzinfo=UTC)


def make_listing(**overrides) -> dict:
    base = {
        "listing_id": "abc123",
        "url": "https://www.autoscout24.com/listings/abc123",
        "brand": "MINI",
        "model": "Hatch",
        "year": 2021,
        "mileage_km": 25000,
        "price_eur": 18500,
        "location": "Munich",
        "country": "DE",
        "first_seen": NOW_UTC,
        "last_seen": NOW_UTC,
    }
    base.update(overrides)
    return base


def make_listing_score(**overrides) -> dict:
    base = {
        "score": 7,
        "reasoning": "Good condition, fair price.",
        "pros": ["Low mileage", "One owner"],
        "cons": ["No sunroof"],
    }
    base.update(overrides)
    return base


def make_scored_listing(**overrides) -> dict:
    base = {
        "listing": make_listing(),
        "score": make_listing_score(),
        "scored_at": NOW_UTC,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Listing tests
# ---------------------------------------------------------------------------


class TestListing:
    def test_round_trip_from_dict(self):
        data = make_listing()
        listing = Listing.model_validate(data)
        assert listing.listing_id == "abc123"
        assert listing.brand == "MINI"
        assert listing.model == "Hatch"
        assert listing.year == 2021
        assert listing.mileage_km == 25000
        assert listing.price_eur == 18500

    def test_raw_field_defaults_to_none(self):
        listing = Listing.model_validate(make_listing())
        assert listing.raw is None

    def test_raw_field_preserved_from_dict(self):
        raw_data = {"id": "xyz", "some_next_js_key": "some_value", "nested": {"a": 1}}
        data = make_listing(raw=raw_data)
        listing = Listing.model_validate(data)
        assert listing.raw == raw_data

    def test_first_seen_is_tz_aware(self):
        listing = Listing.model_validate(make_listing())
        assert listing.first_seen.tzinfo is not None

    def test_last_seen_is_tz_aware(self):
        listing = Listing.model_validate(make_listing())
        assert listing.last_seen.tzinfo is not None

    def test_rejects_naive_first_seen(self):
        naive_dt = datetime(2026, 5, 1, 12, 0, 0)  # no tzinfo
        with pytest.raises(ValidationError):
            Listing.model_validate(make_listing(first_seen=naive_dt))

    def test_rejects_naive_last_seen(self):
        naive_dt = datetime(2026, 5, 1, 12, 0, 0)
        with pytest.raises(ValidationError):
            Listing.model_validate(make_listing(last_seen=naive_dt))

    def test_year_lower_bound(self):
        with pytest.raises(ValidationError):
            Listing.model_validate(make_listing(year=1979))

    def test_year_upper_bound(self):
        with pytest.raises(ValidationError):
            Listing.model_validate(make_listing(year=2031))

    def test_year_boundary_accepted(self):
        listing = Listing.model_validate(make_listing(year=1980))
        assert listing.year == 1980
        listing2 = Listing.model_validate(make_listing(year=2030))
        assert listing2.year == 2030

    def test_mileage_km_rejects_negative(self):
        with pytest.raises(ValidationError):
            Listing.model_validate(make_listing(mileage_km=-1))

    def test_price_eur_rejects_negative(self):
        with pytest.raises(ValidationError):
            Listing.model_validate(make_listing(price_eur=-1))

    def test_location_and_country_are_optional(self):
        listing = Listing.model_validate(make_listing(location=None, country=None))
        assert listing.location is None
        assert listing.country is None


# ---------------------------------------------------------------------------
# ListingScore tests
# ---------------------------------------------------------------------------


class TestListingScore:
    def test_valid_score_accepted(self):
        score = ListingScore.model_validate(make_listing_score(score=5))
        assert score.score == 5

    def test_score_boundary_1_accepted(self):
        score = ListingScore.model_validate(make_listing_score(score=1))
        assert score.score == 1

    def test_score_boundary_10_accepted(self):
        score = ListingScore.model_validate(make_listing_score(score=10))
        assert score.score == 10

    def test_score_0_rejected(self):
        with pytest.raises(ValidationError):
            ListingScore.model_validate(make_listing_score(score=0))

    def test_score_11_rejected(self):
        with pytest.raises(ValidationError):
            ListingScore.model_validate(make_listing_score(score=11))

    def test_score_negative_rejected(self):
        with pytest.raises(ValidationError):
            ListingScore.model_validate(make_listing_score(score=-1))

    def test_pros_is_list_of_str(self):
        score = ListingScore.model_validate(make_listing_score(pros=["a", "b"]))
        assert isinstance(score.pros, list)
        assert all(isinstance(p, str) for p in score.pros)

    def test_cons_is_list_of_str(self):
        score = ListingScore.model_validate(make_listing_score(cons=["x"]))
        assert isinstance(score.cons, list)

    def test_empty_pros_and_cons_accepted(self):
        score = ListingScore.model_validate(make_listing_score(pros=[], cons=[]))
        assert score.pros == []
        assert score.cons == []

    def test_reasoning_empty_string_rejected(self):
        with pytest.raises(ValidationError):
            ListingScore.model_validate(make_listing_score(reasoning=""))

    def test_reasoning_non_empty_accepted(self):
        score = ListingScore.model_validate(make_listing_score(reasoning="Good car."))
        assert score.reasoning == "Good car."


# ---------------------------------------------------------------------------
# ScoredListing tests — NESTED composition
# ---------------------------------------------------------------------------


class TestScoredListing:
    def test_nested_listing_is_listing_instance(self):
        sl = ScoredListing.model_validate(make_scored_listing())
        assert isinstance(sl.listing, Listing)

    def test_nested_score_is_listing_score_instance(self):
        sl = ScoredListing.model_validate(make_scored_listing())
        assert isinstance(sl.score, ListingScore)

    def test_scored_at_is_tz_aware(self):
        sl = ScoredListing.model_validate(make_scored_listing())
        assert sl.scored_at.tzinfo is not None

    def test_rejects_naive_scored_at(self):
        naive_dt = datetime(2026, 5, 1, 12, 0, 0)
        with pytest.raises(ValidationError):
            ScoredListing.model_validate(make_scored_listing(scored_at=naive_dt))

    def test_nested_access_s_listing_price_eur(self):
        sl = ScoredListing.model_validate(make_scored_listing())
        assert sl.listing.price_eur == 18500

    def test_nested_access_s_score_score(self):
        sl = ScoredListing.model_validate(make_scored_listing())
        assert sl.score.score == 7

    def test_nested_access_s_listing_brand(self):
        sl = ScoredListing.model_validate(make_scored_listing())
        assert sl.listing.brand == "MINI"

    def test_round_trip_serialization(self):
        sl = ScoredListing.model_validate(make_scored_listing())
        dumped = sl.model_dump()
        # Re-instantiate from dumped dict should work
        sl2 = ScoredListing.model_validate(dumped)
        assert sl2.listing.listing_id == sl.listing.listing_id
        assert sl2.score.score == sl.score.score


# ---------------------------------------------------------------------------
# PriceChange tests
# ---------------------------------------------------------------------------


class TestPriceChange:
    def test_valid_price_change_accepted(self):
        pc = PriceChange.model_validate(
            {
                "listing_id": "abc123",
                "changed_at": NOW_UTC,
                "old_price": 20000,
                "new_price": 18500,
            }
        )
        assert pc.old_price == 20000
        assert pc.new_price == 18500

    def test_equal_prices_rejected(self):
        with pytest.raises(ValidationError):
            PriceChange.model_validate(
                {
                    "listing_id": "abc123",
                    "changed_at": NOW_UTC,
                    "old_price": 18500,
                    "new_price": 18500,
                }
            )

    def test_changed_at_is_tz_aware(self):
        pc = PriceChange.model_validate(
            {
                "listing_id": "abc123",
                "changed_at": NOW_UTC,
                "old_price": 20000,
                "new_price": 18000,
            }
        )
        assert pc.changed_at.tzinfo is not None

    def test_rejects_naive_changed_at(self):
        naive_dt = datetime(2026, 5, 1, 12, 0, 0)
        with pytest.raises(ValidationError):
            PriceChange.model_validate(
                {
                    "listing_id": "abc123",
                    "changed_at": naive_dt,
                    "old_price": 20000,
                    "new_price": 18000,
                }
            )

    def test_price_increase_accepted(self):
        pc = PriceChange.model_validate(
            {
                "listing_id": "abc123",
                "changed_at": NOW_UTC,
                "old_price": 16000,
                "new_price": 18000,
            }
        )
        assert pc.new_price > pc.old_price


# ---------------------------------------------------------------------------
# RunRecord tests
# ---------------------------------------------------------------------------


class TestRunRecord:
    def test_notes_truncated_to_500_chars(self):
        long_notes = "x" * 600
        record = RunRecord.model_validate(
            {
                "run_at": NOW_UTC,
                "new_count": 5,
                "updated_count": 2,
                "removed_count": 1,
                "errors": 0,
                "notes": long_notes,
            }
        )
        assert len(record.notes) == 500

    def test_notes_under_500_unchanged(self):
        short_notes = "All good."
        record = RunRecord.model_validate(
            {
                "run_at": NOW_UTC,
                "new_count": 5,
                "updated_count": 2,
                "removed_count": 1,
                "errors": 0,
                "notes": short_notes,
            }
        )
        assert record.notes == short_notes

    def test_notes_exactly_500_unchanged(self):
        exact_notes = "y" * 500
        record = RunRecord.model_validate(
            {
                "run_at": NOW_UTC,
                "new_count": 5,
                "updated_count": 2,
                "removed_count": 1,
                "errors": 0,
                "notes": exact_notes,
            }
        )
        assert len(record.notes) == 500
        assert record.notes == exact_notes

    def test_run_at_is_tz_aware(self):
        record = RunRecord.model_validate(
            {
                "run_at": NOW_UTC,
                "new_count": 0,
                "updated_count": 0,
                "removed_count": 0,
                "errors": 0,
                "notes": "",
            }
        )
        assert record.run_at.tzinfo is not None

    def test_rejects_naive_run_at(self):
        naive_dt = datetime(2026, 5, 1, 12, 0, 0)
        with pytest.raises(ValidationError):
            RunRecord.model_validate(
                {
                    "run_at": naive_dt,
                    "new_count": 0,
                    "updated_count": 0,
                    "removed_count": 0,
                    "errors": 0,
                    "notes": "",
                }
            )

    def test_counts_accept_zero(self):
        record = RunRecord.model_validate(
            {
                "run_at": NOW_UTC,
                "new_count": 0,
                "updated_count": 0,
                "removed_count": 0,
                "errors": 0,
                "notes": "Clean run.",
            }
        )
        assert record.new_count == 0
        assert record.errors == 0


# ---------------------------------------------------------------------------
# Listing enrichment fields tests
# ---------------------------------------------------------------------------


class TestListingEnrichmentFields:
    """Tests for the four optional enrichment fields added in Step 2."""

    def test_equipment_defaults_to_empty_list(self):
        listing = Listing.model_validate(make_listing())
        assert listing.equipment == []

    def test_exterior_color_defaults_to_none(self):
        listing = Listing.model_validate(make_listing())
        assert listing.exterior_color is None

    def test_interior_color_defaults_to_none(self):
        listing = Listing.model_validate(make_listing())
        assert listing.interior_color is None

    def test_upholstery_defaults_to_none(self):
        listing = Listing.model_validate(make_listing())
        assert listing.upholstery is None

    def test_equipment_can_be_populated(self):
        listing = Listing.model_validate(
            make_listing(equipment=["Klimaanlage", "SHZ", "Navi"])
        )
        assert listing.equipment == ["Klimaanlage", "SHZ", "Navi"]

    def test_equipment_populated_is_list_of_str(self):
        listing = Listing.model_validate(
            make_listing(equipment=["DAB", "PDC"])
        )
        assert isinstance(listing.equipment, list)
        assert all(isinstance(item, str) for item in listing.equipment)

    def test_equipment_empty_list_accepted(self):
        listing = Listing.model_validate(make_listing(equipment=[]))
        assert listing.equipment == []

    def test_exterior_color_can_be_string(self):
        listing = Listing.model_validate(make_listing(exterior_color="Hellblau"))
        assert listing.exterior_color == "Hellblau"

    def test_exterior_color_can_be_none(self):
        listing = Listing.model_validate(make_listing(exterior_color=None))
        assert listing.exterior_color is None

    def test_interior_color_can_be_string(self):
        listing = Listing.model_validate(make_listing(interior_color="Black"))
        assert listing.interior_color == "Black"

    def test_interior_color_can_be_none(self):
        listing = Listing.model_validate(make_listing(interior_color=None))
        assert listing.interior_color is None

    def test_upholstery_can_be_string(self):
        listing = Listing.model_validate(make_listing(upholstery="Leather"))
        assert listing.upholstery == "Leather"

    def test_upholstery_can_be_none(self):
        listing = Listing.model_validate(make_listing(upholstery=None))
        assert listing.upholstery is None

    def test_model_dump_round_trip_preserves_equipment(self):
        original = Listing.model_validate(
            make_listing(equipment=["Klimaanlage", "SHZ"])
        )
        dumped = original.model_dump()
        restored = Listing.model_validate(dumped)
        assert restored.equipment == ["Klimaanlage", "SHZ"]

    def test_model_dump_round_trip_preserves_exterior_color(self):
        original = Listing.model_validate(make_listing(exterior_color="Island Blue"))
        dumped = original.model_dump()
        restored = Listing.model_validate(dumped)
        assert restored.exterior_color == "Island Blue"

    def test_model_dump_round_trip_preserves_interior_color(self):
        original = Listing.model_validate(make_listing(interior_color="Carbon Black"))
        dumped = original.model_dump()
        restored = Listing.model_validate(dumped)
        assert restored.interior_color == "Carbon Black"

    def test_model_dump_round_trip_preserves_upholstery(self):
        original = Listing.model_validate(make_listing(upholstery="Cloth"))
        dumped = original.model_dump()
        restored = Listing.model_validate(dumped)
        assert restored.upholstery == "Cloth"

    def test_model_dump_includes_none_color_fields(self):
        listing = Listing.model_validate(make_listing())
        dumped = listing.model_dump()
        assert "exterior_color" in dumped
        assert "interior_color" in dumped
        assert "upholstery" in dumped
        assert dumped["exterior_color"] is None
        assert dumped["interior_color"] is None
        assert dumped["upholstery"] is None

    def test_model_dump_includes_equipment_field(self):
        listing = Listing.model_validate(make_listing())
        dumped = listing.model_dump()
        assert "equipment" in dumped
        assert dumped["equipment"] == []

    def test_no_transmission_field_on_listing(self):
        """transmission must NOT be a Listing field — it stays in raw['vehicle']['transmission']."""
        listing = Listing.model_validate(make_listing())
        assert not hasattr(listing, "transmission")

    def test_transmission_kwarg_silently_ignored(self):
        """Pydantic extra='ignore' must silently drop unknown 'transmission' kwarg."""
        listing = Listing.model_validate(make_listing(transmission="Manual"))
        assert not hasattr(listing, "transmission")


# ---------------------------------------------------------------------------
# Import completeness test
# ---------------------------------------------------------------------------


class TestImports:
    def test_all_five_models_importable(self):
        """Verify all five models can be imported from autoscout_pipeline.models."""
        from autoscout_pipeline.models import (  # noqa: F401
            Listing,
            ListingScore,
            PriceChange,
            RunRecord,
            ScoredListing,
        )
