"""Where mutable runtime artifacts live.

Defaults to the repo root, so local/Mac runs and a fresh clone behave exactly as before. On a
server we set SUMPLUS_DATA_DIR to a mounted volume (e.g. /data) so the live state, the
hash-chained receipts, and the ledgers survive container redeploys.
"""
from __future__ import annotations

import os
from pathlib import Path

# …/sumplus-trader-bnb  (this file is agent/ops/paths.py)
REPO_ROOT = Path(__file__).resolve().parent.parent.parent

# Runtime artifacts root. Unset → repo root (unchanged local behaviour); set to a mounted volume
# on a server so trades/receipts/ledgers are durable across redeploys.
DATA_DIR = Path(os.environ.get("SUMPLUS_DATA_DIR") or REPO_ROOT)


def data_path(name: str) -> Path:
    """Absolute path to a runtime artifact under DATA_DIR (created on first use)."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return DATA_DIR / name
