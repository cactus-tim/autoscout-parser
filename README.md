# AutoScout24 MINI Pipeline

A daily Python pipeline that scrapes AutoScout24 for MINI Hatch listings (mileage 20–30k km, price ≤ 23k EUR, DE/AT/CH), extracts structured data from Next.js SSR pages via `__NEXT_DATA__`, scores each listing with OpenAI GPT-4.1 nano through `instructor`, persists results to Google Sheets (three-tab schema with dedup and price history), and notifies Telegram when score ≥ 8. The browser stack uses `cloverlabs-camoufox` for Akamai-resistant browser fingerprinting; the scoring brief is fully configurable via `brief.md`.

## Quickstart

```bash
cp .env.example .env
# Fill in OPENAI_API_KEY, SHEET_ID, TG_TOKEN, TG_CHAT_ID, CREDS_PATH
uv sync
uv run autoscout-pipeline --help
uv run autoscout-pipeline --dry-run
```

## Setup

See `deploy/README.md` for full Hetzner CAX11 VPS setup instructions.

## Configuration

All settings are read from environment variables (see `.env.example`).
The scoring brief is in `brief.md` — edit it to change how listings are ranked.

## Project Structure

```
src/autoscout_pipeline/
  config.py          # pydantic-settings Settings class
  models.py          # Listing, ListingScore, ScoredListing, RunRecord, PriceChange
  pipeline.py        # Async orchestrator + Typer CLI
  logging_setup.py   # JSON-line logger
  scraper/           # camoufox fetcher, __NEXT_DATA__ parser, search iterator
  scoring/           # instructor + AsyncOpenAI scorer with Semaphore(5) concurrency
  sheets/            # gspread adapter: bootstrap, dedup, batch upsert, formatting
  notify/            # Telegram notifier with score gate and html.escape
tests/               # Unit tests (fixtures only, no network)
tests_integration/   # Live Sheets tests (INTEGRATION_TESTS=1 required)
deploy/              # systemd service/timer + install.sh
```

## Troubleshooting

- **`NextDataMissingError`**: The `__NEXT_DATA__` JSON block was not found in the fetched HTML. AutoScout24 injects it client-side after Next.js hydration; a dump of the raw HTML is saved to `/tmp/as24_dump_<ts>.html` for inspection. Ensure camoufox binary is fetched (`python -m camoufox fetch`) and system libraries are installed (see `deploy/install.sh`).
- **`EmptyResultsError`**: The search returned no listings. The URL bucket codes for mileage/price may have changed. Check the URL template documented in `scraper/search.py`.
- **`SheetSchemaError`**: The existing Google Sheet has different headers than expected. Either the sheet was modified manually or the schema was updated. Back up the sheet data and run `--force-bootstrap` (future feature) or recreate the tabs manually.
- **OpenAI 401**: Your `OPENAI_API_KEY` is invalid or expired. Regenerate it at https://platform.openai.com/api-keys.
- **Rate-limit timeout**: The pipeline exceeded the systemd `TimeoutStartSec=1800`. This happens on the OpenAI free tier (3 RPM). A paid tier with ≥500 RPM is required for production runs with Semaphore(5) concurrency at 200 listings.
- **Camoufox missing libs**: On Ubuntu 24.04 ARM64 ensure `libxcomposite1t64`, `libgtk-3-0t64`, and `libxt6t64` (t64 variants) are installed. See `deploy/install.sh`.
