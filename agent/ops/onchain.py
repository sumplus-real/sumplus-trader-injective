"""On-chain balance reader — the truth source the live loop reconciles against.

The internal ledger can drift from reality (a swap that broadcast but timed out before we booked
it, a watchdog restart that lost an unsaved fill). Rather than trust the ledger, every tick re-reads
the wallet's real token balances here and overwrites positions/cash from them. eth_call(balanceOf)
and eth_getBalance are cheap and, unlike eth_getLogs, are not rate-limited on the public BSC RPCs.

All BSC universe + quote tokens are 18-decimal, so one divisor covers them.
"""
from __future__ import annotations

from typing import Any

from agent.ops.rpc import RpcPool

# symbol -> (contract address, decimals). BSC mainnet. Mirrors twak_backend._TOKEN_ADDRESSES.
BSC_TOKENS: dict[str, tuple[str, int]] = {
    "USDT": ("0x55d398326f99059fF775485246999027B3197955", 18),
    "USDC": ("0x8AC76a51cc950d9822D68b83fE1Ad97B32Cd580d", 18),
    "WBNB": ("0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c", 18),
    "BTCB": ("0x7130d2A12B9BCbFAe4f2634d864A1Ee1Ce3Ead9c", 18),
    "ETH":  ("0x2170Ed0880ac9A755fd29B2688956BD959F933F8", 18),
    "CAKE": ("0x0E09FaBB73Bd3Ade0a17ECC321fD13a19e81cE82", 18),
}

# ERC-20 balanceOf(address) selector.
_BALANCEOF = "0x70a08231"


def _encode_address_arg(address: str) -> str:
    return address.lower().replace("0x", "").rjust(64, "0")


def _to_int(raw: Any) -> int:
    if isinstance(raw, str):
        return int(raw, 16) if raw.startswith("0x") else int(raw)
    if isinstance(raw, int):
        return raw
    raise ValueError(f"unexpected RPC result type: {raw!r}")


def read_token_balances(rpc: RpcPool, wallet: str, symbols: list[str]) -> dict[str, float]:
    """Return {SYMBOL: human-unit balance} for the requested ERC-20 symbols. Raises on RPC failure
    so the caller can fail closed (hold) rather than trade against a guessed balance."""
    out: dict[str, float] = {}
    for sym in symbols:
        key = sym.upper()
        if key not in BSC_TOKENS:
            continue
        addr, decimals = BSC_TOKENS[key]
        data = _BALANCEOF + _encode_address_arg(wallet)
        resp = rpc.call("eth_call", [{"to": addr, "data": data}, "latest"])
        out[key] = _to_int(resp.get("result")) / (10 ** decimals)
    return out


def read_native_bnb(rpc: RpcPool, wallet: str) -> float:
    """Return the wallet's native BNB balance (the gas reserve, not tradeable NAV)."""
    resp = rpc.call("eth_getBalance", [wallet, "latest"])
    return _to_int(resp.get("result")) / (10 ** 18)
