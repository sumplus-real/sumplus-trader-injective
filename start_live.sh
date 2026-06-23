#!/usr/bin/env bash
# Launch the unattended live trading loop, detached so it survives the terminal/session closing.
# Secrets are read at runtime: .env (gitignored) + the protected wallet-password file. No secret here.
set -euo pipefail
cd "$(dirname "$0")"

# Node 22 must be on PATH so the python twak subprocess can find the CLI.
export NVM_DIR="$HOME/.nvm"
# shellcheck disable=SC1091
source "$NVM_DIR/nvm.sh"
nvm use 22 >/dev/null

# Load config (DEEPSEEK/CMC keys, EXECUTION_BACKEND=twak, TWAK_BIN abs path, BSC_RPC, START_NAV).
set -a
# shellcheck disable=SC1091
source .env
set +a

# Wallet password for unattended twak signing (keychain fallback may not be available when detached).
export TWAK_WALLET_PASSWORD="$(cat "$HOME/.config/sumplus-trader/wallet-password.txt")"

# Belt-and-suspenders: force the live signer regardless of shell.
export EXECUTION_BACKEND=twak
export MODE=live

# Unbuffered stdout so live_run.log shows ticks in real time during the unattended window.
export PYTHONUNBUFFERED=1

echo "[start_live] node=$(node -v) backend=$EXECUTION_BACKEND start_nav=$START_NAV $(date)" >> live_run.log
exec /usr/local/bin/python3 -m agent.cli loop
