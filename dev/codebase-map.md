# AutoScout24 MINI Pipeline — Codebase Map

**Last Updated:** 2026-05-05

---

## Project Overview

AutoScout24 MINI Pipeline is a daily Python async scraper that harvests MINI Hatch listings from autoscout24.com (20–30k km, ≤23k EUR, DE/AT/CH), extracts structured data from Next.js SSR pages via `__NEXT_DATA__`, scores each listing with OpenAI GPT-4.1-nano using `instructor` (Mode.TOOLS), persists results to Google Sheets with three-tab schema (listings, price_history, runs), and sends Telegram alerts for scores ≥8. The browser stack uses `cloverlabs-camoufox[geoip]` for Akamai-resistant fingerprinting. Scoring criteria are fully configurable via `brief.md`.

---

## Module Map

### Top-Level Directories

| Directory       | Purpose |
|-----------------|---------|
| `src/autoscout_pipeline/` | Core pipeline packages (models, config, scraper, scoring, sheets, notifications) |
| `tests/` | Unit tests with fixtures, mocked external services (camoufox, OpenAI, gspread, httpx) |
| `tests_integration/` | Integration tests for live Google Sheets; gated by `INTEGRATION_TESTS=1` env var |
| `scripts/` | Entry-point utilities: `smoke.py` (end-to-end smoke test), `capture_fixtures.py` (real HTML capture), `recon_detail.py` (one-shot live schema recon) |
| `deploy/` | Systemd service/timer config, idempotent ARM64 installer for Hetzner CAX11 |
| `dev/` | Development artifacts: task tracking, context docs, code reviews |
| `docs/` | User-facing documentation, examples, credentials template |

### Core Packages

#### `src/autoscout_pipeline/`

| Module | Purpose |
|--------|---------|
| `__init__.py` | Package metadata and version |
| `models.py` | Pydantic v2 data classes: `Listing`, `ListingScore`, `ScoredListing` (NESTED), `PriceChange`, `RunRecord`. All datetimes tz-aware UTC via field_validator. `Listing` carries four optional enrichment fields: `equipment: list[str]`, `exterior_color`, `interior_color`, `upholstery`. |
| `config.py` | Pydantic Settings class reading all env vars (OPENAI_API_KEY, SHEET_ID, CREDS_PATH, TG_TOKEN, TG_CHAT_ID, throttle/threshold settings, integration test flags). `as24_enrich: bool = True` controls detail-page enrichment. |
| `pipeline.py` | Async orchestrator: CLI entrypoint via Typer; `run(settings, dry_run)` implements full sequence (scrape → CONTAINS/EXCLUDES filter → transmission filter → base-Cooper filter → dedup → enrich → score → upsert → record → notify). Dry-run skips all writes. |
| `logging_setup.py` | Logging configuration (propagates to scraper, scorer, sheets, telegram) |

#### `src/autoscout_pipeline/scraper/`

Web scraping and parsing for AutoScout24 search/detail pages.

| Module | Purpose |
|--------|---------|
| `fetch.py` | `fetch_page_html(url)`: camoufox-backed fetcher using `wait_until="networkidle"` + explicit `wait_for_selector('script#__NEXT_DATA__')` to ensure Next.js hydration. Tenacity retry (3 attempts, exponential backoff 2-15s). `BrowserSession`: async context manager that holds a single Camoufox instance across sequential detail-page fetches; exposes `session.fetch(url)` with the same retry/selector logic. |
| `parse.py` | Pure functions to extract JSON from `__NEXT_DATA__` script tag; `NextDataMissingError` with HTML dump on failure; two-path fallback for listings array. `parse_listing_detail(data)` extracts enrichment fields (`equipment`, `exterior_color`, `interior_color`, `upholstery`) from `props.pageProps.listingDetails`; private `_flatten_equipment(raw)` normalises flat-list[str] and list[dict] equipment shapes. |
| `enrich.py` | `enrich_with_details(listings, throttle_min, throttle_max, session=None)`: sequential detail-page enrichment — fetches each listing's URL via `BrowserSession`, calls `parse_listing_detail`, mutates listing in place. Circuit breaker trips after 5 consecutive network failures (`CIRCUIT_BREAKER_THRESHOLD = 5`). Non-network exceptions do not increment the failure counter. |
| `search.py` | URL builder and `iter_listings(criteria)` async generator. Polite throttle (configurable 2–6s random jitter) between page requests. |
| `errors.py` | Custom exceptions: `NextDataMissingError`, `EmptyResultsError` |
| `__init__.py` | Package marker |

#### `src/autoscout_pipeline/sheets/`

Google Sheets integration via gspread.

| Module | Purpose |
|--------|---------|
| `schema.py` | Constants: `LISTINGS_HEADERS` (16 cols, score at index 11 = column L), `PRICE_HISTORY_HEADERS`, `RUNS_HEADERS`, `SCORE_COLUMN_LETTER = "L"`, and `SheetSchemaError` exception for mismatches. |
| `client.py` | `SheetsClient` wrapper: `bootstrap()` (idempotent, raises on mismatch), `get_existing_ids()`, `append_listings()` (batch via gspread API), `upsert_scores()`, `record_price_changes()`, `record_run()`. Private `_scored_to_row()` helper serializes ScoredListing to 16-element row. All writes use batch APIs. |
| `formatting.py` | Conditional formatting rules for Sheets (color score column L, stripe rows) |
| `__init__.py` | Package marker |

#### `src/autoscout_pipeline/scoring/`

OpenAI-based listing evaluation.

| Module | Purpose |
|--------|---------|
| `scorer.py` | `LLMScorer` class: `__init__(api_key, model, brief_path)` initializes AsyncOpenAI + instructor (Mode.TOOLS only). `score(listing)` returns `ListingScore` or sentinel score=1 on error. Exposes `_mode` and `_client` attributes for test pinning. |
| `batch.py` | `score_many(listings)` concurrency layer: asyncio.Semaphore(5) gates up to 5 concurrent LLM calls, returns list of `ScoredListing` (NESTED layout). |
| `prompt.py` | `load_brief(path)`, `build_system_prompt(brief)`, `render_listing(listing)` — prompt engineering utilities. `render_listing` emits enrichment-aware fields in order: `exterior_color`, `interior_color`, `upholstery`, `equipment_list` (joined `; `), then `model_text` as tail fallback when structured fields are empty. |
| `__init__.py` | Package marker |

#### `src/autoscout_pipeline/notify/`

Telegram notifications for high-scoring listings.

| Module | Purpose |
|--------|---------|
| `telegram.py` | `TelegramNotifier` class: `__init__(token, chat_id, threshold)`. `send_batch(scored_listings)` filters by score, html.escape all interpolated fields, sends messages via httpx.AsyncClient.post. Swallows network errors gracefully; 0.5s delay between messages. |
| `__init__.py` | Package marker |

---

## Key Entry Points

### 1. CLI: `autoscout-pipeline` Console Script

**Location:** `src/autoscout_pipeline/pipeline.py:cli()`

Typer-based CLI with `--dry-run` flag. Called from systemd timer (prod) or manual invocation:

```bash
uv run autoscout-pipeline --dry-run    # preview, no writes
uv run autoscout-pipeline               # full run with writes + notifications
```

### 2. `scripts/smoke.py`

**Purpose:** End-to-end smoke test with all external services mocked.

- Mocks: camoufox → fixture HTML; OpenAI → deterministic ListingScore; gspread → MagicMock; Telegram → httpx 200 OK; `enrich_with_details` → passthrough (identity)
- Exercises full pipeline in ~4 seconds
- Command: `uv run python -m scripts.smoke`
- Output: `OK smoke OK: scraped=12 new=12 scored=12 notified=3 in 4.2s`

### 3. `scripts/capture_fixtures.py`

**Purpose:** Capture real AutoScout24 HTML to refresh test fixtures.

- Uses live camoufox to navigate autoscout24.com
- Writes:
  - `tests/fixtures/autoscout_listings_page1.html` (search results)
  - `tests/fixtures/autoscout_listing_detail.html` (detail page)
- Requires: camoufox binary (`python -m camoufox fetch`), live network
- Command: `uv run python -m scripts.capture_fixtures`

### 4. `scripts/recon_detail.py`

**Purpose:** One-shot live schema reconnaissance for the detail page.

- Fetches first live listing URL from `iter_listings`, fetches its detail page via `fetch_page_html`, writes the HTML to `tests/fixtures/autoscout_listing_detail.html`, and writes `dev/active/detail-page-fetch/recon-notes.md` with structured schema notes for all four enrichment fields.
- Requires: live network, camoufox binary
- Command: `uv run python -m scripts.recon_detail`

---

## External Dependencies Summary

| Package | Role | Version |
|---------|------|---------|
| `cloverlabs-camoufox[geoip]` | Browser automation (Akamai bypass, German fingerprint) | ≥0.5,<0.6 |
| `instructor` | Pydantic-powered OpenAI schema extraction | ≥1.15,<2 |
| `openai` | OpenAI API client (used via instructor + AsyncOpenAI) | latest |
| `gspread` | Google Sheets API client | ≥6.1.4 |
| `gspread-formatting` | Conditional formatting for Sheets | latest |
| `pydantic` | Data validation | ≥2 |
| `pydantic-settings` | Environment-based configuration | latest |
| `httpx` | Async HTTP client (Telegram notifications) | latest |
| `tenacity` | Retry logic (camoufox timeout handling) | latest |
| `typer` | CLI framework | latest |
| `python-dotenv` | .env file loading | latest |
| `orjson` | JSON serialization | latest |
| `selectolax` | HTML parsing for `__NEXT_DATA__` extraction | latest |

**Dev Dependencies:**
- `pytest`, `pytest-asyncio` (async test runner, `asyncio_mode = "auto"` required)
- `respx` (mock httpx)
- `ruff` (linter)

---

## Test Layout

### `tests/` — Unit Tests (Mocked, Fast)

All tests use fixtures and mocks; no real network, sheets, or OpenAI calls. Around 207 tests total.

| Test File | Coverage |
|-----------|----------|
| `test_models.py` | Pydantic models: field validation, tz-aware enforcement, model_validator (PriceChange), RunRecord truncation; enrichment field defaults (`equipment=[]`, colour fields `None`) |
| `test_scraper_parse.py` | HTML → JSON extraction, NextDataMissingError path, two-path fallback logic; `parse_listing_detail` type/shape assertions against live fixture; `_flatten_equipment` parametrized over flat-list[str], list[dict], missing-key, None |
| `test_scraper_fetch.py` | `BrowserSession` async-CM lifecycle (open/close once), sequential multi-fetch, HTML return, `state="attached"` selector wait, page close, tenacity retry on `PlaywrightTimeoutError` |
| `test_scraper_enrich.py` | `enrich_with_details`: empty-list, skip-empty-url, per-listing error handling, throttle sleep count, empty-input-no-session, passed-session-reused, circuit-breaker trips at 5, breaker-resets-on-success |
| `test_scraper_search.py` | URL builder, throttle logic, iter_listings pagination |
| `test_sheets_schema.py` | LISTINGS_HEADERS, SCORE_COLUMN_LETTER ("L") matching |
| `test_sheets_client.py` | Bootstrap (idempotent, raises SheetSchemaError), dedup, row serialization, batch upsert, price history, run record |
| `test_scoring.py` | LLMScorer (Mode.TOOLS pinning, AsyncOpenAI client), score_many concurrency, error sentinel; `render_listing` enrichment field output |
| `test_notify.py` | TelegramNotifier: threshold gating, html.escape, network error swallowing, batch delay |
| `test_pipeline.py` | Full async run: scrape → dedup → score → upsert → record → notify flow, dry-run skips writes; transmission filter (Manual/Manuell/Schaltgetriebe dropped; Automatic/DSG/DCT/Steptronic/None kept); base-Cooper filter (11 cases); enrich wiring (called when `as24_enrich=True`, skipped when `False`); filter-ordering log |
| `conftest.py` | Shared fixtures (mock OpenAI, gspread, httpx; temp .env; fixture HTML) |
| `fixtures/` | Real captured HTML: `autoscout_listings_page1.html`, `autoscout_listings_no_next_data.html`, `autoscout_listing_detail.html` |

### `tests_integration/` — Integration Tests (Live Sheets, Gated)

Run only when `INTEGRATION_TESTS=1` and `INTEGRATION_SHEET_ID=<id>` env vars set.

| Test File | Coverage |
|-----------|----------|
| `test_sheets_live.py` | Real gspread calls: bootstrap, append, upsert, read-back verification on live Sheets |
| `conftest.py` | Session-scoped fixture for sheet pre-clean and post-clean |

---

## Deployment

### Artifacts in `deploy/`

| File | Purpose |
|------|---------|
| `install.sh` | Idempotent ARM64 installer for Hetzner CAX11 (Ubuntu 24.04): system deps, uv, autoscout user, `uv sync`, camoufox binary. Uses t64 ABI libs (libxcomposite1t64, libgtk-3-0t64, libxt6t64). |
| `autoscout-pipeline.service` | Systemd service definition (runs as `autoscout` user, restarts on failure, logs to journal) |
| `autoscout-pipeline.timer` | Systemd timer: runs daily at configured UTC time |
| `README.md` | Deploy workflow: setup GCP, download installer, run on Hetzner, enable timer |

### Deployment Flow

1. **Bootstrap Hetzner CAX11:**
   ```bash
   curl -s https://raw.githubusercontent.com/<org>/autoscout-parser/main/deploy/install.sh | bash
   ```

2. **Configure environment** (as autoscout user in `/opt/autoscout`):
   - Copy `.env.example` → `.env` with OPENAI_API_KEY, SHEET_ID, CREDS_PATH, TG_TOKEN
   - Place `creds.json` (GCP service account)
   - Edit `brief.md` with scoring criteria

3. **Enable systemd timer:**
   ```bash
   sudo systemctl enable autoscout-pipeline.timer
   sudo systemctl start autoscout-pipeline.timer
   ```

4. **Monitor:**
   ```bash
   sudo journalctl -u autoscout-pipeline.service -f
   ```

---

## Key Decisions & Constraints

- **ScoredListing NESTED layout:** `s.listing`, `s.score`, `s.scored_at` (not flat dict)
- **camoufox networkidle + wait_for_selector:** Both required for Next.js hydration (verified 2026-05-01)
- **instructor Mode.TOOLS only:** gpt-4.1-nano forbids TOOLS_STRICT, JSON_SCHEMA, RESPONSES_TOOLS
- **AsyncOpenAI (not sync):** Semaphore(5) concurrency requires actual async/await
- **LISTINGS_HEADERS: 16 columns, score at column L** (0-based index 11)
- **Batch-only gspread writes:** Per-cell loops hit rate limits at ~200 listings
- **Dedup before scoring:** Only new listing_ids scored, controls OpenAI costs
- **Dry-run mode:** Skips SheetsClient, GCP creds not needed for smoke tests
- **Python 3.11+ required:** Locally and on Hetzner
- **OpenAI paid tier required:** ≥500 RPM for ~200 listings with Semaphore(5), systemd 1800s timeout
- **INTEGRATION_TESTS gated:** Live Sheets only when env vars set
- **Transmission field in raw dict only:** `transmission` is NOT a `Listing` model field; read from `listing.raw["vehicle"]["transmission"]` in pipeline filter and `render_listing`. `ConfigDict(extra="ignore")` would silently swallow a `transmission=` constructor kwarg.
- **Base-Cooper tokenizer uses regex split:** `re.split(r"[\s\-./]+", model.lower())` catches `Cooper-S`, `Cooper.S`, `Cooper/S`. The no-separator form `CooperS` is a deferred edge case.
- **Circuit breaker threshold = 5 outer failures:** 15 total page-load attempts (after tenacity's 3x retry). Non-network exceptions do not increment the failure counter.
- **Enrichment mutates listings in place:** `enrich_with_details` assigns fields directly; Pydantic v2 allows attribute assignment.
- **Sheets schema unchanged:** `LISTINGS_HEADERS` (16 cols) untouched; equipment/colour are ephemeral (in-memory only for scoring).
- **Light-blue strict bonus only:** Only `Hellblau`/`Island Blue`/`Iceberg Blue`/`Electric Blue`/`Light Blue`/`Light-Blue Metallic`/`LightBlueMetallic` earn +1; other blue-family colours earn +0.

---

## File Structure (Tree)

```
autoscout-parser/
├── src/autoscout_pipeline/
│   ├── __init__.py
│   ├── models.py                 (Listing with 4 enrichment fields, ListingScore, ScoredListing NESTED, etc.)
│   ├── config.py                 (Settings from env/.env; as24_enrich bool)
│   ├── pipeline.py               (async run, CLI via Typer; transmission + base-Cooper filters; enrich stage)
│   ├── logging_setup.py
│   ├── scraper/
│   │   ├── __init__.py
│   │   ├── fetch.py              (camoufox + networkidle + wait_for_selector; BrowserSession async-CM)
│   │   ├── parse.py              (__NEXT_DATA__ extraction; parse_listing_detail; _flatten_equipment)
│   │   ├── enrich.py             (enrich_with_details; circuit breaker threshold=5)
│   │   ├── search.py             (URL builder, iter_listings, throttle)
│   │   └── errors.py             (NextDataMissingError, EmptyResultsError)
│   ├── sheets/
│   │   ├── __init__.py
│   │   ├── schema.py             (LISTINGS_HEADERS, SCORE_COLUMN_LETTER, SheetSchemaError)
│   │   ├── client.py             (SheetsClient, bootstrap, append, upsert, _scored_to_row)
│   │   └── formatting.py         (Conditional formatting rules)
│   ├── scoring/
│   │   ├── __init__.py
│   │   ├── scorer.py             (LLMScorer, Mode.TOOLS, AsyncOpenAI)
│   │   ├── batch.py              (score_many with Semaphore(5))
│   │   └── prompt.py             (load_brief, build_system_prompt, render_listing with enrichment fields)
│   └── notify/
│       ├── __init__.py
│       └── telegram.py           (TelegramNotifier, html.escape, batch send)
├── tests/
│   ├── __init__.py
│   ├── conftest.py               (Shared fixtures)
│   ├── fixtures/
│   │   ├── autoscout_listings_page1.html
│   │   ├── autoscout_listings_no_next_data.html
│   │   ├── autoscout_listing_detail.html  (live captured HTML)
│   │   └── README.md
│   ├── test_models.py
│   ├── test_scraper_parse.py
│   ├── test_scraper_fetch.py
│   ├── test_scraper_enrich.py
│   ├── test_scraper_search.py
│   ├── test_sheets_schema.py
│   ├── test_sheets_client.py
│   ├── test_scoring.py
│   ├── test_notify.py
│   └── test_pipeline.py
├── tests_integration/
│   ├── __init__.py
│   ├── conftest.py               (Session fixture for live Sheets)
│   └── test_sheets_live.py
├── scripts/
│   ├── __init__.py
│   ├── smoke.py                  (End-to-end mocked smoke test)
│   ├── capture_fixtures.py       (Real camoufox HTML capture)
│   └── recon_detail.py           (One-shot live detail-page schema recon)
├── deploy/
│   ├── install.sh                (Hetzner CAX11 ARM64 idempotent installer)
│   ├── autoscout-pipeline.service
│   ├── autoscout-pipeline.timer
│   └── README.md
├── dev/
│   ├── done/                     (Completed task artifacts)
│   ├── active/                   (Active task tracking)
│   └── codebase-map.md           (This file)
├── docs/
│   ├── creds.json.example
│   └── (User-facing docs)
├── pyproject.toml                (uv manifest: deps, pytest config)
├── README.md                     (Quickstart, config guide, GCP/Telegram setup)
├── brief.md                      (Scoring criteria — user-editable; baseline 6, light-blue strict +1)
├── .env.example                  (Template for .env)
└── .gitignore
```

---

## Quick Start for Contributors

1. **Clone & install:**
   ```bash
   git clone https://github.com/<org>/autoscout-parser.git
   cd autoscout-parser
   uv sync
   ```

2. **Run unit tests:**
   ```bash
   pytest tests/
   ```

3. **Smoke test (mocked):**
   ```bash
   uv run python -m scripts.smoke
   ```

4. **Refresh fixtures (requires live network):**
   ```bash
   python -m camoufox fetch
   uv run python -m scripts.capture_fixtures
   ```

5. **Integration test (requires INTEGRATION_TESTS=1 env var + real Sheets):**
   ```bash
   INTEGRATION_TESTS=1 INTEGRATION_SHEET_ID=<id> pytest tests_integration/
   ```

6. **Lint:**
   ```bash
   ruff check .
   ```
