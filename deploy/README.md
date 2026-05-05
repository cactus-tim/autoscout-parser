# Deployment

Docker-based deploy. The container runs forever in scheduler mode, firing the
pipeline on the cron expression in `SCHEDULE_CRON` (default 03:15 UTC daily).
No host systemd, no host cron — everything lives inside the container.

> **Legacy systemd unit files** are preserved under `deploy/legacy-systemd/`
> for reference only — not used by the Docker flow.

---

## Prerequisites

- A Linux host with **Docker Engine ≥ 24** and **Docker Compose plugin v2**.
- Outbound internet access (Camoufox boots a real Firefox, hits AS24 + OpenAI + Telegram + Sheets API).
- ~2 GB of disk for the built image (Firefox binary takes most of it).
- ~600 MB RAM for the running container at idle; spikes during scrape.

OS does not matter — Ubuntu 22.04 / 24.04, Debian, Alpine on the host all work.
The image itself is `python:3.11-slim-bookworm`.

---

## First-time setup on a new server

```bash
git clone <repo-url> /opt/autoscout
cd /opt/autoscout

# 1. Configure secrets
cp .env.example .env
$EDITOR .env

# 2. Drop in the GCP service-account JSON
cp /path/to/creds.json .
chmod 600 creds.json .env

# 3. Build + start (detached)
docker compose up -d --build

# 4. Verify it's running and the cron is registered
docker compose logs -f
```

You should see:

```
{"ts":"...","level":"INFO","logger":"autoscout_pipeline.pipeline","msg":"Scheduler starting; cron='15 3 * * *' (UTC), run_on_startup=False"}
```

---

## Configuration

All knobs live in `.env`. Key vars:

| Variable                  | Default            | Meaning |
|---------------------------|--------------------|---------|
| `OPENAI_API_KEY`          | —                  | Required. |
| `OPENAI_MODEL`            | `gpt-4.1-nano`     | We currently use `gpt-4.1-mini`. |
| `TG_TOKEN` / `TG_CHAT_ID` | —                  | Set both to enable Telegram. Group IDs start with `-`. |
| `SHEET_ID`                | —                  | Required. Google Sheets ID from URL. |
| `SCORE_NOTIFY_THRESHOLD`  | `8`                | Telegram threshold. We use `7`. |
| `AS24_THROTTLE_MIN/MAX`   | `2.0` / `6.0`      | Per-page throttle in seconds. |
| `AS24_ENRICH`             | `true`             | Detail-page enrichment toggle. |
| `SCHEDULE_CRON`           | `15 3 * * *` (UTC) | Cron expression for periodic runs. |
| `RUN_ON_STARTUP`          | `false`            | If true, fires one run immediately on container start (handy for smoke-testing on a new server). |

`CREDS_PATH` and `BRIEF_PATH` are overridden by `docker-compose.yml` to
`/app/creds.json` and `/app/brief.md` — no need to set them in `.env` for the
container, but they still work for direct `uv run` on the host.

---

## Operational commands

```bash
# Tail logs
docker compose logs -f

# Run a one-shot dry-run (no Sheets writes, no Telegram) — bypasses scheduler
docker compose run --rm autoscout autoscout-pipeline --dry-run

# Trigger a real run NOW, ignoring schedule
docker compose run --rm autoscout autoscout-pipeline

# Stop the scheduler
docker compose down

# Rebuild after code changes
git pull && docker compose up -d --build
```

---

## Updating the brief without rebuilding

`brief.md` is mounted read-only from the host into the container. Edit it on
the host and the next scheduled run picks it up — `prompt.load_brief()` re-reads
the file each run thanks to its lru_cache being scoped to one process and the
compose container restarting only on crash. (For an immediate effect, `docker
compose restart autoscout`.)

---

## Troubleshooting

**Camoufox download fails during build.** Some networks block GitHub Releases /
Moose CDN. Build the image on a host with clean outbound HTTPS, or pre-pull
the binary and `COPY` it in.

**`chat not found` from Telegram.** The bot must be added to the group with
permission to send messages. For private DMs, the user has to send `/start`
to the bot at least once before the first message.

**Sheets `403`.** Share the spreadsheet with the service-account email
(`client_email` field of `creds.json`) as Editor.

**Scheduled run is skipped.** Check timezone — cron is UTC, not local. To run
at 06:15 Berlin (UTC+1 in winter / UTC+2 in summer), use `15 5 * * *` or
`15 4 * * *` accordingly, or set `TZ=Europe/Berlin` in compose if you want
local interpretation (APScheduler honours the trigger's `timezone` arg, which
we hard-code to UTC; change in `pipeline.py:run_scheduler` if you want host TZ).
