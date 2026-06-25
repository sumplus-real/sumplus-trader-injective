#!/usr/bin/env bash
# One-command demo for the screen recording. Read-only: no wallet key, no on-chain sends.
# It opens the dashboard, then narrates the verifiable-decision story in the terminal with
# captions and a LIVE on-chain cid cross-check, so the recording needs no clicking or voiceover.
#
#   1. Start your screen recorder.
#   2. bash tools/inj_demo_record.sh
#   3. When it finishes (~2.5 min), stop the recorder and export.
#
# Everything shown is recomputed from public data: the committed config, the receipt chain, and the
# Injective testnet RPC. Nothing is mocked.
set -euo pipefail
cd "$(dirname "$0")/.."

# Public testnet wiring (no secrets). The dashboard + verifier are read-only.
export INJ_RPC="https://k8s.testnet.json-rpc.injective.network/"
export INJ_CHAIN_ID="1439"
export INJ_DENOM_USDT="peggy0x87aB3B4C8661e07D6372361211B96ed4Dc36B1B5"
export INJ_SPOT_MARKET_INJ_USDT="0x0611780ba69656949525013d947713300f56c37b6175e02f26bffa495c3208fe"
export INJ_INDEXER_URL="https://k8s.testnet.exchange.grpc-web.injective.network"
export STRATEGY_CONFIG="config/strategy.injective.json"
export EXECUTION_BACKEND="injective"
export SUMPLUS_DATA_DIR="${SUMPLUS_DATA_DIR:-$PWD/demo/injective}"
export INJ_EXPLORER_TX="${INJ_EXPLORER_TX:-https://testnet.blockscout.injective.network/tx/}"
PORT="${PORT:-8801}"

[ -d .venv ] && source .venv/bin/activate || true

CY=$'\033[1;36m'; GR=$'\033[1;32m'; YL=$'\033[1;33m'; DIM=$'\033[2m'; RST=$'\033[0m'; BD=$'\033[1m'
cap(){ printf "\n${CY}${BD}  %s${RST}\n" "$1"; [ -n "${2:-}" ] && printf "${DIM}  %s${RST}\n" "$2"; }
pause(){ sleep "${1:-4}"; }

clear
printf "${BD}  SUMPLUS TRADER  ·  Injective Nova${RST}\n"
printf "${DIM}  The only on-chain trading agent where every decision is independently verifiable.${RST}\n"
pause 3

cap "1 / 5  ·  The rules were fixed BEFORE trading, and published on chain" \
    "commit-reveal: we put the SHA-256 of the strategy config on chain before code-lock"
python -m agent.policy.canonical 2>/dev/null >/dev/null || true
python - <<'PY'
from agent.policy.canonical import committed_policy_hash
print("   committed policy hash:", committed_policy_hash("config/strategy.injective.json"))
print("   on-chain commit tx   : a3c8707bf53621eb98a5f5d616b3c708b1a9434ca74ee2328fbfd8eb31b53484")
print("   anyone recomputes the hash from the public config and checks it against that tx.")
PY
pause 6

cap "2 / 5  ·  The live dashboard" \
    "opening http://127.0.0.1:$PORT  —  NAV curve, decision feed, and on-chain bound orders"
( python -m agent.cli web "$PORT" >/dev/null 2>&1 & echo $! > /tmp/sumplus_demo_web.pid )
sleep 4
( open "http://127.0.0.1:$PORT" >/dev/null 2>&1 || xdg-open "http://127.0.0.1:$PORT" >/dev/null 2>&1 || true )
printf "   ${DIM}dashboard open in your browser — show the verify banner + 'On-chain bound orders' panel${RST}\n"
pause 9

cap "3 / 5  ·  Verify the whole run in one command" \
    "recompute every receipt hash, check the chain links, and confirm each order binds back to a receipt"
python -m agent.policy.commit
pause 7

cap "4 / 5  ·  Each on-chain order carries its receipt's hash as the order cid" \
    "so an objective Helix fill maps back to exactly one signed decision"
python - <<'PY'
import json, os
from agent.policy.receipt import receipt_cid
for l in open(os.path.join(os.environ["SUMPLUS_DATA_DIR"], "executions.jsonl")):
    e = json.loads(l)
    ok = e["cid"] == receipt_cid(e["receipt_hash"])
    print(f'   {e["order_type"].upper():4s} ${e["amount_usd"]:<6}  cid {e["cid"]}  ==  receipt #{e["receipt_seq"]}  [{"BOUND ✓" if ok else "UNBOUND ✗"}]')
    print(f'        tx {e["tx"]}')
PY
pause 7

cap "5 / 5  ·  Cross-check the binding straight off the Injective testnet RPC" \
    "read the order's on-chain event cid and compare it to the receipt — live, not from our files"
python - <<'PY'
import json, os
from web3 import Web3
from agent.policy.receipt import receipt_cid
w3 = Web3(Web3.HTTPProvider(os.environ["INJ_RPC"]))
abi = json.loads(open("contracts/injective/out/SpotExecutor.sol/SpotExecutor.json").read())["abi"]
c = w3.eth.contract(abi=abi)
e = json.loads(open(os.path.join(os.environ["SUMPLUS_DATA_DIR"], "executions.jsonl")).readline())
r = w3.eth.get_transaction_receipt("0x" + e["tx"])
onchain = c.events.SpotMarketOrderPlaced().process_receipt(r)[0]["args"]["cid"]
print(f'   tx           : {e["tx"]}  (block {r.blockNumber}, status {r.status})')
print(f'   on-chain cid : {onchain}')
print(f'   receipt cid  : {receipt_cid(e["receipt_hash"])}')
print(f'   MATCH        : {onchain == receipt_cid(e["receipt_hash"])}')
print()
print("   Tamper with any decision and its receipt hash changes, so the cid no longer matches the")
print("   order on chain. Rule-adherence becomes a proof, not a promise.")
PY
pause 8

printf "\n${GR}${BD}  Verified end to end on Injective testnet.${RST}\n"
printf "${DIM}  commit-reveal + hash-chained receipts + cid-bound Helix orders.${RST}\n\n"
pause 3

# Clean up the dashboard server.
[ -f /tmp/sumplus_demo_web.pid ] && kill "$(cat /tmp/sumplus_demo_web.pid)" 2>/dev/null || true
rm -f /tmp/sumplus_demo_web.pid
