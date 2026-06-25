"""Commit-reveal: the one move no other team will ship in 16 hours.

BEFORE code-lock, the agent publishes its policy hash to its ERC-8004 identity (one transaction).
AFTER the unattended week, anyone recomputes the hash from the public repo and verifies every
receipt referenced it — proving the agent obeyed rules fixed before the market moved. This turns
"rule adherence" from the fluffiest judged criterion into a recompute-anyone-can-verify proof.

This module builds the commit payload and provides the public verifier. The actual on-chain
transaction is sent by agent/identity/commit_publish.py (needs a wallet + gas).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agent.policy.canonical import committed_policy_hash, load_config
from agent.policy.receipt import ReceiptChain, verify_chain
from agent.policy import execlog

PROOF_PATH = Path(__file__).resolve().parent.parent.parent / "config" / "proof.json"


def build_commitment(*, agent_id: str, repo_url: str = "") -> dict[str, Any]:
    """The payload committed to the ERC-8004 identity before code-lock. `committed_at` and the
    tx hash are filled in by the publisher once the transaction lands."""
    cfg = load_config()
    return {
        "schema": "sumplus.policy-commitment/v1",
        "agent_id": agent_id,
        "policy_hash": committed_policy_hash(),
        "strategy_version": cfg.get("version", "unknown"),
        "config_file": "config/strategy.json",
        "canonicalisation": "drop _-keys; sort keys; compact json; sha256",
        "repo_url": repo_url,
        "note": "Every live decision receipt references policy_hash. Recompute it from config/strategy.json to verify.",
    }


def verify_live(receipts_path: Path | str | None = None,
                executions_path: Path | str | None = None) -> dict[str, Any]:
    """Public verifier: recompute the committed hash, check the receipt chain against it, and bind
    every logged on-chain order back to the committed decision it came from.

    Three checks, all recomputable from the public repo + logs:
      1. chain_intact            — the receipt hash chain is unbroken (no past decision rewritten).
      2. all_reference_committed — every receipt carries the committed policy hash.
      3. executions_bound        — every executed order's cid is the receipt hash prefix, and that
                                   receipt is a trade the policy allowed."""
    expected = committed_policy_hash()
    chain = ReceiptChain(receipts_path) if receipts_path else ReceiptChain()
    records = chain.read_all()
    result = verify_chain(records, expected_policy_hash=expected)

    execs = execlog.read_all(executions_path) if executions_path else execlog.read_all()
    exec_result = execlog.verify_executions(execs, records)

    return {
        "committed_policy_hash": expected,
        "receipts": result.get("count", 0),
        "chain_intact": result.get("ok", False),
        "all_reference_committed_hash": result.get("policy_ok", False),
        "broken_at": result.get("broken_at"),
        "executions": exec_result.get("count", 0),
        "executions_bound": exec_result.get("ok", False),
        "executions_bad": exec_result.get("bad", []),
    }


def _main() -> None:
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "commitment":
        agent_id = sys.argv[2] if len(sys.argv) > 2 else "sumplus-trader-bnb"
        print(json.dumps(build_commitment(agent_id=agent_id), indent=2))
    else:
        print(json.dumps(verify_live(), indent=2))


if __name__ == "__main__":
    _main()
