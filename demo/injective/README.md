# Injective testnet demo run — verifiable artifacts

These are the real artifacts from a live Injective EVM testnet (chain 1439) run of the agent. They
are committed so anyone can verify rule-adherence without trusting us or re-running anything.

- `receipts.jsonl` — the hash-chained decision receipts (14 decisions). Every receipt references the
  committed policy hash `sha256:59991a59…` and links to the previous one.
- `executions.jsonl` — the two on-chain Helix orders, each carrying its receipt's hash as the order
  `cid`. A real bound BUY and a take-profit SELL.
- `live_equity.jsonl` — the NAV curve the loop recorded each tick.
- `abstentions.jsonl` — the avoided-loss ledger: every decline, marked to market.

## Verify it yourself

```sh
STRATEGY_CONFIG=config/strategy.injective.json EXECUTION_BACKEND=injective \
SUMPLUS_DATA_DIR=demo/injective python -m agent.policy.commit
```

Expect `chain_intact: true`, `all_reference_committed_hash: true`, `executions_bound: true`.

Cross-check a binding straight off the chain (read-only, public RPC):

```sh
INJ_RPC=https://k8s.testnet.json-rpc.injective.network/ python - <<'PY'
import json
from web3 import Web3
from agent.policy.receipt import receipt_cid
w3 = Web3(Web3.HTTPProvider("https://k8s.testnet.json-rpc.injective.network/"))
abi = json.loads(open("contracts/injective/out/SpotExecutor.sol/SpotExecutor.json").read())["abi"]
c = w3.eth.contract(abi=abi)
e = json.loads(open("demo/injective/executions.jsonl").readline())
r = w3.eth.get_transaction_receipt("0x" + e["tx"])
onchain = c.events.SpotMarketOrderPlaced().process_receipt(r)[0]["args"]["cid"]
print("on-chain cid:", onchain, "==", receipt_cid(e["receipt_hash"]), "->", onchain == receipt_cid(e["receipt_hash"]))
PY
```

On-chain references: commit `a3c8707b…`, BUY `d31ba264…`, SELL `107d6935…`. See `docs/INJECTIVE_DEMO.md`.
