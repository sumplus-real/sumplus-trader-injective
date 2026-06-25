"""Pick an execution backend. mock (offline) unless a real Maria base URL is configured
and mode is live."""
from __future__ import annotations

import os

from agent.execution.backend import ExecutionBackend
from agent.execution.mock_backend import MockBackend


def make_backend(mode: str) -> ExecutionBackend:
    # EXECUTION_BACKEND wins when set: twak (BSC signer) | injective (Helix spot) |
    # maria (our hosted layer) | mock.
    chosen = os.environ.get("EXECUTION_BACKEND", "").lower()
    if chosen == "twak":
        from agent.execution.twak_backend import TwakBackend  # lazy: subprocess wrapper
        return TwakBackend()
    if chosen == "injective":
        from agent.execution.injective_backend import InjectiveBackend  # lazy: web3 only when used
        return InjectiveBackend()
    if chosen == "mock" or mode == "mock":
        return MockBackend()
    if chosen == "maria" or os.environ.get("MARIA_BASE_URL"):
        from agent.execution.maria_backend import MariaBackend  # lazy: httpx client only when used
        return MariaBackend()
    return MockBackend()
