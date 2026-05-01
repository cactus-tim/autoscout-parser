# AutoScout24 MINI Pipeline — Tasks

## Phase 1: Project Bootstrap — NOT STARTED
- [ ] 1.1 Run `uv init --package autoscout_pipeline --lib` to create src-layout — `pyproject.toml`
  - Acceptance: `uv sync` returns 0; `uv run python -c "import autoscout_pipeline"` succeeds
- [ ] 1.2 Add all runtime and dev dependencies to `pyproject.toml`; include `asyncio_mode = "auto"` pytest block — `pyproject.toml`
  - Acceptance: includes `cloverlabs-camoufox[geoip]>=0.5,<0.6`, `instructor>=1.15,<2`, `gspread>=6.1.4`, and all others; pytest asyncio_mode block present
- [ ] 1.3 Create package stub files: `__init__.py` for each subpackage, `config.py` (Settings), `models.py` (empty), `pipeline.py` (no-op), `logging_setup.py` (JSON-line logger) — `src/autoscout_pipeline/`
  - Acceptance: all imports resolve; `uv run ruff check .` returns 0
- [ ] 1.4 Create support files: `.python-version`, `.gitignore`, `.env.example`, `brief.md` (placeholder), `ruff.toml`, `README.md` skeleton, `tests/__init__.py`, `tests/conftest.py`, `tests_integration/__init__.py` — repo root + tests/
  - Acceptance: `uv run pytest -q` runs zero tests and exits 0

## Phase 2: Pydantic Models — NOT STARTED
- [ ] 2.1 Implement `Listing`, `ListingScore`, `ScoredListing` (NESTED: `listing: Listing`, `score: ListingScore`, `scored_at: datetime`), `RunRecord`, `PriceChange` — `src/autoscout_pipeline/models.py`
  - Acceptance: all five importable from `autoscout_pipeline.models`; ScoredListing has NESTED layout; all datetimes are timezone-aware UTC
- [ ] 2.2 Write round-trip, validator, and composition tests — `tests/test_models.py`
  - Acceptance: `uv run pytest tests/test_models.py -v` — 5+ tests pass; ListingScore rejects score=0/11; PriceChange rejects equal prices; RunRecord.notes truncated at 500 chars; ScoredListing scored_at is timezone-aware

## Phase 3: Scraper Module — NOT STARTED
- [ ] 3.1 Implement `NextDataMissingError`, `EmptyResultsError` — `src/autoscout_pipeline/scraper/errors.py`
  - Acceptance: importable
- [ ] 3.2 Implement camoufox fetch wrapper with `networkidle` + `wait_for_selector('script#__NEXT_DATA__')` and tenacity retry — `src/autoscout_pipeline/scraper/fetch.py`
  - Acceptance: code comment explains why networkidle is required; retry on PlaywrightTimeoutError (3 attempts, exponential backoff 2–15s)
- [ ] 3.3 Implement `extract_next_data(html) -> dict`, `parse_listings_page(data) -> list[Listing]`, `parse_listing_detail(data) -> Listing` — `src/autoscout_pipeline/scraper/parse.py`
  - Acceptance: pure functions; NextDataMissingError raised + raw HTML saved to `/tmp/as24_dump_<ts>.html` on missing tag; tries `pageProps.listings` then `pageProps.initialState.search.results` paths; logs which path matched
- [ ] 3.4 Discover autoscout24.com URL parameter codes (manual step), then implement `build_search_url(page)` and `iter_listings()` async generator — `src/autoscout_pipeline/scraper/search.py`
  - Acceptance: module-level docstring records discovered URL template, discovery date, and note that `miles`/`price` are coded buckets; polite throttle between pages using AS24_THROTTLE_MIN/MAX from config
- [ ] 3.5 Create `scripts/capture_fixtures.py` and populate fixture HTML files — `scripts/capture_fixtures.py`, `tests/fixtures/`
  - Acceptance: `tests/fixtures/autoscout_listings_page1.html` (real, post-hydration), `tests/fixtures/autoscout_listings_no_next_data.html` (synthetic, __NEXT_DATA__ tag stripped), `tests/fixtures/autoscout_listing_detail.html`, `tests/fixtures/README.md` all committed
- [ ] 3.6 Write parse tests (fixture-based, no network) and URL builder unit tests — `tests/test_scraper_parse.py`, `tests/test_scraper_search.py`
  - Acceptance: `uv run pytest tests/test_scraper_parse.py tests/test_scraper_search.py -v` passes; includes `test_extract_next_data_raises_on_missing_script_tag`; parse test asserts ≥10 Listing objects from fixture with price < 23000 and mileage 20000–30000

## Phase 4: Sheets Adapter — NOT STARTED
- [ ] 4.1 Implement header lists, tab name constants, `SCORE_COLUMN_LETTER = "L"` — `src/autoscout_pipeline/sheets/schema.py`
  - Acceptance: LISTINGS_HEADERS has exactly 16 elements; LISTINGS_HEADERS.index("score") == 11 (0-based); SCORE_COLUMN_LETTER = "L"
- [ ] 4.2 Implement conditional format rules applied to range `L2:L10000` — `src/autoscout_pipeline/sheets/formatting.py`
  - Acceptance: four rules in priority order: score ≥8 green, ≥6 yellow, ≥4 none, <4 light red; range string contains "L2:L"
- [ ] 4.3 Implement `SheetsClient` with `bootstrap()`, `get_existing_ids()`, `upsert_listings()`, `record_run()`, `record_price_change()` — `src/autoscout_pipeline/sheets/client.py`
  - Acceptance: bootstrap() idempotent; raises SheetSchemaError on header mismatch; marks stale rows status=removed; resurrects removed listings to status=active; all writes use append_rows / batch_update (no per-cell loops)
- [ ] 4.4 Implement private `_scored_to_row(s: ScoredListing, first_seen, last_seen, status) -> list` helper — `src/autoscout_pipeline/sheets/client.py`
  - Acceptance: returns exactly 16 elements matching LISTINGS_HEADERS order; pros joined as `"; ".join(s.score.pros)`; cons joined as `"; ".join(s.score.cons)`; accesses score via NESTED layout (`s.listing.*`, `s.score.*`)
- [ ] 4.5 Write gspread-mocked unit tests and schema pure-unit tests — `tests/test_sheets_client.py`, `tests/test_sheets_schema.py`
  - Acceptance: `uv run pytest tests/test_sheets_*.py -v` passes; includes `test_score_column_letter_matches_header_index`, `test_bootstrap_applies_conditional_format_to_column_L`, `test_upsert_uses_batch_append`, `test_upsert_resurrects_removed_listing`; includes `test_scored_to_row_builds_16_element_row` and `test_scored_to_row_joins_pros_cons`

## Phase 5: LLM Scoring Module — NOT STARTED
- [ ] 5.1 Implement system prompt assembly reading `brief.md` and listing renderer that excludes `raw` field — `src/autoscout_pipeline/scoring/prompt.py`
  - Acceptance: brief contents appear in system prompt; rendered listing does not include the raw dict
- [ ] 5.2 Implement `LLMScorer` with `AsyncOpenAI` + `instructor.from_openai(..., mode=Mode.TOOLS)`, `score()` method, error sentinel — `src/autoscout_pipeline/scoring/scorer.py`
  - Acceptance: `self._mode is instructor.Mode.TOOLS` (enum identity); underlying client is `AsyncOpenAI` instance; on API error returns sentinel ListingScore(score=1, reasoning="LLM scoring failed: <err>", ...)
- [ ] 5.3 Implement `score_many(listings) -> list[ScoredListing]` with `asyncio.Semaphore(5)` — `src/autoscout_pipeline/scoring/batch.py`
  - Acceptance: peak concurrent in-flight count never exceeds 5; returns ScoredListing with NESTED layout (`s.listing`, `s.score`, `s.scored_at`)
- [ ] 5.4 Write scoring tests with AsyncMock — `tests/test_scoring.py`
  - Acceptance: `uv run pytest tests/test_scoring.py -v` passes; includes `test_scorer_pins_mode_to_tools` (enum identity), `test_scorer_uses_async_openai_client` (class identity), `test_score_many_respects_semaphore`, `test_render_listing_excludes_raw_dict`

## Phase 6: Telegram Notifier — NOT STARTED
- [ ] 6.1 Implement `TelegramNotifier.send()` and `send_batch()` with html.escape on all interpolated fields, 10s timeout, error swallowing — `src/autoscout_pipeline/notify/telegram.py`
  - Acceptance: score < threshold sends no request; network errors logged as warning and not re-raised; send_batch sends sequentially with 0.5s delay; parse_mode="HTML"
- [ ] 6.2 Write httpx-mocked tests via respx — `tests/test_notify.py`
  - Acceptance: `uv run pytest tests/test_notify.py -v` passes; includes `test_send_escapes_reasoning_html` (reasoning with `<script>` appears escaped in payload), `test_send_swallows_network_error`, `test_send_batch_filters_and_sends_only_high_scores`

## Phase 7: Pipeline Orchestrator — NOT STARTED
- [ ] 7.1 Implement `async def run(settings, dry_run)` and Typer `cli()` — `src/autoscout_pipeline/pipeline.py`
  - Acceptance: sequence: configure logging → bootstrap → iterate listings → dedup via get_existing_ids() → score new only → upsert → record_run → notify; --dry-run skips all writes and notifications; uses NESTED ScoredListing access (`s.listing.*`, `s.score.*`); top-level exceptions caught, logged, exit 1
- [ ] 7.2 Write orchestrator tests with all components mocked — `tests/test_pipeline.py`
  - Acceptance: `uv run pytest tests/test_pipeline.py -v` passes; includes `test_pipeline_skips_listings_already_in_sheet` (1 of 3 deduplicated), `test_pipeline_handles_scrape_error` (RunRecord.errors=1), `test_pipeline_only_notifies_above_threshold` (only score=9 notified of 5/7/9), `test_pipeline_dry_run_makes_no_writes`

## Phase 8: Deployment Artifacts — NOT STARTED
- [ ] 8.1 Author `autoscout-pipeline.service` (Type=oneshot, TimeoutStartSec=1800, EnvironmentFile) and `autoscout-pipeline.timer` (03:15 UTC, RandomizedDelaySec=600, Persistent=true) — `deploy/autoscout-pipeline.service`, `deploy/autoscout-pipeline.timer`
  - Acceptance: `systemd-analyze verify deploy/autoscout-pipeline.{service,timer}` returns no errors; both units have [Install] sections
- [ ] 8.2 Author idempotent ARM64-aware `install.sh` — `deploy/install.sh`
  - Acceptance: `bash -n deploy/install.sh` (syntax check) passes; uses `libxcomposite1t64` NOT `libxcomposite1`; also uses `libgtk-3-0t64` and `libxt6t64`; includes comment to verify t64 package names on target; downloads camoufox binary via `python -m camoufox fetch`
- [ ] 8.3 Author `deploy/README.md` (full deploy guide), update `README.md` (project overview, quickstart, GCP steps, Telegram setup, troubleshooting), create `docs/creds.json.example` — `deploy/README.md`, `README.md`, `docs/creds.json.example`
  - Acceptance: README covers troubleshooting for NextDataMissingError, EmptyResultsError, SheetSchemaError, OpenAI 401, rate-limit timeout, and paid-tier requirement; creds.json.example has all standard service-account keys as placeholders

## Phase 9: End-to-End Smoke Script — NOT STARTED
- [ ] 9.1 Write fixture-backed smoke script — `scripts/smoke.py`
  - Acceptance: `uv run python -m scripts.smoke` prints one-line summary and exits 0 in <30 seconds; uses fixture HTML, mocked AsyncOpenAI, mocked gspread, mocked httpx; no assertions (sanity tool, not test)

## Phase 10: Integration Tests Against Real Sheets — NOT STARTED
- [ ] 10.1 Write `conftest.py` with global skipif marker (INTEGRATION_TESTS=1 + INTEGRATION_SHEET_ID required) and session-scoped pre/post-clean fixture — `tests_integration/conftest.py`
  - Acceptance: without env vars, `uv run pytest tests_integration/ -v` reports all skipped, exit 0
- [ ] 10.2 Write live Sheets integration tests — `tests_integration/test_sheets_live.py`
  - Acceptance: with env + creds all tests pass; includes `test_bootstrap_creates_three_tabs_on_real_sheet`, `test_bootstrap_idempotent`, `test_upsert_inserts_then_updates` (price change creates price_history row), `test_record_run_appends_to_runs_tab`, `test_conditional_formatting_applied_once_to_column_L`

---
## Stats
- Total: 22 tasks across 10 phases · ~17h estimated
- Done: 0 / 22

## How to Update
Check off tasks with [x] and update `autoscout-mini-pipeline-context.md` SESSION PROGRESS after each milestone. Update phase headers: all tasks done → "COMPLETE", some done → "IN PROGRESS".
