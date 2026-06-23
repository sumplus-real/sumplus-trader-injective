"""Crash-safe JSON state persistence."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


class StateError(RuntimeError):
    """Raised when persistent state cannot be loaded or saved."""


class PersistentState:
    """Atomic JSON store for operational state."""

    DEFAULTS: dict[str, Any] = {
        "positions": {},
        "high_water_mark": 0.0,
        "nav": 0.0,
        "stable_usd": 0.0,
        "receipt_seq": 0,
        "last_tick_ts": 0.0,
        "last_trade_ts": 0.0,
        "trades_this_week": 0,
        "trades_last_hour": 0,
        "intent_seq": 0,
        # pending_intent != None means a trade was persisted right before broadcast and we have not
        # confirmed it settled. On restart the loop must reconcile from chain instead of re-deciding.
        "pending_intent": None,
        "mode": "paper",
        "kill": False,
    }

    def __init__(self, path: str) -> None:
        self.path = Path(path)
        self.data: dict[str, Any] = dict(self.DEFAULTS)
        self.data["positions"] = {}

    def load(self) -> dict[str, Any]:
        """Load state, ignoring abandoned temp files from interrupted writes."""
        if not self.path.exists():
            self.data = self._fresh_defaults()
            return dict(self.data)

        try:
            loaded = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise StateError(f"could not load state: {exc}") from exc
        if not isinstance(loaded, dict):
            raise StateError("state root is not an object")

        state = self._fresh_defaults()
        state.update(loaded)
        self.data = state
        return dict(self.data)

    def save(self) -> None:
        """Atomically write state via temp file and rename."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.path.with_name(f".{self.path.name}.tmp")
        encoded = json.dumps(self.data, sort_keys=True, separators=(",", ":"))

        try:
            with tmp_path.open("w", encoding="utf-8") as fh:
                fh.write(encoded)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp_path, self.path)
            self._fsync_dir(self.path.parent)
        except Exception as exc:
            raise StateError(f"could not save state: {exc}") from exc

    def update(self, **kw: Any) -> dict[str, Any]:
        """Update fields and persist them immediately."""
        unknown = set(kw) - set(self.DEFAULTS)
        if unknown:
            raise StateError(f"unknown state fields: {sorted(unknown)}")
        self.data.update(kw)
        self.save()
        return dict(self.data)

    def write(self, state: dict[str, Any]) -> dict[str, Any]:
        """Persist the WHOLE state in a single atomic save.

        The live loop carries a richer state than DEFAULTS (cash, trade counters, pending intent),
        so we store the full dict rather than validate field-by-field. One save per tick keeps the
        on-disk snapshot atomic and consistent — a crash mid-tick leaves the *previous* complete
        snapshot, never a half-written one. This replaces the old per-field update() loop that
        crashed on the first non-DEFAULTS key and left guardrail counters unpersisted."""
        merged = dict(self.DEFAULTS)
        merged["positions"] = {}
        merged.update(state)
        self.data = merged
        self.save()
        return dict(self.data)

    def get(self, key: str, default: Any = None) -> Any:
        """Read one state value."""
        return self.data.get(key, default)

    def _fresh_defaults(self) -> dict[str, Any]:
        state = dict(self.DEFAULTS)
        state["positions"] = {}
        return state

    @staticmethod
    def _fsync_dir(path: Path) -> None:
        try:
            fd = os.open(path, os.O_RDONLY)
        except OSError:
            return
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

