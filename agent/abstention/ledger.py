"""Avoided-loss ledger: record every abstention, mark it to market, total the losses dodged.

When the agent declines a would-be entry at price p0 and the price later sits at p1, the
hypothetical P&L of having taken it is (p1 - p0)/p0 * size. If that number is negative, restraint
*avoided a loss*. We sum the avoided losses (the headline), and also keep the honest net figure
(restraint sometimes costs upside) so the story is not cherry-picked.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Optional

from agent.ops.paths import data_path

LEDGER_PATH = data_path("abstentions.jsonl")

VALID_REASONS = {
    "stale_data", "vol_spike", "thin_liquidity", "drawdown_proximity",
    "slippage_mismatch", "regime_conflict", "exposure_full", "rate_or_interval",
}


@dataclass
class Abstention:
    seq: int
    ts: float
    symbol: str
    reason: str
    side: str                 # the action we declined: "buy" (entry) | "sell" (exit)
    ref_price: float          # price at the moment we abstained
    size_usd: float
    marked: bool = False
    mark_ts: Optional[float] = None
    mark_price: Optional[float] = None
    hypothetical_pnl_usd: Optional[float] = None   # >0 means abstaining cost us; <0 means it saved us

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class AbstentionLedger:
    def __init__(self, path: Path | str = LEDGER_PATH):
        self.path = Path(path)

    def _all(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        return [json.loads(l) for l in self.path.read_text().splitlines() if l.strip()]

    def _write(self, records: list[dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text("".join(json.dumps(r) + "\n" for r in records))

    def record(self, *, ts: float, symbol: str, reason: str, side: str,
               ref_price: float, size_usd: float) -> Abstention:
        records = self._all()
        seq = records[-1]["seq"] + 1 if records else 0
        a = Abstention(seq=seq, ts=ts, symbol=symbol.upper(),
                       reason=reason if reason in VALID_REASONS else "regime_conflict",
                       side=side, ref_price=ref_price, size_usd=size_usd)
        with self.path.open("a") as f:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            f.write(json.dumps(a.to_dict()) + "\n")
        return a

    def mark_to_market(self, prices: dict[str, float], now_ts: float, *, min_age_s: float = 0.0) -> int:
        """Mark unmarked abstentions whose symbol has a current price. Returns count marked."""
        records = self._all()
        marked = 0
        for r in records:
            if r.get("marked"):
                continue
            if now_ts - r["ts"] < min_age_s:
                continue
            px = prices.get(r["symbol"].upper())
            if px is None or not r.get("ref_price"):
                continue
            move = (px - r["ref_price"]) / r["ref_price"]
            # for a declined BUY, hypothetical pnl = +move*size; for a declined SELL, the inverse.
            sign = 1.0 if r["side"] == "buy" else -1.0
            r["hypothetical_pnl_usd"] = round(sign * move * r["size_usd"], 4)
            r["mark_price"] = px
            r["mark_ts"] = now_ts
            r["marked"] = True
            marked += 1
        if marked:
            self._write(records)
        return marked

    def summary(self) -> dict[str, Any]:
        records = self._all()
        marked = [r for r in records if r.get("marked") and r.get("hypothetical_pnl_usd") is not None]
        avoided_loss = sum(-r["hypothetical_pnl_usd"] for r in marked if r["hypothetical_pnl_usd"] < 0)
        missed_gain = sum(r["hypothetical_pnl_usd"] for r in marked if r["hypothetical_pnl_usd"] > 0)
        by_reason: dict[str, int] = {}
        for r in records:
            by_reason[r["reason"]] = by_reason.get(r["reason"], 0) + 1
        return {
            "abstentions": len(records),
            "marked": len(marked),
            "avoided_loss_usd": round(avoided_loss, 2),
            "missed_gain_usd": round(missed_gain, 2),
            "net_restraint_usd": round(avoided_loss - missed_gain, 2),
            "by_reason": by_reason,
        }
