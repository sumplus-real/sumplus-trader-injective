"""The execution log: the bridge between a committed decision and its objective on-chain order.

A receipt commits the *decision* and is immutable (rewriting it breaks the hash chain), so the
on-chain realisation of that decision cannot be stapled back into the receipt. Instead each
executed trade appends one record here, keyed by the receipt it came from:

    {receipt_seq, receipt_hash, cid, tx, order_hash, market, ...}

The binding is two-way and checkable by anyone:
  - cid == receipt_cid(receipt_hash)  — the on-chain order's cid is the receipt hash prefix.
  - receipt_hash exists in receipts.jsonl as an allowed/clamped trade.
  - order_hash / tx are the objective Injective records to cross-check on the explorer.

So "this order on Helix came from that committed decision" is a recompute, not a claim.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Optional

from agent.ops.paths import data_path
from agent.policy.receipt import receipt_cid

EXECUTIONS_PATH = data_path("executions.jsonl")


@dataclass
class ExecutionRecord:
    receipt_seq: int
    receipt_hash: str
    cid: str
    ts: str
    executed: bool
    source: Optional[str] = None
    market: Optional[str] = None
    order_type: Optional[str] = None
    tx: Optional[str] = None
    order_hash: Optional[str] = None
    ref_price: Optional[float] = None
    quantity_base: Optional[float] = None
    amount_usd: Optional[float] = None
    error: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def record_execution(*, receipt_seq: int, receipt_hash: str, cid: str, ts: str,
                     executed: bool, detail: dict[str, Any], error: Optional[str] = None,
                     path: Path | str = EXECUTIONS_PATH) -> ExecutionRecord:
    """Append one execution record binding a receipt to its on-chain order."""
    detail = detail or {}
    rec = ExecutionRecord(
        receipt_seq=receipt_seq, receipt_hash=receipt_hash, cid=cid, ts=ts, executed=executed,
        source=detail.get("source"), market=detail.get("market"),
        order_type=detail.get("order_type"), tx=detail.get("tx"),
        order_hash=detail.get("order_hash"), ref_price=detail.get("ref_price"),
        quantity_base=detail.get("quantity_base"), amount_usd=detail.get("amount_usd"),
        error=error,
    )
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a") as f:
        f.write(json.dumps(rec.to_dict()) + "\n")
    return rec


def read_all(path: Path | str = EXECUTIONS_PATH) -> list[dict[str, Any]]:
    p = Path(path)
    if not p.exists():
        return []
    return [json.loads(l) for l in p.read_text().splitlines() if l.strip()]


def verify_executions(records: list[dict[str, Any]], receipts: list[dict[str, Any]]
                      ) -> dict[str, Any]:
    """Re-check every execution record against the receipt chain. Returns
    {ok, count, cid_ok, receipt_ok, bad}. Anyone can run this over the public
    executions.jsonl + receipts.jsonl to confirm each on-chain order maps to a committed decision."""
    by_hash = {r["hash"]: r for r in receipts}
    bad: list[dict[str, Any]] = []
    cid_ok = receipt_ok = True
    for rec in records:
        rh = rec.get("receipt_hash", "")
        # 1) the cid the chain saw must be the receipt hash prefix
        if rec.get("cid") != receipt_cid(rh):
            cid_ok = False
            bad.append({"receipt_hash": rh, "why": "cid != receipt_cid(receipt_hash)"})
            continue
        # 2) the receipt must exist and be a trade the policy let through
        src = by_hash.get(rh)
        if src is None:
            receipt_ok = False
            bad.append({"receipt_hash": rh, "why": "receipt not found in chain"})
            continue
        if src.get("verdict") not in ("allow", "clamp"):
            receipt_ok = False
            bad.append({"receipt_hash": rh, "why": f"receipt verdict is {src.get('verdict')}, not a trade"})
    return {"ok": cid_ok and receipt_ok, "count": len(records),
            "cid_ok": cid_ok, "receipt_ok": receipt_ok, "bad": bad}
