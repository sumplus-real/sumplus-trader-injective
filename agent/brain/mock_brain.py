"""Deterministic rule-based brain — lets the whole agent run end-to-end with no API key.

Not the real strategy. A transparent momentum/mean-reversion rule so judges (and CI) can run
the loop and the guardrail without a DeepSeek key. The real brain is deepseek_strategy.py.
"""
from __future__ import annotations

from typing import Any

from agent.brain.base import Brain
from agent.types import Decision


class MockBrain(Brain):
    def __init__(self, default_trade_usd: float = 25.0):
        self.default_trade_usd = default_trade_usd

    async def decide(self, snapshot: dict[str, Any], policy_summary: dict[str, Any]) -> Decision:
        pair = snapshot.get("pair", {})
        chain = snapshot.get("chain", "")
        frm, to = pair.get("from", "USDC"), pair.get("to", "MNT")

        # Simple mean-reversion: if the traded token dropped >3% in 24h, buy a little; if up >5%, take profit.
        spot = snapshot.get("spot", {})
        pct = None
        if isinstance(spot, dict):
            pct = (spot.get(to, {}) or {}).get("pct_24h")

        if pct is None:
            return Decision("hold", chain, frm, to, 0, 0.3, "no price signal; holding")
        if pct <= -3:
            return Decision("buy", chain, frm, to, self.default_trade_usd, 0.6,
                            f"{to} down {pct:.1f}% in 24h, small mean-reversion buy")
        if pct >= 5:
            return Decision("sell", chain, to, frm, self.default_trade_usd, 0.6,
                            f"{to} up {pct:.1f}% in 24h, take partial profit")
        return Decision("hold", chain, frm, to, 0, 0.4, f"{to} flat ({pct:.1f}%); holding")
