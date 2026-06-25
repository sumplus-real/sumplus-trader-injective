"""The decision tick — where every layer meets.

    CMC data ─► survival strategy ─► Maria policy engine ─► hash-chained receipt
                                            │
                              trade ◄───────┴───────► abstention (avoided-loss ledger)
                                │
                          TWAK / backend executes on PancakeSwap

One intent per tick. Every outcome (trade, clamp, reject, abstain, hold) produces a receipt that
references the committed policy hash, so the whole week is verifiable after the fact. Runs fully
offline with the mock backend + mock CMC scenario.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Optional

from agent.policy.canonical import committed_policy_hash, digest, load_config
from agent.policy.engine import PolicyEngine, PortfolioView, MarketView
from agent.policy.receipt import ReceiptChain
from agent.abstention.ledger import AbstentionLedger
from agent.strategy import survival
from agent.strategy.signals import rank_entries
from agent.data.cmc import get_token_views
from agent.execution.executor import Executor
from agent.types import Decision


def _iso(ts: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))


def _intent_to_decision(intent: survival.Intent) -> Decision:
    side = "buy" if intent.action in ("enter", "rebalance") and intent.to_token not in ("USDT", "USDC") else \
           "sell" if intent.action in ("exit",) or (intent.action == "rebalance" and intent.to_token in ("USDT", "USDC")) else \
           "hold"
    # rebalance-up has to_token = risky (buy); rebalance-down has to_token = quote (sell)
    if intent.action == "rebalance":
        side = "sell" if intent.to_token in ("USDT", "USDC") else "buy"
    if intent.action == "enter":
        side = "buy"
    if intent.action == "exit":
        side = "sell"
    return Decision(side=side, chain=intent.chain, from_token=intent.from_token,
                    to_token=intent.to_token, amount_usd=intent.amount_usd,
                    confidence=intent.confidence, rationale=intent.rationale)


def build_portfolio_state(state: dict, views: list, cfg: dict) -> survival.PortfolioState:
    price = {v.symbol.upper(): v.price for v in views}
    positions = {}
    risky_usd = 0.0
    for sym, p in (state.get("positions") or {}).items():
        pos = survival.Position(symbol=sym.upper(), qty=float(p["qty"]),
                                entry_price=float(p["entry_price"]), entry_ts=float(p["entry_ts"]))
        positions[sym.upper()] = pos
        risky_usd += pos.qty * price.get(sym.upper(), pos.entry_price)
    nav = float(state.get("nav", state.get("portfolio_value_usd", 1000.0)))
    hwm = float(state.get("high_water_mark", nav))
    drawdown_pct = max(0.0, (hwm - nav) / hwm * 100) if hwm > 0 else 0.0
    risky_exposure_pct = risky_usd / nav if nav > 0 else 0.0
    since = time.time() - float(state.get("last_trade_ts", 0)) if state.get("last_trade_ts") else 1e9
    return survival.PortfolioState(
        nav_usd=nav, stable_usd=max(0.0, nav - risky_usd), positions=positions,
        drawdown_pct=drawdown_pct, risky_exposure_pct=risky_exposure_pct,
        trades_this_week=int(state.get("trades_this_week", 0)),
        seconds_since_last_trade=since,
    )


@dataclass
class TickResult:
    intent_action: str
    decision: dict[str, Any]
    verdict: str
    reason: str
    ladder_rung: str
    receipt_hash: str
    executed: bool = False
    abstained: bool = False


async def tick(*, state: dict, executor: Optional[Executor] = None, cfg: Optional[dict] = None,
               now_ts: Optional[float] = None, market: Optional[tuple] = None,
               persist: Optional[Any] = None) -> tuple[TickResult, dict]:
    """Run one decision. Returns (result, updated_state). Pure-ish: caller persists the state.

    `market` optionally injects (views, data_ts) — used by the simulator to drive the exact same
    pipeline off a synthetic price series instead of the live CMC feed.

    `persist` is an optional callback(state_dict) the live loop passes so we can durably mark an
    intent as pending *before* the swap is broadcast. If the process dies between broadcast and
    book-keeping, the restart sees the pending intent, reconciles from chain, and does NOT re-fire
    the same trade — the root fix for the over-execution bug."""
    cfg = cfg or load_config()
    now_ts = now_ts or time.time()
    ph = committed_policy_hash()
    chain = ReceiptChain()
    absl = AbstentionLedger()

    if market is not None:
        views, data_ts = market
    else:
        symbols = list(cfg.get("universe", [])) + list(cfg.get("quote_tokens", []))
        views, data_ts = await get_token_views(symbols, cfg)
    price = {v.symbol.upper(): v.price for v in views}
    data_age = max(0.0, now_ts - data_ts)

    pstate = build_portfolio_state(state, views, cfg)
    trade_chain = next((c for c, v in cfg.get("chains", {}).items() if v.get("enabled")), "bsc")
    intent = survival.decide(views, pstate, cfg, now_ts,
                             quote=cfg.get("quote_tokens", ["USDT"])[0], chain=trade_chain)
    decision = _intent_to_decision(intent)

    regime = "risk_on" if rank_entries(views, cfg.get("signal", {})) else "risk_off"
    pv = PolicyEngine(cfg).check(
        decision,
        PortfolioView(nav_usd=pstate.nav_usd, drawdown_pct=pstate.drawdown_pct,
                      risky_exposure_pct=pstate.risky_exposure_pct,
                      trades_last_hour=int(state.get("trades_last_hour", 0)),
                      seconds_since_last_trade=pstate.seconds_since_last_trade),
        MarketView(data_age_s=data_age, regime=regime),
    )

    inputs_digest = digest({"views": [v.__dict__ for v in views], "drawdown": pstate.drawdown_pct})
    receipt = chain.append(policy_hash=ph, kind=pv.kind, decision=decision.to_dict(),
                           verdict=("hold" if pv.kind == "hold" else pv.action),
                           reason=pv.reason, inputs_digest=inputs_digest, ts=_iso(now_ts))

    result = TickResult(intent_action=intent.action, decision=decision.to_dict(),
                        verdict=pv.action, reason=pv.reason, ladder_rung=pv.ladder_rung,
                        receipt_hash=receipt.hash)

    # Abstention bookkeeping: a hold, or a trade the policy rejected, is a recorded restraint.
    # We record the risky token we DECLINED TO BUY and the price we'd have paid, so it can be
    # marked to market later (avoided loss). symbol and ref_price must be the SAME token.
    if intent.action == "hold" or pv.action == "reject":
        stables = set(cfg.get("quote_tokens", ["USDT", "USDC"]))
        cand = rank_entries(views, cfg.get("signal", {}))
        rec_sym = None
        if pv.action == "reject" and decision.is_trade():
            risky = [t.upper() for t in (decision.from_token, decision.to_token) if t.upper() not in stables]
            rec_sym = risky[0] if risky else None
        if rec_sym is None and cand:
            rec_sym = cand[0][0].symbol.upper()
        if rec_sym is None:
            # No risk_on candidate (e.g. mid-crash): the entry we declined is the one a naive
            # momentum-chaser would have taken — the biggest mover. Declining a falling knife is
            # exactly the restraint we want to mark to market.
            movers = [v for v in views if v.symbol.upper() not in stables and v.pct_4h is not None]
            if movers:
                rec_sym = max(movers, key=lambda v: abs(v.pct_4h)).symbol.upper()
        if rec_sym and rec_sym not in stables and price.get(rec_sym):
            reason = intent.abstain_reason or "regime_conflict"
            if pv.action == "reject":
                reason = ("drawdown_proximity" if ("drawdown" in pv.reason or "stablecoin" in pv.reason)
                          else "stale_data" if "stale" in pv.reason
                          else "rate_or_interval" if "rate" in pv.reason
                          else "exposure_full" if "exposure" in pv.reason
                          else "regime_conflict")
            absl.record(ts=now_ts, symbol=rec_sym, reason=reason, side="buy",
                        ref_price=float(price[rec_sym]),
                        size_usd=float(cfg["risk"]["max_single_trade_usd"]) * 0.3)
            result.abstained = True

    # Execution (only on an allowed/clamped trade). We book the internal fill only when the trade
    # actually executed (live/TWAK) or is a simulated/mock fill — never on a live executed=False,
    # which would record a phantom position. The executor is the real-world side-effect.
    new_state = dict(state)
    new_state["pending_intent"] = None
    if pv.allowed and decision.is_trade():
        amount = pv.final_amount_usd
        if executor is not None and executor.mode not in ("mock", "paper"):
            # Durably mark the intent BEFORE broadcasting, so a crash mid-swap is recoverable
            # (the restart reconciles from chain instead of re-firing this same trade).
            seq = int(state.get("intent_seq", 0)) + 1
            pending = {"seq": seq, "side": decision.side, "from_token": decision.from_token,
                       "to_token": decision.to_token, "amount_usd": amount, "ts": _iso(now_ts)}
            if persist is not None:
                staged = dict(new_state)
                staged["intent_seq"] = seq
                staged["pending_intent"] = pending
                persist(staged)
            new_state["intent_seq"] = seq
            exec_res = await executor.execute(decision, amount)
            result.executed = bool(exec_res.executed)
        elif executor is not None:
            exec_res = await executor.execute(decision, amount)
            result.executed = bool(exec_res.executed) or executor.mode in ("mock", "paper")
        else:
            result.executed = True  # simulated fill

        if result.executed:
            _apply_fill(new_state, decision, amount, price, now_ts)
            new_state["last_trade_ts"] = now_ts
            new_state["trades_this_week"] = int(state.get("trades_this_week", 0)) + 1
        new_state["pending_intent"] = None

    # mark abstentions to market once they have aged ~24h, so the price has had time to move
    # and the avoided-loss / missed-gain figure is meaningful rather than ~0.
    absl.mark_to_market(price, now_ts, min_age_s=24 * 3600)
    return result, new_state


def _apply_fill(state: dict, decision: Decision, amount_usd: float, price: dict, now_ts: float) -> None:
    """Book an internal fill: update positions + stable cash so NAV can be marked to market."""
    positions = dict(state.get("positions") or {})
    stable = float(state.get("stable_usd", state.get("nav", 0.0)))
    if decision.side == "buy":
        sym = decision.to_token.upper()
        px = price.get(sym) or 0.0
        if px > 0 and amount_usd <= stable + 1e-9:
            qty = amount_usd / px
            stable -= amount_usd
            if sym in positions:
                old = positions[sym]
                tot_qty = old["qty"] + qty
                old["entry_price"] = (old["entry_price"] * old["qty"] + px * qty) / tot_qty if tot_qty else px
                old["qty"] = tot_qty
            else:
                positions[sym] = {"qty": qty, "entry_price": px, "entry_ts": now_ts}
    elif decision.side == "sell":
        sym = decision.from_token.upper()
        px = price.get(sym) or 0.0
        if sym in positions and px > 0:
            qty_to_sell = min(positions[sym]["qty"], amount_usd / px)
            stable += qty_to_sell * px
            positions[sym]["qty"] -= qty_to_sell
            if positions[sym]["qty"] <= 1e-9:
                positions.pop(sym)
    state["positions"] = positions
    state["stable_usd"] = stable


def mark_nav(state: dict, price: dict) -> float:
    """Mark NAV to market: stable cash + positions valued at current prices. Updates HWM."""
    stable = float(state.get("stable_usd", state.get("nav", 0.0)))
    risky = sum(p["qty"] * (price.get(s.upper()) or p["entry_price"])
                for s, p in (state.get("positions") or {}).items())
    nav = stable + risky
    state["nav"] = nav
    state["high_water_mark"] = max(float(state.get("high_water_mark", nav)), nav)
    return nav
