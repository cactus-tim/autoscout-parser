# Test Fixtures

These fixtures are **synthetic** — they were hand-crafted to satisfy the parse contract
without requiring a live network connection or a headless browser.

## Files

| File | Purpose |
|------|---------|
| `autoscout_listings_page1.html` | Minimal HTML with `<script id="__NEXT_DATA__">` containing 12 plausible MINI Hatch listings under `props.pageProps.listings`. Prices < 23000 EUR, mileage 20000–30000 km. |
| `autoscout_listings_no_next_data.html` | Same structure but with the `__NEXT_DATA__` script tag **removed**. Used to exercise the `NextDataMissingError` path in `scraper/parse.py`. |
| `autoscout_listing_detail.html` | Minimal HTML with `props.pageProps.listingDetails` for one fully-populated MINI Cooper listing. |

## Refreshing from the Live Site

Run `scripts/capture_fixtures.py` against the live autoscout24.com to regenerate real HTML:

```bash
uv run python -m scripts.capture_fixtures
```

This uses `cloverlabs-camoufox` (headless Firefox) and writes the output to this directory.
**Requires:** camoufox binary installed (`python -m camoufox fetch`), network access, and a
working `geoip` database (installed via `cloverlabs-camoufox[geoip]`).

> **Note:** The synthetic fixtures were created on 2026-05-01. AutoScout24 may change its
> `__NEXT_DATA__` schema structure between Next.js deployments. If `parse_listings_page` or
> `parse_listing_detail` start failing on live data, re-run `capture_fixtures.py` and update
> the parse paths accordingly.
