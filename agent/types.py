"""Shared types for the trading agent."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Literal, Optional

Side = Literal["buy", "sell", "hold"]


@dataclass
class Decision:
    """A single trade decision proposed by the brain."""
    side: Side
    chain: str
    from_token: str
    to_token: str
    amount_usd: float
    confidence: float            # 0..1, brain's self-reported conviction
    rationale: str               # one-line human-readable reason (for the demo + judges)

    def is_trade(self) -> bool:
        return self.side in ("buy", "sell") and self.amount_usd > 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class GuardrailVerdict:
    allowed: bool
    reason: str                  # why allowed / why rejected — drives the demo narrative
    clamped_amount_usd: Optional[float] = None   # set if we reduced the size to fit caps


@dataclass
class ExecutionResult:
    executed: bool
    dry_run: bool
    detail: dict[str, Any] = field(default_factory=dict)   # quote / tx payload / tx hash
    error: Optional[str] = None
