"""Publish the commit-reveal: put the policy hash on-chain BEFORE code-lock.

We send one 0-value transaction from the agent wallet to itself whose calldata carries a
human-readable tag plus the committed policy hash. On the chain explorer anyone can read the input
data and the block timestamp, proving the agent fixed its rules before the live window opened. After
the run, recompute the hash from the committed config and check it matches — and that every receipt
referenced it. That is rule-adherence as a proof instead of a promise.

Two chains, same mechanism:
  - bsc        (default): chainId 56, BSC_RPC, AGENT_PRIVATE_KEY + AGENT_ADDRESS, BscScan.
  - injective  (--chain injective or EXECUTION_BACKEND=injective): chainId 1439 testnet, INJ_RPC,
               AGENT_WALLET_PRIVATE_KEY + AGENT_WALLET_ADDRESS, Injective EVM explorer. The hash is
               taken over config/strategy.injective.json (or STRATEGY_CONFIG if set), so the commit
               matches the config the Injective agent actually runs.

Dry-run by default (prints the unsigned tx + the readable tag). A real send needs the wallet key,
an RPC, and a little gas — a human step (see docs/HUMAN_STEPS.md).
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

from agent.policy.commit import build_commitment
from agent.policy.canonical import committed_policy_hash

TAG = "sumplus.policy/v1 "

ROOT = Path(__file__).resolve().parent.parent.parent
_INJ_DEFAULT_CONFIG = ROOT / "config" / "strategy.injective.json"


def _chain_profile(chain: str) -> dict[str, Any]:
    """Resolve per-chain wiring. Injective falls back to its own committed config so the published
    hash matches what the Injective agent runs; BSC keeps the original strategy.json default."""
    if chain == "injective":
        cfg_path = os.environ.get("STRATEGY_CONFIG") or str(_INJ_DEFAULT_CONFIG)
        return {
            "chain": "injective",
            "chain_id": int(os.environ.get("INJ_CHAIN_ID", "1439")),
            "rpc": os.environ.get("INJ_RPC", ""),
            "key": os.environ.get("AGENT_WALLET_PRIVATE_KEY", ""),
            "address": os.environ.get("AGENT_WALLET_ADDRESS", ""),
            "config_path": cfg_path,
            "agent_id": os.environ.get("AGENT_ID", "sumplus-trader-injective"),
            "explorer": os.environ.get(
                "INJ_EXPLORER_TX", "https://testnet.blockscout.injective.network/tx/"),
            "need": "set INJ_RPC + AGENT_WALLET_PRIVATE_KEY + AGENT_WALLET_ADDRESS and pass --send",
        }
    return {
        "chain": "bsc",
        "chain_id": int(os.environ.get("BSC_CHAIN_ID", "56")),
        "rpc": os.environ.get("BSC_RPC", "https://bsc-dataseed.bnbchain.org"),
        "key": os.environ.get("AGENT_PRIVATE_KEY", ""),
        "address": os.environ.get("AGENT_ADDRESS", ""),
        "config_path": os.environ.get("STRATEGY_CONFIG", ""),  # "" => canonical default
        "agent_id": os.environ.get("AGENT_ID", "sumplus-trader-bnb"),
        "explorer": "https://bscscan.com/tx/",
        "need": "set AGENT_PRIVATE_KEY + AGENT_ADDRESS + BSC_RPC and pass --send to broadcast",
    }


def commitment_calldata(policy_hash: str) -> tuple[str, str]:
    """Return (human_tag, hex_calldata) embedding the committed policy hash."""
    tag = TAG + policy_hash
    return tag, "0x" + tag.encode("utf-8").hex()


def build_unsigned_tx(*, agent_address: str, calldata: str, chain_id: int = 56, nonce: int = 0,
                      gas_price_wei: int = 1_000_000_000, gas: int = 60_000) -> dict[str, Any]:
    return {
        "from": agent_address, "to": agent_address, "value": 0,
        "data": calldata, "chainId": chain_id, "nonce": nonce,
        "gas": gas, "gasPrice": gas_price_wei,
    }


def _resolve_chain(chain: str | None) -> str:
    chain = (chain or os.environ.get("EXECUTION_BACKEND", "")).lower()
    return "injective" if chain == "injective" else "bsc"


def publish(*, dry_run: bool = True, chain: str | None = None) -> dict[str, Any]:
    prof = _chain_profile(_resolve_chain(chain))
    ph = (committed_policy_hash(prof["config_path"]) if prof["config_path"]
          else committed_policy_hash())
    tag, data = commitment_calldata(ph)
    commitment = build_commitment(agent_id=prof["agent_id"],
                                  repo_url=os.environ.get("REPO_URL", ""))
    # Point the commitment payload at the config we actually hashed for this chain.
    commitment["policy_hash"] = ph
    if prof["config_path"]:
        rel = os.path.relpath(prof["config_path"], ROOT) if os.path.isabs(prof["config_path"]) \
            else prof["config_path"]
        commitment["config_file"] = rel
        commitment["note"] = (f"Every live decision receipt references policy_hash. "
                              f"Recompute it from {rel} to verify.")

    if dry_run or not prof["key"] or not prof["address"]:
        return {"dry_run": True, "chain": prof["chain"], "chain_id": prof["chain_id"],
                "policy_hash": ph, "tag": tag, "calldata": data, "commitment": commitment,
                "note": prof["need"]}

    from web3 import Web3
    w3 = Web3(Web3.HTTPProvider(prof["rpc"]))
    nonce = w3.eth.get_transaction_count(prof["address"])
    tx = build_unsigned_tx(agent_address=prof["address"], calldata=data,
                           chain_id=prof["chain_id"], nonce=nonce, gas_price_wei=w3.eth.gas_price)
    signed = w3.eth.account.sign_transaction(tx, private_key=prof["key"])
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    return {"dry_run": False, "chain": prof["chain"], "chain_id": prof["chain_id"],
            "policy_hash": ph, "tx_hash": tx_hash.hex(), "tag": tag, "commitment": commitment,
            "explorer": prof["explorer"] + tx_hash.hex()}


def main() -> None:
    dry = "--send" not in sys.argv
    chain = None
    if "--chain" in sys.argv:
        i = sys.argv.index("--chain")
        chain = sys.argv[i + 1] if i + 1 < len(sys.argv) else None
    print(json.dumps(publish(dry_run=dry, chain=chain), indent=2))


if __name__ == "__main__":
    main()
