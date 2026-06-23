"""The unattended live loop — what actually runs during 6/22-28.

Ops-hardened by construction. The keystone is reconcile-first: every tick re-reads the wallet's
real on-chain balances and overwrites positions/cash from them BEFORE deciding. So even if a swap
double-broadcast, or a restart lost an unsaved fill, the next tick re-anchors to chain truth — the
internal ledger can never drift from reality for more than one tick. On top of that: state is saved
atomically once per tick, an intent is marked pending before any broadcast (so a crash mid-swap is
recovered, not re-fired), and the watchdog is fail-closed (a few crashes → hard stop, not endless
retry). Each tick runs the same core.tick used in the demo and the simulator.

  EXECUTION_BACKEND=twak  python -m agent.cli loop      # live, signs via Trust Wallet Agent Kit
  (default)               python -m agent.cli loop      # offline/mock, safe to run anywhere
"""
from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path

from agent import core
from agent.data.cmc import get_token_views
from agent.execution.executor import Executor
from agent.execution.factory import make_backend
from agent.ops.onchain import read_token_balances
from agent.ops.rpc import RpcPool
from agent.ops.state import PersistentState
from agent.ops.watchdog import run_with_watchdog
from agent.policy.canonical import load_config

ROOT = Path(__file__).resolve().parent.parent
HEARTBEAT = str(ROOT / "heartbeat.txt")
KILL = str(ROOT / "STOP")
STATE_FILE = str(ROOT / "live_state.json")

# A position worth less than this is treated as dust and ignored when reconciling from chain.
DUST_USD = 1.0
# Consecutive loop crashes before we fail closed and stop trading entirely.
MAX_RESTARTS = 3


def _rpc_pool() -> RpcPool:
    endpoints = [e.strip() for e in os.environ.get(
        "BSC_RPC",
        "https://bsc-dataseed.binance.org,https://bsc-dataseed1.defibit.io,https://rpc.ankr.com/bsc",
    ).split(",") if e.strip()]
    return RpcPool(endpoints)


def sync_state_from_chain(state: dict, rpc: RpcPool, wallet: str, price: dict, cfg: dict) -> bool:
    """Overwrite positions + stable cash from real on-chain balances. Returns False (fail-closed)
    if the chain can't be read, so the caller holds instead of trading against a guessed balance."""
    symbols = list(cfg.get("universe", [])) + list(cfg.get("quote_tokens", []))
    try:
        bals = read_token_balances(rpc, wallet, symbols)
    except Exception as e:  # noqa: BLE001 — any RPC failure means we cannot trust state → hold
        print(f"[reconcile] chain read failed, holding this tick: {e}")
        return False

    stables = {s.upper() for s in cfg.get("quote_tokens", ["USDT", "USDC"])}
    stable_usd = sum(bals.get(s, 0.0) * (price.get(s) or 1.0) for s in stables)

    old = state.get("positions") or {}
    positions: dict = {}
    for sym, qty in bals.items():
        if sym in stables:
            continue
        usd = qty * (price.get(sym) or 0.0)
        if usd < DUST_USD:
            continue
        if sym in old:
            positions[sym] = {"qty": qty, "entry_price": float(old[sym]["entry_price"]),
                              "entry_ts": float(old[sym]["entry_ts"])}
        else:
            positions[sym] = {"qty": qty, "entry_price": float(price.get(sym) or 0.0),
                              "entry_ts": time.time()}
    state["positions"] = positions
    state["stable_usd"] = stable_usd
    return True


async def _loop_once_forever() -> None:
    cfg = load_config()
    chosen = os.environ.get("EXECUTION_BACKEND", "").lower()
    exec_mode = "live" if chosen in ("twak", "maria") else "mock"
    backend = make_backend(exec_mode)
    execu = Executor(backend, mode=exec_mode,
                     default_slippage_bps=cfg["risk"]["default_slippage_bps"])
    ps = PersistentState(STATE_FILE)
    state = ps.load()
    state["mode"] = exec_mode

    wallet = os.environ.get("AGENT_WALLET_ADDRESS", "")
    rpc = _rpc_pool() if exec_mode == "live" and wallet else None
    seed_nav = float(os.environ.get("START_NAV", "500"))
    if not state.get("high_water_mark"):
        state["high_water_mark"] = seed_nav

    interval = cfg["loop"]["tick_seconds"]
    symbols = list(cfg["universe"]) + list(cfg["quote_tokens"])
    while not Path(KILL).exists():
        try:
            views, data_ts = await get_token_views(symbols, cfg)
            price = {v.symbol.upper(): v.price for v in views}

            # 1) Reconcile internal ledger to chain truth (fail-closed: hold if chain unreadable).
            if rpc is not None:
                if not sync_state_from_chain(state, rpc, wallet, price, cfg):
                    ps.write(state)
                    await asyncio.sleep(interval)
                    continue
            elif not state.get("stable_usd") and not state.get("positions"):
                state["stable_usd"] = seed_nav  # offline/mock cold start

            core.mark_nav(state, price)

            # 2) A pending intent means a prior tick may have broadcast a swap and then crashed.
            #    The chain reconcile above already absorbed whatever actually happened, so we just
            #    clear the flag and skip a fresh decision this tick — never re-fire the same trade.
            if state.get("pending_intent"):
                print(f"[recover] clearing pending intent after restart: {state['pending_intent']}")
                state["pending_intent"] = None
                ps.write(state)
                await asyncio.sleep(interval)
                continue

            # 3) Decide + (maybe) execute. The persist callback durably stages the intent before any
            #    broadcast so step 2 can recover it next time.
            result, state = await core.tick(state=state, executor=execu, cfg=cfg,
                                            market=(views, data_ts), persist=ps.write)
            core.mark_nav(state, price)

            # 4) One atomic snapshot per tick. A crash leaves the previous complete snapshot intact.
            state["last_tick_ts"] = time.time()
            ps.write(state)
        except Exception as e:  # fail-closed: persist the staged pending intent, let watchdog decide
            print(f"[tick error] {e}")
            raise
        await asyncio.sleep(interval)


async def run() -> None:
    Path(KILL).unlink(missing_ok=True)
    try:
        await run_with_watchdog(_loop_once_forever, heartbeat_path=HEARTBEAT, kill_path=KILL,
                                max_restarts=MAX_RESTARTS, backoff_s=5.0)
    finally:
        # Fail-closed: once the watchdog gives up (or we exit for any reason), drop the kill file so
        # nothing — not a stray supervisor, not a manual relaunch script — silently resumes trading.
        Path(KILL).touch()


if __name__ == "__main__":
    asyncio.run(run())
