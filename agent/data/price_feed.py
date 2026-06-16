"""Market snapshot for the brain.

Sources:
  - CMC spot prices for trend context (if CMC_API_KEY set; else a mock spot so the loop runs offline).
  - A live executable quote from the execution backend (real Maria price, or mock).
"""
from __future__ import annotations

import os
from typing import Any

import httpx

from agent.execution.backend import ExecutionBackend

# Offline fallback 24h-change so the mock brain has a signal without a CMC key.
_MOCK_SPOT = {
    "MNT": {"price": 0.80, "pct_24h": -4.2},
    "BNB": {"price": 600.0, "pct_24h": 1.1},
    "USDC": {"price": 1.0, "pct_24h": 0.0},
    "USDT": {"price": 1.0, "pct_24h": 0.0},
}


async def cmc_prices(symbols: list[str]) -> dict[str, Any]:
    api_key = os.environ.get("CMC_API_KEY", "")
    if not api_key:
        return {s: _MOCK_SPOT.get(s, {"price": None, "pct_24h": None}) for s in symbols}
    url = "https://pro-api.coinmarketcap.com/v1/cryptocurrency/quotes/latest"
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.get(url, headers={"X-CMC_PRO_API_KEY": api_key},
                        params={"symbol": ",".join(symbols)})
    r.raise_for_status()
    data = r.json().get("data", {})
    out = {}
    for s in symbols:
        q = (data.get(s, {}) or {}).get("quote", {}).get("USD", {})
        out[s] = {"price": q.get("price"), "pct_24h": q.get("percent_change_24h")}
    return out


async def build_snapshot(backend: ExecutionBackend, chain: str, pair: dict,
                         probe_amount: str = "10") -> dict[str, Any]:
    snapshot: dict[str, Any] = {"chain": chain, "pair": pair}
    snapshot["spot"] = await cmc_prices(sorted({pair["from"], pair["to"]}))
    try:
        snapshot["live_quote"] = await backend.get_quote(
            chain=chain, from_token=pair["from"], to_token=pair["to"], amount=probe_amount,
        )
    except Exception as e:
        snapshot["live_quote"] = {"error": str(e)}
    return snapshot
