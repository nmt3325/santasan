#!/usr/bin/env bash
set -uo pipefail

PROFILES_DIR="${PROFILES_DIR:-/data/chrome}"
CDP_PORT="${CDP_PORT:-9222}"
RELAY_PORT="${RELAY_PORT:-3000}"
ACCOUNTS="${ACCOUNTS:-account1}"
RELAY_START="${RELAY_START:-pnpm start:relay}"
CONFIG_PATH="${CONFIG_PATH:-config.yaml}"
RUN_ONCE="${RUN_ONCE:---once}"
PY="/app/santasan/.venv/bin/python"

CHROME_PID=""
RELAY_PID=""

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

start_chrome() {
  local acct="$1"
  local dir="$PROFILES_DIR/$acct"
  mkdir -p "$dir"
  rm -f "$dir"/Singleton{Lock,Socket,Cookie} "$dir"/DevToolsActivePort 2>/dev/null || true

  log "[chrome] starting account=$acct dir=$dir"
  chromium \
    --headless=new \
    --no-sandbox \
    --password-store=basic \
    --remote-debugging-address=127.0.0.1 \
    --remote-debugging-port="$CDP_PORT" \
    --user-data-dir="$dir" \
    --no-first-run \
    --no-default-browser-check \
    --disable-dev-shm-usage \
    about:blank >/tmp/santasan-chrome-"$acct".log 2>&1 &

  CHROME_PID=$!
  for _ in $(seq 1 60); do
    curl -fsS "http://127.0.0.1:$CDP_PORT/json/version" >/dev/null 2>&1 && return 0
    kill -0 "$CHROME_PID" 2>/dev/null || {
      log "[chrome] died account=$acct"
      tail -n 80 /tmp/santasan-chrome-"$acct".log 2>/dev/null || true
      return 1
    }
    sleep 0.5
  done
  log "[chrome] CDP not ready account=$acct"
  tail -n 80 /tmp/santasan-chrome-"$acct".log 2>/dev/null || true
  return 1
}

stop_chrome() {
  [ -n "$CHROME_PID" ] || return 0
  log "[chrome] stopping pid=$CHROME_PID"
  kill "$CHROME_PID" 2>/dev/null || true
  for _ in $(seq 1 20); do
    kill -0 "$CHROME_PID" 2>/dev/null || break
    sleep 0.5
  done
  kill -9 "$CHROME_PID" 2>/dev/null || true
  CHROME_PID=""
}

start_relay() {
  log "[relay] starting"
  ( cd /app/relay && eval "$RELAY_START" ) >/tmp/santasan-relay.log 2>&1 &
  RELAY_PID=$!
  for _ in $(seq 1 60); do
    curl -fsS "http://127.0.0.1:$RELAY_PORT/health" >/dev/null 2>&1 && return 0
    kill -0 "$RELAY_PID" 2>/dev/null || {
      log "[relay] died"
      tail -n 120 /tmp/santasan-relay.log 2>/dev/null || true
      return 1
    }
    sleep 0.5
  done
  log "[relay] health timeout"
  tail -n 120 /tmp/santasan-relay.log 2>/dev/null || true
  return 1
}

stop_relay() {
  [ -n "$RELAY_PID" ] || return 0
  log "[relay] stopping pid=$RELAY_PID"
  kill "$RELAY_PID" 2>/dev/null || true
  wait "$RELAY_PID" 2>/dev/null || true
  RELAY_PID=""
}

login_alive() {
  local code
  code="$(curl -sS -o /tmp/santasan-users-me.json -w '%{http_code}' \
    -H "x-profile-name: active" \
    "http://127.0.0.1:$RELAY_PORT/2/users/me" || true)"
  [ "$code" = "200" ]
}

cleanup() {
  stop_relay
  stop_chrome
}
trap cleanup EXIT INT TERM

run_santasan_account() {
  local acct="$1"
  log "==================== $acct ===================="

  start_chrome "$acct" || {
    log "[skip] $acct chrome failed"
    stop_chrome
    return 0
  }

  start_relay || {
    log "[skip] $acct relay failed"
    stop_relay
    stop_chrome
    return 0
  }

  if login_alive; then
    log "[santasan] running account=$acct"
    (
      cd /app/santasan
      USE_SAFE_RELAY=true \
      RELAY_SERVER_URL="http://127.0.0.1:$RELAY_PORT" \
      RELAY_PROFILE_NAME=active \
      CDP_ENDPOINT_URL="http://127.0.0.1:$CDP_PORT" \
      "$PY" src/main.py --config "$CONFIG_PATH" --account "$acct" $RUN_ONCE
    ) || log "[warn] santasan run failed account=$acct"
  else
    log "[alert] $acct session dead. Run login mode for this account."
    cat /tmp/santasan-users-me.json 2>/dev/null || true
  fi

  stop_relay
  stop_chrome
  sleep 1
}

run_all() {
  local normalized
  normalized="${ACCOUNTS//,/ }"
  for acct in $normalized; do
    run_santasan_account "$acct"
  done
}

login_mode() {
  local acct="${1:?usage: login <account>}"
  start_chrome "$acct" || exit 1
  log "[login] ready for $acct on 127.0.0.1:$CDP_PORT"
  log "[login] use SSH tunnel, then open chrome://inspect on your Mac"
  wait "$CHROME_PID"
}

verify_mode() {
  local acct="${1:?usage: verify <account>}"
  start_chrome "$acct" || exit 1
  start_relay || exit 1
  if login_alive; then
    log "OK: $acct logged in"
    cat /tmp/santasan-users-me.json
  else
    log "NG: $acct login/session failed"
    cat /tmp/santasan-users-me.json 2>/dev/null || true
    exit 1
  fi
}

MODE="${1:-run}"
shift || true

case "$MODE" in
  run) run_all ;;
  login) login_mode "$@" ;;
  verify) verify_mode "$@" ;;
  *) log "unknown mode: $MODE"; exit 1 ;;
esac
