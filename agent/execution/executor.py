"""Turn a guardrail-approved Decision into a swap via the execution backend.

paper mode  → quote only (no broadcast).
live  mode  → execute_swap through the backend (Maria may itself still be in dry-run until its
              own MARIA_SKILLS_TX_ENABLED flag is on; we surface whatever it returns).
mock  mode  → MockBackend returns deterministic fake fills (offline).
"""
from __future__ import annotations

from agent.execution.backend import ExecutionBackend
from agent.types import Decision, ExecutionResult


class Executor:
    def __init__(self, backend: ExecutionBackend, mode: str = "mock", default_slippage_bps: int = 50):
        self.backend = backend
        self.mode = mode
        self.slippage_bps = default_slippage_bps

    async def execute(self, decision: Decision, amount_usd: float, cid: str = "") -> ExecutionResult:
        amount = f"{amount_usd:g}"
        if self.mode == "paper":
            quote = await self.backend.get_quote(
                chain=decision.chain, from_token=decision.from_token,
                to_token=decision.to_token, amount=amount, slippage_bps=self.slippage_bps,
            )
            return ExecutionResult(executed=False, dry_run=True, detail={"mode": "paper", "quote": quote})

        # cid binds the on-chain order back to the committed receipt. Only backends that put it on
        # chain (Injective) declare accepts_cid; everyone else keeps the original signature.
        extra = {"cid": cid} if (cid and getattr(self.backend, "accepts_cid", False)) else {}
        return await self.backend.execute_swap(
            chain=decision.chain, from_token=decision.from_token,
            to_token=decision.to_token, amount=amount, slippage_bps=self.slippage_bps, **extra,
        )
