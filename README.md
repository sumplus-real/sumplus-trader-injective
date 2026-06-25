# Sumplus Trader on Injective

An autonomous trading agent on Injective whose every decision anyone can independently verify.
Before it trades, it publishes the hash of its strategy on chain. Every decision it then makes
becomes a hash-chained receipt, and every order it places on Helix carries that receipt's hash as
its on-chain client id. The order the exchange matched maps back to exactly one signed decision,
against rules the agent fixed before the market moved.

Built for Injective Nova. **Start with [`docs/INJECTIVE_DEMO.md`](docs/INJECTIVE_DEMO.md).** The
verified testnet artifacts (14 hash-chained receipts, 2 cid-bound Helix orders) ship in
[`demo/injective/`](demo/injective/), so anyone can verify rule-adherence without re-running
anything.

**On-chain proof (Injective EVM testnet, chain 1439).** Commit `a3c8707b…`, bound BUY `d31ba264…`
(cid `299b3af4…` equals receipt #0), bound SELL `107d6935…` (cid `a6f8f83b…` equals receipt #11).

## How it binds to Injective

Helix is a fully on-chain central limit order book, so each order is an on-chain object rather than
an off-chain promise, and the Exchange precompile lets every order carry a client id into the
chain's own records. Our SpotExecutor contract places spot orders through that precompile with the
client id set to the decision receipt's hash. On most chains you can verify the decision. On
Injective you can verify the decision and the fill, and confirm they are the same event.

The verifiable core, the survival-first strategy, the policy engine, the CoinMarketCap data client
paid per request over x402, and the operational hardening (watchdog, RPC failover, durable intent,
crash-safe restart) carry over from the BNB build this is based on. TWAK keeps signing keys on the
machine and ERC-8004 carries the agent's on-chain identity and policy commitment.

## Quickstart (no keys, no network)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

python -m agent.cli demo        # guardrail: allow / clamp / reject
python -m agent.cli simulate 6  # drive the real pipeline over a 6-week crash-and-recovery
python -m agent.cli verify      # recompute the committed hash + verify the receipt chain
python -m agent.cli web         # dashboard at http://127.0.0.1:8800
python -m pytest -q             # full test suite
python backtest/run.py          # Track 2: champion vs challenger head-to-head
```

Out of the box it runs fully offline: a deterministic mock brain, a mock execution backend, and a
fixed CMC scenario. Add your keys and set `EXECUTION_BACKEND=twak` to trade for real.

## Layout

- `agent/strategy/`: the survival-first strategy (signals and intent), frozen in `config/strategy.json`
- `agent/policy/`: the Maria layer. Policy engine, hash-chained receipts, commit-reveal.
- `agent/abstention/`: the avoided-loss ledger, so a decision not to trade is recorded too
- `agent/data/`: CoinMarketCap MCP client and x402 receipts, the only data source
- `agent/execution/`: the `ExecutionBackend` seam with a TWAK adapter, a Maria client, and an offline mock
- `agent/ops/`: what it takes to survive a week alone. Watchdog, RPC failover, nonce, persistent state, reconcile.
- `agent/identity/`: ERC-8004 registration and the commit-reveal publisher
- `agent/core.py`: the decision tick where every layer meets. `agent/simulate.py` drives a synthetic week.
- `agent/web.py`: the dashboard. `agent/run_live.py`: the live unattended loop.
- `skills/sumplus-survival-strategy/`: the Track 2 CMC Strategy Skill. Reads CMC market data, emits a backtestable StrategySpec.
- `backtest/`: the Track 2 head-to-head plus `real_data_live.py` (the committed spec on real recent data). `docs/`: BUILD_SPEC, TRACK2_RESEARCH, HUMAN_STEPS.

## Verifiability

`config/strategy.json` is the committed policy. Its SHA-256, with comments stripped, keys sorted,
and whitespace removed, gets published to the agent's ERC-8004 identity before code-lock. Every
receipt in `receipts.jsonl` references that hash. `python -m agent.cli verify` recomputes it and
walks the chain to check nothing was edited after the fact.

## What ships here, and what doesn't

This repo is the agent itself. Maria and Arsenal are hosted services that sit behind
`ExecutionBackend`, so the repo carries only a client and an offline mock. That keeps the whole
agent runnable and auditable without putting the backend source in public. `.env` is gitignored.

## Safety

The agent only touches a dedicated wallet you fund for it. Risky exposure is capped at 12%, and a
drawdown ladder moves everything to stablecoins once losses reach 3%. That leaves three points of
room under the competition's 6% elimination line. Across a six-week crash-and-recovery stress test,
it never crosses that line.
