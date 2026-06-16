"""Pick an execution backend. mock (offline) unless a real Maria base URL is configured
and mode is live."""
from __future__ import annotations

import os

from agent.execution.backend import ExecutionBackend
from agent.execution.mock_backend import MockBackend


def make_backend(mode: str) -> ExecutionBackend:
    # 'mock' or missing Maria config → offline. 'paper'/'live' with MARIA_BASE_URL → real client.
    if mode in ("mock",) or not os.environ.get("MARIA_BASE_URL"):
        return MockBackend()
    from agent.execution.maria_backend import MariaBackend  # lazy: httpx client only when used
    return MariaBackend()
