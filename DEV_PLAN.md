# Dev Plan — Autonomous Guardrailed Trading Agent

Project name: **Sumplus Trader** (public repo handle: `sumplus-trader`).

Targets three track slots with ONE shared core:
- Mantle "Turing Test Hackathon" — **Trading & Strategy** + **Agentic Economy** tracks. Deadline 2026-06-15 15:59 UTC (~22h). No live trading required: deploy on Mantle + demo + repo + pitch.
- BNB "AI Trading Agent" — **Track 1 Autonomous Trading Agents**. Build by 2026-06-21 12:00, live PnL 2026-06-22..28, ERC-8004 identity on BSC.

## Architecture (one stack, two chains)

```
DeepSeek V4 (decision)  ──► agent/brain/deepseek_strategy.py
        │  market snapshot in, structured DECISION out (buy/sell/hold + pair + size)
        ▼
agent/loop.py  (autonomous tick loop, no human approval)
        │  decision → local guardrail pre-check → execute
        ▼
agent/execution/maria_client.py  ──► Maria A2A  POST /api/v2/skill/maria-swap/invoke
        │                                   (Maria enforces its OWN policy gate, signs via Privy, broadcasts)
        ▼
Arsenal  ──► DEX routing:  Mantle = Agni/FusionX (being built)   BSC = PancakeSwap V3 (exists)
        ▼
on-chain swap on Mantle (5000) / BSC (56)
```

Brain = ours (DeepSeek-driven strategy harness). Hand = Maria (secure execution + policy gate). Legs = Arsenal (DEX routing). Identity = ERC-8004.

## Differentiator / demo story

Not "look at my returns." The story is **safe autonomy**: the agent decides and executes on its own, but it physically cannot exceed its delegation. Demo centerpiece = agent attempts an over-policy trade (all-in, or a non-whitelisted token) and Maria's policy gate hard-rejects it on-chain-side, no human in the loop. Hits Agentic Economy + Trading & Strategy at once.

## Work breakdown + status

### A. External deps (delegated, in progress)
- [ ] **Arsenal**: Mantle DEX skill (Agni/FusionX, chain 5000), get_quote + build_swap_tx. → need `arsenal_skill_id` + real contract addrs. *(delegated to @Sumplus-arsenal)*
- [ ] **Maria**: add `mantle`/`bsc` to maria-swap chain enum + chain config + Privy-on-Mantle; dry-run execute_swap proves chain_id 5000 tx builds. → need `MARIA_BASE_URL`, a service bearer token, and a delegated-user JWT with `allowed_actions=["swap"]`. *(delegated to @maria)*

### B. Brain (ours — this repo) — DONE
- [x] `agent/brain/prompt.py` — strategy system prompt + JSON decision schema
- [x] `agent/brain/deepseek_strategy.py` — DeepSeek V4 (OpenAI-compatible), parse + validate
- [x] `agent/brain/mock_brain.py` + `factory.py` — rule-based fallback so it runs with NO key
- [x] `agent/data/price_feed.py` — snapshot (CMC + live quote; offline mock fallback)

### C. Execution + safety (ours) — DONE
- [x] `agent/execution/backend.py` + `mock_backend.py` + `maria_backend.py` + `factory.py` — open-source seam: offline mock vs hosted Maria client
- [x] `agent/execution/maria_client.py` — A2A client (correct contract; needs tokens to go live)
- [x] `agent/execution/executor.py` — mock / paper / live modes
- [x] `agent/guardrail/policy.py` — whitelist / caps / drawdown / rate (5 tests pass)
- [x] `agent/ledger.py` — decision + execution log

### D. Identity + loop + chat (ours) — DONE
- [x] `agent/loop.py` — autonomous tick loop, honours runtime pause + live cap overrides
- [x] `agent/runtime.py` + `agent/chat.py` — self-contained conversational control surface (status/why/pause/resume/set-cap/tick); no ClawPlus needed
- [x] `agent/cli.py` — entrypoints demo | tick | loop | chat | register
- [x] `agent/identity/register_8004.py` — ERC-8004 registration (BSC; ABI TBD-confirm)
- [x] `agent/demo/guardrail_demo.py` — over-policy-rejection demo

### Still blocked on delegated backends (A) before a REAL on-chain swap
- [ ] real Mantle swap once Arsenal `arsenal_skill_id` + Maria mantle wiring land + `.env` tokens + funded wallet

### E. Submission
- [ ] Real swap on Mantle (deploy proof) with a small amount
- [ ] Demo video + README pitch + ARCHITECTURE
- [ ] Submit to Mantle (2 tracks) before 6/15 15:59 UTC
- [ ] (next week) BSC live config + 8004 register + Track 1 register before 6/22

## Config / secrets needed (fill .env)
- `DEEPSEEK_API_KEY`, `DEEPSEEK_MODEL` (confirm exact V4 model id)
- `MARIA_BASE_URL`, `MARIA_SERVICE_TOKEN`, `MARIA_DELEGATED_USER_TOKEN`, `AGENT_ID`
- `MANTLE_RPC`, `BSC_RPC`
- `AGENT_WALLET_*` — the dedicated fresh wallet (also the ERC-8004 identity + trading wallet)

## Open decisions for Jakob
1. Public hackathon project NAME (branding).
2. Risk caps / whitelist values in `config/strategy.json` (position size, max single trade, drawdown cap, allowed pairs).
3. Real test capital amount on Mantle (a few $ for deploy proof) and BSC ($500–1000, live).
