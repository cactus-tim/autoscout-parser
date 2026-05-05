# Detail Page Fetch + Enrichment — Tasks

## Wave 1

### Step 1: Live Recon — capture and document `listingDetails` schema  (type: simple)  NOT STARTED
- [ ] 1.1 Write `scripts/recon_detail.py`; run against live site; commit HTML fixture + recon-notes.md
  - Files: `scripts/recon_detail.py`, `tests/fixtures/autoscout_listing_detail.html`, `dev/active/detail-page-fetch/recon-notes.md`
  - Acceptance: `python -c "from autoscout_pipeline.scraper.parse import extract_next_data; import pathlib; d = extract_next_data(pathlib.Path('tests/fixtures/autoscout_listing_detail.html').read_text()); print(list(d['props']['pageProps']['listingDetails'].keys()))"` prints a non-trivial key list; `recon-notes.md` has all four field sections + Open issues section; no challenge HTML committed.
  - Depends On: —
  - Can-Parallel-With: —

---

## Wave 2

### Step 2: Extend `Listing` model with optional enrichment fields  (type: tdd)  DONE
- [x] 2.1 Add `equipment`, `exterior_color`, `interior_color`, `upholstery` to `Listing`; write `TestListingEnrichmentFields`
  - Files: `src/autoscout_pipeline/models.py`, `tests/test_models.py`
  - Acceptance: `uv run pytest tests/test_models.py -v` passes; `Listing()` defaults to `equipment == []` and three colour fields `is None`; no existing test broken.
  - Depends On: —
  - Can-Parallel-With: Step 4

### Step 4: Add `BrowserSession` async-CM in `scraper/fetch.py`  (type: tdd)  DONE
- [x] 4.1 Implement `BrowserSession`; write `tests/test_scraper_fetch.py` with ~4 tests
  - Files: `src/autoscout_pipeline/scraper/fetch.py`, `tests/test_scraper_fetch.py`
  - Acceptance: `uv run pytest tests/test_scraper_fetch.py -v` passes (CM lifecycle, two sequential fetches, retry on `PlaywrightTimeoutError`); `fetch_page_html` untouched; mock `AsyncCamoufox`, no live network.
  - Depends On: —
  - Can-Parallel-With: Step 2

---

## Wave 3

### Step 3: Rewrite `parse_listing_detail` for the live schema  (type: tdd)  NOT STARTED
- [ ] 3.1 Rewrite `parse_listing_detail` + add `_flatten_equipment`; rewrite `TestParseListingDetail`
  - Files: `src/autoscout_pipeline/scraper/parse.py`, `tests/test_scraper_parse.py`
  - Acceptance: `uv run pytest tests/test_scraper_parse.py -v` passes with ~7–9 tests; all four enrichment fields populated from live fixture; `raw` preserved on returned `Listing`; no reference to `AS24-DETAIL-001` / `19900` / `22500`; full suite green.
  - Implementation notes:
    - Tests use paths from `recon-notes.md` as source of truth.
    - Use shape/type assertions for equipment items (NOT exact item names — live inventory rotates).
    - `_flatten_equipment` is parametrized over: flat-list[str], list[dict-with-items], missing-key, None.
    - Keep `raw=raw` on returned Listing — required by transmission filter and `render_listing`.
  - Depends On: Step 1, Step 2
  - Can-Parallel-With: Step 4 (if Step 4 already started before Step 3)

---

## Wave 4

### Step 5: Implement `enrich_with_details` + add `as24_enrich` setting  (type: tdd)  DONE
- [x] 5.1 Create `src/autoscout_pipeline/scraper/enrich.py`; add `as24_enrich` to `config.py`; write `tests/test_scraper_enrich.py`
  - Files: `src/autoscout_pipeline/scraper/enrich.py`, `src/autoscout_pipeline/config.py`, `tests/test_scraper_enrich.py`
  - Acceptance: `uv run pytest tests/test_scraper_enrich.py -v` passes with ~8 tests; `Settings.as24_enrich` defaults to `True`; full suite green.
  - Implementation notes:
    - Circuit breaker threshold = 5 outer failures = 15 total page-load attempts; comment in code near `CIRCUIT_BREAKER_THRESHOLD`.
    - Non-network exceptions (`KeyError`, `ValueError`, generic) reset consecutive counter to 0; do NOT trip the breaker.
    - Startup `logger.info` announces expected duration (see plan skeleton).
    - Throttle sleep only between listings, not after the last one.
    - Tests: enrich-all-succeeds, skip-empty-url, continue-on-per-listing-error, throttle-N-minus-1-sleeps, empty-input-no-session, passed-session-reused, circuit-breaker-aborts-at-5, breaker-resets-on-success.
  - Depends On: Step 2, Step 3, Step 4
  - Can-Parallel-With: —

---

## Wave 5 (parallel pair)

### Step 6: Wire enrichment into `pipeline.run()` + transmission and base-Cooper filters  (type: tdd)  DONE
- [x] 6.1 Add two filters + enrichment call to `pipeline.py`; update tests; patch smoke script
  - Files: `src/autoscout_pipeline/pipeline.py`, `tests/test_pipeline.py`, `scripts/smoke.py`
  - Acceptance: `uv run pytest tests/test_pipeline.py -v` passes; `uv run python -m scripts.smoke` reports `OK smoke OK`; checklist below all satisfied.
  - Implementation notes:
    - Filter order: CONTAINS → EXCLUDES → transmission → base-Cooper → dedup → enrich → score.
    - Transmission filter reads `listing.raw["vehicle"]["transmission"]` — NOT `getattr(listing, "transmission", ...)`.
    - Test listings for transmission use `raw={"vehicle": {"transmission": "Manual"}}` constructor — NOT `transmission="Manual"` kwarg (Pydantic `extra="ignore"` silently drops unknown kwargs).
    - Base-Cooper tokenizer: `re.split(r"[\s\-./]+", model.lower())`; reject tokens in `{"s", "se", "sd", "sds", "jcw"}` or literal `"john cooper works"` in string.
    - Passthrough patch for existing tests: `patch("autoscout_pipeline.pipeline.enrich_with_details", new_callable=AsyncMock, side_effect=lambda lst, **kw: lst)` in all 5 existing async tests + `_make_settings` defaults `as24_enrich=True`.
    - Smoke patch exact form: `new_callable=AsyncMock, side_effect=lambda lst, **kw: lst` — NOT `new=AsyncMock(...)`, NOT bare `AsyncMock(side_effect=...)`.
    - New tests: enrich-called-when-setting-true, enrich-skipped-when-setting-false, transmission-drops-manual (Manual/Manuell/Schaltgetriebe), transmission-keeps-automatic (Automatic/Automatik/DKG/DCT/DSG/Steptronic/Tiptronic/Halbautomatik/None-raw), base-Cooper-parametrized-11-cases, filter-ordering-log-funnel.
  - Verification checklist:
    - [ ] Transmission test listings constructed with `raw={"vehicle": {"transmission": "..."}}`.
    - [ ] Base-Cooper parametrized test includes `Cooper.S` and `Cooper/S`.
    - [ ] Smoke patch uses `new_callable=AsyncMock`, not `new=AsyncMock(...)` and not bare `AsyncMock(side_effect=...)`.
    - [ ] All four filter log lines at `INFO`.
  - Depends On: Step 5
  - Can-Parallel-With: Step 7

### Step 7: Recalibrate `brief.md` + extend `render_listing`  (type: simple)  NOT STARTED
- [ ] 7.1 Extend `render_listing` to emit enrichment fields; rewrite `brief.md` calibration
  - Files: `src/autoscout_pipeline/scoring/prompt.py`, `brief.md`, `tests/test_scoring.py`
  - Acceptance: `uv run pytest tests/test_scoring.py -v` passes; `Listing(equipment=["Klimaanlage", "SHZ"], exterior_color="Hellblau")` renders with `equipment_list: Klimaanlage; SHZ` and `exterior_color: Hellblau` in output; `brief.md` contains calibration example with final score 6; light-blue strict allow-list present; baseline statement reads "starts at 6".
  - Implementation notes:
    - `render_listing` emits in order: `exterior_color`, `interior_color`, `upholstery`, `equipment_list` (joined `; `), then `model_text` as tail fallback.
    - System prompt: read structured fields first; fall back to `model_text` only when field is `unknown`/empty; cite exact matched substring in reasoning.
    - `brief.md` colour bonus: light-blue strict list ONLY for +1; other blues get pros mention at +0; no additive loose-blue stack.
    - Calibration example math: 6 + 0 = 6 (plain "Blue" exterior not in strict allow-list).
    - Dealbreakers kept as defence-in-depth (5-door, BEV, manual, non-base Cooper).
    - Seat heating penalty removed — unknown SHZ goes to cons text only, no numeric penalty.
    - PR description must note: operators should re-merge local `brief.md` customisations after deploy.
  - Depends On: Step 2
  - Can-Parallel-With: Step 6

---

## Wave 6

### Step 8: Cleanup + full regression  (type: simple)  DONE
- [x] 8.1 Verify zero synthetic-fixture refs; ruff clean; update `dev/codebase-map.md` and `README.md`
  - Files: `dev/codebase-map.md`, `README.md`
  - Acceptance: `grep -rn "AS24-DETAIL-001\|22500\|19900" tests/ scripts/ src/` returns zero hits; `uv run pytest tests/ -v && ruff check . && ruff format --check . && uv run python -m scripts.smoke` all pass; `dev/codebase-map.md` has entries for `enrich.py`, `BrowserSession`, `as24_enrich`, transmission filter, base-Cooper filter.
  - Implementation notes:
    - `codebase-map.md` additions: `enrich.py` row under scraper/ table; `BrowserSession` appended to fetch.py row; transmission + base-Cooper filters appended to pipeline.py row; three new Key Decisions entries.
    - `README.md`: add `AS24_ENRICH` (default true) to env vars table.
  - Depends On: Step 6, Step 7
  - Can-Parallel-With: —

---

## Stats

- Total: 8 tasks (one per plan step) · ~8.5h
- Done: 0 / 8

## How to Update

Check off tasks with `[x]` and update `detail-page-fetch-context.md` SESSION PROGRESS section after each milestone. When all tasks in a step are complete, update the step header to show `DONE`.
