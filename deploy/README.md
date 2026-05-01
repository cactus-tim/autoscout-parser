# Hetzner CAX11 Deployment Guide

This guide walks through a fresh deployment of the AutoScout24 MINI pipeline on a
Hetzner Cloud CAX11 server (Ubuntu 24.04, ARM64). All steps are idempotent; you
can re-run `install.sh` after updates.

## Prerequisites

- **Server**: Hetzner CAX11 (or any EU ARM64 VPS) with Ubuntu 24.04 LTS
- **Access**: SSH access with a user that has `sudo` privileges
- **Credentials ready**:
  - `OPENAI_API_KEY` (paid tier ≥500 RPM recommended — see Troubleshooting)
  - `TG_TOKEN` and `TG_CHAT_ID` (from BotFather — see root README)
  - `SHEET_ID` (Google Sheet URL fragment)
  - `creds.json` (GCP service account — see root README)

---

## Step 1 — Provision the VPS

1. Log in to [Hetzner Cloud Console](https://console.hetzner.cloud/).
2. Click **+ New Server**.
3. Choose:
   - **Location**: any EU region (DE recommended for MINI listings)
   - **Image**: Ubuntu 24.04
   - **Type**: CAX11 (2 vCPU ARM64, 4 GB RAM)
   - **SSH key**: add your public key
4. Click **Create & Buy Now**.
5. Note the server's public IP address.

---

## Step 2 — SSH in and clone the repo

```bash
ssh root@<SERVER_IP>

# Clone the repository as root (or your sudo user) to /opt/autoscout
git clone https://github.com/<your-org>/autoscout-parser.git /opt/autoscout

# Hand ownership to your current user so you can edit config files;
# install.sh will later create the dedicated 'autoscout' system user
# and chown only the runtime artefacts it writes.
chown -R $USER:$USER /opt/autoscout
```

---

## Step 3 — Configure environment variables

```bash
cd /opt/autoscout
cp .env.example .env
nano .env   # or vim, or any editor
```

Fill in every required variable:

| Variable         | Description                                        |
|------------------|----------------------------------------------------|
| `OPENAI_API_KEY` | OpenAI API key (paid tier ≥500 RPM for production) |
| `TG_TOKEN`       | Telegram bot token from @BotFather                 |
| `TG_CHAT_ID`     | Your Telegram chat/channel ID from @userinfobot    |
| `SHEET_ID`       | The long ID from your Google Sheet URL             |
| `CREDS_PATH`     | Path to `creds.json` (default: `/opt/autoscout/creds.json`) |

---

## Step 4 — Copy the GCP service-account credentials

Transfer `creds.json` from your local machine to the server:

```bash
# Run this on your LOCAL machine
scp creds.json root@<SERVER_IP>:/opt/autoscout/creds.json
```

The file must be valid JSON (not the example file). See `docs/creds.json.example`
for the expected structure. Protect it:

```bash
chmod 600 /opt/autoscout/creds.json
```

---

## Step 5 — Run the installer

```bash
cd /opt/autoscout
bash deploy/install.sh
```

The script will:
1. Install system dependencies (ARM64 t64 variants for Ubuntu 24.04).
2. Install `uv` if missing.
3. Create the `autoscout` system user at `/opt/autoscout` if missing.
4. Run `uv sync --frozen` to install Python dependencies.
5. Download the camoufox Firefox binary (`python -m camoufox fetch`).
6. Install and enable the systemd service and timer.

Re-running is safe; every step checks whether it is already done.

---

## Step 6 — Dry-run smoke check

Verify the pipeline wires up without writing anything:

```bash
sudo -u autoscout /opt/autoscout/.venv/bin/autoscout-pipeline --dry-run
```

Expected output: a JSON-structured log showing listing counts, scores, and
`dry_run=true` annotations with no Sheets writes or Telegram messages.

---

## Step 7 — Verify the timer

```bash
systemctl list-timers autoscout-pipeline.timer
```

The timer fires daily at **03:15 UTC** with a randomised jitter of up to 600 s
(10 minutes). The `Persistent=true` flag ensures a missed run (e.g. server was
off) fires immediately on next boot.

---

## Logs

Stream live output from the most recent or running job:

```bash
journalctl -u autoscout-pipeline.service -f
```

View the last 200 lines:

```bash
journalctl -u autoscout-pipeline.service -n 200 --no-pager
```

---

## Manual run

Trigger a full run immediately (bypasses the timer schedule):

```bash
sudo systemctl start autoscout-pipeline.service
```

Check the exit status:

```bash
systemctl status autoscout-pipeline.service
```

---

## Updating the pipeline

```bash
cd /opt/autoscout
git pull
bash deploy/install.sh   # re-syncs deps and reloads systemd
```

---

## File layout on the server

```
/opt/autoscout/
  .env                  # secrets — chmod 600
  creds.json            # GCP service account — chmod 600
  brief.md              # scoring brief — edit to tune ranking
  .venv/                # uv-managed virtual environment
  deploy/               # systemd units + this README
/etc/systemd/system/
  autoscout-pipeline.service
  autoscout-pipeline.timer
```
