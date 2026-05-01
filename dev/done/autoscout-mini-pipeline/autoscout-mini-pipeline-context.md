# AutoScout24 MINI Pipeline — Context

## SESSION PROGRESS (2026-05-01)

### COMPLETED
- Phase 1 (Steps 1.1–1.4): Full project bootstrap — uv src-layout init, all deps in pyproject.toml, package stubs, tooling files. All acceptance gates pass.
- Phase 2 (Steps 2.1–2.2): Pydantic models fully implemented. Five models (Listing, ListingScore, ScoredListing, PriceChange, RunRecord) in src/autoscout_pipeline/models.py. ScoredListing uses NESTED composition (listing: Listing, score: ListingScore, scored_at: datetime). All datetimes require tz-aware UTC via field_validator. PriceChange rejects equal prices via model_validator. RunRecord truncates notes at 500 chars. 44 tests in tests/test_models.py pass; ruff clean.

### IN PROGRESS
- Phase 3: Scraper Module (Steps 3.1–3.6)

### BLOCKERS
- None

## Quick Resume
1. Read this file
2. Check `autoscout-mini-pipeline-tasks.md` for what's next
3. Read `autoscout-mini-pipeline-plan.md` Phase 1 for strategy
4. Start with: Task 1.1 — run `uv init --package autoscout_pipeline --lib` to initialize the src-layout project

## Key Files

**`pyproject.toml`**
- Role: uv project manifest; declares all runtime + dev dependencies; holds pytest asyncio_mode config
- Planned change: Create from scratch; must include `asyncio_mode = "auto"` in `[tool.pytest.ini_options]`
- Status: NOT STARTED

**`src/autoscout_pipeline/models.py`**
- Role: Canonical data model consumed by all pipeline modules
- Planned change: Implement Listing, ListingScore, ScoredListing (NESTED), RunRecord, PriceChange
- Status: DONE (Phase 2)

**`src/autoscout_pipeline/config.py`**
- Role: Single Settings class via pydantic-settings; reads all env vars from .env
- Planned change: Create with all settings typed; AS24_THROTTLE_MIN/MAX, INTEGRATION_TESTS, etc.
- Status: NOT STARTED

**`src/autoscout_pipeline/scraper/fetch.py`**
- Role: camoufox-backed HTML fetcher with networkidle + selector wait and tenacity retry
- Planned change: Create; must include explanatory comment on why networkidle is required
- Status: NOT STARTED

**`src/autoscout_pipeline/scraper/parse.py`**
- Role: Pure functions to extract and parse __NEXT_DATA__ from HTML
- Planned change: Create; NextDataMissingError + HTML dump on failure; two path fallback for listings array
- Status: NOT STARTED

**`src/autoscout_pipeline/scraper/search.py`**
- Role: URL builder and async listing iterator
- Planned change: Create; URL template discovered manually before coding; polite throttle between pages
- Status: NOT STARTED

**`src/autoscout_pipeline/sheets/schema.py`**
- Role: Single source of truth for header definitions and SCORE_COLUMN_LETTER
- Planned change: Create; LISTINGS_HEADERS has 16 elements; SCORE_COLUMN_LETTER = "L"
- Status: NOT STARTED

**`src/autoscout_pipeline/sheets/client.py`**
- Role: gspread wrapper; bootstrap, dedup, batch upsert, price history, run record
- Planned change: Create; private _scored_to_row helper; all writes use batch APIs; idempotent bootstrap
- Status: NOT STARTED

**`src/autoscout_pipeline/scoring/scorer.py`**
- Role: LLMScorer using AsyncOpenAI + instructor Mode.TOOLS; error sentinel
- Planned change: Create; exposes _mode attribute for test pinning; client must be AsyncOpenAI
- Status: NOT STARTED

**`src/autoscout_pipeline/scoring/batch.py`**
- Role: Concurrent scorer with asyncio.Semaphore(5)
- Planned change: Create; returns ScoredListing with NESTED layout
- Status: NOT STARTED

**`src/autoscout_pipeline/notify/telegram.py`**
- Role: Score-gated Telegram notifier using httpx; html.escape on all interpolated fields
- Planned change: Create; swallows network errors; 0.5s delay in send_batch
- Status: NOT STARTED

**`src/autoscout_pipeline/pipeline.py`**
- Role: Async orchestrator and Typer CLI entrypoint
- Planned change: Full implementation; dedup-before-scoring sequence; dry-run flag skips all writes
- Status: NOT STARTED

**`tests/fixtures/autoscout_listings_page1.html`**
- Role: Real captured HTML from autoscout24.com (post-hydration, contains __NEXT_DATA__)
- Planned change: Create by running capture_fixtures.py; must be committed to repo
- Status: NOT STARTED

**`tests/fixtures/autoscout_listings_no_next_data.html`**
- Role: Synthetic fixture with __NEXT_DATA__ script tag stripped; exercises error path
- Planned change: Create; used by test_extract_next_data_raises_on_missing_script_tag
- Status: NOT STARTED

**`deploy/install.sh`**
- Role: Idempotent ARM64-aware install script for Hetzner CAX11
- Planned change: Create; uses libxcomposite1t64 (Ubuntu 24.04 t64 variant)
- Status: NOT STARTED

**`brief.md`**
- Role: User-configurable scoring brief read once per LLMScorer init
- Planned change: Create placeholder text; user replaces with real criteria
- Status: NOT STARTED

## Decisions

**ScoredListing field convention: NESTED (authoritative)**
- Decision: `ScoredListing` has fields `listing: Listing`, `score: ListingScore`, `scored_at: datetime`. Access pattern throughout the codebase: `s.listing.price_eur`, `s.score.score`, `s.scored_at`.
- Rationale: Composition over flat dict; makes field ownership unambiguous; Steps 2, 4, and 7 must all follow this layout consistently.

**camoufox: networkidle + explicit selector wait**
- Decision: `wait_until="networkidle"` AND `page.wait_for_selector('script#__NEXT_DATA__', timeout=15000)` are both required.
- Rationale: `__NEXT_DATA__` is injected client-side after Next.js hydration; `domcontentloaded` fires before hydration completes. Verified in May 2026: a raw WebFetch of autoscout24.com returned no `__NEXT_DATA__` tag.

**instructor Mode.TOOLS (locked)**
- Decision: `Mode.TOOLS` only. Forbidden modes for gpt-4.1-nano: `TOOLS_STRICT`, `JSON_SCHEMA`, `RESPONSES_TOOLS`, `RESPONSES_TOOLS_WITH_INBUILT_TOOLS`.
- Rationale: nano returns "Unsupported model" on strict/JSON_SCHEMA modes; RESPONSES_TOOLS compat unverified. Pinned by `test_scorer_pins_mode_to_tools` (enum identity check).

**AsyncOpenAI client (not synchronous OpenAI)**
- Decision: Import and instantiate `AsyncOpenAI`, not `OpenAI`.
- Rationale: Semaphore-gated concurrency in `score_many` only works if the client actually awaits; synchronous client blocks. Pinned by `test_scorer_uses_async_openai_client` (class identity check).

**LISTINGS_HEADERS: 16 columns, score in column L**
- Decision: `LISTINGS_HEADERS = ["listing_id","url","first_seen","last_seen","brand","model","year","mileage_km","price_eur","location","country","score","reasoning","pros","cons","status"]`. Score is at 0-based index 11, column letter **L**. `SCORE_COLUMN_LETTER = "L"`.
- Rationale: The 15-column schema from the research doc lacked `country`; adding it between `location` and `score` shifts score from K to L. All formatting ranges, tests, and comments must reference L, never K. Pinned by `test_score_column_letter_matches_header_index`.

**gspread batch-only writes**
- Decision: All gspread writes use `append_rows` and `batch_update`. No per-cell loops.
- Rationale: Research doc §4 explicitly warns about rate limits. Per-cell writes at ~200 listings would hit quota.

**Dedup before scoring**
- Decision: `sheets.get_existing_ids()` is called before LLM scoring; only new listing_ids are scored.
- Rationale: Avoids re-scoring already-known listings on every daily run, controlling OpenAI costs.

**cloverlabs-camoufox (not classic camoufox)**
- Decision: `pip install cloverlabs-camoufox[geoip]`; `from camoufox.async_api import AsyncCamoufox` (import name unchanged).
- Rationale: Classic camoufox frozen at v0.4.11 (Jan 2025); cloverlabs fork is at v0.5.5 (Mar 2026) with active Akamai-bypass updates. Both publish under the `camoufox` import name.

**geoip=True at runtime**
- Decision: Install `[geoip]` extra AND set `geoip=True` at runtime.
- Rationale: Hetzner DE IP must produce a German fingerprint (timezone=Europe/Berlin, locale=de-DE) automatically. Consistent stance: install DB + use it.

**`_scored_to_row` private helper in client.py**
- Decision: A private `_scored_to_row(s: ScoredListing, first_seen, last_seen, status) -> list` helper builds the 16-element row in LISTINGS_HEADERS order; `pros` and `cons` are joined as `"; ".join(...)`.
- Rationale: Centralizes row serialization; makes it unit-testable independently of gspread mocks; prevents column-order drift across the upsert logic.

**bootstrap() raises on header mismatch (SheetSchemaError)**
- Decision: Never silently overwrite existing sheet data; raise `SheetSchemaError` on mismatch.
- Rationale: Protects user data. Operator must manually reconcile or add a `--force-bootstrap` flag (future enhancement, out of scope for MVP).

**Removed-listing resurrection**
- Decision: If a listing previously marked `status=removed` reappears in a scrape run, set `status=active`.
- Rationale: Listings can be temporarily pulled and re-listed; treating this as a new listing would duplicate rows.

## Constraints

- Real network is forbidden in `tests/` — fixtures only.
- Integration tests (`tests_integration/`) touch real Sheets only when `INTEGRATION_TESTS=1` and `INTEGRATION_SHEET_ID` are set.
- No proxy rotation or CAPTCHA solving in scope.
- OpenAI paid tier (≥500 RPM) is required; free tier (3 RPM) will cause runs to exceed the 1800s systemd timeout at 200 listings with Semaphore(5).
- Python 3.11+ required locally and on Hetzner.
- `asyncio_mode = "auto"` must be set in `pyproject.toml` from Step 1; without it, async tests silently pass unchecked in pytest-asyncio 0.23+ strict mode.

## Open Questions (carried from draft review — non-blocking)

1. **MINI Hatch model code on autoscout24.com**: AutoScout splits MINI into multiple models. Step 3 URL discovery must determine whether "MINI Hatch 3-door + 5-door" is a single `model=` value, multiple values, or requires `body=hatchback` filter. The actual answer is a runtime artifact the implementing agent locks in during Step 3.

2. **Bucket codes for `miles` and `price`**: These are coded buckets (e.g. `miles=2,3`), not raw values. The implementing agent must discover the exact codes for 20–30k km and ≤23k EUR during Step 3 URL discovery. Wrong codes silently return zero listings; only `EmptyResultsError` flags this at runtime. Open question: should the URL builder validate against a known-good code dictionary?

3. **Spreadsheet ownership**: Should `bootstrap()` be allowed to run on an existing sheet with non-matching headers (overwrite)? Current plan errs on safe side (raise `SheetSchemaError`). A `--force-bootstrap` flag could be added in a future iteration.

4. **Integration test sheet bootstrapping**: Plan opts for a fixed test sheet via `INTEGRATION_SHEET_ID` with a session-scoped pre/post-clean fixture, rather than creating a fresh sheet via Drive API per session. Acceptable trade-off for MVP.

5. **OpenAI tier**: README documents that paid tier (≥500 RPM) is required. User should confirm account tier before first production run.

## Amendments Applied

- `ScoredListing` field convention made explicit: NESTED layout (`listing: Listing`, `score: ListingScore`, `scored_at: datetime`) with access pattern `s.listing.price_eur`, `s.score.score`. Documented in Decisions and propagated to Steps 2/4/5/7 task acceptance criteria.
- Step 4 `_scored_to_row` helper made explicit: private method `_scored_to_row(s: ScoredListing, first_seen, last_seen, status) -> list`; builds 16-element row in LISTINGS_HEADERS order; pros/cons joined as `"; ".join(...)`; must have a dedicated unit test. Added as Task 4.4 in tasks.md.
- Step 8 `install.sh`: changed `libxcomposite1` to `libxcomposite1t64` (Ubuntu 24.04 ARM64 t64 variant). Also noted in the deploy plan that `libgtk-3-0t64` and `libxt6t64` are the t64 equivalents for the same distro.
