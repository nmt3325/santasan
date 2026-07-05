#!/usr/bin/env bash
set -euo pipefail

# Run santasan with one shared CDP port by switching Chrome user-data-dir
# account by account. This script is intended for the Debian/headless host.

ACCOUNTS="${ACCOUNTS:-account1 account2 account3}"
CHROME_BIN="${CHROME_BIN:-google-chrome}"
CHROME_DATA_ROOT="${CHROME_DATA_ROOT:-/data/chrome}"
RUNTIME_DIR="${RUNTIME_DIR:-/run/santasan}"
CDP_HOST="${CDP_HOST:-127.0.0.1}"
CDP_PORT="${CDP_PORT:-9222}"
RELAY_URL="${RELAY_SERVER_URL:-http://127.0.0.1:3001}"
RELAY_PROFILE_NAME="${RELAY_PROFILE_NAME:-active}"
CONFIG_PATH="${CONFIG_PATH:-config.yaml}"
PYTHON_BIN="${PYTHON_BIN:-.venv/bin/python}"
PROJECT_DIR="${PROJECT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
RELAY_COMPOSE_DIR="${RELAY_COMPOSE_DIR:-$HOME/daemons/twitter_api_safe_relay/docker}"
RELAY_COMPOSE_FILE="${RELAY_COMPOSE_FILE:-docker-compose.yml}"
LOCK_FILE="${LOCK_FILE:-$RUNTIME_DIR/lock}"
RUN_ONCE="${RUN_ONCE:---once}"

mkdir -p "$RUNTIME_DIR"

log() {
  printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"
}

wait_http() {
  local url="$1"
  local attempts="${2:-60}"
  for _ in $(seq 1 "$attempts"); do
    if curl -fsS "$url" >/dev/null 2>&1; then
      return 0
    fi
    sleep 0.5
  done
  return 1
}

stop_relay() {
  if [ -d "$RELAY_COMPOSE_DIR" ]; then
    docker compose -f "$RELAY_COMPOSE_DIR/$RELAY_COMPOSE_FILE" stop twitter-relay >/dev/null 2>&1 || true
  fi
}

start_relay() {
  docker compose -f "$RELAY_COMPOSE_DIR/$RELAY_COMPOSE_FILE" up -d twitter-relay
  wait_http "$RELAY_URL/health" 60
}

stop_chrome() {
  local pid=""
  if [ -f "$RUNTIME_DIR/chrome.pid" ]; then
    pid="$(cat "$RUNTIME_DIR/chrome.pid" 2>/dev/null || true)"
  fi

  if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
    log "Stopping Chrome pid=$pid"
    kill "$pid" 2>/dev/null || true
    for _ in $(seq 1 30); do
      kill -0 "$pid" 2>/dev/null || break
      sleep 0.5
    done
    kill -9 "$pid" 2>/dev/null || true
  fi

  if [ -f "$RUNTIME_DIR/active" ]; then
    local active
    active="$(cat "$RUNTIME_DIR/active" 2>/dev/null || true)"
    if [ -n "$active" ]; then
      rm -f "$CHROME_DATA_ROOT/$active"/Singleton{Lock,Socket,Cookie} 2>/dev/null || true
      rm -f "$CHROME_DATA_ROOT/$active"/DevToolsActivePort 2>/dev/null || true
    fi
  fi

  rm -f "$RUNTIME_DIR/chrome.pid"
}

start_chrome() {
  local account="$1"
  local profile_dir="$CHROME_DATA_ROOT/$account"
  mkdir -p "$profile_dir"

  log "Starting Chrome for $account using $profile_dir"
  "$CHROME_BIN" \
    --headless=new \
    --remote-debugging-address="$CDP_HOST" \
    --remote-debugging-port="$CDP_PORT" \
    --user-data-dir="$profile_dir" \
    --no-first-run \
    --no-default-browser-check \
    --disable-dev-shm-usage \
    about:blank >/tmp/santasan-chrome-"$account".log 2>&1 &

  echo "$!" > "$RUNTIME_DIR/chrome.pid"
  echo "$account" > "$RUNTIME_DIR/active"
  wait_http "http://$CDP_HOST:$CDP_PORT/json/version" 60
}

assert_login_alive() {
  local account="$1"
  curl -fsS -H "x-profile-name: $RELAY_PROFILE_NAME" "$RELAY_URL/2/users/me" >/tmp/santasan-users-me-"$account".json
}

run_account() {
  local account="$1"
  stop_relay
  stop_chrome
  start_chrome "$account"
  start_relay

  if ! assert_login_alive "$account"; then
    log "SKIP $account: X login is not alive. Re-login this Chrome profile."
    return 0
  fi

  log "Running santasan for $account"
  (
    cd "$PROJECT_DIR"
    USE_SAFE_RELAY=true \
      RELAY_SERVER_URL="$RELAY_URL" \
      RELAY_PROFILE_NAME="$RELAY_PROFILE_NAME" \
      CDP_ENDPOINT_URL="http://$CDP_HOST:$CDP_PORT" \
      "$PYTHON_BIN" src/main.py --config "$CONFIG_PATH" --account "$account" $RUN_ONCE
  )
}

main() {
  exec 9>"$LOCK_FILE"
  flock -n 9 || {
    log "Another santasan active-profile cycle is already running."
    exit 1
  }

  trap 'stop_relay; stop_chrome' EXIT

  for account in $ACCOUNTS; do
    run_account "$account"
  done
}

main "$@"
