"""Survival-first intent: regime + portfolio -> exactly one intent. Deterministic.

Priority order (capital preservation first):
  1. EXIT   — any held position hitting stop-loss / take-profit / time-stop, or forced de-risk
              when the drawdown ladder says so.
  2. ENTER  — the best risk_on token, only if there is exposure room. Volatility-scaled size.
  3. REBALANCE — a tiny in-policy nudge toward the target risky ratio; this is what guarantees the
              minimum qualifying trade count without overtrading.
  4. HOLD   — otherwise, with an explicit abstain reason (logged, marked-to-market later).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from agent.strategy.signals import TokenView, Regime, classify, rank_entries


@dataclass
class Position:
    symbol: str
    qty: float
    entry_price: float
    entry_ts: float


@dataclass
class PortfolioState:
    nav_usd: float
    stable_usd: float
    positions: dict[str, Position] = field(default_factory=dict)
    drawdown_pct: float = 0.0
    risky_exposure_pct: float = 0.0
    trades_this_week: int = 0
    seconds_since_last_trade: float = 1e9


@dataclass
class Intent:
    action: str                  # enter | exit | rebalance | hold
    chain: str
    from_token: str
    to_token: str
    amount_usd: float
    confidence: float
    rationale: str
    abstain_reason: str = ""     # set when action == hold, names the binding filter


def _ladder_rung(drawdown_pct: float, cfg: dict) -> str:
    rung = "none"
    for r in sorted(cfg.get("drawdown_ladder", []), key=lambda x: x["at_pct"]):
        if drawdown_pct >= r["at_pct"]:
            rung = r["action"]
    return rung


def _vol_scaled_size(nav: float, vol_pct: Optional[float], cfg: dict, halve: bool) -> float:
    risk = cfg["risk"]
    lo = float(risk.get("min_single_trade_pct", 0.01))
    hi = float(risk.get("max_single_trade_pct", 0.03))
    vmax = float(cfg.get("signal", {}).get("vol_enter_max_pct", 4.0))
    if vol_pct is None:
        frac = lo
    else:
        # lower vol -> larger size, within [lo, hi]
        scale = max(0.0, min(1.0, (vmax - vol_pct) / vmax))
        frac = lo + (hi - lo) * scale
    if halve:
        frac /= 2.0
    usd = frac * nav
    return min(usd, float(risk["max_single_trade_usd"]))


def decide(views: list[TokenView], portfolio: PortfolioState, cfg: dict, now_ts: float,
           quote: str = "USDT", chain: str = "bsc") -> Intent:
    risk = cfg["risk"]
    rung = _ladder_rung(portfolio.drawdown_pct, cfg)
    price = {v.symbol.upper(): v.price for v in views}

    # 1. EXITS — protect first.
    for sym, pos in portfolio.positions.items():
        sym = sym.upper()
        px = price.get(sym)
        if px is None or pos.qty <= 0:
            continue
        pnl_pct = (px - pos.entry_price) / pos.entry_price * 100 if pos.entry_price else 0.0
        held_h = (now_ts - pos.entry_ts) / 3600.0
        usd = pos.qty * px
        reason = None
        if rung == "stablecoin_mode":
            reason = f"stablecoin mode (drawdown {portfolio.drawdown_pct:.2f}%), flatten {sym}"
        elif pnl_pct <= -float(risk["stop_loss_pct"]):
            reason = f"stop-loss {sym} {pnl_pct:+.1f}%"
        elif pnl_pct >= float(risk["take_profit_pct"]):
            reason = f"take-profit {sym} {pnl_pct:+.1f}%"
        elif held_h >= float(risk["max_hold_hours"]):
            reason = f"time-stop {sym} held {held_h:.0f}h"
        if reason:
            return Intent("exit", chain, sym, quote, round(usd, 2), 0.9, reason)

    # 2. ENTRIES — only if the ladder permits new risk and there is exposure room.
    # Only universe (investable) tokens are entry candidates. Quote/stablecoins are the
    # cash leg and must never be ranked as a buy target: a stablecoin's noise momentum can
    # otherwise read as "risk_on" and yield a nonsensical quote->quote (e.g. USDT->USDT) intent.
    universe_set = {t.upper() for t in cfg.get("universe", [])}
    entry_views = [v for v in views if v.symbol.upper() in universe_set]
    max_risky = float(risk.get("max_risky_exposure_pct", 0.20))
    room = max_risky - portfolio.risky_exposure_pct
    can_take_risk = rung in ("none", "halve_size") and room > 0.01
    if can_take_risk:
        ranked = rank_entries(entry_views, cfg.get("signal", {}))
        for v, r in ranked:
            if v.symbol.upper() in portfolio.positions:
                continue  # already long
            size = _vol_scaled_size(portfolio.nav_usd, v.vol_24h_pct, cfg, halve=(rung == "halve_size"))
            size = min(size, room * portfolio.nav_usd)
            if size >= 1.0:
                return Intent("enter", chain, quote, v.symbol.upper(), round(size, 2), 0.7,
                              f"enter {v.symbol.upper()}: {r.reason}")

    # 3. MICRO-REBALANCE — guarantees minimum trade count without overtrading.
    mt = cfg.get("min_trades", {})
    target = float(mt.get("target_risky_ratio", 0.15))
    band = float(mt.get("rebalance_band", 0.05))
    micro = float(mt.get("micro_rebalance_usd", 12))
    can_rebalance = portfolio.seconds_since_last_trade >= float(risk["min_trade_interval_seconds"])
    if can_rebalance and rung != "stablecoin_mode":
        if portfolio.risky_exposure_pct < target - band and can_take_risk:
            ranked = rank_entries(entry_views, cfg.get("signal", {}))
            tok = ranked[0][0].symbol.upper() if ranked else None
            if not tok:
                # Scheduled rebalance (committed min_trades intent: "guarantee the minimum
                # qualifying trade count"). When no token is risk_on, still nudge toward the
                # target risky ratio using the calmest (lowest-vol) un-held universe token,
                # so the minimum trade count is met without chasing momentum.
                calm = sorted((v for v in entry_views if v.symbol.upper() not in portfolio.positions),
                              key=lambda v: v.vol_24h_pct if v.vol_24h_pct is not None else 1e9)
                tok = calm[0].symbol.upper() if calm else None
            if tok:
                return Intent("rebalance", chain, quote, tok, round(micro, 2), 0.4,
                              f"micro-rebalance up toward {target*100:.0f}% risky ({tok})")
        elif portfolio.risky_exposure_pct > target + band and portfolio.positions:
            sym = max(portfolio.positions, key=lambda s: portfolio.positions[s].qty * price.get(s.upper(), 0)).upper()
            return Intent("rebalance", chain, sym, quote, round(micro, 2), 0.4,
                          f"micro-rebalance down toward {target*100:.0f}% risky ({sym})")

    # 4. HOLD — name the binding reason for the abstention ledger.
    if rung in ("stablecoin_mode", "no_new_risk"):
        why = "drawdown_proximity"
    elif room <= 0.01:
        why = "exposure_full"
    elif not rank_entries(entry_views, cfg.get("signal", {})):
        why = "regime_conflict"
    else:
        why = "rate_or_interval"
    return Intent("hold", chain, quote, quote, 0.0, 0.3, "no qualifying action", abstain_reason=why)
