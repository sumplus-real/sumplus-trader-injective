"""Demo centerpiece: an autonomous agent that CANNOT break its leash.

Runs three scenarios end to end and prints a clean transcript for the video:
  1. In-policy trade            -> allowed, routed to Maria.
  2. Oversized trade            -> clamped down to the cap (not rejected, made safe).
  3. Non-whitelisted token      -> hard rejected, never reaches the chain.

The rejection is deterministic (driven by config/strategy.json), so the demo is repeatable.
The same caps are enforced by Maria server-side, so this is not theatre — bypassing the local
guardrail would still hit a server-side rejection.
"""
from __future__ import annotations

import json
from pathlib import Path

from agent.guardrail.policy import Guardrail
from agent.types import Decision

CFG = json.loads((Path(__file__).resolve().parent.parent.parent / "config" / "strategy.json").read_text())

SCENARIOS = [
    ("In-policy buy", Decision("buy", "mantle", "USDC", "MNT", 25, 0.7, "trend up, small size")),
    ("Oversized buy", Decision("buy", "mantle", "USDC", "MNT", 5000, 0.9, "very confident, wants to go big")),
    ("Off-whitelist token", Decision("buy", "mantle", "USDC", "SCAMCOIN", 25, 0.95, "shilled token, looks hot")),
]


def main() -> None:
    guard = Guardrail(CFG)
    print("=" * 64)
    print("  GUARDRAILED AUTONOMOUS AGENT — policy enforcement demo")
    print("=" * 64)
    for name, decision in SCENARIOS:
        v = guard.check(decision, portfolio_value_usd=1000.0, drawdown_pct=0.0, trades_last_hour=0)
        print(f"\n▶ {name}")
        print(f"    agent wants: {decision.side} ${decision.amount_usd:g} {decision.from_token}->{decision.to_token} on {decision.chain}")
        print(f"    rationale:   {decision.rationale}")
        status = "ALLOWED" if v.allowed else "REJECTED"
        if v.clamped_amount_usd is not None:
            status = "ALLOWED (CLAMPED)"
        print(f"    guardrail:   {status} — {v.reason}")
    print("\n" + "=" * 64)
    print("  No human approved any of this. The leash held.")
    print("=" * 64)


if __name__ == "__main__":
    main()
