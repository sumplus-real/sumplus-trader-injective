"""Drawdown tracking: high-water mark advances up, drawdown measured down from it."""
import importlib

from agent import portfolio


def setup_function():
    # fresh state each test
    if portfolio.STATE_PATH.exists():
        portfolio.STATE_PATH.unlink()


def teardown_function():
    if portfolio.STATE_PATH.exists():
        portfolio.STATE_PATH.unlink()


def test_hwm_and_drawdown():
    assert portfolio.update_and_drawdown(1000.0) == 0.0      # first value sets HWM
    assert portfolio.update_and_drawdown(1100.0) == 0.0      # new high, no drawdown
    dd = portfolio.update_and_drawdown(990.0)                # 10% below HWM 1100
    assert round(dd, 1) == 10.0
    assert portfolio.update_and_drawdown(1100.0) == 0.0      # recover to HWM
