#!/usr/bin/env bash
# Display Visualizer installer for Raspberry Pi 4 / 5 (Raspberry Pi OS,
# Debian Bookworm / Bullseye). Idempotent — safe to re-run to upgrade.
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/PierreGode/Display-visualizer/main/install.sh | bash
#   # or from a clone:
#   sudo bash install.sh
#
# What it does:
#   1. Installs apt deps (python3-venv, python3-pip, nodejs 20, git, DejaVu
#      Sans + Sans Mono fonts used by the sim's text/char-LCD rendering)
#   2. Clones or updates the repo under /opt/display-visualizer
#   3. Creates a Python venv and installs backend deps
#   4. Builds the frontend to backend-served static files
#   5. Installs a systemd unit that runs uvicorn on port 8080
#
# Configuration via env vars (all optional):
#   INSTALL_DIR         default /opt/display-visualizer
#   REPO_URL            default https://github.com/PierreGode/Display-visualizer.git
#   REPO_REF            default main
#   PORT                default 8080
#   SERVICE_USER        default www-data (or 'pi' if it exists)
#   CLAUDE_PROJECT_DIR  default /project — Claude can read files in this dir only
#   CLAUDE_CONFIG_DIR   default <INSTALL_DIR>/.claude-config — service-writable
#                       Claude Code config/credentials dir (so the in-app web
#                       login can persist a session even though /home is mounted
#                       read-only for the service)
#   SKIP_CLAUDE=1       skip installing Claude Code CLI (opt out of AI assistant)

set -euo pipefail

INSTALL_DIR="${INSTALL_DIR:-/opt/display-visualizer}"
REPO_URL="${REPO_URL:-https://github.com/PierreGode/Display-visualizer.git}"
REPO_REF="${REPO_REF:-main}"
PORT="${PORT:-8080}"
CLAUDE_PROJECT_DIR="${CLAUDE_PROJECT_DIR:-/project}"
CLAUDE_CONFIG_DIR="${CLAUDE_CONFIG_DIR:-${INSTALL_DIR}/.claude-config}"
SKIP_CLAUDE="${SKIP_CLAUDE:-0}"

if id pi >/dev/null 2>&1; then
    SERVICE_USER="${SERVICE_USER:-pi}"
else
    SERVICE_USER="${SERVICE_USER:-www-data}"
fi

log() { printf '\033[1;32m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m==>\033[0m %s\n' "$*" >&2; }
die() { printf '\033[1;31m==>\033[0m %s\n' "$*" >&2; exit 1; }

if [[ $EUID -ne 0 ]]; then
    die "install.sh must be run as root (use sudo)."
fi

if [[ ! -f /etc/os-release ]]; then
    warn "Cannot detect OS. Continuing anyway."
else
    . /etc/os-release
    log "Detected: ${PRETTY_NAME:-unknown}"
fi

log "Installing apt dependencies (this may take a while)…"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y --no-install-recommends \
    git \
    python3 \
    python3-venv \
    python3-pip \
    fonts-dejavu-core \
    fonts-dejavu-mono \
    ca-certificates \
    curl \
    build-essential \
    >/dev/null

if ! command -v node >/dev/null 2>&1 || ! node --version | grep -qE '^v(20|21|22)\.'; then
    log "Installing Node.js 20.x via NodeSource…"
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash - >/dev/null
    apt-get install -y --no-install-recommends nodejs >/dev/null
else
    log "Node.js already present: $(node --version)"
fi

if [[ "${SKIP_CLAUDE}" != "1" ]]; then
    if ! command -v claude >/dev/null 2>&1; then
        log "Installing Claude Code CLI (@anthropic-ai/claude-code)…"
        npm install -g @anthropic-ai/claude-code >/dev/null
    else
        log "Claude Code CLI already present: $(claude --version 2>/dev/null || echo unknown)"
    fi
fi

log "Cloning / updating repo to ${INSTALL_DIR}…"
if [[ -d "${INSTALL_DIR}/.git" ]]; then
    git -C "${INSTALL_DIR}" fetch --quiet origin "${REPO_REF}"
    git -C "${INSTALL_DIR}" checkout --quiet "${REPO_REF}"
    git -C "${INSTALL_DIR}" reset --hard "origin/${REPO_REF}" --quiet
else
    mkdir -p "$(dirname "${INSTALL_DIR}")"
    git clone --branch "${REPO_REF}" --depth 1 "${REPO_URL}" "${INSTALL_DIR}" >/dev/null
fi

log "Creating Python venv and installing backend deps…"
python3 -m venv "${INSTALL_DIR}/.venv"
"${INSTALL_DIR}/.venv/bin/pip" install --quiet --upgrade pip
"${INSTALL_DIR}/.venv/bin/pip" install --quiet -r "${INSTALL_DIR}/requirements.txt"

log "Building frontend…"
pushd "${INSTALL_DIR}/frontend" >/dev/null
npm ci --silent --no-audit --no-fund
npm run build --silent
popd >/dev/null

log "Setting ownership to ${SERVICE_USER}…"
chown -R "${SERVICE_USER}:${SERVICE_USER}" "${INSTALL_DIR}"

if [[ -f "${INSTALL_DIR}/update.sh" ]]; then
    chmod +x "${INSTALL_DIR}/update.sh"
fi

log "Installing sudoers rule so the service can restart itself on update…"
SUDOERS_FILE="/etc/sudoers.d/display-visualizer"
cat >"${SUDOERS_FILE}" <<EOF
# Allow the service user to restart the visualizer without a password. Scoped
# to exactly this unit — no other systemctl actions permitted.
${SERVICE_USER} ALL=(root) NOPASSWD: /bin/systemctl restart display-visualizer.service
EOF
chmod 0440 "${SUDOERS_FILE}"
if ! visudo -cf "${SUDOERS_FILE}" >/dev/null; then
    warn "sudoers rule failed validation — removing"
    rm -f "${SUDOERS_FILE}"
fi

if [[ ! -d "${CLAUDE_PROJECT_DIR}" ]]; then
    log "Creating empty project dir at ${CLAUDE_PROJECT_DIR} (Claude will read files here)…"
    mkdir -p "${CLAUDE_PROJECT_DIR}"
    chown "${SERVICE_USER}:${SERVICE_USER}" "${CLAUDE_PROJECT_DIR}"
fi

if [[ "${SKIP_CLAUDE}" != "1" ]]; then
    log "Preparing Claude config dir at ${CLAUDE_CONFIG_DIR} (writable by ${SERVICE_USER} for in-app login)…"
    mkdir -p "${CLAUDE_CONFIG_DIR}"
    chown -R "${SERVICE_USER}:${SERVICE_USER}" "${CLAUDE_CONFIG_DIR}"
    chmod 0700 "${CLAUDE_CONFIG_DIR}"

    # If the service user already ran `claude login` in their own home, carry
    # that session into the service config dir so the app works immediately
    # without a second login. Fresh installs use the in-app 'Sign in' button.
    USER_HOME="$(getent passwd "${SERVICE_USER}" | cut -d: -f6)"
    if [[ -n "${USER_HOME}" && -f "${USER_HOME}/.claude/.credentials.json" \
          && ! -f "${CLAUDE_CONFIG_DIR}/.credentials.json" ]]; then
        log "Seeding existing Claude login from ${USER_HOME}/.claude…"
        cp "${USER_HOME}/.claude/.credentials.json" "${CLAUDE_CONFIG_DIR}/.credentials.json"
        chown "${SERVICE_USER}:${SERVICE_USER}" "${CLAUDE_CONFIG_DIR}/.credentials.json"
        chmod 0600 "${CLAUDE_CONFIG_DIR}/.credentials.json"
    fi
fi

ENV_FILE="/etc/display-visualizer.env"
if [[ ! -f "${ENV_FILE}" ]]; then
    log "Creating ${ENV_FILE} (edit to point Claude at a project on this Pi)…"
    cat >"${ENV_FILE}" <<ENVEOF
# Runtime overrides for display-visualizer. Edited values survive reinstalls.
# Point the in-app Claude agent at a codebase it may read (read-only). It can be
# any directory the service user can read, including another user's home — the
# service mounts /home read-only, so reading is allowed. Example:
#   CLAUDE_PROJECT_DIR=/home/ragnar/Ragnar
#CLAUDE_PROJECT_DIR=${CLAUDE_PROJECT_DIR}
ENVEOF
    chmod 0644 "${ENV_FILE}"
fi

log "Installing systemd unit…"
cat >/etc/systemd/system/display-visualizer.service <<EOF
[Unit]
Description=Display Visualizer
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${SERVICE_USER}
Group=${SERVICE_USER}
WorkingDirectory=${INSTALL_DIR}
Environment=CLAUDE_PROJECT_DIR=${CLAUDE_PROJECT_DIR}
Environment=CLAUDE_CONFIG_DIR=${CLAUDE_CONFIG_DIR}
# Optional operator overrides (e.g. CLAUDE_PROJECT_DIR); wins over the lines
# above. Loaded last so edits to the env file take effect without touching this
# unit. The leading '-' makes it optional.
EnvironmentFile=-/etc/display-visualizer.env
ExecStart=${INSTALL_DIR}/.venv/bin/uvicorn backend.main:app --host 0.0.0.0 --port ${PORT}
Restart=on-failure
RestartSec=3
# Modest sandboxing — user code already runs in its own subprocess.
# ProtectHome is 'read-only' (not 'true') so the service can read the
# Claude Code CLI's OAuth session in ~${SERVICE_USER}/.claude/.
NoNewPrivileges=true
ProtectSystem=full
ProtectHome=read-only
PrivateTmp=true

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now display-visualizer.service >/dev/null

sleep 1
if systemctl is-active --quiet display-visualizer.service; then
    IP=$(hostname -I 2>/dev/null | awk '{print $1}' || echo "<pi-ip>")
    log "Service is up. Open http://${IP}:${PORT} on your LAN."
    if [[ "${SKIP_CLAUDE}" != "1" ]]; then
        log "AI assistant: open the app, click the Claude panel, and use 'Sign in to Claude' — the whole login runs in the browser."
    fi
else
    warn "Service failed to start. Diagnostic:"
    journalctl -u display-visualizer.service --no-pager -n 30 || true
    exit 1
fi
