"""Injective spot-market registry + on-chain unit helpers.

The Injective analogue of agent/ops/onchain.py's BSC_TOKENS plus the unit math the
Exchange precompile needs. Everything chain-specific about Injective lives here so the
backend and reconcile loop stay readable.

Two number formats matter (see ExchangeTypes.sol):
  - CHAIN FORMAT: native token decimals. Used for deposit/withdraw amounts and for
    reading subaccount balances. USDT = 6 decimals, INJ = 18.
  - API FORMAT (UFixed256x18): the human value scaled by 1e18. Used for order
    price and quantity, regardless of the token's own decimals.

Market ids and denoms differ between mainnet and the EVM testnet, so every one of
them is env-overridable. The committed defaults are Injective MAINNET values; for
testnet, set INJ_SPOT_MARKET_INJ_USDT / INJ_DENOM_USDT from
`injectived q exchange spot-markets` against the testnet node before going live.
"""
from __future__ import annotations

import os
from decimal import Decimal
from typing import Any

CHAIN_ID = int(os.environ.get("INJ_CHAIN_ID", "1776"))  # Injective native EVM mainnet
EXCHANGE_PRECOMPILE = "0x0000000000000000000000000000000000000065"

# symbol -> (denom, decimals). Mainnet defaults; override per-env for testnet.
INJ_TOKENS: dict[str, tuple[str, int]] = {
    "INJ": (os.environ.get("INJ_DENOM_INJ", "inj"), 18),
    "USDT": (
        os.environ.get("INJ_DENOM_USDT", "peggy0xdAC17F958D2ee523a2206206994597C13D831ec7"),
        6,
    ),
}

# Which symbols are the tradeable (risky) leg vs the quote/stable leg.
RISKY_SYMBOLS = {"INJ"}
QUOTE_SYMBOLS = {"USDT"}

# pair "BASE/QUOTE" -> Helix spot market id. Env-overridable (testnet differs).
# Default = Injective mainnet INJ/USDT spot market. VERIFY on testnet before live.
SPOT_MARKETS: dict[str, str] = {
    "INJ/USDT": os.environ.get(
        "INJ_SPOT_MARKET_INJ_USDT",
        "0xa508cb32923323679f29a032c70342c147c17d0145625922b0ef22e955c844c0",
    ),
}


def subaccount_id(contract_address: str, index: int = 1) -> str:
    """Default subaccount id for a contract: address + 24-hex index, 0x + 64 hex.

    The official exchange-direct demo uses index 1 (suffix ...0001); we follow it.
    Index 0 (all zeros) is the chain's "default" subaccount with special bank-credit
    semantics; using an explicit index keeps deposit and order on the same subaccount.
    """
    addr = contract_address.lower().replace("0x", "")
    if len(addr) != 40:
        raise ValueError(f"bad contract address: {contract_address!r}")
    return "0x" + addr + f"{index:024x}"


def to_ufixed(value: float | str | Decimal) -> int:
    """Human value -> UFixed256x18 (API FORMAT): scale by 1e18. For order price/quantity."""
    return int(Decimal(str(value)) * (10 ** 18))


def from_ufixed(raw: int) -> Decimal:
    return Decimal(int(raw)) / (10 ** 18)


def to_chain_amount(human: float | str | Decimal, decimals: int) -> int:
    """Human value -> CHAIN FORMAT integer for deposit/withdraw (token-native decimals)."""
    return int(Decimal(str(human)) * (10 ** decimals))


def from_chain_amount(raw: int, decimals: int) -> Decimal:
    return Decimal(int(raw)) / (10 ** decimals)


def token(symbol: str) -> tuple[str, int]:
    key = symbol.upper()
    if key not in INJ_TOKENS:
        raise KeyError(f"unknown Injective token symbol: {symbol!r}")
    return INJ_TOKENS[key]


def market_id(base: str, quote: str) -> str:
    pair = f"{base.upper()}/{quote.upper()}"
    mid = SPOT_MARKETS.get(pair)
    if not mid:
        raise KeyError(
            f"no spot market id for {pair}; set INJ_SPOT_MARKET_{base.upper()}_{quote.upper()} "
            f"(find it via `injectived q exchange spot-markets`)"
        )
    return mid


def classify_swap(from_token: str, to_token: str) -> dict[str, Any]:
    """Map an agent swap (from_token -> to_token) onto a Helix spot order.

    USDT -> INJ  =>  market BUY of INJ on INJ/USDT  (spend quote, gain base)
    INJ  -> USDT =>  market SELL of INJ on INJ/USDT (spend base, gain quote)
    """
    f, t = from_token.upper(), to_token.upper()
    if f in QUOTE_SYMBOLS and t in RISKY_SYMBOLS:
        return {"side": "buy", "base": t, "quote": f, "order_type": "buy"}
    if f in RISKY_SYMBOLS and t in QUOTE_SYMBOLS:
        return {"side": "sell", "base": f, "quote": t, "order_type": "sell"}
    raise ValueError(
        f"unsupported Injective pair {from_token}->{to_token}; "
        f"one leg must be quote {sorted(QUOTE_SYMBOLS)}, the other risky {sorted(RISKY_SYMBOLS)}"
    )
