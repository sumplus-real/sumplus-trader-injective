"""Conversational control surface — the agent's own chat, no ClawPlus required.

A user can ask the running agent about itself and steer it:
  - "status" / "how are you doing"      → paused?, portfolio, last decisions
  - "positions" / "portfolio"           → current portfolio value
  - "why" / "explain"                   → the rationale behind the most recent decisions
  - "policy" / "limits"                 → active caps + whitelist
  - "pause" / "resume"                  → toggle autonomous trading
  - "set cap <field> <value>"           → live-adjust a risk cap (e.g. set cap max_single_trade_usd 20)
  - "tick"                              → run one decision cycle right now

UI-agnostic: handle(message) -> reply. CLI REPL below; an HTTP/web front-end can wrap the same
handle(). Free-form questions route to DeepSeek when a key is set, else a rule-based fallback.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
from pathlib import Path

from agent import ledger, runtime

CFG = json.loads((Path(__file__).resolve().parent.parent / "config" / "strategy.json").read_text())


def _recent(events: set[str], n: int = 5) -> list[dict]:
    p = ledger.LEDGER_PATH
    if not p.exists():
        return []
    out = []
    for line in p.read_text().splitlines():
        try:
            e = json.loads(line)
        except Exception:
            continue
        if e.get("event") in events:
            out.append(e)
    return out[-n:]


def _status() -> str:
    from agent import portfolio
    st = runtime.load()
    flag = "PAUSED" if st.get("paused") else "RUNNING"
    pf = portfolio.snapshot()
    last = _recent({"decision"}, 3)
    lines = [f"Status: {flag} | portfolio ${pf['value_usd']:.2f} | drawdown {pf['drawdown_pct']:.2f}% (cap {CFG['risk']['max_drawdown_pct']}%)"]
    if last:
        lines.append("Recent decisions:")
        for e in last:
            d = e["decision"]
            lines.append(f"  - {d['side']} ${d['amount_usd']:g} {d['from_token']}->{d['to_token']} ({d['rationale']})")
    return "\n".join(lines)


def _why() -> str:
    last = _recent({"guardrail"}, 3)
    if not last:
        return "No decisions yet."
    lines = ["Most recent decisions and what the guardrail did:"]
    for e in last:
        d = e["decision"]
        lines.append(f"  - {d['side']} {d['from_token']}->{d['to_token']}: {d['rationale']} | guardrail: {e['reason']}")
    return "\n".join(lines)


def _policy() -> str:
    r = CFG["risk"]
    ov = runtime.load().get("overrides", {})
    r = {**r, **ov}
    pairs = ", ".join(f"{p['from']}->{p['to']}@{p['chain']}" for p in CFG["allowed_pairs"])
    return (f"Active policy:\n  pairs: {pairs}\n  max single trade: ${r['max_single_trade_usd']}\n"
            f"  max position: {r['max_position_pct']*100:.0f}%  | drawdown cap: {r['max_drawdown_pct']}%\n"
            f"  max trades/hour: {r['max_trades_per_hour']}")


async def handle(message: str) -> str:
    msg = message.strip().lower()

    if msg in ("status", "how are you", "how are you doing"):
        return _status()
    if msg in ("positions", "portfolio"):
        st = runtime.load()
        return f"Portfolio value: ${st['portfolio_value_usd']:.2f}"
    if msg.startswith("why") or msg.startswith("explain"):
        return _why()
    if msg in ("policy", "limits", "caps"):
        return _policy()
    if msg == "pause":
        runtime.update(paused=True)
        return "Paused. The agent will not open new trades until resumed."
    if msg == "resume":
        runtime.update(paused=False)
        return "Resumed. Autonomous trading is active."
    if msg == "tick":
        from agent.loop import tick, make_brain, make_backend, Executor, _effective_cfg
        cfg = _effective_cfg()
        backend = make_backend(cfg.get("mode", "mock"))
        execu = Executor(backend, mode=cfg.get("mode", "mock"))
        steps = await tick(make_brain(), backend, execu, portfolio_value_usd=runtime.load()["portfolio_value_usd"])
        return "Ran one cycle:\n" + "\n".join(
            f"  - {s['decision']['side']} {s['decision']['from_token']}->{s['decision']['to_token']}: {s['verdict']}" for s in steps
        ) or "Ran one cycle (no enabled pairs)."

    m = re.match(r"set cap (\w+)\s+([\d.]+)", msg)
    if m:
        field, val = m.group(1), float(m.group(2))
        if field not in CFG["risk"]:
            return f"Unknown cap '{field}'. Known: {', '.join(CFG['risk'])}"
        ov = runtime.load().get("overrides", {})
        ov[field] = val
        runtime.update(overrides=ov)
        return f"Set {field} = {val} (live)."

    return await _freeform(message)


async def _freeform(message: str) -> str:
    if not os.environ.get("DEEPSEEK_API_KEY"):
        return ("I can answer: status, positions, why, policy, pause, resume, tick, "
                "or 'set cap <field> <value>'.")
    # DeepSeek is OpenAI-compatible REST — call it directly with httpx (already a dependency), no SDK.
    import httpx
    context = _status() + "\n" + _policy()
    base = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/")
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{base}/chat/completions",
            headers={"Authorization": f"Bearer {os.environ['DEEPSEEK_API_KEY']}"},
            json={
                "model": os.environ.get("DEEPSEEK_MODEL", "deepseek-chat"),
                "messages": [
                    {"role": "system", "content": "You are the trading agent speaking to its operator. "
                     "Answer briefly and factually using the provided state. Do not invent numbers."},
                    {"role": "user", "content": f"State:\n{context}\n\nOperator asks: {message}"},
                ],
                "temperature": 0.3,
            },
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"].get("content") or ""


def repl() -> None:
    print("Agent chat. Type 'status', 'why', 'pause', 'resume', 'tick', 'policy', or a question. Ctrl-C to exit.")
    while True:
        try:
            msg = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if not msg:
            continue
        print("agent>", asyncio.run(handle(msg)))


if __name__ == "__main__":
    repl()
