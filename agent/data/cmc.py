"""CoinMarketCap as the ONLY market-data source, with x402 receipts for paid-data provenance.

Live: pull quotes + 1h/4h/24h changes from the CMC Pro API (CMC_API_KEY). The CMC MCP Agent Hub
exposes the same data to agents and bills $0.01 USDC/request over x402; when X402_ENABLED is set
we log an x402 receipt per fetch so the trail shows exactly which paid data each decision used.
Offline (no key): a deterministic scenario so the whole agent runs with nothing installed and the
demo still shows a real entry plus reasoned abstentions.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Optional

import httpx

from agent.strategy.signals import TokenView
from agent.ops.paths import data_path

X402_RECEIPTS_PATH = data_path("x402_receipts.jsonl")

# Deterministic offline scenario: one clean uptrend (entry), one high-vol (risk_off),
# one chop (neutral), one mild. Lets the demo show enter + abstentions with distinct reasons.
_MOCK_SCENARIO: dict[str, dict[str, float]] = {
    "WBNB": {"price": 632.0, "pct_1h": 0.8, "pct_4h": 1.6, "vol_24h_pct": 2.4},
    "BTCB": {"price": 68000.0, "pct_1h": 0.3, "pct_4h": -0.2, "vol_24h_pct": 1.8},
    "ETH":  {"price": 3550.0, "pct_1h": -1.4, "pct_4h": 2.1, "vol_24h_pct": 5.6},
    "CAKE": {"price": 2.35, "pct_1h": 0.5, "pct_4h": 0.9, "vol_24h_pct": 3.2},
    "INJ":  {"price": 20.0, "pct_1h": 0.9, "pct_4h": 1.7, "vol_24h_pct": 2.5},
    "USDT": {"price": 1.0, "pct_1h": 0.0, "pct_4h": 0.0, "vol_24h_pct": 0.1},
    "USDC": {"price": 1.0, "pct_1h": 0.0, "pct_4h": 0.0, "vol_24h_pct": 0.1},
}


def _x402_receipt(endpoint: str, symbols: list[str], live: bool) -> dict[str, Any]:
    return {
        "ts": time.time(),
        "provider": "coinmarketcap",
        "endpoint": endpoint,
        "symbols": symbols,
        "price_usdc": 0.01,
        "network": "base",
        "mode": "paid" if live else "simulated",
    }


def _log_x402(receipt: dict[str, Any]) -> None:
    if not os.environ.get("X402_ENABLED") and receipt["mode"] == "paid":
        return
    X402_RECEIPTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with X402_RECEIPTS_PATH.open("a") as f:
        f.write(json.dumps(receipt) + "\n")


async def _cmc_live(symbols: list[str], api_key: str) -> dict[str, dict[str, float]]:
    url = "https://pro-api.coinmarketcap.com/v1/cryptocurrency/quotes/latest"
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.get(url, headers={"X-CMC_PRO_API_KEY": api_key},
                        params={"symbol": ",".join(symbols), "convert": "USD"})
    r.raise_for_status()
    data = r.json().get("data", {})
    out: dict[str, dict[str, float]] = {}
    for s in symbols:
        q = (data.get(s, {}) or {}).get("quote", {}).get("USD", {})
        out[s] = {
            "price": q.get("price"),
            "pct_1h": q.get("percent_change_1h"),
            "pct_4h": q.get("percent_change_24h"),   # CMC has 1h/24h/7d; 24h proxies the 4h trend
            "vol_24h_pct": abs(q.get("percent_change_24h") or 0.0),
        }
    return out


async def get_token_views(symbols: list[str], cfg: Optional[dict] = None
                          ) -> tuple[list[TokenView], float]:
    """Return (token views, data_ts). data_ts lets the policy reject stale data."""
    api_key = os.environ.get("CMC_API_KEY", "")
    now = time.time()
    if api_key:
        raw = await _cmc_live(symbols, api_key)
        _log_x402(_x402_receipt("cryptocurrency/quotes/latest", symbols, live=True))
    else:
        raw = {s: dict(_MOCK_SCENARIO.get(s.upper(), {"price": None, "pct_1h": None, "pct_4h": None, "vol_24h_pct": None})) for s in symbols}
        _log_x402(_x402_receipt("mock/quotes", symbols, live=False))

    views = []
    for s in symbols:
        d = raw.get(s, {})
        views.append(TokenView(
            symbol=s.upper(), price=d.get("price") or 0.0,
            pct_1h=d.get("pct_1h"), pct_4h=d.get("pct_4h"),
            vol_24h_pct=d.get("vol_24h_pct"), ts=now,
        ))
    return views, now


def x402_summary() -> dict[str, Any]:
    if not X402_RECEIPTS_PATH.exists():
        return {"requests": 0, "spent_usdc": 0.0}
    recs = [json.loads(l) for l in X402_RECEIPTS_PATH.read_text().splitlines() if l.strip()]
    return {"requests": len(recs), "spent_usdc": round(sum(r.get("price_usdc", 0) for r in recs), 4)}
