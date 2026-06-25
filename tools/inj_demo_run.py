"""Injective testnet demo driver: drive the live agent over a scripted INJ tape.

This runs the EXACT production decision path — reconcile-first from the SpotExecutor subaccount,
agent.core.tick (survival brain -> Maria policy engine -> hash-chained receipt -> cid-bound order),
and the execution log — but on a cadence we control and over a deterministic price path. The
committed policy (config/strategy.injective.json, hash published on-chain) is loaded and enforced
unchanged; we only choose WHEN to tick and WHAT market the brain sees, exactly as agent/simulate.py
does for backtests. That keeps the demo reproducible in a short recording window while every decision
stays verifiable against the committed hash.

The tape is a mild INJ uptrend (an ENTER that buys up to the 20% exposure cap), a plateau (holds,
recorded as restraint), and a take-profit spike near the end (an EXIT that sells). Buys/sells are real
Helix orders when --live is set; the on-chain reference price and tick-snapping come from the live
book, so only the DECISION is scripted, never the execution price.

  python -m tools.inj_demo_run --ticks 18 --interval 8           # dry: no on-chain tx
  python -m tools.inj_demo_run --ticks 18 --interval 90 --live   # real testnet orders

Always set SUMPLUS_DATA_DIR to an isolated dir first so the demo's receipt chain is self-contained
and the frozen BNB chain is never touched.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import time

from agent.policy.canonical import load_config
from agent.execution.executor import Executor
from agent.execution.injective_backend import InjectiveBackend
from agent.ops.state import PersistentState
from agent.run_live import sync_state_from_injective, _append_equity_point, STATE_FILE, EQUITY_FILE
from agent.strategy.signals import TokenView
from agent import core


def _tape(i: int, n: int) -> dict:
    """INJ view for tick i of n. Mild agreeing uptrend (risk_on, vol < 4% ceiling) so the brain
    enters; a take-profit spike in the last fifth so a position exits. USDT held flat."""
    spike_at = max(1, int(n * 0.8))
    if i >= spike_at:
        # Take-profit phase: push price well past the +4% take-profit so an open INJ position exits.
        base = 20.0 * 1.06
        return {"price": base, "pct_1h": 2.4, "pct_4h": 3.1, "vol_24h_pct": 2.8}
    # Uptrend phase: 1h and 4h agree positive, vol under the 4% entry ceiling.
    drift = 1.0 + 0.004 * i
    return {"price": 20.0 * drift, "pct_1h": 1.3, "pct_4h": 1.9, "vol_24h_pct": 2.2}


def _views(i: int, n: int, now: float) -> list[TokenView]:
    inj = _tape(i, n)
    return [
        TokenView(symbol="INJ", price=inj["price"], pct_1h=inj["pct_1h"], pct_4h=inj["pct_4h"],
                  vol_24h_pct=inj["vol_24h_pct"], ts=now),
        TokenView(symbol="USDT", price=1.0, pct_1h=0.0, pct_4h=0.0, vol_24h_pct=0.1, ts=now),
    ]


async def run(ticks: int, interval: float, live: bool) -> None:
    cfg = load_config()
    backend = InjectiveBackend(dry_run=not live)
    mode = "live" if live else "paper"
    execu = Executor(backend, mode=mode, default_slippage_bps=cfg["risk"]["default_slippage_bps"])
    ps = PersistentState(STATE_FILE)
    state = ps.load()
    state["mode"] = mode

    print(f"[demo] data_dir={os.environ.get('SUMPLUS_DATA_DIR', '(repo root)')} "
          f"executor={backend.executor_addr} live={live} dry_run={backend.dry_run}")

    for i in range(ticks):
        now = time.time()
        views = _views(i, ticks, now)
        price = {v.symbol.upper(): v.price for v in views}

        # 1) Reconcile-first: chain truth (the SpotExecutor subaccount) overwrites positions/cash.
        if not sync_state_from_injective(state, backend, price, cfg):
            print(f"[demo {i:02d}] reconcile failed -> hold")
            ps.write(state)
            await asyncio.sleep(interval)
            continue
        core.mark_nav(state, price)

        # 2) One decision through the full committed pipeline, on the scripted tape.
        result, state = await core.tick(state=state, executor=execu, cfg=cfg,
                                        now_ts=now, market=(views, now), persist=ps.write)
        core.mark_nav(state, price)
        nav = float(state.get("nav", 0.0))
        state["high_water_mark"] = max(float(state.get("high_water_mark", nav) or nav), nav)
        _append_equity_point(state, result)
        state["last_tick_ts"] = time.time()
        ps.write(state)

        ex = "EXEC" if result.executed else ("abst" if result.abstained else "----")
        print(f"[demo {i:02d}] INJ={price['INJ']:.3f} intent={result.intent_action:9s} "
              f"verdict={result.verdict:7s} {ex} nav={nav:.3f} :: {result.reason}")
        if i < ticks - 1:
            await asyncio.sleep(interval)

    print(f"[demo] done. receipts/executions/equity under {os.environ.get('SUMPLUS_DATA_DIR','.')}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ticks", type=int, default=18)
    ap.add_argument("--interval", type=float, default=8.0, help="seconds between ticks")
    ap.add_argument("--live", action="store_true", help="send real Helix orders (else dry-run)")
    a = ap.parse_args()
    asyncio.run(run(a.ticks, a.interval, a.live))


if __name__ == "__main__":
    main()
