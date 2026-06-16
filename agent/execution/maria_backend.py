"""Real execution backend: delegates to the hosted Maria A2A endpoint via MariaClient.

This file is a CLIENT only. No Maria/Arsenal source lives here — just the public API contract.
"""
from __future__ import annotations

from typing import Any

from agent.execution.backend import ExecutionBackend
from agent.execution.maria_client import MariaClient
from agent.types import ExecutionResult


class MariaBackend(ExecutionBackend):
    def __init__(self, client: MariaClient | None = None):
        self.client = client or MariaClient()

    async def get_quote(self, chain, from_token, to_token, amount, slippage_bps=50) -> dict[str, Any]:
        return await self.client.get_quote(chain, from_token, to_token, amount, slippage_bps)

    async def execute_swap(self, chain, from_token, to_token, amount, slippage_bps=50) -> ExecutionResult:
        return await self.client.execute_swap(chain, from_token, to_token, amount, slippage_bps)
