# Submission — Mantle Turing Test Hackathon 2026

> Project: **Sumplus Trader**. Tracks: **Trading & Strategy** + **Agentic Economy**.

## One-liner

An autonomous on-chain trading agent that decides and executes entirely on its own, yet is
structurally incapable of exceeding its leash.

## The problem

Most "AI trading agent" demos are a bot with a hot private key and a prompt. They can trade, but
nothing stops them from going all-in, chasing a shilled token, or blowing past a drawdown. The
thing standing between an autonomous agent and the chain is exactly what nobody shows. That trust
gap is why autonomous on-chain agents are not taken seriously yet.

## What we built

A trading agent split into honest layers:

- **Brain** — a DeepSeek-driven strategy that reads a market snapshot and proposes one decision
  (buy / sell / hold, pair, size, rationale). The strategy harness is ours; the model is the engine.
- **Guardrail** — a deterministic policy layer that allows, clamps, or hard-rejects every decision
  against a whitelist, size caps, a drawdown circuit-breaker, and a rate limit.
- **Secure execution** — approved trades route to a separate execution layer (Maria) that enforces
  the same policy server-side, signs with a server wallet, and broadcasts the swap.
- **DEX routing** — on Mantle the swap is routed through Agni Finance (chain 5000) via our Arsenal
  routing layer.
- **Conversational surface** — a built-in web chat: a user can ask the agent its status, ask why it
  made a decision, and pause / resume / adjust caps in plain language. No human approves trades; the
  human supervises.

The pitch is not "look at my returns." It is **safe autonomy** — the agent runs by itself, and the
leash holds. Defence in depth: the guardrail self-limits the brain, and the execution layer enforces
the same policy independently, so the safety property does not depend on the model behaving.

**Who holds the leash:** the user does. The delegating user sets the policy — which pairs, the
per-trade and drawdown caps, the allocation target — and issues an on-chain delegation that binds it
server-side. The agent then acts autonomously inside that envelope. Two independent layers enforce
it: our guardrail in the agent, and the execution layer's delegation check before it ever signs. In
our live run the brain mis-judged and tried to add exposure; both the policy and the leash held and
the trade never reached the chain.

## Why it fits the tracks

- **Trading & Strategy** — a real strategy engine deciding and executing spot swaps on Mantle, with
  risk management (drawdown breaker, position caps) built into the trade path, not bolted on.
- **Agentic Economy** — an autonomous agent that acts on-chain under a delegated, enforceable policy.
  This is what makes agent-driven on-chain activity safe enough to scale.

## Deployed on Mantle — live autonomous run

The agent ran live on Mantle (chain 5000), driven by DeepSeek V4 under a target-allocation
rebalancing mandate, executing real swaps through Agni Finance. Every decision is logged in
`ledger.jsonl` and summarised in `live_trail_summary.json` — an immutable on-chain decision trail.

The wallet started ~78% concentrated in MNT. The agent autonomously decided to de-risk, executed
two real rebalancing swaps that brought MNT exposure from 77.9% down to ~41%, and then, when it
tried to over-correct by buying MNT back, the deterministic guardrail hard-rejected the off-whitelist
pair. The leash held even when the brain wanted to act.

| # | decision | MNT alloc | guardrail | on-chain tx |
|---|----------|-----------|-----------|-------------|
| 1 | sell ~$3.5 MNT→USDC | 77.9% | allowed | [`0x8208a9c7…`](https://mantlescan.xyz/tx/0x8208a9c72dbf7ccdd32278580017e641534887890b139cfc17748af67a2d3122) ✅ |
| 2 | sell ~$2.9 MNT→USDC | 57.6% | allowed | [`0xa2082e72…`](https://mantlescan.xyz/tx/0xa2082e729b5b5493326b2ea7d112090bdb9e3663445120bec379a53816ad43ff) ✅ |
| 3 | buy MNT (rebalance up) | 40.6% | **rejected** (off-whitelist pair) | — |

Plus a standalone proof swap (4 MNT → 2.2344 USDC):
[`0x889c6432…`](https://mantlescan.xyz/tx/0x889c64321833c1f27c87cacf4d455cfcdf840b14f4deaf49dab915726495cd45) ✅

- **Wallet (on-chain actor):** `0x5B9687e2F0BF34BBB9e7937488a513BD82A12dD3`
- **Router:** Agni SwapRouter `0x319B69888b0d11cEC22caA5034e25FfFBDc88421`

Three real on-chain swaps, two of them autonomous risk-driven rebalances; the guardrail rejection is
from the same live run, not a canned demo. An ERC-8004 identity ties the agent's wallet to a
registered agent id.

## Run it (no keys, no network)

```bash
python -m agent.cli demo     # guardrail enforcement: allow / clamp / reject
python -m agent.cli web      # web chat + live status panel  →  http://127.0.0.1:8800
python -m agent.cli tick     # one autonomous decision cycle
```

Ships with an offline mock brain and mock execution backend so anyone can run the full agent with
nothing installed. Add keys to switch to the real DeepSeek brain and live Mantle execution.

## Demo script (90 seconds — entirely in the browser)

Run `python -m agent.cli web` once and open `http://127.0.0.1:8800`. Everything below is clicks on
that one page; no terminal.

1. Click **▶ Guardrail demo** — three decisions render: an in-policy buy is **allowed**, an oversized
   buy is **clamped** to the cap, a shilled off-whitelist token is **rejected**. "No human approved
   any of this. The leash held."
2. Click **▶ Tick** — the agent makes a decision; the status panel updates (portfolio, drawdown vs
   cap, recent decisions with allow/blocked badges). Type `set cap max_single_trade_usd 10` in the
   box, click Tick again — the next size is clamped live. Click **Pause** — it stops opening trades.
   Supervised autonomy in plain language.
3. **The money shot — real on-chain proof (right panel).** The "Live on-chain proof" panel lists the
   real swaps this agent executed on Mantle, each linking to Mantlescan. "Same agent, running live:
   it found itself 78% concentrated in MNT, autonomously executed two real rebalancing swaps down to
   41%, then tried to over-correct — and the guardrail rejected the off-policy trade. No human in the
   loop. The leash held on-chain." Click a Mantlescan link to show the confirmed transaction.

## Tech

DeepSeek (decision) · custom guardrail · Maria secure execution layer · Arsenal DEX routing
(Agni Finance on Mantle) · ERC-8004 identity · Python / FastAPI. Open-source agent; the execution
and routing layers run as hosted services behind a clean API boundary.

## Open-source boundary

This repo is the agent. The execution layer (Maria) and DEX router (Arsenal) are hosted services
behind `ExecutionBackend`; the repo ships only an API client plus an offline mock, so the full agent
is runnable and auditable without exposing backend source.

## What's next

Live execution against a funded Mantle wallet; the same chain-agnostic engine extends to BSC for
live-PnL autonomous trading.
