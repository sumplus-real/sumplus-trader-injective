"""Append-only ledger of every decision + execution. Feeds the demo, the judges, and the
drawdown / rate-limit calculations the guardrail reads back."""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from agent.ops.paths import data_path

LEDGER_PATH = data_path("ledger.jsonl")


def record(event: str, payload: dict[str, Any]) -> None:
    LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LEDGER_PATH.open("a") as f:
        f.write(json.dumps({"ts": _now(), "event": event, **payload}) + "\n")


def _now() -> str:
    # epoch passed in by caller in real runs; time.time() acceptable for live ledger.
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def trades_last_hour() -> int:
    if not LEDGER_PATH.exists():
        return 0
    cutoff = time.time() - 3600
    n = 0
    for line in LEDGER_PATH.read_text().splitlines():
        try:
            e = json.loads(line)
        except Exception:
            continue
        if e.get("event") != "executed":
            continue
        t = time.mktime(time.strptime(e["ts"], "%Y-%m-%dT%H:%M:%SZ"))
        if t >= cutoff:
            n += 1
    return n
