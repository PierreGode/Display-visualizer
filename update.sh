#!/usr/bin/env bash
# Display Visualizer — self-update script.
#
# Runs from the repo root as the service user. Called by the backend when the
# user clicks "Update" in the UI; can also be invoked directly:
#
#   sudo -u pi bash /opt/waveshare-visualizer/update.sh
#
# What it does:
#   1. git fetch + git reset --hard origin/main
#   2. Reinstalls Python deps in the venv
#   3. Rebuilds the frontend
#   4. Restarts the systemd unit (requires the sudoers rule installed by
#      install.sh: `%svc ALL=(root) NOPASSWD: /bin/systemctl restart …`)
#
# Any output is captured by the backend into /tmp/waveshare-visualizer-update-*.log.

set -euo pipefail

INSTALL_DIR="$(cd "$(dirname "$0")" && pwd)"
SERVICE_NAME="${SERVICE_NAME:-waveshare-visualizer.service}"

log() { printf '[update %(%H:%M:%S)T] %s\n' -1 "$*"; }

log "starting update in ${INSTALL_DIR}"
cd "${INSTALL_DIR}"

log "git fetch"
git fetch --quiet origin main

log "git reset --hard origin/main"
git reset --hard origin/main --quiet

if [[ -f requirements.txt && -x .venv/bin/pip ]]; then
    log "pip install -r requirements.txt"
    .venv/bin/pip install --quiet --upgrade -r requirements.txt
fi

if [[ -f frontend/package.json ]]; then
    log "npm ci && npm run build"
    (
        cd frontend
        npm ci --silent --no-audit --no-fund
        npm run build --silent
    )
fi

log "restarting ${SERVICE_NAME}"
# systemctl restart is executed via sudo — install.sh drops a NOPASSWD rule
# scoped to exactly this unit. If the rule is missing this line will fail
# loudly and the previous version keeps running.
if command -v sudo >/dev/null 2>&1; then
    sudo -n /bin/systemctl restart "${SERVICE_NAME}"
else
    /bin/systemctl restart "${SERVICE_NAME}"
fi

log "done"
