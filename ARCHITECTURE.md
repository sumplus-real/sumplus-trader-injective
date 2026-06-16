# Architecture

A chain-agnostic autonomous trading agent built by composing three production Sumplus
components plus an on-chain identity. The agent decides and executes with no human in the
loop, yet it is structurally incapable of exceeding its delegated authority.

```
                 ┌──────────────────────────────────────────────┐
                 │  BRAIN  (this repo)                           │
   market ─────► │  agent/data/price_feed.py  → snapshot         │
   data          │  agent/brain/deepseek_strategy.py (DeepSeek)  │
                 │     → Decision{side,pair,size,rationale}      │
                 └───────────────┬──────────────────────────────┘
                                 ▼
                 ┌──────────────────────────────────────────────┐
                 │  GUARDRAIL (this repo)                        │
                 │  agent/guardrail/policy.py                    │
                 │   whitelist · size caps · drawdown · rate     │
                 │   → allow / clamp / reject  (deterministic)   │
                 └───────────────┬──────────────────────────────┘
                                 ▼  (only approved trades)
                 ┌──────────────────────────────────────────────┐
                 │  HAND  (Maria — secure execution layer)       │
                 │  A2A: POST /api/v2/skill/maria-swap/invoke    │
                 │  enforces delegation policy server-side,      │
                 │  signs via Privy server wallet, broadcasts    │
                 └───────────────┬──────────────────────────────┘
                                 ▼
                 ┌──────────────────────────────────────────────┐
                 │  LEGS  (Arsenal — multi-chain DEX routing)    │
                 │  Mantle → Agni/FusionX   ·   BSC → PancakeSwap │
                 └───────────────┬──────────────────────────────┘
                                 ▼
                     on-chain swap: Mantle (5000) / BSC (56)

   IDENTITY: ERC-8004 registration ties the dedicated wallet to an on-chain agent id.
```

## Why two guardrail layers
The local guardrail keeps the agent from ever *proposing* an out-of-policy trade and gives the
demo a deterministic, explainable rejection. Maria enforces the *same* caps server-side via the
delegation policy, so the safety property does not depend on the brain behaving. Defence in depth.

## Chain-agnostic by construction
The brain and guardrail are chain-neutral. Switching targets is a config change
(`config/strategy.json` chains + pairs). Mantle and BSC are the same code path; only the DEX
behind Arsenal and the chain id differ. This is what lets one build serve both hackathons.
