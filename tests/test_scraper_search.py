"""Tests for scraper/search.py — URL builder and search iterator (pure unit tests).

No live network access. Tests only cover build_search_url; iter_listings is not
tested here because it requires a live camoufox browser.
"""

from autoscout_pipeline.scraper.search import build_search_url


class TestBuildSearchUrl:
    """Pure unit tests for the URL builder — no network, no browser."""

    def _default_criteria(self) -> dict:
        return {
            "make": "mini",
            "model": "mini",
            "priceto": 23000,
            "kmfrom": 20000,
            "kmto": 30000,
            "cy": "D,A,CH",
            "atype": "C",
        }

    def test_returns_string(self) -> None:
        url = build_search_url(self._default_criteria(), page=1)
        assert isinstance(url, str)

    def test_url_starts_with_autoscout24(self) -> None:
        url = build_search_url(self._default_criteria(), page=1)
        assert url.startswith("https://www.autoscout24.com/")

    def test_url_contains_make_param(self) -> None:
        url = build_search_url(self._default_criteria(), page=1)
        assert "make=" in url or "/lst/mini" in url

    def test_url_contains_model_param(self) -> None:
        url = build_search_url(self._default_criteria(), page=1)
        assert "model=" in url or "/lst/mini/mini" in url

    def test_url_contains_price_param(self) -> None:
        url = build_search_url(self._default_criteria(), page=1)
        assert "priceto=23000" in url

    def test_url_contains_mileage_params(self) -> None:
        url = build_search_url(self._default_criteria(), page=1)
        # kmfrom and/or kmto must appear (mileage range)
        assert "kmfrom=20000" in url
        assert "kmto=30000" in url

    def test_url_contains_country_param(self) -> None:
        url = build_search_url(self._default_criteria(), page=1)
        # cy parameter for Germany, Austria, Switzerland
        assert "cy=" in url

    def test_page_param_appended_page1(self) -> None:
        url = build_search_url(self._default_criteria(), page=1)
        assert "page=1" in url

    def test_page_param_appended_page3(self) -> None:
        url = build_search_url(self._default_criteria(), page=3)
        assert "page=3" in url

    def test_different_pages_produce_different_urls(self) -> None:
        url1 = build_search_url(self._default_criteria(), page=1)
        url2 = build_search_url(self._default_criteria(), page=2)
        assert url1 != url2

    def test_criteria_without_optional_params(self) -> None:
        """Minimal criteria — only make and model — should still produce a valid URL."""
        criteria = {"make": "mini", "model": "mini"}
        url = build_search_url(criteria, page=1)
        assert "page=1" in url
        assert "autoscout24.com" in url

    def test_atype_param_present(self) -> None:
        url = build_search_url(self._default_criteria(), page=1)
        assert "atype=C" in url

    def test_sort_param_present(self) -> None:
        """Search URL should include a sort parameter for reproducible ordering."""
        url = build_search_url(self._default_criteria(), page=1)
        assert "sort=" in url

    def test_custom_make_model(self) -> None:
        criteria = {"make": "bmw", "model": "3er", "priceto": 30000}
        url = build_search_url(criteria, page=1)
        assert "bmw" in url.lower() or "make=bmw" in url

    def test_url_is_valid_http(self) -> None:
        url = build_search_url(self._default_criteria(), page=1)
        assert url.startswith("https://")
        assert "?" in url  # must have query string
