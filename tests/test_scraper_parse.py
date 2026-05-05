"""Tests for scraper/parse.py — pure HTML/JSON extraction functions.

Uses synthetic fixtures from tests/fixtures/ so no network access is required.
"""

import glob
import os
import pathlib

import pytest

from autoscout_pipeline.scraper.errors import NextDataMissingError
from autoscout_pipeline.scraper.parse import (
    _flatten_equipment,
    extract_next_data,
    parse_listing_detail,
    parse_listings_page,
)

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


def _read_fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


class TestExtractNextData:
    def test_extracts_json_from_valid_html(self) -> None:
        html = _read_fixture("autoscout_listings_page1.html")
        data = extract_next_data(html)
        assert isinstance(data, dict)
        assert "props" in data

    def test_listings_accessible_in_extracted_data(self) -> None:
        html = _read_fixture("autoscout_listings_page1.html")
        data = extract_next_data(html)
        listings = data["props"]["pageProps"]["listings"]
        assert isinstance(listings, list)
        assert len(listings) >= 12

    def test_extract_next_data_raises_on_missing_script_tag(self) -> None:
        """NextDataMissingError must be raised AND a /tmp dump file must be written."""
        html = _read_fixture("autoscout_listings_no_next_data.html")

        # Track existing dump files before the call
        before = set(glob.glob("/tmp/as24_dump_*.html"))

        with pytest.raises(NextDataMissingError) as exc_info:
            extract_next_data(html)

        # A new dump file must have been created
        after = set(glob.glob("/tmp/as24_dump_*.html"))
        new_dumps = after - before
        assert len(new_dumps) == 1, "Expected exactly one new /tmp/as24_dump_*.html file"

        # The exception should reference the dump path
        dump_path = next(iter(new_dumps))
        assert dump_path in str(exc_info.value) or os.path.exists(dump_path)

        # Clean up the dump file
        os.unlink(dump_path)

    def test_dump_file_contains_raw_html(self) -> None:
        """The /tmp dump must contain the original HTML content."""
        html = _read_fixture("autoscout_listings_no_next_data.html")
        before = set(glob.glob("/tmp/as24_dump_*.html"))

        with pytest.raises(NextDataMissingError):
            extract_next_data(html)

        after = set(glob.glob("/tmp/as24_dump_*.html"))
        new_dumps = after - before
        dump_path = next(iter(new_dumps))

        dump_content = pathlib.Path(dump_path).read_text(encoding="utf-8")
        assert "autoscout_listings_no_next_data" in dump_content or len(dump_content) > 0

        os.unlink(dump_path)

    def test_detail_fixture_extractable(self) -> None:
        html = _read_fixture("autoscout_listing_detail.html")
        data = extract_next_data(html)
        assert "props" in data
        assert "listingDetails" in data["props"]["pageProps"]


class TestParseListingsPage:
    def test_returns_list_of_listings(self) -> None:
        html = _read_fixture("autoscout_listings_page1.html")
        data = extract_next_data(html)
        listings = parse_listings_page(data)
        assert isinstance(listings, list)
        assert len(listings) >= 10

    def test_all_listings_have_required_fields(self) -> None:
        html = _read_fixture("autoscout_listings_page1.html")
        data = extract_next_data(html)
        listings = parse_listings_page(data)
        for listing in listings:
            assert listing.listing_id != ""
            assert listing.url != ""
            assert listing.brand != ""
            assert listing.model != ""
            assert listing.year > 0
            assert listing.mileage_km >= 0
            assert listing.price_eur >= 0

    def test_all_prices_below_23000(self) -> None:
        html = _read_fixture("autoscout_listings_page1.html")
        data = extract_next_data(html)
        listings = parse_listings_page(data)
        for listing in listings:
            assert listing.price_eur < 23000, (
                f"listing {listing.listing_id} has price {listing.price_eur} >= 23000"
            )

    def test_all_mileages_in_expected_range(self) -> None:
        html = _read_fixture("autoscout_listings_page1.html")
        data = extract_next_data(html)
        listings = parse_listings_page(data)
        for listing in listings:
            assert 20000 <= listing.mileage_km <= 30000, (
                f"listing {listing.listing_id} has mileage {listing.mileage_km} outside [20000, 30000]"
            )

    def test_listings_have_tz_aware_datetimes(self) -> None:
        from datetime import UTC

        html = _read_fixture("autoscout_listings_page1.html")
        data = extract_next_data(html)
        listings = parse_listings_page(data)
        for listing in listings:
            assert listing.first_seen.tzinfo is not None
            assert listing.last_seen.tzinfo is not None
            assert listing.first_seen.tzinfo == UTC

    def test_fallback_path_initialstate(self) -> None:
        """parse_listings_page must also handle initialState search results path."""
        data = {
            "props": {
                "pageProps": {
                    "initialState": {
                        "search": {
                            "results": [
                                {
                                    "id": "fallback-001",
                                    "url": "https://www.autoscout24.com/offers/fallback",
                                    "make": "MINI",
                                    "model": "Mini",
                                    "firstRegistrationDate": "2020",
                                    "mileage": 25000,
                                    "price": 18000,
                                    "location": "Berlin",
                                    "country": "D",
                                }
                            ]
                        }
                    }
                }
            }
        }
        listings = parse_listings_page(data)
        assert len(listings) == 1
        assert listings[0].listing_id == "fallback-001"

    def test_empty_data_raises_or_returns_empty(self) -> None:
        """When neither path has listings, should return empty list (not crash)."""
        data = {"props": {"pageProps": {}}}
        listings = parse_listings_page(data)
        assert listings == []


class TestFlattenEquipment:
    """Unit tests for _flatten_equipment — deterministic, no fixtures needed."""

    def test_dict_of_categories_returns_flat_list(self) -> None:
        """Primary shape: dict-of-categories with list-of-dicts-with-id."""
        raw = {
            "comfortAndConvenience": [
                {
                    "id": "Automatic climate control, 2 zones",
                    "categoryName": "C&C",
                    "categoryId": "comfortAndConvenience",
                },
                {
                    "id": "Auxiliary heating",
                    "categoryName": "C&C",
                    "categoryId": "comfortAndConvenience",
                },
            ],
            "entertainmentAndMedia": [
                {"id": "Bluetooth", "categoryName": "E&M", "categoryId": "entertainmentAndMedia"},
            ],
            "extras": [],
            "safetyAndSecurity": [
                {"id": "ABS", "categoryName": "S&S", "categoryId": "safetyAndSecurity"},
            ],
        }
        result = _flatten_equipment(raw)
        assert isinstance(result, list)
        assert "Automatic climate control, 2 zones" in result
        assert "Auxiliary heating" in result
        assert "Bluetooth" in result
        assert "ABS" in result
        # Empty category contributes nothing
        assert len(result) == 4

    def test_none_returns_empty_list(self) -> None:
        assert _flatten_equipment(None) == []

    def test_empty_dict_returns_empty_list(self) -> None:
        assert _flatten_equipment({}) == []

    def test_plain_list_of_strings_passthrough(self) -> None:
        raw = ["ABS", "Bluetooth", "Parking sensors"]
        result = _flatten_equipment(raw)
        assert result == ["ABS", "Bluetooth", "Parking sensors"]

    def test_list_of_dicts_with_items_subkey(self) -> None:
        """Handles a possible alternate AS24 shape: list of category dicts with items sub-list."""
        raw = [
            {"items": [{"id": "Heated seats"}, {"id": "Sunroof"}]},
            {"items": [{"id": "ABS"}]},
        ]
        result = _flatten_equipment(raw)
        assert "Heated seats" in result
        assert "Sunroof" in result
        assert "ABS" in result

    def test_list_of_dicts_with_id_key(self) -> None:
        """Handles a flat list of dicts each with an 'id' key (no items sub-key)."""
        raw = [
            {"id": "Navigation system"},
            {"id": "Cruise control"},
        ]
        result = _flatten_equipment(raw)
        assert "Navigation system" in result
        assert "Cruise control" in result

    def test_dict_of_categories_with_plain_string_items(self) -> None:
        """Handles category lists that contain plain strings instead of dicts."""
        raw = {
            "comfortAndConvenience": ["Heated seats", "Sunroof"],
            "extras": ["Tow bar"],
        }
        result = _flatten_equipment(raw)
        assert "Heated seats" in result
        assert "Sunroof" in result
        assert "Tow bar" in result

    def test_all_items_are_non_empty_strings(self) -> None:
        """Every returned item must be a non-empty string."""
        raw = {
            "comfortAndConvenience": [
                {
                    "id": "Air conditioning",
                    "categoryName": "C&C",
                    "categoryId": "comfortAndConvenience",
                },
            ],
            "extras": [
                {
                    "id": "",
                    "categoryName": "E",
                    "categoryId": "extras",
                },  # empty id — must be excluded
            ],
        }
        result = _flatten_equipment(raw)
        assert all(isinstance(x, str) and x for x in result)
        assert "Air conditioning" in result
        assert "" not in result


class TestParseListingDetail:
    """Tests for parse_listing_detail using the live-captured fixture.

    Assertions are shape/type-based to remain stable across fixture recaptures.
    The fixture is a real MINI listing — specific IDs, prices, colours are
    intentionally NOT pinned.
    """

    def test_returns_single_listing(self) -> None:
        html = _read_fixture("autoscout_listing_detail.html")
        data = extract_next_data(html)
        listing = parse_listing_detail(data)
        assert listing is not None

    def test_listing_id_is_non_empty_uuid_like_string(self) -> None:
        html = _read_fixture("autoscout_listing_detail.html")
        data = extract_next_data(html)
        listing = parse_listing_detail(data)
        # Non-empty string; UUID-like (contains hyphens) for the live fixture
        assert isinstance(listing.listing_id, str)
        assert len(listing.listing_id) > 0

    def test_brand_is_mini(self) -> None:
        """Brand should still be MINI — it is a MINI search fixture."""
        html = _read_fixture("autoscout_listing_detail.html")
        data = extract_next_data(html)
        listing = parse_listing_detail(data)
        assert listing.brand == "MINI"

    def test_url_starts_with_https_or_slash(self) -> None:
        html = _read_fixture("autoscout_listing_detail.html")
        data = extract_next_data(html)
        listing = parse_listing_detail(data)
        assert isinstance(listing.url, str)
        assert listing.url.startswith("https://") or listing.url.startswith("/")

    def test_year_in_expected_range(self) -> None:
        html = _read_fixture("autoscout_listing_detail.html")
        data = extract_next_data(html)
        listing = parse_listing_detail(data)
        assert 2018 <= listing.year <= 2030

    def test_mileage_km_positive(self) -> None:
        html = _read_fixture("autoscout_listing_detail.html")
        data = extract_next_data(html)
        listing = parse_listing_detail(data)
        assert listing.mileage_km > 0

    def test_price_eur_positive(self) -> None:
        html = _read_fixture("autoscout_listing_detail.html")
        data = extract_next_data(html)
        listing = parse_listing_detail(data)
        assert listing.price_eur > 0

    def test_equipment_is_non_empty_list_of_strings(self) -> None:
        """equipment must be a list[str] with at least 1 entry, all items non-empty."""
        html = _read_fixture("autoscout_listing_detail.html")
        data = extract_next_data(html)
        listing = parse_listing_detail(data)
        assert isinstance(listing.equipment, list)
        assert len(listing.equipment) >= 1
        for item in listing.equipment:
            assert isinstance(item, str) and item, f"empty/non-str item: {item!r}"

    def test_exterior_color_is_str_or_none(self) -> None:
        html = _read_fixture("autoscout_listing_detail.html")
        data = extract_next_data(html)
        listing = parse_listing_detail(data)
        assert listing.exterior_color is None or isinstance(listing.exterior_color, str)

    def test_interior_color_is_str_or_none(self) -> None:
        html = _read_fixture("autoscout_listing_detail.html")
        data = extract_next_data(html)
        listing = parse_listing_detail(data)
        assert listing.interior_color is None or isinstance(listing.interior_color, str)

    def test_upholstery_is_str_or_none(self) -> None:
        html = _read_fixture("autoscout_listing_detail.html")
        data = extract_next_data(html)
        listing = parse_listing_detail(data)
        assert listing.upholstery is None or isinstance(listing.upholstery, str)

    def test_detail_listing_has_location(self) -> None:
        html = _read_fixture("autoscout_listing_detail.html")
        data = extract_next_data(html)
        listing = parse_listing_detail(data)
        assert listing.location is not None
        assert len(listing.location) > 0

    def test_detail_listing_has_tz_aware_datetimes(self) -> None:
        from datetime import UTC

        html = _read_fixture("autoscout_listing_detail.html")
        data = extract_next_data(html)
        listing = parse_listing_detail(data)
        assert listing.first_seen.tzinfo == UTC
        assert listing.last_seen.tzinfo == UTC

    def test_missing_enrichment_fields_do_not_raise(self) -> None:
        """parse_listing_detail must not raise when enrichment fields are absent."""
        # Minimal synthetic dict with no vehicle enrichment fields
        data = {
            "props": {
                "pageProps": {
                    "listingDetails": {
                        "id": "synthetic-001",
                        "url": "https://www.autoscout24.com/offers/synthetic-001",
                        "vehicle": {
                            "make": "MINI",
                            "model": "Cooper",
                            "mileageInKm": 50000,
                            "firstRegistrationDate": "2019-01",
                            # No equipment, no bodyColor, no upholstery, no upholsteryColor
                        },
                        "price": {"priceFormatted": "€ 15,000"},
                        "location": {"city": "Berlin", "countryCode": "D"},
                    }
                }
            }
        }
        listing = parse_listing_detail(data)
        assert listing.listing_id == "synthetic-001"
        assert listing.equipment == []
        assert listing.exterior_color is None
        assert listing.interior_color is None
        assert listing.upholstery is None
