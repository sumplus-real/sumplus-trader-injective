# Sumplus Trader

> **Injective Nova submission — you are on the `injective` branch.**
> This branch ports the verifiable-decision core to Injective EVM and the Helix on-chain order book.
> Every decision the agent makes is bound to an on-chain Helix order anyone can verify against a
> policy committed before trading started. Start here: **[`docs/INJECTIVE_DEMO.md`](docs/INJECTIVE_DEMO.md)**.
> The verified testnet artifacts (14 hash-chained receipts, 2 cid-bound orders) live in
> [`demo/injective/`](demo/injective/). On-chain proof (chain 1439): commit `a3c8707b…`,
> bound BUY `d31ba264…`, bound SELL `107d6935…`.
> The README below describes the original BNB build, which the Injective version is built on.

A self-custody AI trader on BSC that can show its work. It runs unattended for a week, and when
the week is over anyone can check that it never broke its own rules. Built for the BNB Hack: AI
Trading Agent Edition.

Most trading bots ask you to trust a screenshot of their returns. This one commits its policy
on-chain before the market opens, then writes a hash-chained receipt for every decision it makes
over the next week. Each receipt points back to that commitment. Clone the repo, recompute the
hash, and you can confirm the agent traded by rules that were fixed before it knew which way the
market would go. The returns are almost beside the point. What this setup proves is that an agent
stayed inside its mandate the whole week while nobody was watching.

It rests on three pieces. TWAK signs every transaction with keys that stay on the machine.
ERC-8004 gives the agent an on-chain identity that carries the policy commitment. Maria writes the
tamper-evident decision trail. Market data comes from the CoinMarketCap MCP server and nowhere
else, paid per request over x402.

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
