# AutoScout24 MINI Pipeline — Plan

## Executive Summary

Build a daily Python pipeline that scrapes AutoScout24 for MINI Hatch listings (mileage 20–30k km, price ≤ 23k EUR, DE/AT/CH), extracts structured data from Next.js SSR pages via `__NEXT_DATA__`, scores each listing with OpenAI GPT-4.1 nano through `instructor`, persists results to Google Sheets (three-tab schema with dedup and price history), notifies Telegram when score ≥ 8, and runs daily on a Hetzner CAX11 VPS via systemd timer. Browser stack is `cloverlabs-camoufox` (the actively maintained fork of camoufox) from day 1; scoring brief is configurable via `brief.md`.

## Current State

The repo is essentially empty: only `research_autoscout24.md` (the architecture brief, in Russian) at the root and a `.git` directory. There is no existing code, no `pyproject.toml`, no `.claude/skills/` directory. Every step is greenfield.

The research doc assumes `autoscout24.ru` + `curl_cffi` + Claude Haiku. User overrides supersede it: canonical autoscout24.com domain, `cloverlabs-camoufox` from day 1, OpenAI GPT-4.1 nano, configurable scoring brief.

## Proposed Approach

10 steps in 5 waves:
- **Wave 1** (sequential): Step 1 — project bootstrap
- **Wave 2** (after 1): Step 2 — Pydantic models
- **Wave 3** (parallel, after 2): Steps 3, 4, 5, 6 — scraper, sheets adapter, LLM scorer, Telegram notifier
- **Wave 4** (after 3+4+5+6): Step 7 — pipeline orchestrator
- **Wave 5** (parallel, after 7): Steps 8, 9, 10 — deploy artifacts, smoke script, integration tests

Key architectural decisions:
- `cloverlabs-camoufox` (not classic camoufox), `geoip=True`, `wait_until="networkidle"` + explicit `wait_for_selector('script#__NEXT_DATA__')` — required because `__NEXT_DATA__` is injected client-side after Next.js hydration.
- `instructor` locked to `Mode.TOOLS` (not `TOOLS_STRICT`, `JSON_SCHEMA`, or `RESPONSES_TOOLS*`); `AsyncOpenAI` client (not synchronous).
- `ScoredListing` uses NESTED composition: `listing: Listing`, `score: ListingScore`, `scored_at: datetime`. Access pattern: `s.listing.price_eur`, `s.score.score`. Steps 2/4/7 must stay consistent with this layout.
- 16-column `LISTINGS_HEADERS` schema; `score` is at 0-based index 11, column letter **L** (NOT K). All formatting ranges, tests, and comments must reference L.
- Dedup before scoring: `sheets.get_existing_ids()` called before LLM, so already-known listings are never re-scored (cost control).
- All gspread operations use batch APIs (`append_rows`, `batch_update`) — never per-cell loops.

## Implementation Phases

### Phase 1: Project Bootstrap (~1h)
**Goal:** Initialize uv project with package skeleton, tooling, and stubs so subsequent steps can land in parallel.

- [ ] 1.1 Run `uv init --package autoscout_pipeline --lib` to create src-layout
  - File: `pyproject.toml`
  - Acceptance: `uv sync` returns 0; `uv run python -c "import autoscout_pipeline"` succeeds

- [ ] 1.2 Add all runtime and dev dependencies to `pyproject.toml`
  - File: `pyproject.toml`
  - Acceptance: includes `cloverlabs-camoufox[geoip]>=0.5,<0.6`, `instructor>=1.15,<2`, `gspread>=6.1.4`, and all others from the plan; `asyncio_mode = "auto"` pytest block present

- [ ] 1.3 Create package stub files: `__init__.py` for each subpackage, `config.py` (Settings via pydantic-settings), `models.py` (empty), `pipeline.py` (no-op stub), `logging_setup.py` (JSON-line logger)
  - Files: `src/autoscout_pipeline/{__init__,config,models,pipeline,logging_setup}.py`, `src/autoscout_pipeline/{scraper,scoring,sheets,notify}/__init__.py`
  - Acceptance: all imports resolve; `uv run ruff check .` returns 0

- [ ] 1.4 Create tooling and support files: `.python-version` (3.11), `.gitignore`, `.env.example` (all env vars listed), `brief.md` (placeholder text), `ruff.toml`, `README.md` skeleton, `tests/__init__.py`, `tests/conftest.py`, `tests_integration/__init__.py`
  - Files: listed above
  - Acceptance: `uv run pytest -q` runs zero tests cleanly and exits 0

### Phase 2: Pydantic Models (~1h)
**Goal:** Implement the canonical data model consumed by all other modules.

- [ ] 2.1 Implement `Listing`, `ListingScore`, `ScoredListing`, `RunRecord`, `PriceChange` in `models.py`
  - File: `src/autoscout_pipeline/models.py`
  - Acceptance: all five models importable from `autoscout_pipeline.models`; `ScoredListing` has fields `listing: Listing`, `score: ListingScore`, `scored_at: datetime` (NESTED layout)

- [ ] 2.2 Write `tests/test_models.py` with round-trip, validator, and composition tests
  - File: `tests/test_models.py`
  - Acceptance: `uv run pytest tests/test_models.py -v` — 5+ tests pass including `ListingScore` rejects score=0/11, `PriceChange` rejects equal prices, `RunRecord.notes` truncated at 500 chars, `ScoredListing` round-trips and `scored_at` is timezone-aware

### Phase 3: Scraper Module (~3h)
**Goal:** Implement camoufox-backed fetcher, `__NEXT_DATA__` extractor, listing parser, and search iterator; populate fixture HTML files.

- [ ] 3.1 Implement `scraper/errors.py` (`NextDataMissingError`, `EmptyResultsError`)
  - File: `src/autoscout_pipeline/scraper/errors.py`
  - Acceptance: importable

- [ ] 3.2 Implement `scraper/fetch.py` — camoufox wrapper with `networkidle` + selector wait, tenacity retry
  - File: `src/autoscout_pipeline/scraper/fetch.py`
  - Acceptance: code has comment explaining why `networkidle` is required; retry on `PlaywrightTimeoutError` (3 attempts, exponential backoff)

- [ ] 3.3 Implement `scraper/parse.py` — `extract_next_data(html) -> dict`, `parse_listings_page(data) -> list[Listing]`, `parse_listing_detail(data) -> Listing`
  - File: `src/autoscout_pipeline/scraper/parse.py`
  - Acceptance: pure functions; `NextDataMissingError` raised + raw HTML saved to `/tmp/as24_dump_<ts>.html` when script tag absent; tries both `pageProps.listings` and `pageProps.initialState.search.results` paths

- [ ] 3.4 Discover autoscout24.com URL parameter codes (manual step), then implement `scraper/search.py` — `build_search_url(page)` and `iter_listings(criteria)` async generator
  - File: `src/autoscout_pipeline/scraper/search.py`
  - Acceptance: module-level docstring records the discovered URL template, discovery date, and note that `miles`/`price` are coded buckets; polite throttle between pages using `AS24_THROTTLE_MIN`/`AS24_THROTTLE_MAX`

- [ ] 3.5 Create `scripts/capture_fixtures.py` and populate fixture HTML files
  - Files: `scripts/capture_fixtures.py`, `tests/fixtures/autoscout_listings_page1.html`, `tests/fixtures/autoscout_listings_no_next_data.html`, `tests/fixtures/autoscout_listing_detail.html`, `tests/fixtures/README.md`
  - Acceptance: fixtures committed; `autoscout_listings_no_next_data.html` has the `__NEXT_DATA__` script tag stripped

- [ ] 3.6 Write `tests/test_scraper_parse.py` and `tests/test_scraper_search.py`
  - Files: `tests/test_scraper_parse.py`, `tests/test_scraper_search.py`
  - Acceptance: `uv run pytest tests/test_scraper_parse.py tests/test_scraper_search.py -v` passes; includes `test_extract_next_data_raises_on_missing_script_tag` and URL builder tests

### Phase 4: Sheets Adapter (~3h)
**Goal:** Implement gspread-backed SheetsClient with idempotent bootstrap, dedup, batch upsert, and conditional formatting on column L.

- [ ] 4.1 Implement `sheets/schema.py` — header lists, tab name constants, `SCORE_COLUMN_LETTER = "L"`
  - File: `src/autoscout_pipeline/sheets/schema.py`
  - Acceptance: `LISTINGS_HEADERS` has 16 elements; `LISTINGS_HEADERS.index("score") == 11` (0-based); `SCORE_COLUMN_LETTER = "L"`

- [ ] 4.2 Implement `sheets/formatting.py` — conditional format rules for score column
  - File: `src/autoscout_pipeline/sheets/formatting.py`
  - Acceptance: applies to range `L2:L10000`; four rules (≥8 green, ≥6 yellow, ≥4 none, <4 light red)

- [ ] 4.3 Implement `sheets/client.py` — `SheetsClient` with `bootstrap()`, `get_existing_ids()`, `upsert_listings()`, `record_run()`, `record_price_change()`
  - File: `src/autoscout_pipeline/sheets/client.py`
  - Acceptance: `bootstrap()` is idempotent; raises `SheetSchemaError` on header mismatch; all writes use batch APIs; marks stale rows `status=removed`; resurrects previously-removed listings when they reappear

- [ ] 4.4 Implement `_scored_to_row(s: ScoredListing, first_seen, last_seen, status) -> list` private helper that builds the 16-element row in `LISTINGS_HEADERS` order; `pros`/`cons` joined as `"; ".join(...)`
  - File: `src/autoscout_pipeline/sheets/client.py`
  - Acceptance: helper is private (`_scored_to_row`); produces exactly 16 elements matching `LISTINGS_HEADERS` order; pros/cons are joined strings

- [ ] 4.5 Write `tests/test_sheets_client.py` and `tests/test_sheets_schema.py`
  - Files: `tests/test_sheets_client.py`, `tests/test_sheets_schema.py`
  - Acceptance: all tests pass including `test_score_column_letter_matches_header_index`, `test_bootstrap_applies_conditional_format_to_column_L`, `test_upsert_uses_batch_append`, `test_upsert_resurrects_removed_listing`; add a unit test for `_scored_to_row` verifying element count and pros/cons join format

### Phase 5: LLM Scoring Module (~2h)
**Goal:** Implement instructor-patched AsyncOpenAI scorer with Mode.TOOLS lock, configurable brief, and bounded concurrency.

- [ ] 5.1 Implement `scoring/prompt.py` — system prompt assembly reading `brief.md`
  - File: `src/autoscout_pipeline/scoring/prompt.py`
  - Acceptance: reads brief once at call time; renders listing fields without dumping `raw` dict

- [ ] 5.2 Implement `scoring/scorer.py` — `LLMScorer` with `AsyncOpenAI`, `Mode.TOOLS`, `score()` method, error sentinel
  - File: `src/autoscout_pipeline/scoring/scorer.py`
  - Acceptance: `self._mode is instructor.Mode.TOOLS`; client is `AsyncOpenAI` instance; on API error returns sentinel `ListingScore(score=1, reasoning="LLM scoring failed: <err>", pros=[], cons=[], ...)`

- [ ] 5.3 Implement `scoring/batch.py` — `score_many(listings) -> list[ScoredListing]` with `asyncio.Semaphore(5)`
  - File: `src/autoscout_pipeline/scoring/batch.py`
  - Acceptance: peak concurrent in-flight count never exceeds 5; returns `ScoredListing` objects with NESTED layout (`s.listing`, `s.score`, `s.scored_at`)

- [ ] 5.4 Write `tests/test_scoring.py`
  - File: `tests/test_scoring.py`
  - Acceptance: `uv run pytest tests/test_scoring.py -v` passes; includes `test_scorer_pins_mode_to_tools` (enum identity), `test_scorer_uses_async_openai_client` (class identity), `test_score_many_respects_semaphore`, `test_render_listing_excludes_raw_dict`

### Phase 6: Telegram Notifier (~1h)
**Goal:** Implement score-gated Telegram notifier using httpx with HTML escaping.

- [ ] 6.1 Implement `notify/telegram.py` — `TelegramNotifier.send()` and `send_batch()` with html.escape on all interpolated fields
  - File: `src/autoscout_pipeline/notify/telegram.py`
  - Acceptance: threshold gate works; 10s timeout; network errors logged as warning and swallowed; `send_batch` sends sequentially with 0.5s delay

- [ ] 6.2 Write `tests/test_notify.py`
  - File: `tests/test_notify.py`
  - Acceptance: `uv run pytest tests/test_notify.py -v` passes; includes `test_send_escapes_reasoning_html` and `test_send_swallows_network_error`

### Phase 7: Pipeline Orchestrator (~2h)
**Goal:** Wire all modules into a working async orchestrator with Typer CLI and dry-run support.

- [ ] 7.1 Implement `pipeline.py` — `async def run(settings, dry_run)` and Typer `cli()` entrypoint
  - File: `src/autoscout_pipeline/pipeline.py`
  - Acceptance: sequence is: configure logging → bootstrap sheets → iterate listings → dedup via `get_existing_ids()` → score new only → upsert → record run → notify; `--dry-run` skips all writes and notifications; uses `ScoredListing` NESTED layout throughout (`s.listing.*`, `s.score.*`)

- [ ] 7.2 Write `tests/test_pipeline.py`
  - File: `tests/test_pipeline.py`
  - Acceptance: `uv run pytest tests/test_pipeline.py -v` passes; includes dedup test (2 of 3 listings scored when 1 already in sheet), scrape-error test (RunRecord.errors=1), threshold test (only score=9 notified among 5/7/9)

### Phase 8: Deployment Artifacts (~2h)
**Goal:** Produce systemd unit+timer, idempotent install.sh for Hetzner CAX11 ARM64, and complete README documentation.

- [ ] 8.1 Author `deploy/autoscout-pipeline.service` and `deploy/autoscout-pipeline.timer`
  - Files: `deploy/autoscout-pipeline.service`, `deploy/autoscout-pipeline.timer`
  - Acceptance: `systemd-analyze verify` returns no errors; timer fires at 03:15 UTC with `RandomizedDelaySec=600`; service has `TimeoutStartSec=1800`

- [ ] 8.2 Author `deploy/install.sh` — idempotent, ARM64-aware, downloads camoufox binary
  - File: `deploy/install.sh`
  - Acceptance: `bash -n deploy/install.sh` (syntax check) passes; uses `libxcomposite1t64` (Ubuntu 24.04 ARM64 t64 variant, NOT `libxcomposite1`); includes comment about verifying t64 package names on target system; also uses `libgtk-3-0t64` and `libxt6t64`

- [ ] 8.3 Author `deploy/README.md` and update top-level `README.md`, create `docs/creds.json.example`
  - Files: `deploy/README.md`, `README.md`, `docs/creds.json.example`
  - Acceptance: `deploy/README.md` covers full setup from fresh CAX11 to first dry-run; top-level README has troubleshooting for `NextDataMissingError`, `EmptyResultsError`, `SheetSchemaError`, OpenAI 401, rate-limit timeout, and paid-tier note

### Phase 9: End-to-End Smoke Script (~0.5h)
**Goal:** Provide a fixture-backed local sanity script that exercises the full flow without touching the network.

- [ ] 9.1 Write `scripts/smoke.py`
  - File: `scripts/smoke.py`
  - Acceptance: `uv run python -m scripts.smoke` prints a one-line summary and exits 0 in <30 seconds; uses fixture HTML, mocked AsyncOpenAI, mocked gspread, mocked httpx

### Phase 10: Integration Tests Against Real Sheets (~1.5h)
**Goal:** Verify the Sheets published contract end-to-end against a live disposable test spreadsheet; skippable by default.

- [ ] 10.1 Write `tests_integration/conftest.py` — global skipif marker + session-scoped pre/post-clean fixture
  - File: `tests_integration/conftest.py`
  - Acceptance: without `INTEGRATION_TESTS=1` and `INTEGRATION_SHEET_ID`, all tests skip and exit 0

- [ ] 10.2 Write `tests_integration/test_sheets_live.py` — bootstrap idempotency, upsert+price-change, run record, conditional formatting on column L
  - File: `tests_integration/test_sheets_live.py`
  - Acceptance: with env + creds all tests pass; `test_conditional_formatting_applied_once_to_column_L` confirms rule range contains `L2:L`

## Key Files Affected

| File | Change | Why |
|------|--------|-----|
| `pyproject.toml` | Create | uv project manifest; all deps declared here |
| `src/autoscout_pipeline/models.py` | Create | Canonical data model for whole pipeline |
| `src/autoscout_pipeline/config.py` | Create | Single Settings class via pydantic-settings |
| `src/autoscout_pipeline/pipeline.py` | Create | Orchestrator and CLI entrypoint |
| `src/autoscout_pipeline/scraper/fetch.py` | Create | camoufox wrapper; networkidle + selector wait |
| `src/autoscout_pipeline/scraper/parse.py` | Create | Pure HTML/JSON parse functions |
| `src/autoscout_pipeline/scraper/search.py` | Create | URL builder + async listing iterator |
| `src/autoscout_pipeline/scraper/errors.py` | Create | NextDataMissingError, EmptyResultsError |
| `src/autoscout_pipeline/sheets/client.py` | Create | gspread wrapper; bootstrap, dedup, upsert |
| `src/autoscout_pipeline/sheets/schema.py` | Create | LISTINGS_HEADERS (16 cols), SCORE_COLUMN_LETTER="L" |
| `src/autoscout_pipeline/sheets/formatting.py` | Create | Conditional format rules for column L |
| `src/autoscout_pipeline/scoring/scorer.py` | Create | LLMScorer; AsyncOpenAI + instructor Mode.TOOLS |
| `src/autoscout_pipeline/scoring/batch.py` | Create | score_many; Semaphore(5) concurrency |
| `src/autoscout_pipeline/scoring/prompt.py` | Create | System prompt; reads brief.md |
| `src/autoscout_pipeline/notify/telegram.py` | Create | TelegramNotifier; html.escape; score gate |
| `src/autoscout_pipeline/logging_setup.py` | Create | JSON-line logger to stdout |
| `tests/fixtures/autoscout_listings_page1.html` | Create | Real captured HTML (must be committed) |
| `tests/fixtures/autoscout_listings_no_next_data.html` | Create | Synthetic fixture for missing-tag error path |
| `tests/fixtures/autoscout_listing_detail.html` | Create | Real detail page capture |
| `brief.md` | Create | Placeholder scoring brief; user replaces |
| `deploy/autoscout-pipeline.service` | Create | systemd service unit |
| `deploy/autoscout-pipeline.timer` | Create | systemd timer (03:15 UTC daily) |
| `deploy/install.sh` | Create | ARM64-aware idempotent install script |
| `deploy/README.md` | Create | Full Hetzner deploy guide |
| `README.md` | Create | Project overview, quickstart, troubleshooting |
| `docs/creds.json.example` | Create | Service-account JSON shape stub |
| `scripts/capture_fixtures.py` | Create | Camoufox-backed fixture capture tool |
| `scripts/smoke.py` | Create | Fixture-backed end-to-end sanity script |
| `tests_integration/conftest.py` | Create | Skippable integration test config |
| `tests_integration/test_sheets_live.py` | Create | Live Sheets integration tests |

## Dependencies & Order Constraints

- Step 1 must complete before everything else (package skeleton).
- Step 2 must complete before Steps 3, 4, 5, 6 (all import from `models.py`).
- Steps 3, 4, 5, 6 can run in parallel after Step 2.
- Step 7 depends on Steps 3+4+5+6 all being complete.
- Steps 8, 9, 10 can run in parallel after Step 7.
- Fixtures in Step 3 are a prerequisite for parse tests; `capture_fixtures.py` must be run before tests are written.

## Risks

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| autoscout24.com changes Next.js page structure | Medium | High | capture_fixtures.py; clear error class; fixture README |
| URL bucket codes for miles/price change silently | Medium | High | EmptyResultsError; discovery documented in search.py docstring |
| MINI Hatch model code discovery yields ambiguous results | Medium | Medium | Fall back to brand=MINI + body_type=hatchback filter |
| Akamai blocks camoufox | Low | High | Documented as accepted risk for MVP; no proxies in scope |
| cloverlabs-camoufox arm64 missing system libs | Medium | Medium | install.sh lists t64 variants; comment to verify on target |
| instructor API changes between minor versions | Low | Medium | Pinned to `>=1.15,<2` |
| Future agent changes Mode.TOOLS to TOOLS_STRICT | Low | High | test_scorer_pins_mode_to_tools (enum identity) fails immediately |
| gspread get_all_records() slow at >10k rows | Low | Low | Documented; acceptable at MVP scale |
| OpenAI free tier (3 RPM) exceeds systemd timeout | Medium | Medium | README documents paid-tier requirement |
| Forgetting asyncio_mode="auto" silently skips async tests | Low | High | Set in pyproject.toml at Step 1; caught by async test in Step 5 |

## Out of Scope

- Proxy rotation or CAPTCHA solving (anti-bot risk accepted for MVP)
- CI/CD pipeline beyond local `uv run pytest`
- Scraper integration tests against live AutoScout24 (too flaky, anti-bot risk)
- Live OpenAI or Telegram tests
- Multiple make/model targets (MVP is MINI Hatch only)
- Creating the Google Sheets spreadsheet programmatically (manual step; bootstrap only creates tabs)
- Creating the Hetzner VPS programmatically (manual step documented in deploy/README.md)

## Timeline

- Phase 1: ~1h
- Phase 2: ~1h
- Phase 3: ~3h
- Phase 4: ~3h
- Phase 5: ~2h
- Phase 6: ~1h
- Phase 7: ~2h
- Phase 8: ~2h
- Phase 9: ~0.5h
- Phase 10: ~1.5h
- Total: ~17h (parallel waves; critical path is ~11h: 1+1+3+2+2+2)
- Created: 2026-05-01
