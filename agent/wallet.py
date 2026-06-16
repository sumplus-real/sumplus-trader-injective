"""EVM wallet helper for the agent's dedicated trading/identity wallet.

Chain-agnostic (Mantle 5000, BSC 56, any EVM). web3 / eth_account are imported lazily so the
offline demo and tests run with nothing installed. Used by portfolio valuation and 8004
registration. The private key lives only in .env (gitignored) — never committed.
"""
from __future__ import annotations

import os
from typing import Any

ERC20_BALANCE_ABI = [{
    "type": "function", "name": "balanceOf", "stateMutability": "view",
    "inputs": [{"name": "owner", "type": "address"}],
    "outputs": [{"name": "", "type": "uint256"}],
}]


def generate() -> dict[str, str]:
    """Create a fresh dedicated wallet. Print once, fund it, put the key in .env. Never reuse a personal wallet."""
    from eth_account import Account
    Account.enable_unaudited_hdwallet_features()
    acct = Account.create()
    return {"address": acct.address, "private_key": acct.key.hex()}


def address_from_env() -> str | None:
    return os.environ.get("AGENT_WALLET_ADDRESS") or None


def _w3(rpc_url: str):
    from web3 import Web3
    return Web3(Web3.HTTPProvider(rpc_url))


def native_balance(rpc_url: str, address: str) -> float:
    w3 = _w3(rpc_url)
    wei = w3.eth.get_balance(w3.to_checksum_address(address))
    return wei / 1e18


def erc20_balance(rpc_url: str, token_addr: str, address: str, decimals: int = 18) -> float:
    w3 = _w3(rpc_url)
    c = w3.eth.contract(address=w3.to_checksum_address(token_addr), abi=ERC20_BALANCE_ABI)
    raw = c.functions.balanceOf(w3.to_checksum_address(address)).call()
    return raw / (10 ** decimals)
