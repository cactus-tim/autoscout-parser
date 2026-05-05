# AutoScout24 MINI Pipeline

A daily Python pipeline that scrapes AutoScout24 for MINI Hatch listings (mileage
20–30k km, price ≤ 23k EUR, DE/AT/CH), extracts structured data from Next.js SSR
pages via `__NEXT_DATA__`, scores each listing with OpenAI GPT-4.1 nano through
`instructor`, persists results to Google Sheets (three-tab schema with dedup and
price history), and notifies Telegram when score ≥ 8. The browser stack uses
`cloverlabs-camoufox` for Akamai-resistant browser fingerprinting; the scoring
brief is fully configurable via `brief.md`.

---

## Quickstart

```bash
git clone https://github.com/<your-org>/autoscout-parser.git
cd autoscout-parser
uv sync
cp .env.example .env
# Fill in OPENAI_API_KEY, TG_TOKEN, TG_CHAT_ID, SHEET_ID, CREDS_PATH
# Edit brief.md to describe your ideal MINI (or keep the placeholder)
uv run python -m camoufox fetch          # download Firefox binary once
uv run autoscout-pipeline --dry-run      # smoke check — no writes
uv run autoscout-pipeline                # full run
```

---

## Configuration

All settings are read from environment variables (loaded from `.env` via
`pydantic-settings`). Copy `.env.example` to `.env` and fill in every value.

| Variable                | Required | Default               | Description                                                                        |
|-------------------------|----------|-----------------------|------------------------------------------------------------------------------------|
| `OPENAI_API_KEY`        | yes      | —                     | OpenAI API key. Paid tier (≥500 RPM) required for production.                      |
| `SHEET_ID`              | yes      | —                     | Google Sheets ID from the URL: `.../d/<SHEET_ID>/edit`.                            |
| `CREDS_PATH`            | yes      | `creds.json`          | Path to GCP service-account JSON file.                                             |
| `TG_TOKEN`              | no       | `""`                  | Telegram bot token from @BotFather. Leave blank to disable Telegram notifications. |
| `TG_CHAT_ID`            | no       | `""`                  | Telegram chat or channel ID from @userinfobot. Leave blank to disable.             |
| `SCORE_NOTIFY_THRESHOLD`| no       | `8`                   | Minimum score (1–10) to trigger a Telegram notification.                           |
| `OPENAI_MODEL`          | no       | `gpt-4.1-nano`        | OpenAI model used for scoring.                                                     |
| `AS24_THROTTLE_MIN`     | no       | `2.0`                 | Minimum seconds to wait between scraper page requests.                             |
| `AS24_THROTTLE_MAX`     | no       | `6.0`                 | Maximum seconds to wait between scraper page requests.                             |
| `AS24_ENRICH`           | no       | `true`                | Fetch each new listing's detail page to extract equipment, colours, and upholstery before scoring. Set to `false` to skip enrichment and reduce run time. |

---

## Detail-Page Enrichment

After scraping and deduplication, the pipeline optionally fetches each new
listing's detail page using the same browser session to extract structured
fields: equipment list, exterior colour, upholstery type, and interior colour.
This enrichment phase adds approximately 3–6 seconds per new listing (governed
by the existing `AS24_THROTTLE_MIN`/`AS24_THROTTLE_MAX` window) and can be
disabled by setting `AS24_ENRICH=false`. The LLM scorer receives these fields
as first-class lines (`equipment_list`, `exterior_color`, `interior_color`,
`upholstery`) rather than inferring them from abbreviated German model strings.

---

## GCP Service Account Setup

The pipeline writes to Google Sheets using a GCP service account. Follow these
five steps to create one:

1. **Create a GCP project**: Go to [console.cloud.google.com](https://console.cloud.google.com/),
   click the project selector, then **New Project**. Give it any name (e.g.
   `autoscout-pipeline`).

2. **Enable APIs**: In the project, go to **APIs & Services → Library**. Search
   for and enable both:
   - **Google Sheets API**
   - **Google Drive API**

3. **Create a service account**: Go to **IAM & Admin → Service Accounts → Create
   Service Account**. Name it (e.g. `autoscout-sheets`). No special roles needed
   at project level — access is granted per-sheet in step 5.

4. **Download `creds.json`**: Open the service account, go to the **Keys** tab,
   click **Add Key → Create new key → JSON**. Save the downloaded file as
   `creds.json` in the repo root (or wherever `CREDS_PATH` points). See
   `docs/creds.json.example` for the expected structure.

5. **Share the Google Sheet**: Open your target Google Sheet. Click **Share**,
   paste the service account email address (looks like
   `autoscout-sheets@<project>.iam.gserviceaccount.com`), set role to **Editor**,
   and click **Send**.

---

## Telegram Bot Setup

1. **Create a bot**: Open Telegram and message [@BotFather](https://t.me/BotFather).
   Send `/newbot`, choose a name and username. BotFather replies with your
   `TG_TOKEN` — copy it to `.env`.

2. **Find your chat ID**: Message [@userinfobot](https://t.me/userinfobot). It
   replies with your numeric user ID. Use that as `TG_CHAT_ID`. For a channel,
   forward any channel message to @userinfobot to get the channel ID (it starts
   with `-100`).

3. **Start the bot**: Send `/start` to your bot at least once, or add it to your
   channel as an admin, so it can send you messages.

---

## Brief Configuration

The file `brief.md` is read once at pipeline startup by `LLMScorer`. It is
injected into the system prompt as your scoring criteria. Edit it to describe
what makes an ideal MINI for your situation:

- Preferred trim levels (Cooper S, JCW, etc.)
- Acceptable colours, interior specs, optional equipment
- Dealbreakers (e.g. private sellers outside DE, flood-history markers)
- Relative weighting (e.g. "low mileage matters more than price within range")

A placeholder `brief.md` is committed to the repo. Replace the placeholder text
with your real criteria before the first production run.

---

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
docs/                # Reference files (creds.json.example, etc.)
```

---

## Troubleshooting

- **`NextDataMissingError`**: The `__NEXT_DATA__` JSON block was not found in the
  fetched HTML. AutoScout24 injects it client-side after Next.js hydration; a dump
  of the raw HTML is saved to `/tmp/as24_dump_<ts>.html` for inspection. If this
  happens repeatedly, the page structure has changed — re-run
  `scripts/capture_fixtures.py` on the live site to capture updated fixture HTML
  and update the parser accordingly.

- **`EmptyResultsError`**: The search returned zero listings. The URL bucket codes
  for mileage or price range may have changed. Open the live autoscout24.com search
  in a browser with the desired filters applied, copy the URL, and compare the
  parameter values against the template in `scraper/search.py`. Update the
  constants if they have drifted.

- **`SheetSchemaError`**: The existing Google Sheet has different column headers
  than `LISTINGS_HEADERS` in `sheets/schema.py`. This means the sheet was modified
  manually or the code schema was updated after the sheet was first created. Back
  up the sheet data, then either restore the expected headers (see
  `LISTINGS_HEADERS` in `sheets/schema.py`) or delete and re-bootstrap the tabs.

- **OpenAI 401**: Your `OPENAI_API_KEY` is invalid, expired, or lacks billing.
  Regenerate it at [platform.openai.com/api-keys](https://platform.openai.com/api-keys)
  and confirm your account has an active payment method (the free tier does not
  support `gpt-4.1-nano`).

- **Rate-limit timeout**: The pipeline exceeded `TimeoutStartSec=1800` (30 min).
  This happens on the OpenAI **free tier (3 RPM)**. With `Semaphore(5)` concurrency
  and ~200 listings per run, you need a paid tier with **≥500 RPM**. Upgrade your
  OpenAI account or reduce `Semaphore` concurrency as a short-term workaround.

- **Telegram 401**: The bot token is wrong or the bot has not been started. Verify
  `TG_TOKEN` in `.env` matches what @BotFather gave you, and send `/start` to the
  bot in Telegram before the first run (or add it as admin to your channel).

- **Camoufox missing libs**: On Ubuntu 24.04 ARM64, ensure the t64 variants are
  installed: `libxcomposite1t64`, `libgtk-3-0t64`, `libxt6t64`. The non-t64 package
  names (`libxcomposite1`, etc.) do not exist on this distro. Run
  `bash deploy/install.sh` to install them automatically.

---

## Deployment (Hetzner CAX11)

See [`deploy/README.md`](deploy/README.md) for the complete step-by-step guide
from a fresh Hetzner CAX11 VPS to a running daily cron job.
