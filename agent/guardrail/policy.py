"""Local guardrail — the agent's self-limit, and the deterministic engine behind the demo.

This mirrors the delegation policy that Maria ALSO enforces server-side. Two reasons to keep
a local copy:
  1. The agent should never even *attempt* an out-of-policy trade in normal operation.
  2. The demo needs a deterministic, explainable rejection ("agent tried X, blocked because Y").

The source of truth for caps is config/strategy.json. Maria's delegation must be configured
with the SAME caps so that even if this layer were bypassed, the server still rejects.
"""
from __future__ import annotations

from agent.types import Decision, GuardrailVerdict


class Guardrail:
    def __init__(self, strategy_cfg: dict):
        self.cfg = strategy_cfg
        self.risk = strategy_cfg["risk"]
        self.allowed_tokens = set(strategy_cfg.get("allowed_tokens", []))
        self.allowed_pairs = {
            (p["chain"], p["from"].upper(), p["to"].upper())
            for p in strategy_cfg.get("allowed_pairs", [])
        }

    def check(self, decision: Decision, *, portfolio_value_usd: float,
              drawdown_pct: float, trades_last_hour: int) -> GuardrailVerdict:
        if not decision.is_trade():
            return GuardrailVerdict(allowed=True, reason="hold — no action")

        ft, tt = decision.from_token.upper(), decision.to_token.upper()

        # 1. token whitelist
        if ft not in self.allowed_tokens or tt not in self.allowed_tokens:
            bad = ft if ft not in self.allowed_tokens else tt
            return GuardrailVerdict(False, f"rejected: token {bad} is not on the whitelist")

        # 2. pair whitelist
        if (decision.chain, ft, tt) not in self.allowed_pairs:
            return GuardrailVerdict(False, f"rejected: pair {ft}->{tt} on {decision.chain} is not allowed")

        # 3. drawdown circuit breaker
        if drawdown_pct >= self.risk["max_drawdown_pct"]:
            return GuardrailVerdict(False, f"rejected: drawdown {drawdown_pct:.1f}% >= cap {self.risk['max_drawdown_pct']}%")

        # 4. rate limit
        if trades_last_hour >= self.risk["max_trades_per_hour"]:
            return GuardrailVerdict(False, f"rejected: {trades_last_hour} trades this hour >= cap {self.risk['max_trades_per_hour']}")

        # 5. position / single-trade caps → clamp rather than reject
        max_single = float(self.risk["max_single_trade_usd"])
        max_by_pct = portfolio_value_usd * float(self.risk["max_position_pct"])
        cap = min(max_single, max_by_pct)
        amount = decision.amount_usd
        if amount > cap:
            return GuardrailVerdict(True, f"allowed (clamped {amount:.2f}->{cap:.2f} to respect caps)", clamped_amount_usd=cap)

        return GuardrailVerdict(True, "allowed — within policy")
