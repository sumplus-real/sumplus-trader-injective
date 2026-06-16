import json
from pathlib import Path

from agent.guardrail.policy import Guardrail
from agent.types import Decision

CFG = json.loads((Path(__file__).resolve().parent.parent / "config" / "strategy.json").read_text())


def g():
    return Guardrail(CFG)


def test_in_policy_allowed():
    v = g().check(Decision("buy", "bsc", "USDT", "WBNB", 25, 0.7, "ok"),
                  portfolio_value_usd=1000, drawdown_pct=0, trades_last_hour=0)
    assert v.allowed and v.clamped_amount_usd is None


def test_oversized_clamped():
    v = g().check(Decision("buy", "bsc", "USDT", "WBNB", 5000, 0.9, "big"),
                  portfolio_value_usd=1000, drawdown_pct=0, trades_last_hour=0)
    assert v.allowed and v.clamped_amount_usd == 100.0


def test_offlist_token_rejected():
    v = g().check(Decision("buy", "bsc", "USDT", "SCAM", 25, 0.9, "shill"),
                  portfolio_value_usd=1000, drawdown_pct=0, trades_last_hour=0)
    assert not v.allowed


def test_drawdown_breaker():
    v = g().check(Decision("buy", "bsc", "USDT", "WBNB", 25, 0.9, "x"),
                  portfolio_value_usd=1000, drawdown_pct=7.0, trades_last_hour=0)
    assert not v.allowed


def test_rate_limit():
    v = g().check(Decision("buy", "bsc", "USDT", "WBNB", 25, 0.9, "x"),
                  portfolio_value_usd=1000, drawdown_pct=0, trades_last_hour=6)
    assert not v.allowed
