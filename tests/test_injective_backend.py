"""Offline tests for the Injective execution layer: unit math, swap classification,
and the dry-run backend. No keys, no network (a fixed reference price is injected via
INJ_REF_PRICE_INJ so the order book is never queried)."""
import asyncio
import os

import pytest

from agent.execution.injective_backend import InjectiveBackend
from agent.ops import injective_market as mkt


def test_subaccount_id_shape():
    sub = mkt.subaccount_id("0xaFf9e1C61dEA470060894f396227fabF8Bfa3157", index=1)
    assert sub.startswith("0x") and len(sub) == 66
    assert sub.endswith("000000000000000000000001")
    # case-normalised address body
    assert "aff9e1c61dea470060894f396227fabf8bfa3157" in sub


def test_unit_conversions():
    assert mkt.to_ufixed("1.5") == 1_500_000_000_000_000_000
    assert mkt.to_chain_amount("50", 6) == 50_000_000        # 50 USDT, 6 decimals
    assert mkt.to_chain_amount("2", 18) == 2 * 10 ** 18      # 2 INJ, 18 decimals
    assert float(mkt.from_ufixed(1_500_000_000_000_000_000)) == 1.5


def test_classify_swap_buy_and_sell():
    buy = mkt.classify_swap("USDT", "INJ")
    assert buy["side"] == "buy" and buy["base"] == "INJ" and buy["order_type"] == "buy"
    sell = mkt.classify_swap("INJ", "USDT")
    assert sell["side"] == "sell" and sell["base"] == "INJ" and sell["order_type"] == "sell"
    with pytest.raises(ValueError):
        mkt.classify_swap("INJ", "INJ")


def test_dry_run_quote_sizing(monkeypatch):
    # Force the order-book fallback so sizing is deterministic offline: the backend prefers the
    # live Helix book and only falls back to INJ_REF_PRICE_INJ when the indexer is unreachable.
    monkeypatch.setenv("INJ_INDEXER_URL", "http://127.0.0.1:1")
    monkeypatch.setenv("INJ_REF_PRICE_INJ", "20")   # $20 / INJ fallback
    monkeypatch.delenv("INJ_RPC", raising=False)
    monkeypatch.delenv("INJ_EXECUTOR_ADDRESS", raising=False)
    b = InjectiveBackend()
    assert b.dry_run is True

    q = asyncio.run(b.get_quote("injective", "USDT", "INJ", "50", slippage_bps=50))
    assert q["side"] == "buy"
    # $50 at $20/INJ = 2.5 INJ base
    assert abs(q["quantity_base"] - 2.5) < 1e-9
    # buy worst price = 20 * (1 + 0.005) = 20.1
    assert abs(q["worst_price"] - 20.1) < 1e-9
    assert q["quantity_ufixed"] == mkt.to_ufixed(2.5)


def test_dry_run_execute_never_broadcasts(monkeypatch):
    monkeypatch.setenv("INJ_INDEXER_URL", "http://127.0.0.1:1")
    monkeypatch.setenv("INJ_REF_PRICE_INJ", "20")
    monkeypatch.delenv("INJ_RPC", raising=False)
    monkeypatch.delenv("INJ_EXECUTOR_ADDRESS", raising=False)
    b = InjectiveBackend()
    res = asyncio.run(b.execute_swap("injective", "USDT", "INJ", "50"))
    assert res.dry_run is True and res.executed is False
    assert res.detail["would_call"] == "SpotExecutor.placeSpotMarketOrder"
    assert res.detail.get("tx") is None


def test_sell_worst_price_below_ref(monkeypatch):
    monkeypatch.setenv("INJ_INDEXER_URL", "http://127.0.0.1:1")
    monkeypatch.setenv("INJ_REF_PRICE_INJ", "20")
    b = InjectiveBackend(dry_run=True)
    q = asyncio.run(b.get_quote("injective", "INJ", "USDT", "40", slippage_bps=100))
    assert q["side"] == "sell"
    # sell worst price = 20 * (1 - 0.01) = 19.8 ; quantity = 40/20 = 2 INJ
    assert abs(q["worst_price"] - 19.8) < 1e-9
    assert abs(q["quantity_base"] - 2.0) < 1e-9


def test_below_min_notional_is_skipped(monkeypatch):
    monkeypatch.setenv("INJ_INDEXER_URL", "http://127.0.0.1:1")
    monkeypatch.setenv("INJ_REF_PRICE_INJ", "20")
    b = InjectiveBackend(dry_run=True)
    # $0.50 is below the 1 USDT market min notional -> skipped cleanly, never sent.
    res = asyncio.run(b.execute_swap("injective", "USDT", "INJ", "0.5"))
    assert res.executed is False
    assert res.detail.get("skipped") == "below_min_notional"
