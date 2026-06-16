"""ERC-8004 agent identity registration (ERC-721-based registry).

Registers the agent's dedicated wallet as an on-chain agent identity. Required for the BNB
Track 1 submission (BSC registry: 0x8004a169fb4a3325136eb29fa0ceb6d2e539a432; same contract is
deployed on Base/other EVM chains, identity format `chainId:contract:tokenId`).

The wallet registered here BECOMES the agent's trading wallet. Use a dedicated, freshly
generated wallet (see agent/wallet.py:generate) funded only with test capital + gas.

ABI: defaults to the ERC-8004 reference IdentityRegistry ABI in abi/erc8004_identity_registry.json.
Before a REAL mainnet registration, verify the exact deployed signature — set ERC8004_FETCH_ABI=1
with EXPLORER_API_KEY to pull the on-chain ABI. Use dry_run=True to encode calldata offline first.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

REGISTRY_BSC = os.environ.get("ERC8004_REGISTRY_BSC", "0x8004a169fb4a3325136eb29fa0ceb6d2e539a432")
ABI_PATH = Path(os.environ.get(
    "ERC8004_ABI_PATH",
    str(Path(__file__).resolve().parent.parent.parent / "abi" / "erc8004_identity_registry.json"),
))


def load_abi() -> list[dict[str, Any]]:
    if os.environ.get("ERC8004_FETCH_ABI") == "1":
        fetched = _fetch_abi(REGISTRY_BSC)
        if fetched:
            return fetched
    return json.loads(ABI_PATH.read_text())["abi"]


def _fetch_abi(address: str, chainid: int = 56) -> list[dict[str, Any]] | None:
    """Pull the verified ABI from Etherscan v2 multichain at go-live (needs EXPLORER_API_KEY)."""
    key = os.environ.get("EXPLORER_API_KEY")
    if not key:
        return None
    import httpx
    url = f"https://api.etherscan.io/v2/api?chainid={chainid}&module=contract&action=getabi&address={address}&apikey={key}"
    r = httpx.get(url, timeout=20)
    data = r.json()
    if str(data.get("status")) == "1":
        return json.loads(data["result"])
    return None


def register(rpc_url: str, registry_addr: str, private_key: str, agent_domain: str,
             dry_run: bool = False) -> dict[str, Any]:
    from web3 import Web3
    w3 = Web3(Web3.HTTPProvider(rpc_url))
    acct = w3.eth.account.from_key(private_key)
    registry = w3.eth.contract(address=Web3.to_checksum_address(registry_addr), abi=load_abi())

    token_uri = f"https://{agent_domain}/.well-known/agent.json"
    metadata = [("name", "Sumplus Trading Agent"), ("type", "autonomous-trader")]
    fn = registry.functions.register(token_uri, metadata)

    if dry_run:
        # Encode calldata WITHOUT sending — verify the encoding offline, no gas, no key needed beyond the address.
        return {"dry_run": True, "to": registry.address, "from": acct.address,
                "calldata": fn._encode_transaction_data(), "token_uri": token_uri}

    tx = fn.build_transaction({
        "from": acct.address,
        "nonce": w3.eth.get_transaction_count(acct.address),
        "gas": 400_000,
        "gasPrice": w3.eth.gas_price,
    })
    signed = acct.sign_transaction(tx)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
    return {"tx_hash": tx_hash.hex(), "agent_address": acct.address, "status": receipt.status}


if __name__ == "__main__":
    out = register(
        rpc_url=os.environ.get("BSC_RPC", "https://bsc-dataseed.binance.org"),
        registry_addr=REGISTRY_BSC,
        private_key=os.environ.get("AGENT_WALLET_PRIVATE_KEY", "0x" + "0" * 64),
        agent_domain=os.environ.get("AGENT_DOMAIN", "sumplus.xyz"),
        dry_run=os.environ.get("DRY_RUN", "1") == "1",
    )
    print(json.dumps(out, indent=2))
