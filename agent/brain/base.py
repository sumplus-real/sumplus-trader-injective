"""Brain interface — anything that turns a market snapshot into a Decision."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from agent.types import Decision


class Brain(ABC):
    @abstractmethod
    async def decide(self, snapshot: dict[str, Any], policy_summary: dict[str, Any]) -> Decision:
        ...
