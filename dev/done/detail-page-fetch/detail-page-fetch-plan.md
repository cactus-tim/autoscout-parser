# Detail Page Fetch + Enrichment — Plan

## Executive Summary

Add a per-listing detail-page enrichment stage to the AutoScout24 pipeline so the LLM scorer receives the full equipment list, exterior/interior colour, and upholstery directly from `props.pageProps.listingDetails` instead of guessing from German abbreviations in `vehicle.modelVersionInput`. Additionally, tighten the pre-LLM trim filter block in `pipeline.py` so manual-transmission and non-base-Cooper variants (Cooper S / SE / SD / JCW) are dropped before any OpenAI cost is spent on them. Recalibrate `brief.md` so clean in-spec listings land at 6, very good ones at 8, and 9–10 are reserved for true unicorns.

## Current State

- The pipeline fetches search-page listings and scores them immediately with the LLM. The only structured data the scorer receives is `vehicle.modelVersionInput` (a free-text German abbreviation string) plus basic fields (price, mileage, year). Equipment, colours, and upholstery are invisible to the scorer.
- Pre-LLM filters drop Clubman/Countryman/etc. and listings whose model doesn't contain "cooper", but Cooper S / SE / SD / JCW and manual-transmission listings still reach the scorer and consume API budget.
- The existing `parse_listing_detail` and its fixture (`tests/fixtures/autoscout_listing_detail.html`) are built against a synthetic hand-written JSON that does not represent the live site schema.
- `brief.md` calibration is too strict: the reference URL (a clean 3-door petrol Cooper with LED + PDC + DAB) was scoring 3–4; it should score 6.

## Proposed Approach

1. **Live recon first**: capture real `listingDetails` JSON shape from the live site; document it in `recon-notes.md` as the single source of truth for parser implementation.
2. **Extend `Listing` model** with four optional enrichment fields (`equipment`, `exterior_color`, `interior_color`, `upholstery`). `transmission` stays in `raw["vehicle"]["transmission"]` — Option A keeps the model surface tight.
3. **Rewrite `parse_listing_detail`** using the real JSON paths from recon notes; add `_flatten_equipment` helper.
4. **Add `BrowserSession`** async-CM to `scraper/fetch.py` — reuses one Camoufox instance across N sequential detail fetches (vs. opening a new browser per call in `fetch_page_html`).
5. **Implement `enrich_with_details`** in a new `scraper/enrich.py` module; add `as24_enrich: bool = True` to `Settings`; include a circuit breaker (5 consecutive outer failures = early abort).
6. **Wire enrichment + new filters into `pipeline.run()`**: transmission filter (reads `raw["vehicle"]["transmission"]`) and base-Cooper-only filter run after existing CONTAINS/EXCLUDES filters; enrichment runs between dedup and scoring; smoke script gets a mandatory passthrough patch.
7. **Update `render_listing` and recalibrate `brief.md`**: emit equipment/colour as first-class lines; raise baseline to 6; light-blue strict earns +1; other bonuses softened to +0.5–+1.
8. **Cleanup**: full regression, ruff, doc updates.

Sheets schema is intentionally NOT changed — equipment/colour exist only in memory for scoring, leaving `LISTINGS_HEADERS` (16 cols) untouched.

## Implementation Phases

### Phase 1: Live Recon (~1h)
**Goal:** Capture the real `listingDetails` JSON shape and replace the synthetic fixture with live HTML.

- [ ] 1.1 Write `scripts/recon_detail.py` and run it against the live site
  - Files: `scripts/recon_detail.py`, `tests/fixtures/autoscout_listing_detail.html`, `dev/active/detail-page-fetch/recon-notes.md`
  - Acceptance: Running `python -c "from autoscout_pipeline.scraper.parse import extract_next_data; import pathlib; d = extract_next_data(pathlib.Path('tests/fixtures/autoscout_listing_detail.html').read_text()); print(list(d['props']['pageProps']['listingDetails'].keys()))"` prints a non-trivial list of keys; `recon-notes.md` exists and follows the required template with all four field sections (`equipment`, `exterior_color`, `interior_color`, `upholstery`) and an `Open issues` section.

### Phase 2: Model + BrowserSession (~1h, both parallel)
**Goal:** Extend `Listing` with enrichment fields and add the reusable browser session abstraction — two fully disjoint file sets.

- [ ] 2.1 Extend `Listing` with four optional enrichment fields (no `transmission` field)
  - Files: `src/autoscout_pipeline/models.py`, `tests/test_models.py`
  - Acceptance: `uv run pytest tests/test_models.py -v` passes; `Listing()` without new kwargs has `equipment == []` and three colour fields `is None`; existing 122 tests still green.

- [ ] 2.2 Add `BrowserSession` async-CM to `scraper/fetch.py`
  - Files: `src/autoscout_pipeline/scraper/fetch.py`, `tests/test_scraper_fetch.py`
  - Acceptance: `uv run pytest tests/test_scraper_fetch.py -v` passes with ~4 tests (CM lifecycle, two sequential fetches, tenacity retry on `PlaywrightTimeoutError`); `fetch_page_html` untouched; no live network used.

### Phase 3: Parse Rewrite (~1.5h)
**Goal:** Rewrite `parse_listing_detail` against the live fixture and recon-derived JSON paths.

- [ ] 3.1 Rewrite `parse_listing_detail` and add `_flatten_equipment`; rewrite `TestParseListingDetail`
  - Files: `src/autoscout_pipeline/scraper/parse.py`, `tests/test_scraper_parse.py`
  - Acceptance: `uv run pytest tests/test_scraper_parse.py -v` passes with ~7–9 new/updated tests; `parse_listing_detail(data)` populates all four enrichment fields for the live fixture; `raw` is preserved on returned `Listing`; synthetic fixture identifiers (`AS24-DETAIL-001`, `19900`, `22500`) no longer asserted.

### Phase 4: Enrichment Module + Config (~2h)
**Goal:** Implement the `enrich_with_details` function with circuit breaker and add the config toggle.

- [ ] 4.1 Create `src/autoscout_pipeline/scraper/enrich.py` and add `as24_enrich` to `config.py`
  - Files: `src/autoscout_pipeline/scraper/enrich.py`, `src/autoscout_pipeline/config.py`, `tests/test_scraper_enrich.py`
  - Acceptance: `uv run pytest tests/test_scraper_enrich.py -v` passes with ~8 tests including the circuit-breaker-trips test and the breaker-resets-on-success test; `Settings.as24_enrich` exists and defaults to `True`; full suite green.

### Phase 5: Pipeline Wiring + Filters (~2h, can run parallel with Phase 6)
**Goal:** Wire the two new filters and enrichment into `pipeline.run()`; update smoke script.

- [ ] 5.1 Add transmission + base-Cooper filters and enrich call to `pipeline.py`; patch smoke script
  - Files: `src/autoscout_pipeline/pipeline.py`, `tests/test_pipeline.py`, `scripts/smoke.py`
  - Acceptance: `uv run pytest tests/test_pipeline.py -v` passes (all existing tests + ~5 new: 2 enrichment wiring, 1 transmission filter with 3+8 values, 1 base-Cooper parametrized over 11 cases, 1 log-ordering); `uv run python -m scripts.smoke` reports `OK smoke OK`; transmission tests use `raw={"vehicle": {"transmission": "..."}}` not `transmission=` kwarg.

### Phase 6: Prompt + Brief Recalibration (~1.5h, can run parallel with Phase 5)
**Goal:** Extend `render_listing` to emit enrichment fields; recalibrate `brief.md` scoring.

- [ ] 6.1 Extend `render_listing` in `prompt.py` and rewrite `brief.md`
  - Files: `src/autoscout_pipeline/scoring/prompt.py`, `brief.md`, `tests/test_scoring.py`
  - Acceptance: `uv run pytest tests/test_scoring.py -v` passes; rendered output for a `Listing(equipment=["Klimaanlage", "SHZ"], exterior_color="Hellblau")` contains `equipment_list: Klimaanlage; SHZ` and `exterior_color: Hellblau`; `brief.md` contains the calibration example with final score 6; light-blue strict list is present.

### Phase 7: Cleanup + Full Regression (~0.5h)
**Goal:** Zero synthetic-fixture references; ruff clean; docs updated; full suite green.

- [ ] 7.1 Final cleanup sweep, doc updates, full regression
  - Files: `dev/codebase-map.md`, `README.md` (if env var table exists)
  - Acceptance: `grep -rn "AS24-DETAIL-001\|22500\|19900" tests/ scripts/ src/` returns zero hits; `uv run pytest tests/ -v && ruff check . && ruff format --check . && uv run python -m scripts.smoke` all pass; `dev/codebase-map.md` has entries for `enrich.py`, `BrowserSession`, `as24_enrich`, transmission filter, and base-Cooper filter.

## Key Files Affected

| File | Change | Why |
|------|--------|-----|
| `scripts/recon_detail.py` | Create | One-shot live recon tool |
| `dev/active/detail-page-fetch/recon-notes.md` | Create | Schema documentation for Steps 3/5 |
| `tests/fixtures/autoscout_listing_detail.html` | Overwrite | Replace synthetic with live capture |
| `src/autoscout_pipeline/models.py` | Edit | Add 4 optional enrichment fields |
| `src/autoscout_pipeline/scraper/fetch.py` | Edit | Add `BrowserSession` async-CM |
| `src/autoscout_pipeline/scraper/parse.py` | Edit | Rewrite `parse_listing_detail` + add `_flatten_equipment` |
| `src/autoscout_pipeline/scraper/enrich.py` | Create | New `enrich_with_details` module |
| `src/autoscout_pipeline/config.py` | Edit | Add `as24_enrich: bool = True` |
| `src/autoscout_pipeline/pipeline.py` | Edit | Two new filters + enrichment call |
| `src/autoscout_pipeline/scoring/prompt.py` | Edit | Emit equipment/colour fields |
| `brief.md` | Edit | Recalibrate scoring |
| `scripts/smoke.py` | Edit | Mandatory passthrough patch for `enrich_with_details` |
| `tests/test_models.py` | Edit | 3 new tests |
| `tests/test_scraper_parse.py` | Edit | Rewrite `TestParseListingDetail` |
| `tests/test_scraper_fetch.py` | Create | ~4 new tests |
| `tests/test_scraper_enrich.py` | Create | ~8 new tests |
| `tests/test_pipeline.py` | Edit | Passthrough patch in all async tests + ~5 new |
| `tests/test_scoring.py` | Edit | 1 new/extended test |
| `dev/codebase-map.md` | Edit | New module/setting/filter entries |
| `README.md` | Edit | Add `AS24_ENRICH` to env vars table |
| NOT touched | — | `sheets/`, `notify/`, `scoring/scorer.py`, `scoring/batch.py`, `deploy/` |

## Dependencies and Order Constraints

```
Wave 1 (sequential, blocking):
  Step 1 (recon) — produces live fixture + recon-notes.md

Wave 2 (parallel after Wave 1):
  Step 2 (Listing fields)  — disjoint from Step 4
  Step 4 (BrowserSession) — disjoint from Step 2
  [then Step 3 sequenced after Step 2 — reads Listing shape]

Wave 3 (after Wave 2):
  Step 5 (enrich) — depends on 2, 3, 4

Wave 4 (parallel after Wave 3):
  Step 6 (pipeline wiring) — disjoint from Step 7
  Step 7 (prompt + brief)  — disjoint from Step 6

Wave 5 (final):
  Step 8 (cleanup) — depends on 6, 7
```

Sequential fallback order: 1 → 2 → 4 → 3 → 5 → 6 → 7 → 8

## Risks

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Akamai challenge page blocks recon | Medium | Blocks all parser work | Retry from different IP; do NOT commit challenge HTML |
| Live `listingDetails` schema radically different from assumed shape | Low | Requires parser redesign | Recon-notes.md as single source of truth; flag in notes and request revision if unexpected |
| Transmission filter no-op if `getattr(listing, "transmission", None)` used instead of `raw["vehicle"]` | Medium | Filter silently drops no one | Use `raw["vehicle"]["transmission"]` path; test must use `raw={"vehicle": {"transmission": "Manual"}}` constructor, NOT `transmission=` kwarg |
| Base-Cooper edge case `CooperS` (no separator) slips through | Low | Rare variant passes filter | Acknowledged Open Question #4; monitor logs post-deploy |
| `brief.md` operator customisations overwritten on deploy | Low | Score shift on next run | PR description must note: re-merge local `brief.md` customisations after deploy |
| Fixture PII (dealer phone/address) in committed HTML | Low | Privacy concern | Review before commit; scrub phone/dealer-name if objected to |
| `scripts/smoke.py` patch wrong form causes pytest-asyncio coroutine issue | Medium | Smoke goes to live network | Exact form: `new_callable=AsyncMock, side_effect=lambda lst, **kw: lst` |

## Out of Scope

- Sheets schema changes — `LISTINGS_HEADERS` (16 cols) stays untouched; equipment/colour are ephemeral (in-memory only for scoring).
- Parallel detail fetching — Camoufox concurrent-page race conditions documented; sequential-only for now.
- Separate throttle knobs (`as24_detail_throttle_min/max`) — reuses existing `as24_throttle_min/max`; can split later if Akamai blocks.
- `transmission` as a `Listing` model field — stays in `raw["vehicle"]["transmission"]` (Option A).
- Integration tests — banned per plan (live-site Akamai blocks CI); unit tests with mocked browser cover the enrichment path.
- `CooperS` (no-separator variant) base-Cooper edge case — deferred to v2.
- `deploy/` and notification changes.

## Timeline

- Total: ~8.5h
- Phase breakdown: Recon ~1h, Model+BrowserSession ~1h (parallel), Parse ~1.5h, Enrich ~2h, Pipeline ~2h (parallel with Prompt ~1.5h), Cleanup ~0.5h
- Created: 2026-05-05
