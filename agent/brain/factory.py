"""Pick a brain: real DeepSeek if a key is present, else the mock rule-based brain."""
from __future__ import annotations

import os

from agent.brain.base import Brain
from agent.brain.mock_brain import MockBrain


def make_brain() -> Brain:
    if os.environ.get("DEEPSEEK_API_KEY"):
        from agent.brain.deepseek_strategy import DeepSeekBrain  # lazy: openai import only when used
        return DeepSeekBrain()
    return MockBrain()
