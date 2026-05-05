# Detail Page Fetch + Enrichment — Context

## SESSION PROGRESS (2026-05-05)

### COMPLETED
- Step 2: Added 4 optional enrichment fields to `Listing` (`equipment: list[str] = []`, `exterior_color`, `interior_color`, `upholstery: str | None = None`); added `TestListingEnrichmentFields` with 21 tests to `tests/test_models.py`; 65/65 model tests pass; 142/143 full-suite tests pass (1 stale synthetic fixture failure in `test_scraper_parse.py` expected at this stage, to be fixed in Step 3).
- Step 4: Added `BrowserSession` async context manager to `scraper/fetch.py`; created `tests/test_scraper_fetch.py` with 7 tests covering CM lifecycle (open/close once), sequential multi-fetch, HTML return, `state="attached"` selector wait, page close, and tenacity retry on `PlaywrightTimeoutError`; `fetch_page_html` untouched.

- Step 5: Created `src/autoscout_pipeline/scraper/enrich.py` with `enrich_with_details` (circuit breaker threshold=5, in-place mutation, one BrowserSession reused); added `as24_enrich: bool = True` to `Settings` in `config.py`; updated `.env.example`; created `tests/test_scraper_enrich.py` with 15 tests covering empty-list, startup log, success path (single+multi+in-place+one-session), per-listing exception handling, throttle sleep, circuit-breaker trips, and circuit-breaker reset; 183/183 tests pass.
- Step 6: Wired `enrich_with_details` into `pipeline.run()` (gated on `settings.as24_enrich`); added `_is_automatic()` (reads `raw["vehicle"]["transmission"]`, AUTOMATIC_TOKENS includes steptronic/s tronic) and `_is_base_cooper()` (token split on `[\s\-./]+`, rejects s/se/sd/sds/jcw and john-cooper-works) filters before dedup; added enrich passthrough patch to `scripts/smoke.py`; updated all existing async tests with enrich passthrough patch; added `as24_throttle_min/max` defaults to `_make_settings()`; 207/207 tests pass, smoke OK.

- Step 8: Grep sweep confirmed zero AS24-DETAIL-001/19900/22500 refs in tests/src/scripts; ruff: 13 auto-fixed (UP0xx, F401, F541) + 2 manual fixes (RUF005 iterable unpack, RUF002 EN-dash docstring); README.md: added AS24_ENRICH env-var row + Detail-Page Enrichment section; dev/codebase-map.md: added enrich.py, BrowserSession, enrichment-aware prompt.py, test_scraper_fetch.py, test_scraper_enrich.py, Key Decisions entries, bumped test count to 207, Last Updated to 2026-05-05; 207 tests pass, smoke OK; committed on branch worktree-agent-a01bc2f0a28b3b6b6.

### IN PROGRESS
- All steps complete

### BLOCKERS
- None

## Quick Resume

1. Read this file.
2. Check `detail-page-fetch-tasks.md` for what's next.
3. Read `detail-page-fetch-plan.md` Phase 1 for strategy.
4. Start with: write `scripts/recon_detail.py`, run it against the live site, commit `tests/fixtures/autoscout_listing_detail.html` and `dev/active/detail-page-fetch/recon-notes.md`.

## Key Files

**`scripts/recon_detail.py`**
- Role: One-shot live recon tool — fetches one detail page, writes real HTML fixture and structured schema notes.
- Planned change: Create from scratch; mirror `scripts/capture_fixtures.py` pattern.
- Status: NOT STARTED

**`dev/active/detail-page-fetch/recon-notes.md`**
- Role: Schema documentation (JSON paths, shapes, excerpts) that Steps 3 and 5 read as single source of truth.
- Planned change: Created by running `recon_detail.py`; must follow the required templated format.
- Status: NOT STARTED

**`tests/fixtures/autoscout_listing_detail.html`**
- Role: HTML fixture for all detail-parser tests.
- Planned change: Overwrite synthetic fixture with live capture from Step 1.
- Status: NOT STARTED

**`src/autoscout_pipeline/models.py`**
- Role: Pydantic v2 `Listing` model.
- Planned change: Add `equipment: list[str] = Field(default_factory=list)`, `exterior_color: str | None = None`, `interior_color: str | None = None`, `upholstery: str | None = None`. Do NOT add `transmission` — it stays in `raw["vehicle"]["transmission"]`.
- Status: NOT STARTED

**`src/autoscout_pipeline/scraper/fetch.py`**
- Role: Low-level HTML fetchers.
- Planned change: Add `BrowserSession` async-CM that wraps a single Camoufox instance lifetime; `fetch_page_html` untouched.
- Status: DONE (Step 4)

**`src/autoscout_pipeline/scraper/parse.py`**
- Role: HTML/JSON parsers including `parse_listing_detail`.
- Planned change: Rewrite `parse_listing_detail` using real JSON paths from recon-notes.md; add private `_flatten_equipment(raw) -> list[str]`.
- Status: NOT STARTED

**`src/autoscout_pipeline/scraper/enrich.py`**
- Role: New module — sequential detail-page enrichment with circuit breaker.
- Planned change: Create from scratch; exports `enrich_with_details(listings, throttle_min, throttle_max, session=None)`.
- Status: NOT STARTED

**`src/autoscout_pipeline/config.py`**
- Role: Pydantic-settings `Settings` class.
- Planned change: Add `as24_enrich: bool = Field(True, ...)`.
- Status: NOT STARTED

**`src/autoscout_pipeline/pipeline.py`**
- Role: Top-level `run()` orchestrator.
- Planned change: Add transmission filter + base-Cooper filter (after existing CONTAINS/EXCLUDES); wire `enrich_with_details` between dedup and scoring; gate on `settings.as24_enrich`.
- Status: NOT STARTED

**`src/autoscout_pipeline/scoring/prompt.py`**
- Role: Builds LLM user and system prompts.
- Planned change: Extend `render_listing` to emit `exterior_color`, `interior_color`, `upholstery`, `equipment_list` (joined `; `); keep `model_text` as tail fallback; update system prompt.
- Status: NOT STARTED

**`brief.md`**
- Role: LLM scoring rubric consumed at runtime.
- Planned change: Raise baseline to 6; light-blue strict earns +1 only; other bonuses +0.5–+1; calibration example at final score 6; dealbreakers kept as defence-in-depth.
- Status: NOT STARTED

**`scripts/smoke.py`**
- Role: Offline smoke test for the pipeline.
- Planned change: Add mandatory passthrough patch for `autoscout_pipeline.pipeline.enrich_with_details` using exact form `new_callable=AsyncMock, side_effect=lambda lst, **kw: lst`.
- Status: NOT STARTED

**`tests/test_scraper_fetch.py`** (new)
- Role: Unit tests for `BrowserSession`.
- Planned change: Create; ~4 tests; mock `AsyncCamoufox`.
- Status: DONE (Step 4) — 7 tests created and passing

**`tests/test_scraper_enrich.py`** (new)
- Role: Unit tests for `enrich_with_details`.
- Planned change: Create; ~8 tests including circuit-breaker and reset scenarios.
- Status: NOT STARTED

## Decisions

**Transmission field placement — Option A (raw dict only)**
- Decision: `transmission` is NOT added to the `Listing` model. It is read from `listing.raw["vehicle"]["transmission"]` in both the pipeline filter and the existing `render_listing`.
- Rationale: Option A keeps Step 2's surface tight at 4 fields. `ConfigDict(extra="ignore")` would silently swallow a `transmission=` constructor kwarg, making tests that rely on that pattern pass for the wrong reason. The `raw` dict is already present and used by `prompt.py`.

**Transmission filter — AUTOMATIC_TOKENS substring match**
- Decision: Keep if `any(tok in transmission.lower() for tok in AUTOMATIC_TOKENS)` where `AUTOMATIC_TOKENS = ("automatic", "automatik", "automat", "dkg", "dct", "dsg", "stronic", "tiptronic")`. Unknown/missing transmission → keep defensively (LLM still sees the field).
- Rationale: Catches all known DCT/DSG marketing names. `"Halbautomatik"` matches `"automatik"` and is kept (acceptable — functionally automatic for the buyer). `"Schaltgetriebe"` / `"Manuell"` / `"Manual"` match nothing → correctly dropped.

**Base-Cooper tokenizer — regex split on `[\s\-./]+`**
- Decision: `re.split(r"[\s\-./]+", model.lower())` to catch `Cooper-S`, `Cooper.S`, `Cooper/S` in addition to space-separated forms. Reject if any token is in `{"s", "se", "sd", "sds", "jcw"}` or if model contains `"john cooper works"`.
- Rationale: Hyphen is the most common separator in slug-form model names; dot and slash also appear. The no-separator form `CooperS` is an acknowledged edge case deferred to v2.

**Circuit breaker semantics**
- Decision: Threshold of 5 = 5 outer failures = 15 total page-load attempts (after tenacity's internal 3x retry is exhausted). Non-network exceptions (KeyError, ValueError, generic Exception) do NOT increment the consecutive counter — only `NextDataMissingError` / `PlaywrightTimeoutError` do.
- Rationale: 5 outer failures is a strong signal of a sustained block rather than transient noise. Non-network parse errors are bugs, not Akamai blocks, and should not abort enrichment.

**Sheets schema unchanged**
- Decision: `LISTINGS_HEADERS` (16 cols) is not modified. Equipment and colour live only in memory for the duration of a pipeline run.
- Rationale: No spreadsheet schema migration needed; existing user spreadsheet is uninterrupted. Auditable equipment data deferred to a later iteration.

**Enrichment mutates listings in place**
- Decision: `enrich_with_details` assigns fields directly onto input `Listing` objects and returns the same list.
- Rationale: Simpler; Pydantic v2 allows attribute assignment by default. If immutability is preferred in future, switch to `model_copy(update=...)`.

**Colour bonus — light-blue strict only**
- Decision: Only `Hellblau` / `Island Blue` / `Iceberg Blue` / `Electric Blue` / `Light Blue` / `Light-Blue Metallic` / `LightBlueMetallic` earn +1. Other blue-family colours (Blue, Blau, British Racing Blue, Midnight Blue, etc.) earn +0 but are mentioned in pros text. No additive loose-blue bonus.
- Rationale: Eliminates double-counting; calibration example (plain "Blue" exterior) scores exactly 6 + 0 = 6 as required.

**Single throttle window**
- Decision: `enrich_with_details` reuses `settings.as24_throttle_min` / `as24_throttle_max`. No separate `as24_detail_throttle_min/max`.
- Rationale: Same anti-bot risk class; simpler config surface. Can be split later if Akamai blocks specifically during enrichment.

**Smoke patch exact form**
- Decision: `patch("autoscout_pipeline.pipeline.enrich_with_details", new_callable=AsyncMock, side_effect=lambda lst, **kw: lst)`.
- Rationale: `new=AsyncMock(...)` creates a shared instance (assertion footguns); bare `AsyncMock(side_effect=...)` hits a subtle pytest-asyncio coroutine-vs-callable issue. The `new_callable` form is the correct idiomatic pattern.

**No integration tests**
- Decision: Integration tests are not written. Live-network tests are banned (Akamai breaks CI). Unit tests with mocked `BrowserSession` cover the enrichment path end-to-end.
- Rationale: `enrich_with_details` introduces no published contract. The Step 1 recon script is a developer/operator tool run manually, not in CI.
