"""End-to-end offline: brain -> guardrail -> mock backend, no keys, no network."""
import asyncio

from agent.brain.mock_brain import MockBrain
from agent.execution.executor import Executor
from agent.execution.mock_backend import MockBackend
from agent.loop import tick


def test_full_tick_offline():
    backend = MockBackend()
    execu = Executor(backend, mode="mock")
    steps = asyncio.run(tick(MockBrain(), backend, execu, portfolio_value_usd=1000.0))
    # Mantle pairs are enabled by default in config; we should get decisions back.
    assert isinstance(steps, list)
    for s in steps:
        assert "decision" in s and "verdict" in s
        # every executed step must carry a clear mock/dry-run marker (never a silent real send)
        if "execution" in s:
            assert s["execution"].get("mode") in ("mock", "paper") or s["execution"].get("tx_hash") is None
