"""Pipeline orchestrator and Typer CLI entrypoint.

Wires the scraper, scorer, sheets adapter, and Telegram notifier into a
single async run() function.  The cli() function exposes a Typer-based
command-line interface with a --dry-run flag.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import logging
import re
import sys
from pathlib import Path

import typer

from autoscout_pipeline.config import Settings
from autoscout_pipeline.logging_setup import configure_logging
from autoscout_pipeline.models import Listing, RunRecord, ScoredListing
from autoscout_pipeline.notify.telegram import TelegramNotifier
from autoscout_pipeline.scoring.batch import score_many
from autoscout_pipeline.scoring.scorer import LLMScorer
from autoscout_pipeline.scraper.enrich import enrich_with_details
from autoscout_pipeline.scraper.errors import EmptyResultsError
from autoscout_pipeline.scraper.search import iter_listings
from autoscout_pipeline.sheets.client import SheetsClient

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Search criteria — edit here to change which listings are scraped.
# ---------------------------------------------------------------------------
SEARCH_CRITERIA: dict = {
    "make": "mini",
    "model": "mini",
    "kmfrom": 20_000,
    "kmto": 50_000,
    "priceto": 24_000,
    "fregfrom": 2021,
    "fregto": 2023,
    "cy": "D,A,CH",
    "atype": "C",
    "ustate": "N,U",
    "sort": "standard",
}

# Post-fetch trim filters on listing.model (case-insensitive substring match).
# AutoScout24 returns all MINI variants under model=mini in the URL, so the
# actual trim ("Cooper", "Cooper S", "Cooper D Clubman", "Countryman") lives
# only in the JSON. Keep anything that says "cooper", drop anything that
# also says one of the non-Hatch body types.
MODEL_NAME_CONTAINS: str | None = "cooper"
MODEL_NAME_EXCLUDES: tuple[str, ...] = (
    "clubman",
    "countryman",
    "cabrio",
    "convertible",
    "roadster",
    "coupe",
)

# ---------------------------------------------------------------------------
# Pre-LLM transmission filter
# ---------------------------------------------------------------------------

AUTOMATIC_TOKENS = (
    "automatic",
    "automatik",
    "automat",
    "dkg",
    "dct",
    "dsg",
    "stronic",
    "s tronic",
    "tiptronic",
    "steptronic",
)


def _is_automatic(listing: Listing) -> bool:
    """Return True if the listing has an automatic (or unknown) transmission.

    Reads from ``listing.raw["vehicle"]["transmission"]``, NOT from a model
    field (which does not exist — ``transmission`` stays in ``raw`` per plan).
    Unknown or missing transmission returns True (defensive keep).
    """
    raw = listing.raw or {}
    vehicle = raw.get("vehicle") if isinstance(raw.get("vehicle"), dict) else {}
    t = (vehicle.get("transmission") or "").strip().lower()
    if not t:
        return True  # unknown → keep defensively
    return any(tok in t for tok in AUTOMATIC_TOKENS)


# ---------------------------------------------------------------------------
# Pre-LLM base-Cooper-only filter
# ---------------------------------------------------------------------------

VARIANT_REJECT_TOKENS = frozenset({"s", "se", "sd", "sds", "jcw"})
JOHN_COOPER_WORKS_RE = re.compile(r"john\s*cooper\s*works", re.I)


def _is_base_cooper(listing: Listing) -> bool:
    """Return True only for base Cooper (no S / SE / SD / JCW / John Cooper Works).

    Uses token-based matching to handle hyphens, dots, slashes, and spaces.
    Returns False for an empty model string.

    Note: the no-separator form ``CooperS`` is a known deferred edge case.
    """
    m = (listing.model or "").lower()
    if not m:
        return False
    if JOHN_COOPER_WORKS_RE.search(m):
        return False
    tokens = set(re.split(r"[\s\-./]+", m))
    return not VARIANT_REJECT_TOKENS & tokens


async def run(settings: Settings, dry_run: bool = False) -> RunRecord:
    """Run the full AutoScout24 MINI pipeline.

    Sequence:
    1. Configure logging.
    2. If not dry_run: construct SheetsClient and call bootstrap().
    3. Iterate listings via iter_listings(SEARCH_CRITERIA).
    4. Dedup: if not dry_run, filter out listings already known to the sheet.
    5. Score new listings via LLMScorer + score_many().
    6. If not dry_run: upsert scored listings to Sheets.
    7. Build a RunRecord summary.
    8. If not dry_run: record run in Sheets.
    9. If not dry_run: send Telegram notifications for high-scoring listings.
    10. Return the RunRecord.

    Parameters
    ----------
    settings:
        Application settings loaded from environment / .env.
    dry_run:
        When True, skip all writes and Telegram notifications.  Scraping and
        scoring still run so the operator can preview what would be processed.
        SheetsClient is NOT constructed in dry_run mode, so no GCP credentials
        are required for a dry-run smoke check.

    Returns
    -------
    RunRecord
        Summary of the pipeline run.
    """
    configure_logging()
    logger.info("Pipeline starting (dry_run=%s)", dry_run)

    err_count = 0
    all_listings = []
    new_listings = []
    scored: list[ScoredListing] = []

    try:
        # --- 2. Construct SheetsClient (only when writes are needed) ---
        if not dry_run:
            sheets = SheetsClient(
                creds_path=Path(settings.creds_path),
                sheet_id=settings.sheet_id,
            )
            sheets.bootstrap()
            logger.info("Sheets bootstrap complete")

        # --- 3. Iterate listings ---
        logger.info("Scraping listings with criteria: %s", SEARCH_CRITERIA)
        try:
            async for listing in iter_listings(
                SEARCH_CRITERIA,
                throttle_min=settings.as24_throttle_min,
                throttle_max=settings.as24_throttle_max,
            ):
                all_listings.append(listing)
        except EmptyResultsError as exc:
            logger.error("Scrape produced no results: %s", exc)
            err_count += 1

        logger.info("Scraped %d listings total", len(all_listings))

        # --- 3a. Post-fetch trim filters ---
        if MODEL_NAME_CONTAINS:
            needle = MODEL_NAME_CONTAINS.lower()
            before = len(all_listings)
            all_listings = [lst for lst in all_listings if needle in lst.model.lower()]
            logger.info(
                "Trim filter include=%r: %d → %d listings",
                MODEL_NAME_CONTAINS,
                before,
                len(all_listings),
            )
        if MODEL_NAME_EXCLUDES:
            excludes = tuple(e.lower() for e in MODEL_NAME_EXCLUDES)
            before = len(all_listings)
            all_listings = [
                lst for lst in all_listings if not any(e in lst.model.lower() for e in excludes)
            ]
            logger.info(
                "Trim filter exclude=%r: %d → %d listings",
                MODEL_NAME_EXCLUDES,
                before,
                len(all_listings),
            )

        before = len(all_listings)
        all_listings = [lst for lst in all_listings if _is_base_cooper(lst)]
        logger.info("Trim filter base-cooper-only: %d → %d listings", before, len(all_listings))

        before = len(all_listings)
        all_listings = [lst for lst in all_listings if _is_automatic(lst)]
        logger.info("Trim filter automatic-only: %d → %d listings", before, len(all_listings))

        # --- 4. Dedup ---
        if dry_run:
            # In dry-run mode we score everything (no sheet writes, but want preview)
            new_listings = all_listings
        else:
            existing = sheets.get_existing_ids()
            new_listings = [lst for lst in all_listings if lst.listing_id not in existing]
        logger.info(
            "Dedup: %d total → %d new (skipping %d already in sheet)",
            len(all_listings),
            len(new_listings),
            len(all_listings) - len(new_listings),
        )

        # --- 4a. Enrich new listings with detail-page data ---
        if settings.as24_enrich and new_listings:
            new_listings = await enrich_with_details(
                new_listings,
                throttle_min=settings.as24_throttle_min,
                throttle_max=settings.as24_throttle_max,
            )

        # --- 5. Score new listings ---
        scorer = LLMScorer(
            api_key=settings.openai_api_key,
            model=settings.openai_model,
            brief_path=Path(settings.brief_path),
        )
        scored = await score_many(scorer, new_listings)
        logger.info("Scored %d new listings", len(scored))

        # Log a summary using NESTED ScoredListing access (s.listing.*, s.score.*)
        for s in scored:
            logger.debug(
                "  scored: id=%s price=%d score=%d",
                s.listing.listing_id,
                s.listing.price_eur,
                s.score.score,
            )

        # --- 6. Upsert to Sheets ---
        today = dt.date.today().isoformat()
        if not dry_run:
            sheets.upsert_listings(scored, today)
            logger.info("Upserted %d listings to Sheets", len(scored))

    except Exception as exc:
        logger.exception("Unexpected pipeline error: %s", exc)
        err_count += 1

    # --- 7. Build RunRecord ---
    # updated_count: listings we saw that were already known (i.e. touched by upsert but not new)
    updated_count = len(all_listings) - len(new_listings)
    # removed_count: stale rows not in today's scrape; tracked by upsert internally
    # For the RunRecord, we can only approximate from existing info at this stage
    removed_count = 0
    notes = (
        f"dry_run={dry_run}; scraped={len(all_listings)}; "
        f"new={len(new_listings)}; scored={len(scored)}; errors={err_count}"
    )
    record = RunRecord(
        run_at=dt.datetime.now(dt.UTC),
        new_count=len(new_listings),
        updated_count=updated_count,
        removed_count=removed_count,
        errors=err_count,
        notes=notes,
    )

    try:
        # --- 8. Record run ---
        if not dry_run:
            sheets.record_run(record)
            logger.info("Run record written: new=%d errors=%d", record.new_count, record.errors)

        # --- 9. Telegram notifications ---
        if not dry_run and settings.tg_token and settings.tg_chat_id:
            notifier = TelegramNotifier(
                token=settings.tg_token,
                chat_id=settings.tg_chat_id,
                threshold=settings.score_notify_threshold,
            )
            sent = await notifier.send_batch(scored)
            logger.info("Telegram: sent %d notification(s)", sent)

    except Exception as exc:
        logger.exception("Post-run step failed: %s", exc)
        err_count += 1

    logger.info("Pipeline complete — RunRecord: %s", record.model_dump())
    return record


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

app = typer.Typer(add_completion=False)


@app.command()
def cli(
    dry_run: bool = typer.Option(False, "--dry-run", help="Skip all writes and notifications."),
) -> None:
    """AutoScout24 MINI pipeline — scrape, score, persist, notify."""
    main(dry_run=dry_run)


def main(dry_run: bool = False) -> None:
    """Imperative shell: load settings and drive asyncio.run(run(...)).

    Used by the ``autoscout-pipeline`` console_script defined in pyproject.toml.
    Exits with code 1 on any unhandled exception so systemd can detect failure.
    """
    try:
        settings = Settings()  # type: ignore[call-arg]
        asyncio.run(run(settings, dry_run=dry_run))
    except Exception as exc:
        logging.getLogger(__name__).exception("Fatal pipeline error: %s", exc)
        sys.exit(1)


if __name__ == "__main__":
    app()
