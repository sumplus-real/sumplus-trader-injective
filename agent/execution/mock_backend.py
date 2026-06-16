"""Offline execution backend. Deterministic fake quotes/fills so the full agent runs with
no network and no hosted Maria/Arsenal. Used for the open-source demo + tests."""
from __future__ import annotations

from typing import Any

from agent.execution.backend import ExecutionBackend
from agent.types import ExecutionResult

# Toy reference prices (USD) for deterministic quotes. Not market data — demo only.
_REF_USD = {"USDC": 1.0, "USDT": 1.0, "MNT": 0.80, "WMNT": 0.80, "BNB": 600.0, "WBNB": 600.0}


class MockBackend(ExecutionBackend):
    def _quote(self, from_token: str, to_token: str, amount: str, slippage_bps: int) -> dict[str, Any]:
        fp = _REF_USD.get(from_token.upper(), 1.0)
        tp = _REF_USD.get(to_token.upper(), 1.0)
        amt_in = float(amount)
        usd = amt_in * fp
        amt_out = usd / tp * (1 - slippage_bps / 10_000)
        return {
            "from_token": from_token, "to_token": to_token,
            "amount_in": amt_in, "amount_out": round(amt_out, 6),
            "price_usd": tp, "slippage_bps": slippage_bps, "source": "mock",
        }

    async def get_quote(self, chain, from_token, to_token, amount, slippage_bps=50):
        q = self._quote(from_token, to_token, amount, slippage_bps)
        q["chain"] = chain
        return q

    async def execute_swap(self, chain, from_token, to_token, amount, slippage_bps=50):
        q = self._quote(from_token, to_token, amount, slippage_bps)
        q["chain"] = chain
        # Mock "fill": no real broadcast, flagged clearly.
        return ExecutionResult(executed=False, dry_run=True,
                               detail={"mode": "mock", "would_send": q, "tx_hash": None})
