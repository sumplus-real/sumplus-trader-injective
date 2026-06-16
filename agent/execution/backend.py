"""ExecutionBackend — the seam between the open-source agent and the (closed) execution layer.

The agent is open source. Maria and Arsenal are NOT: they live behind this interface as a
hosted service. The open repo ships:
  - MockBackend  — deterministic, offline, lets anyone run the full loop with no backend.
  - MariaBackend — a thin HTTP client to our hosted Maria A2A endpoint (no Maria source here).

Swapping backends is a config flag. Nothing about Maria/Arsenal internals is disclosed.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from agent.types import ExecutionResult


class ExecutionBackend(ABC):
    @abstractmethod
    async def get_quote(self, chain: str, from_token: str, to_token: str, amount: str,
                        slippage_bps: int = 50) -> dict[str, Any]:
        ...

    @abstractmethod
    async def execute_swap(self, chain: str, from_token: str, to_token: str, amount: str,
                           slippage_bps: int = 50) -> ExecutionResult:
        ...
