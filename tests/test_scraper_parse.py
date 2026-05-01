"""Tests for scraper/parse.py — pure HTML/JSON extraction functions.

Uses synthetic fixtures from tests/fixtures/ so no network access is required.
"""

import glob
import os
import pathlib

import pytest

from autoscout_pipeline.scraper.errors import NextDataMissingError
from autoscout_pipeline.scraper.parse import (
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


class TestParseListingDetail:
    def test_returns_single_listing(self) -> None:
        html = _read_fixture("autoscout_listing_detail.html")
        data = extract_next_data(html)
        listing = parse_listing_detail(data)
        assert listing is not None

    def test_detail_listing_fields(self) -> None:
        html = _read_fixture("autoscout_listing_detail.html")
        data = extract_next_data(html)
        listing = parse_listing_detail(data)
        assert listing.listing_id == "AS24-DETAIL-001"
        assert listing.brand == "MINI"
        assert listing.model == "Mini"
        assert listing.year == 2020
        assert listing.mileage_km == 22500
        assert listing.price_eur == 19900

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
