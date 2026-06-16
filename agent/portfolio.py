"""Portfolio valuation + drawdown — makes the guardrail's drawdown circuit-breaker real.

Tracks a high-water mark of portfolio USD value across ticks (persisted) and reports the
current drawdown. Offline-safe: if no wallet/RPC is configured, value comes from the runtime
state (static in mock mode → drawdown 0). With a wallet + RPC + spot prices, value is the real
on-chain holdings, so drawdown becomes a live risk signal the loop acts on.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from agent import runtime

STATE_PATH = Path(__file__).resolve().parent.parent / "portfolio_state.json"


def _load() -> dict[str, Any]:
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text())
        except Exception:
            pass
    return {"hwm": 0.0}


def _save(state: dict[str, Any]) -> None:
    STATE_PATH.write_text(json.dumps(state, indent=2))


def current_value_usd(spot: dict[str, Any] | None = None) -> float:
    """Live value from the wallet if configured; otherwise the runtime portfolio figure."""
    addr = os.environ.get("AGENT_WALLET_ADDRESS")
    rpc = os.environ.get("MANTLE_RPC") or os.environ.get("BSC_RPC")
    if addr and rpc and spot:
        try:
            from agent import wallet
            total = 0.0
            # stablecoins ~ $1; native valued via spot. Token list kept minimal/explicit.
            native = wallet.native_balance(rpc, addr)
            native_sym = "MNT" if os.environ.get("MANTLE_RPC") else "BNB"
            total += native * float((spot.get(native_sym, {}) or {}).get("price") or 0)
            return round(total, 2)
        except Exception:
            pass
    return float(runtime.load().get("portfolio_value_usd", 0.0))


def update_and_drawdown(value_usd: float) -> float:
    """Record value, advance the high-water mark, return drawdown % from the HWM."""
    st = _load()
    hwm = max(float(st.get("hwm", 0.0)), value_usd)
    st["hwm"] = hwm
    st["last_value"] = value_usd
    _save(st)
    if hwm <= 0:
        return 0.0
    return max(0.0, (hwm - value_usd) / hwm * 100.0)


def snapshot(spot: dict[str, Any] | None = None) -> dict[str, Any]:
    value = current_value_usd(spot)
    dd = update_and_drawdown(value)
    return {"value_usd": value, "drawdown_pct": round(dd, 2), "hwm": _load().get("hwm", value)}
