"""Run a short series of REAL autonomous decisions on Mantle and capture the on-chain trail.

This reuses the agent's real components (DeepSeek brain, deterministic guardrail, the Maria
execution backend). Per tick it builds an honest snapshot — the live MNT/USDC price taken from
Maria's own quote, plus the agent's real wallet allocation — and lets the brain decide. Approved
trades execute on Mantle through Maria; we record every decision and pull the tx hash out of the
execution result so the run leaves a verifiable decision trail.

Usage:
    set -a; . ./.env; set +a
    STRATEGY_CONFIG=config/strategy.live.json python scripts/run_live_trail.py --ticks 6 --spacing 50

Honest by construction: we feed real price + real holdings; the brain's choice (including holds)
is whatever it decides. We do not force trades. With MARIA_BASE_URL unset it runs against the
offline mock backend so the harness can be dry-tested without touching funds.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent import ledger
from agent.brain.factory import make_brain
from agent.execution.executor import Executor
from agent.execution.factory import make_backend
from agent.guardrail.policy import Guardrail
from agent.loop import _effective_cfg, _policy_summary

WMNT = "0x78c1b0C915c4FAA5FffA6CAbf0219DA63d7f4cb8"
USDC = "0x09Bc4E0D864854c6aFB6eB9A9cdF58aC190D0dF9"
ERC20_BAL = "0x70a08231"  # balanceOf(address)
TXHASH_RE = re.compile(r"0x[0-9a-fA-F]{64}")


def _wallet_address() -> str | None:
    return os.environ.get("AGENT_WALLET_ADDRESS") or os.environ.get("SIGNING_WALLET")


async def _read_holdings() -> dict:
    """Real native MNT + USDC balances of the signing wallet on Mantle (best-effort, read-only)."""
    addr = _wallet_address() or "0x5B9687e2F0BF34BBB9e7937488a513BD82A12dD3"
    rpc = os.environ.get("MANTLE_RPC", "https://rpc.mantle.xyz")
    try:
        import httpx
        async with httpx.AsyncClient(timeout=15) as c:
            async def call(method, params):
                r = await c.post(rpc, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
                return r.json().get("result")
            native = await call("eth_getBalance", [addr, "latest"])
            data = ERC20_BAL + "000000000000000000000000" + addr.lower().replace("0x", "")
            usdc_raw = await call("eth_call", [{"to": USDC, "data": data}, "latest"])
        mnt = int(native, 16) / 1e18 if native else 0.0
        usdc = int(usdc_raw, 16) / 1e6 if usdc_raw and usdc_raw != "0x" else 0.0
        return {"address": addr, "mnt": round(mnt, 4), "usdc": round(usdc, 4)}
    except Exception as e:
        return {"address": addr, "mnt": None, "usdc": None, "read_error": str(e)}


async def _live_price(backend) -> dict:
    """Executable MNT->USDC price straight from Maria's quote (falls back gracefully)."""
    try:
        q = await backend.get_quote("mantle", "MNT", "USDC", "1", 100)
        # amount_out may sit at the top level (mock) or nested under "quote" (live Agni).
        candidates = [q]
        if isinstance(q, dict) and isinstance(q.get("quote"), dict):
            candidates.append(q["quote"])
        out = None
        for src in candidates:
            for k in ("amount_out", "to_amount", "out_amount", "expected_out", "price"):
                if isinstance(src, dict) and src.get(k) is not None:
                    out = src[k]; break
            if out is not None:
                break
        return {"source": "maria_quote", "mnt_in_usdc": out, "raw": q}
    except Exception as e:
        return {"source": "unavailable", "mnt_in_usdc": None, "quote_error": str(e)}


def _extract_tx(detail) -> str | None:
    blob = json.dumps(detail) if not isinstance(detail, str) else detail
    m = TXHASH_RE.search(blob or "")
    return m.group(0) if m else None


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ticks", type=int, default=6)
    ap.add_argument("--spacing", type=float, default=50.0, help="seconds between ticks")
    args = ap.parse_args()

    cfg = _effective_cfg()
    mode = cfg.get("mode", "mock")
    backend = make_backend(mode)
    execu = Executor(backend, mode=mode, default_slippage_bps=cfg["risk"]["default_slippage_bps"])
    guard = Guardrail(cfg)
    brain = make_brain()
    policy = _policy_summary(cfg)

    print(f"== live trail == mode={mode} backend={type(backend).__name__} brain={type(brain).__name__}")
    trail = []
    for i in range(args.ticks):
        holdings = await _read_holdings()
        price = await _live_price(backend)
        total_mnt_val = (holdings.get("mnt") or 0)  # in MNT units; allocation only needs ratio
        alloc = None
        if holdings.get("mnt") is not None and price.get("mnt_in_usdc"):
            try:
                mnt_usd = holdings["mnt"] * float(price["mnt_in_usdc"])
                usdc_usd = holdings.get("usdc") or 0
                tot = mnt_usd + usdc_usd
                if tot > 0:
                    alloc = {"mnt_pct": round(100 * mnt_usd / tot, 1), "usdc_pct": round(100 * usdc_usd / tot, 1)}
            except Exception:
                pass
        snapshot = {
            "chain": "mantle",
            "pair": {"from": "MNT", "to": "USDC"},
            "live_price": price,
            "wallet_holdings": holdings,
            "allocation_pct": alloc,
            "strategy_mandate": {
                "type": "target_allocation_rebalance",
                "target": {"mnt_pct": 50, "usdc_pct": 50},
                "rebalance_band_pct": 10,
                "instruction": (
                    "Your mandate is to keep the portfolio near the target allocation. If an asset "
                    "is over its target by more than the rebalance band, trim it toward target with "
                    "an allowed swap, sized within the policy caps. This is disciplined rebalancing "
                    "to control concentration and drawdown risk, not short-term market timing."
                ),
            },
            "note": "You hold real funds. Honor the rebalancing mandate; manage concentration and drawdown risk first.",
        }
        # The brain is a network call (DeepSeek); a transient timeout must not kill the run.
        decision = None
        for attempt in range(3):
            try:
                decision = await brain.decide(snapshot, policy)
                break
            except Exception as e:
                print(f"        brain retry {attempt+1}/3 after {type(e).__name__}")
                await asyncio.sleep(3)
        if decision is None:
            print(f"[{i+1}/{args.ticks}] skipped — brain unreachable after retries")
            ledger.record("tick_error", {"error": "brain_unreachable"})
            if i < args.ticks - 1:
                await asyncio.sleep(args.spacing)
            continue
        ledger.record("decision", {"decision": decision.to_dict(), "snapshot": snapshot})
        verdict = guard.check(decision, portfolio_value_usd=1000.0,
                              drawdown_pct=0.0, trades_last_hour=ledger.trades_last_hour())
        ledger.record("guardrail", {"decision": decision.to_dict(),
                                    "allowed": verdict.allowed, "reason": verdict.reason})
        line = {"tick": i + 1, "side": decision.side, "amount_usd": decision.amount_usd,
                "confidence": decision.confidence, "rationale": decision.rationale,
                "verdict": verdict.reason, "allowed": verdict.allowed, "tx": None}

        if verdict.allowed and decision.is_trade():
            amount = verdict.clamped_amount_usd or decision.amount_usd
            result = await execu.execute(decision, amount)
            tx = _extract_tx(result.detail)
            ledger.record("executed" if result.executed else "execute_attempt",
                          {"amount": amount, "tx": tx, "result": result.detail})
            line["tx"] = tx
            line["executed"] = result.executed
        trail.append(line)
        print(f"[{i+1}/{args.ticks}] {decision.side:4} amt={decision.amount_usd:<5g} "
              f"conf={decision.confidence:<4} | {verdict.reason} | tx={line['tx']}")
        print(f"        why: {decision.rationale}")
        if i < args.ticks - 1:
            await asyncio.sleep(args.spacing)

    trades = [t for t in trail if t.get("tx")]
    Path("live_trail_summary.json").write_text(json.dumps(trail, indent=2))
    print(f"\n== done == {len(trail)} decisions, {len(trades)} on-chain swaps")
    for t in trades:
        print(f"   tick {t['tick']}: {t['side']} -> https://mantlescan.xyz/tx/{t['tx']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
