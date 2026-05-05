"""Live reconnaissance: fetch one AutoScout24 detail page and document its schema.

Usage
-----
    uv run python -m scripts.recon_detail

What it does
~~~~~~~~~~~~
1. Calls ``iter_listings(SEARCH_CRITERIA)`` from pipeline.py to obtain the first
   live listing from AutoScout24.
2. Fetches the detail page HTML via ``fetch_page_html(listing.url)`` (camoufox).
3. Writes the raw HTML to ``tests/fixtures/autoscout_listing_detail.html``
   (overwrites the previous synthetic fixture).
4. Extracts ``__NEXT_DATA__`` JSON and walks ``props.pageProps.listingDetails``.
5. Writes ``dev/active/detail-page-fetch/recon-notes.md`` documenting the schema.

The script is intentionally single-use / one-shot reconnaissance. Re-run it
whenever the live schema needs to be re-checked.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import pathlib
import sys
import textwrap

FIXTURES_DIR = pathlib.Path(__file__).parent.parent / "tests" / "fixtures"
RECON_NOTES_PATH = (
    pathlib.Path(__file__).parent.parent / "dev" / "active" / "detail-page-fetch" / "recon-notes.md"
)


def _safe_excerpt(obj: object, max_lines: int = 12) -> str:
    """Return a pretty-printed JSON excerpt of *obj*, capped to *max_lines* lines."""
    try:
        text = json.dumps(obj, ensure_ascii=False, indent=2)
    except (TypeError, ValueError):
        text = repr(obj)
    lines = text.splitlines()
    if len(lines) > max_lines:
        lines = [*lines[:max_lines], f"  ... ({len(lines) - max_lines} more lines)"]
    return "\n".join(lines)


def _shape(obj: object) -> str:
    """Return a human-readable Shape enum for *obj*."""
    if obj is None:
        return "null"
    if isinstance(obj, list):
        if not obj:
            return "flat-list[str]"
        sample = obj[0]
        if isinstance(sample, str):
            return "flat-list[str]"
        if isinstance(sample, dict):
            return "list[dict-with-items]"
        return f"list[{type(sample).__name__}]"
    if isinstance(obj, str):
        # Detect HTML blobs
        if "<" in obj and ">" in obj:
            return "localized-html-blob"
        return "string"
    if isinstance(obj, dict):
        return "dict"
    return f"other ({type(obj).__name__})"


def _dig(data: dict, *keys: str) -> object:
    """Walk nested dicts; return None if any key is missing."""
    cur: object = data
    for k in keys:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(k)
    return cur


async def _recon() -> None:
    # ------------------------------------------------------------------
    # Lazy imports — surface missing deps early with helpful messages.
    # ------------------------------------------------------------------
    try:
        import orjson
        from selectolax.parser import HTMLParser
    except ImportError as exc:
        print(f"ERROR: missing dependency: {exc}", file=sys.stderr)
        sys.exit(1)

    try:
        from autoscout_pipeline.pipeline import SEARCH_CRITERIA
        from autoscout_pipeline.scraper.fetch import fetch_page_html
        from autoscout_pipeline.scraper.search import iter_listings
    except ImportError as exc:
        print(
            f"ERROR: could not import from autoscout_pipeline: {exc}",
            file=sys.stderr,
        )
        sys.exit(1)

    # ------------------------------------------------------------------
    # Step 1 — get first listing from search.
    # ------------------------------------------------------------------
    print("Fetching first listing from search …")
    first_listing = None
    async for listing in iter_listings(
        SEARCH_CRITERIA, max_pages=1, throttle_min=0.0, throttle_max=0.0
    ):
        first_listing = listing
        break  # we only need the first

    if first_listing is None:
        print("ERROR: iter_listings returned no listings.", file=sys.stderr)
        sys.exit(1)

    detail_url = first_listing.url
    print(f"  First listing URL: {detail_url}")

    # ------------------------------------------------------------------
    # Step 2 — fetch detail page HTML.
    # ------------------------------------------------------------------
    print("Fetching detail page HTML …")
    html = await fetch_page_html(detail_url)
    print(f"  Fetched {len(html):,} bytes")

    # ------------------------------------------------------------------
    # Step 3 — save raw HTML fixture (overwrites synthetic fixture).
    # ------------------------------------------------------------------
    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)
    detail_fixture = FIXTURES_DIR / "autoscout_listing_detail.html"
    detail_fixture.write_text(html, encoding="utf-8")
    print(f"  Wrote fixture: {detail_fixture}")

    # ------------------------------------------------------------------
    # Step 4 — extract __NEXT_DATA__ and walk listingDetails.
    # ------------------------------------------------------------------
    tree = HTMLParser(html)
    node = tree.css_first("script#__NEXT_DATA__")
    if node is None:
        print(
            "ERROR: __NEXT_DATA__ not found in fetched HTML — "
            "possible Akamai challenge. See /tmp/as24_dump_*.html",
            file=sys.stderr,
        )
        sys.exit(1)

    data: dict = orjson.loads(node.text(strip=True))
    listing_details: dict | None = _dig(data, "props", "pageProps", "listingDetails")  # type: ignore[assignment]

    if listing_details is None:
        print(
            "WARNING: props.pageProps.listingDetails is absent — "
            "detail page may use a different schema.",
            file=sys.stderr,
        )
        # Still write what we found so downstream steps can inspect.
        listing_details = {}

    # ------------------------------------------------------------------
    # Step 5 — walk target enrichment fields.
    # ------------------------------------------------------------------
    captured_at = dt.datetime.now(dt.UTC).strftime("%Y-%m-%d %H:%M:%SZ")

    fields_of_interest = [
        (
            "equipment",
            ("props", "pageProps", "listingDetails", "vehicle", "equipment"),
            _dig(data, "props", "pageProps", "listingDetails", "vehicle", "equipment"),
        ),
        (
            "exterior_color",
            ("props", "pageProps", "listingDetails", "vehicle", "exterior"),
            _dig(data, "props", "pageProps", "listingDetails", "vehicle", "exterior"),
        ),
        (
            "interior_color",
            ("props", "pageProps", "listingDetails", "vehicle", "interior"),
            _dig(data, "props", "pageProps", "listingDetails", "vehicle", "interior"),
        ),
        (
            "upholstery",
            ("props", "pageProps", "listingDetails", "vehicle", "upholstery"),
            _dig(data, "props", "pageProps", "listingDetails", "vehicle", "upholstery"),
        ),
    ]

    # If some fields are null, try alternate paths that are common in AS24 schemas.
    def _try_alternates(field_name: str) -> tuple[tuple[str, ...], object]:
        """Return (path_tuple, value) for known alternate locations."""
        vehicle = _dig(data, "props", "pageProps", "listingDetails", "vehicle")
        if not isinstance(vehicle, dict):
            vehicle = {}

        if field_name == "equipment":
            # Check top-level equipmentKeys, features, keyFeatures, highlights
            for alt_key in ("equipmentKeys", "features", "keyFeatures", "highlights", "options"):
                val = _dig(data, "props", "pageProps", "listingDetails", alt_key)
                if val is not None:
                    return (
                        ("props", "pageProps", "listingDetails", alt_key),
                        val,
                    )
                val = vehicle.get(alt_key)
                if val is not None:
                    return (
                        ("props", "pageProps", "listingDetails", "vehicle", alt_key),
                        val,
                    )

        if field_name in ("exterior_color", "interior_color", "upholstery"):
            key_map = {
                "exterior_color": ("color", "exteriorColor", "colourExterior", "bodyColor"),
                "interior_color": ("interiorColor", "colourInterior", "interior"),
                "upholstery": ("upholstery", "seatMaterial", "interiorMaterial"),
            }
            for alt_key in key_map.get(field_name, ()):
                val = _dig(data, "props", "pageProps", "listingDetails", alt_key)
                if val is not None:
                    return (
                        ("props", "pageProps", "listingDetails", alt_key),
                        val,
                    )
                val = vehicle.get(alt_key)
                if val is not None:
                    return (
                        ("props", "pageProps", "listingDetails", "vehicle", alt_key),
                        val,
                    )

        return (("props", "pageProps", "listingDetails", field_name), None)

    # Resolve fields (try primary path, fall back to alternates).
    resolved: list[tuple[str, tuple[str, ...], object]] = []
    for fname, primary_path, primary_val in fields_of_interest:
        if primary_val is not None:
            resolved.append((fname, primary_path, primary_val))
        else:
            alt_path, alt_val = _try_alternates(fname)
            resolved.append((fname, alt_path, alt_val))

    # ------------------------------------------------------------------
    # Step 6 — build recon-notes.md.
    # ------------------------------------------------------------------
    sections: list[str] = []
    open_issues: list[str] = []

    for fname, path, val in resolved:
        path_str = str(path)
        shape = _shape(val)
        excerpt = _safe_excerpt(val) if val is not None else "null"
        notes_lines: list[str] = []

        if val is None:
            notes_lines.append(
                "Field not found at primary path or any known alternate path. "
                "Inspect the raw JSON at the path above."
            )
            open_issues.append(
                f"`{fname}` was null / not found — downstream parser "
                "will need to locate the correct path from the raw fixture."
            )
        else:
            # Add field-specific notes
            if fname == "equipment" and shape == "flat-list[str]":
                notes_lines.append(
                    "List of plain German-language equipment string labels. "
                    "Suitable for direct use as a comma-joined string."
                )
            elif fname == "equipment" and shape == "list[dict-with-items]":
                notes_lines.append(
                    "List of dicts — inspect `items` key or similar for the actual string labels."
                )
            elif fname == "equipment" and shape == "localized-html-blob":
                notes_lines.append(
                    "HTML blob — will need BeautifulSoup/selectolax stripping before use."
                )
                open_issues.append(
                    "`equipment` is an HTML blob — downstream parser must strip HTML tags."
                )

        sections.append(
            f"### {fname}\n"
            f"- JSON path: `{path_str}`\n"
            f"- Shape: {shape}\n"
            f"- Excerpt:\n"
            f"  ```json\n" + textwrap.indent(excerpt, "  ") + "\n  ```\n"
            "- Notes: " + (" ".join(notes_lines) if notes_lines else "No special notes.")
        )

    if not open_issues:
        open_issues.append(
            "No blocking issues found. All four target fields were located. "
            "Confirm paths during Step 3 implementation."
        )

    # PII check note
    open_issues.append(
        "Fixture contains real listing data including seller/dealer name, "
        "city/zip, phone (if present). No API keys or bot tokens detected "
        "in a spot-check of the captured HTML."
    )

    schema_block = "\n\n".join(sections)
    issues_block = "\n".join(f"- {issue}" for issue in open_issues)

    notes_content = f"""# Recon notes — captured {captured_at}

URL: {detail_url}

## Schema findings

For each enrichment field:
- **JSON path** (tuple of keys)
- **Shape enum** (`flat-list[str]`, `list[dict-with-items]`, `localized-html-blob`, `string`, `null`, `other`)
- **Excerpt** (pretty-printed JSON of that sub-tree)
- **Notes / gotchas**

{schema_block}

## Open issues for downstream steps
{issues_block}
"""

    RECON_NOTES_PATH.parent.mkdir(parents=True, exist_ok=True)
    RECON_NOTES_PATH.write_text(notes_content, encoding="utf-8")
    print(f"  Wrote recon notes: {RECON_NOTES_PATH}")
    print("\nRecon complete.")
    print(f"  Fixture:    {detail_fixture}")
    print(f"  Recon notes: {RECON_NOTES_PATH}")


def main() -> None:
    asyncio.run(_recon())


if __name__ == "__main__":
    main()
