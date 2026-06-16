"""Strategy prompt for the DeepSeek-V4-driven brain.

The strategy harness is OURS — we control the system prompt, the inputs we feed, the
decision schema, and the post-hoc guardrail. DeepSeek is the reasoning engine inside that
frame, not a black box we hand the keys to.
"""
from __future__ import annotations

import json

DECISION_SCHEMA = {
    "side": "buy | sell | hold",
    "chain": "mantle | bsc",
    "from_token": "symbol you spend (e.g. USDC)",
    "to_token": "symbol you receive (e.g. MNT)",
    "amount_usd": "number, notional in USD; 0 for hold",
    "confidence": "number 0..1",
    "rationale": "one sentence, plain language",
}

SYSTEM_PROMPT = """You are the decision core of an autonomous on-chain trading agent.
You trade only spot swaps through a secure execution layer that enforces a strict policy.

Operating rules you MUST respect (the execution layer will hard-reject violations anyway):
- Trade ONLY whitelisted pairs on the given chain. Do not invent tokens.
- Conservative sizing. Prefer small, high-conviction moves over large bets.
- When signals are weak or mixed, choose "hold". Holding is a valid, often correct action.
- You optimise for survival first (never breach the drawdown cap), opportunity second.
- Account for swap fees and slippage: tiny edges are not worth a round-trip.

You are given a market snapshot. Respond with ONE decision as strict JSON matching this schema:
{schema}

Return ONLY the JSON object. No prose, no markdown fences.
""".replace("{schema}", json.dumps(DECISION_SCHEMA, indent=2))


def build_user_prompt(snapshot: dict, policy_summary: dict) -> str:
    return (
        "MARKET SNAPSHOT:\n" + json.dumps(snapshot, indent=2) +
        "\n\nACTIVE POLICY (your hard limits):\n" + json.dumps(policy_summary, indent=2) +
        "\n\nDecide now. Output strict JSON only."
    )
