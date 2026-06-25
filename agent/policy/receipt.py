"""Tamper-evident, hash-chained decision receipts.

Every decision the agent makes — a trade, a clamp, a rejection, an abstention, even a hold —
produces a Receipt and appends it to an append-only chain. Each receipt commits to the previous
one:

    receipt.hash = sha256( prev_hash + canonical(body) )

where body = {seq, ts, policy_hash, decision, verdict, reason, inputs_digest}. Change any past
receipt and every hash after it breaks — so the trail cannot be quietly rewritten after the
market moved. Each receipt also carries the committed `policy_hash`, tying the decision to the
rules published to the agent's ERC-8004 identity before code-lock.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Optional

from agent.policy.canonical import canonical_bytes, sha256_hex
from agent.ops.paths import data_path

GENESIS = "sha256:" + "0" * 64
RECEIPTS_PATH = data_path("receipts.jsonl")

# The on-chain order carries a client order id (cid) that points back to the exact receipt that
# authorised it. Injective caps the cid length, so we take the leading hex of the receipt hash:
# 32 hex = 128-bit binding, safely under the cap. The full receipt hash stays in the execution log,
# so the bind is recoverable both ways (cid -> receipt prefix, execution record -> full hash).
CID_HEX_LEN = 32


def receipt_cid(receipt_hash: str) -> str:
    """Derive the on-chain cid from a receipt hash. Binds the objective on-chain fill back to the
    committed decision: change the decision and its receipt hash changes, so the cid no longer
    matches the order the chain recorded."""
    return receipt_hash.split(":", 1)[-1][:CID_HEX_LEN]


@dataclass
class Receipt:
    seq: int
    ts: str
    policy_hash: str
    kind: str                 # trade | clamp | reject | abstain | hold | exit
    decision: dict[str, Any]
    verdict: str              # allowed | clamped | rejected | abstained | hold
    reason: str
    inputs_digest: str        # digest of the market inputs that produced this decision
    prev_hash: str
    hash: str = ""

    def body(self) -> dict[str, Any]:
        return {
            "seq": self.seq, "ts": self.ts, "policy_hash": self.policy_hash,
            "kind": self.kind, "decision": self.decision, "verdict": self.verdict,
            "reason": self.reason, "inputs_digest": self.inputs_digest,
        }

    def compute_hash(self) -> str:
        return "sha256:" + sha256_hex(self.prev_hash.encode() + canonical_bytes(self.body()))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ReceiptChain:
    """Append-only hash chain persisted to receipts.jsonl."""

    def __init__(self, path: Path | str = RECEIPTS_PATH):
        self.path = Path(path)

    def _last(self) -> Optional[dict[str, Any]]:
        if not self.path.exists():
            return None
        last = None
        for line in self.path.read_text().splitlines():
            line = line.strip()
            if line:
                last = json.loads(line)
        return last

    def head(self) -> tuple[int, str]:
        """(next_seq, prev_hash)."""
        last = self._last()
        if last is None:
            return 0, GENESIS
        return last["seq"] + 1, last["hash"]

    def append(self, *, policy_hash: str, kind: str, decision: dict[str, Any],
               verdict: str, reason: str, inputs_digest: str, ts: str) -> Receipt:
        seq, prev = self.head()
        r = Receipt(seq=seq, ts=ts, policy_hash=policy_hash, kind=kind, decision=decision,
                    verdict=verdict, reason=reason, inputs_digest=inputs_digest, prev_hash=prev)
        r.hash = r.compute_hash()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a") as f:
            f.write(json.dumps(r.to_dict()) + "\n")
        return r

    def read_all(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        return [json.loads(l) for l in self.path.read_text().splitlines() if l.strip()]


def verify_chain(records: list[dict[str, Any]], *, expected_policy_hash: Optional[str] = None
                 ) -> dict[str, Any]:
    """Re-walk a receipt chain. Returns {ok, count, broken_at, policy_ok}. Anyone can run this
    against the public receipts.jsonl + committed config to confirm the agent obeyed the rules
    fixed before the market moved."""
    prev = GENESIS
    policy_ok = True
    for i, rec in enumerate(records):
        r = Receipt(
            seq=rec["seq"], ts=rec["ts"], policy_hash=rec["policy_hash"], kind=rec["kind"],
            decision=rec["decision"], verdict=rec["verdict"], reason=rec["reason"],
            inputs_digest=rec["inputs_digest"], prev_hash=rec["prev_hash"],
        )
        if rec["prev_hash"] != prev:
            return {"ok": False, "count": len(records), "broken_at": i, "why": "prev_hash mismatch"}
        if r.compute_hash() != rec["hash"]:
            return {"ok": False, "count": len(records), "broken_at": i, "why": "hash mismatch"}
        if expected_policy_hash is not None and rec["policy_hash"] != expected_policy_hash:
            policy_ok = False
        prev = rec["hash"]
    return {"ok": True, "count": len(records), "broken_at": None, "policy_ok": policy_ok}
