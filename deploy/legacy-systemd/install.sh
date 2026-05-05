#!/usr/bin/env bash
# Idempotent installer for Hetzner CAX11 (Ubuntu 24.04 ARM64).
# Re-run safely: skips already-installed packages.
set -euo pipefail

# NOTE: Ubuntu 24.04 introduced t64 ABI for time-related libs (Y2038 fix).
# Several X11/GTK packages were renamed. Verify these names on the target system
# via `apt-cache search libxcomposite` if install fails.
PKGS=(
  git curl
  libgtk-3-0t64
  libxt6t64
  libxcomposite1t64
  libxdamage1
  libxrandr2
  libgbm1
  libpango-1.0-0
  libasound2t64
  fonts-liberation
)

echo "→ apt update + install system deps"
sudo apt-get update -qq
sudo apt-get install -y --no-install-recommends "${PKGS[@]}"

echo "→ install uv (if missing)"
if ! command -v uv &>/dev/null; then
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
fi

echo "→ create autoscout user (if missing)"
if ! id -u autoscout &>/dev/null; then
    sudo useradd --system --create-home --home-dir /opt/autoscout --shell /bin/bash autoscout
fi

echo "→ sync deps in /opt/autoscout"
sudo -u autoscout bash -c 'cd /opt/autoscout && uv sync --frozen'

echo "→ download camoufox firefox binary"
sudo -u autoscout bash -c 'cd /opt/autoscout && uv run python -m camoufox fetch'

echo "→ install systemd unit + timer"
sudo cp deploy/autoscout-pipeline.service /etc/systemd/system/
sudo cp deploy/autoscout-pipeline.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now autoscout-pipeline.timer

echo "✓ done. Check status: systemctl list-timers autoscout-pipeline.timer"
