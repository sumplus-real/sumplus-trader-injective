"""Canonicalisation + the committed policy hash.

The policy hash is the spine of the whole "verifiable" claim. It must be computable by anyone,
deterministically, from the public repo — judges included. The rule is simple and fixed:

    canonical(obj):
        - drop every key whose name starts with "_" (comments / annotations), recursively
        - sort object keys
        - serialise with compact separators and ensure_ascii, no insignificant whitespace
    policy_hash = "sha256:" + hex(sha256(canonical(strategy.json)))

Because the rule is this boring, it cannot be gamed: re-run it on the committed config and you
get the same hash the agent published before the market moved.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

# The active strategy config. Defaults to the BNB committed config; a deployment can point at its
# own config (e.g. the Injective profile) via STRATEGY_CONFIG so its receipts reference the hash of
# the config it actually ran. Same canonicalisation rule, so anyone can recompute either hash.
_DEFAULT_CONFIG = Path(__file__).resolve().parent.parent.parent / "config" / "strategy.json"
CONFIG_PATH = Path(os.environ.get("STRATEGY_CONFIG", _DEFAULT_CONFIG))


def strip_comments(obj: Any) -> Any:
    """Recursively drop keys starting with '_' (annotations); leave everything else intact."""
    if isinstance(obj, dict):
        return {k: strip_comments(v) for k, v in obj.items() if not k.startswith("_")}
    if isinstance(obj, list):
        return [strip_comments(v) for v in obj]
    return obj


def canonical_bytes(obj: Any) -> bytes:
    """Deterministic byte serialisation: comments stripped, keys sorted, no extra whitespace."""
    cleaned = strip_comments(obj)
    return json.dumps(cleaned, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def policy_hash(config: dict[str, Any]) -> str:
    """The committed policy hash for a strategy config dict."""
    return "sha256:" + sha256_hex(canonical_bytes(config))


def load_config(path: Path | str = CONFIG_PATH) -> dict[str, Any]:
    return json.loads(Path(path).read_text())


def committed_policy_hash(path: Path | str = CONFIG_PATH) -> str:
    """The policy hash of the on-disk committed config — what gets published to ERC-8004."""
    return policy_hash(load_config(path))


def digest(obj: Any) -> str:
    """Short content digest of arbitrary decision inputs, for receipts."""
    return "sha256:" + sha256_hex(canonical_bytes(obj))
