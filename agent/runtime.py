"""Shared runtime state — the handle the chat layer uses to supervise the loop.

The autonomous loop reads this every tick (paused? current caps?). The chat layer writes it
(pause/resume/adjust). Persisted to disk so chat and loop can run as separate processes.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

STATE_PATH = Path(__file__).resolve().parent.parent / "runtime_state.json"

_DEFAULT: dict[str, Any] = {
    "paused": False,
    "portfolio_value_usd": 1000.0,
    "overrides": {},   # e.g. {"max_single_trade_usd": 20}
}


def load() -> dict[str, Any]:
    if STATE_PATH.exists():
        try:
            return {**_DEFAULT, **json.loads(STATE_PATH.read_text())}
        except Exception:
            pass
    return dict(_DEFAULT)


def save(state: dict[str, Any]) -> None:
    STATE_PATH.write_text(json.dumps(state, indent=2))


def update(**changes: Any) -> dict[str, Any]:
    state = load()
    state.update(changes)
    save(state)
    return state
