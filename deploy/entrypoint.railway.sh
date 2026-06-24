#!/usr/bin/env bash
# Container entrypoint for the live trader.
#   1. Restore the twak signer keystore from base64 env vars (never baked into the image).
#   2. Seed the durable data volume from the committed demo files on first boot.
#   3. Run the dashboard (background, binds $PORT) + the live loop (foreground). If either
#      process exits, take the container down non-zero so Railway restarts it cleanly.
# No secret is ever echoed.
set -uo pipefail

DATA_DIR="${SUMPLUS_DATA_DIR:-/data}"
mkdir -p "$DATA_DIR" "$HOME/.twak"

# ── 1. Restore the signer keystore ──────────────────────────────────────────────────────
if [ -n "${TWAK_WALLET_JSON_B64:-}" ]; then
  echo "$TWAK_WALLET_JSON_B64" | base64 -d > "$HOME/.twak/wallet.json" \
    || { echo "[entrypoint] FATAL: wallet.json decode failed"; exit 1; }
  chmod 600 "$HOME/.twak/wallet.json"
  echo "[entrypoint] restored ~/.twak/wallet.json"
else
  echo "[entrypoint] WARN: TWAK_WALLET_JSON_B64 unset (fine for paper/mock mode)"
fi
if [ -n "${TWAK_CREDENTIALS_JSON_B64:-}" ]; then
  echo "$TWAK_CREDENTIALS_JSON_B64" | base64 -d > "$HOME/.twak/credentials.json" \
    || { echo "[entrypoint] FATAL: credentials.json decode failed"; exit 1; }
  chmod 600 "$HOME/.twak/credentials.json"
  echo "[entrypoint] restored ~/.twak/credentials.json"
fi

# ── 2. Seed the durable data dir on first boot ──────────────────────────────────────────
# Committed demo files give the dashboard something to render and let the receipt chain
# continue from the published history. Never overwrite data already on the volume.
for f in receipts.jsonl ledger.jsonl abstentions.jsonl x402_receipts.jsonl sim_equity.jsonl; do
  if [ ! -f "$DATA_DIR/$f" ] && [ -f "/app/$f" ]; then
    cp "/app/$f" "$DATA_DIR/$f"
    echo "[entrypoint] seeded $f"
  fi
done
# Optional one-time live_state seed (carries high-water-mark + guardrail counters at cutover).
if [ ! -f "$DATA_DIR/live_state.json" ] && [ -n "${SEED_LIVE_STATE_B64:-}" ]; then
  echo "$SEED_LIVE_STATE_B64" | base64 -d > "$DATA_DIR/live_state.json" \
    && echo "[entrypoint] seeded live_state.json from cutover snapshot"
fi

# ── 3. Supervise dashboard + loop ───────────────────────────────────────────────────────
PORT="${PORT:-8800}"
echo "[entrypoint] node=$(node -v) python=$(python3 --version) backend=${EXECUTION_BACKEND:-mock} mode=${MODE:-paper}"

uvicorn agent.web:app --host 0.0.0.0 --port "$PORT" &
DASH_PID=$!
python3 -m agent.cli loop &
LOOP_PID=$!

# Whichever exits first brings the container down so Railway restarts both cleanly.
wait -n "$DASH_PID" "$LOOP_PID"
echo "[entrypoint] a child process exited; stopping container for a clean restart"
kill "$DASH_PID" "$LOOP_PID" 2>/dev/null || true
exit 1
