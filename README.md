# Sumplus Trader

> An autonomous, guardrailed on-chain trading agent.

An autonomous on-chain trading agent that **decides and executes on its own, but cannot exceed
its leash.** A DeepSeek-driven brain proposes trades; a deterministic guardrail clamps or
rejects them; Maria, a secure execution layer, enforces the same policy server-side, signs, and
broadcasts the swap through Arsenal's DEX routing. Chain-agnostic: the same agent runs on Mantle
and BSC.

The pitch is not "look at my returns." It is **safe autonomy** — the thing most trading-agent
demos quietly skip.

## Quickstart (runs with NO keys, NO network)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt        # only needed for live mode; demo/tick run on stdlib

python3 -m agent.cli demo     # guardrail enforcement demo (allow / clamp / reject)
python3 -m agent.cli tick     # one autonomous decision cycle, offline
python3 -m agent.cli chat     # talk to the agent: status, why, pause, resume, set cap, tick
python3 -m agent.cli loop     # run the autonomous loop forever
```

Out of the box the agent runs fully offline: a **MockBrain** (rule-based) stands in for DeepSeek
and a **MockBackend** stands in for the execution layer, so anyone can clone and run the whole
thing. Add keys in `.env` to switch to the real DeepSeek brain and live execution.

## Open-source boundary

This agent is open source. The execution layer it calls (Maria) and the DEX router behind it
(Arsenal) are **hosted services, not included here** — they sit behind `ExecutionBackend`. The
repo ships only a thin API client (`MariaBackend`) plus an offline `MockBackend`. No backend
source, no secrets (`.env` is gitignored).

## Modes (`config/strategy.json` → `mode`)
- `mock` — offline, deterministic fake fills. Default. For demo / CI / judges.
- `paper` — real quotes from the live backend, no broadcast.
- `live` — real execution through Maria (which has its own server-side policy gate + signing).

## Layout
- `agent/brain/` — DeepSeek V4 decision strategy (the part we built; the model is the engine, the harness is ours)
- `agent/guardrail/` — local policy enforcement (whitelist, caps, drawdown, rate)
- `agent/execution/` — Maria A2A client + executor (paper / live)
- `agent/data/` — market snapshot (CMC + live on-chain quote)
- `agent/identity/` — ERC-8004 registration
- `agent/demo/` — the guardrail demo
- `config/strategy.json` — risk caps, whitelisted pairs, chains
- `ARCHITECTURE.md` — the full design · `DEV_PLAN.md` — build status + open decisions

## Safety
The agent runs against a **dedicated, freshly generated wallet** funded only with test capital
and gas. The wallet that signs is the wallet registered as the ERC-8004 identity. Never a
personal wallet. Live execution stays gated until a real funded smoke test passes.
