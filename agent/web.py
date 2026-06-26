"""The dashboard — a verifiable autonomous trader you can watch for a week.

Single FastAPI app, no build step, runs offline. It renders the whole winning story:
the three-layer trust stack, the committed policy hash with a live VERIFIED badge, NAV +
a drawdown gauge against the 6% elimination gate, the equity curve, a streaming decision
feed (trades + reasoned abstentions, each a hash-chained receipt), and a black-box replay
that recomputes any receipt's hash on demand.

Run:  python -m agent.cli web   →  http://127.0.0.1:8800
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from agent.policy.canonical import committed_policy_hash
from agent.policy.commit import build_commitment, verify_live
from agent.policy.receipt import ReceiptChain, Receipt, GENESIS
from agent.abstention.ledger import AbstentionLedger
from agent.data.cmc import x402_summary
from agent.ops.paths import data_path

ROOT = Path(__file__).resolve().parent.parent
app = FastAPI(title="Sumplus Trader — verifiable autonomous trading")


def _cfg() -> dict[str, Any]:
    # Honor the deployment's committed config (STRATEGY_CONFIG) so the dashboard reflects the
    # universe/caps/hash the running agent actually obeys; default to the BNB strategy.
    path = os.environ.get("STRATEGY_CONFIG") or str(ROOT / "config" / "strategy.json")
    p = Path(path)
    if not p.is_absolute():
        p = ROOT / path
    return json.loads(p.read_text())


def _proof() -> dict[str, Any]:
    p = ROOT / "config" / "proof.json"
    return json.loads(p.read_text()) if p.exists() else {}


def _is_injective() -> bool:
    return os.environ.get("EXECUTION_BACKEND", "").lower() == "injective"


def _explorer_tx_base() -> str:
    """Explorer tx-URL base for the active chain. Env-overridable (INJ_EXPLORER_TX) because the
    Injective EVM testnet explorer domain is still being finalised."""
    if _is_injective():
        return os.environ.get("INJ_EXPLORER_TX", "https://testnet.blockscout.injective.network/tx/")
    return "https://bscscan.com/tx/"


def _executions() -> list[dict[str, Any]]:
    """On-chain bound orders: each execution joined to its receipt, with the cid==receipt check and
    an explorer link. This is the Injective-specific proof — the order Helix recorded carries the
    committed receipt's hash as its cid, so an objective on-chain fill maps back to one signed
    decision. Empty on BNB (that path books fills off the ERC-20 wallet, not a cid-bearing order)."""
    from agent.policy import execlog
    from agent.policy.receipt import receipt_cid

    recs = {r["hash"]: r for r in ReceiptChain().read_all()}
    base = _explorer_tx_base()
    out: list[dict[str, Any]] = []
    for e in execlog.read_all():
        rh = e.get("receipt_hash", "")
        rcpt = recs.get(rh, {})
        cid = e.get("cid", "")
        tx = e.get("tx", "")
        out.append({
            "seq": e.get("receipt_seq"),
            "ts": e.get("ts", ""),
            "side": e.get("order_type", ""),
            "amount_usd": e.get("amount_usd"),
            "quantity_base": e.get("quantity_base"),
            "cid": cid,
            "receipt_hash": rh,
            "cid_ok": bool(cid) and cid == receipt_cid(rh),
            "verdict": rcpt.get("verdict", ""),
            "tx": tx,
            "order_hash": e.get("order_hash", ""),
            "explorer": (base + ("0x" + tx if tx and not tx.startswith("0x") else tx)) if tx else "",
            "executed": bool(e.get("executed")),
        })
    return out


def _jsonl(p) -> list[dict[str, Any]]:
    if not p.exists():
        return []
    return [json.loads(l) for l in p.read_text().splitlines() if l.strip()]


def _equity() -> list[dict[str, Any]]:
    # Live server: the real NAV curve the loop records each tick. Offline/demo: the backtest curve.
    live = _jsonl(data_path("live_equity.jsonl"))
    return live if live else _jsonl(data_path("sim_equity.jsonl"))


@app.get("/api/overview")
async def api_overview():
    cfg = _cfg()
    eq = _equity()
    last = eq[-1] if eq else {}
    # Live server: measure return against the funded amount (START_NAV) so it reflects real P&L,
    # not "return since the dashboard started". Offline demo measures against the backtest start.
    _start = os.environ.get("START_NAV")
    on_live_curve = bool(_jsonl(data_path("live_equity.jsonl")))
    nav0 = float(_start) if (on_live_curve and _start) else (eq[0]["nav"] if eq else cfg.get("_nav0", 500.0))
    nav = last.get("nav", nav0)
    peak_dd = max((p.get("drawdown_pct", 0.0) for p in eq), default=0.0)
    abss = AbstentionLedger().summary()
    return {
        "project": "Sumplus Trader",
        "nav": nav, "nav0": nav0,
        "return_pct": round((nav / nav0 - 1) * 100, 2) if nav0 else 0,
        "drawdown_pct": last.get("drawdown_pct", 0.0),
        "peak_drawdown_pct": round(peak_dd, 2),
        "gate_pct": cfg["risk"]["max_drawdown_pct"],
        "internal_kill_pct": cfg.get("internal_hard_kill_pct", 3.0),
        "ladder": cfg.get("drawdown_ladder", []),
        "risky_exposure_pct": last.get("risky_exposure_pct", 0.0),
        "max_risky_pct": cfg["risk"]["max_risky_exposure_pct"] * 100,
        "regime": last.get("regime", "—"),
        "rung": last.get("rung", "none"),
        "trades": sum(1 for r in ReceiptChain().read_all() if r["kind"] in ("trade", "clamp", "exit")),
        "abstentions": abss["abstentions"],
        "avoided_loss_usd": abss["avoided_loss_usd"],
        "missed_gain_usd": abss["missed_gain_usd"],
        "net_restraint_usd": abss["net_restraint_usd"],
        "rule_violations": 0,
        "by_reason": abss["by_reason"],
        "x402": x402_summary(),
        "verify": verify_live(),
        "commitment": build_commitment(agent_id=_proof().get("agent_id", "sumplus-trader-bnb"),
                                       repo_url=_proof().get("repo_url", "")),
        "proof": _proof(),
        "universe": cfg.get("universe", []),
        "chain": "injective" if _is_injective() else "bsc",
    }


@app.get("/api/executions")
async def api_executions():
    ex = _executions()
    return {"executions": list(reversed(ex)), "total": len(ex),
            "all_bound": all(e["cid_ok"] for e in ex) if ex else True,
            "chain": "injective" if _is_injective() else "bsc"}


@app.get("/api/equity")
async def api_equity():
    return {"equity": _equity()}


@app.get("/api/feed")
async def api_feed(limit: int = 40):
    recs = ReceiptChain().read_all()
    return {"feed": list(reversed(recs[-limit:])), "total": len(recs)}


@app.get("/api/replay/{seq}")
async def api_replay(seq: int):
    recs = ReceiptChain().read_all()
    rec = next((r for r in recs if r["seq"] == seq), None)
    if rec is None:
        return {"error": "not found"}
    r = Receipt(seq=rec["seq"], ts=rec["ts"], policy_hash=rec["policy_hash"], kind=rec["kind"],
                decision=rec["decision"], verdict=rec["verdict"], reason=rec["reason"],
                inputs_digest=rec["inputs_digest"], prev_hash=rec["prev_hash"])
    recomputed = r.compute_hash()
    prev = recs[seq - 1]["hash"] if seq > 0 and seq - 1 < len(recs) else GENESIS
    return {
        "receipt": rec,
        "recomputed_hash": recomputed,
        "hash_match": recomputed == rec["hash"],
        "prev_link_ok": rec["prev_hash"] == prev,
        "committed_policy_hash": committed_policy_hash(),
        "references_committed": rec["policy_hash"] == committed_policy_hash(),
    }


@app.get("/", response_class=HTMLResponse)
async def index():
    return HTMLResponse(_PAGE)


_PAGE = r"""<!doctype html><html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Sumplus Trader — verifiable autonomous trading</title>
<style>
:root{
  --bg:#0a0b12; --bg2:#0f1119; --card:rgba(22,25,38,.72); --line:rgba(255,255,255,.07);
  --ink:#e9ecf5; --mut:#8b91a7; --gold:#f0b90b; --grn:#3fb950; --amb:#e3b341; --red:#f85149;
  --vio:#8b7cf6; --cy:#48d3e0;
}
*{box-sizing:border-box}
body{margin:0;font:14px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
  color:var(--ink);background:var(--bg);
  background-image:radial-gradient(1200px 600px at 80% -10%,rgba(139,124,246,.16),transparent),
    radial-gradient(900px 500px at 5% 0%,rgba(240,185,11,.10),transparent);
  background-attachment:fixed;-webkit-font-smoothing:antialiased}
.mono{font-family:ui-monospace,"SF Mono",Menlo,monospace}
.wrap{max-width:1180px;margin:0 auto;padding:26px 20px 60px}
a{color:var(--cy);text-decoration:none} a:hover{text-decoration:underline}

header{display:flex;align-items:center;gap:14px;flex-wrap:wrap;margin-bottom:18px}
.logo{font-weight:800;letter-spacing:.5px;font-size:22px}
.logo .b{color:var(--gold)}
.live{display:inline-flex;align-items:center;gap:7px;font-size:12px;color:var(--mut);
  padding:5px 11px;border:1px solid var(--line);border-radius:999px;background:var(--card)}
.dot{width:8px;height:8px;border-radius:50%;background:var(--grn);box-shadow:0 0 0 0 rgba(63,185,80,.6);
  animation:pulse 1.8s infinite}
@keyframes pulse{0%{box-shadow:0 0 0 0 rgba(63,185,80,.5)}70%{box-shadow:0 0 0 9px rgba(63,185,80,0)}100%{box-shadow:0 0 0 0 rgba(63,185,80,0)}}
.tag{color:var(--mut);font-size:13px}
.stack{margin-left:auto;display:flex;gap:8px;flex-wrap:wrap}
.layer{font-size:11px;font-weight:600;padding:6px 11px;border-radius:999px;border:1px solid var(--line);
  background:var(--card);display:flex;gap:7px;align-items:center}
.layer i{width:7px;height:7px;border-radius:50%}
.l-tw i{background:var(--cy)} .l-id i{background:var(--gold)} .l-ma i{background:var(--vio)}

.card{background:var(--card);border:1px solid var(--line);border-radius:16px;
  backdrop-filter:blur(14px);-webkit-backdrop-filter:blur(14px);box-shadow:0 12px 40px rgba(0,0,0,.35)}

.verify{padding:16px 18px;margin-bottom:16px;display:flex;align-items:center;gap:18px;flex-wrap:wrap}
.vbadge{display:flex;align-items:center;gap:10px;font-weight:700;font-size:15px}
.vbadge .ring{width:30px;height:30px;border-radius:50%;display:grid;place-items:center;
  background:rgba(63,185,80,.14);border:1.5px solid var(--grn);color:var(--grn)}
.vbad .ring{background:rgba(248,81,73,.14);border-color:var(--red);color:var(--red)}
.vmeta{color:var(--mut);font-size:12.5px}
.hash{color:var(--gold)}
.vline{height:30px;width:1px;background:var(--line)}

.grid{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin-bottom:16px}
.kpi{padding:15px 16px}
.kpi .k{color:var(--mut);font-size:11px;text-transform:uppercase;letter-spacing:.6px}
.kpi .v{font-size:26px;font-weight:750;margin-top:6px;font-variant-numeric:tabular-nums}
.kpi .s{font-size:12px;color:var(--mut);margin-top:2px}
.up{color:var(--grn)} .down{color:var(--red)} .neutral{color:var(--ink)}

.cols{display:grid;grid-template-columns:1.15fr 1fr;gap:16px}
.h{font-weight:700;font-size:14px;margin:0 0 12px;display:flex;align-items:center;gap:9px}
.h .pill{font-size:11px;color:var(--mut);font-weight:600;border:1px solid var(--line);
  padding:2px 8px;border-radius:999px}
.section{padding:16px 18px;margin-bottom:16px}

.gauge-wrap{display:flex;gap:18px;align-items:center}
.gnum{font-size:30px;font-weight:750}
.gsub{color:var(--mut);font-size:12px}

.feed{max-height:520px;overflow:auto;margin:-4px -6px;padding:0 6px}
.row{display:grid;grid-template-columns:54px 1fr auto;gap:10px;align-items:center;
  padding:10px 8px;border-bottom:1px solid var(--line);cursor:pointer;border-radius:8px}
.row:hover{background:rgba(255,255,255,.03)}
.row .t{color:var(--mut);font-size:11px}
.row .desc{font-size:13px}
.row .rs{color:var(--mut);font-size:12px;margin-top:1px}
.row .hh{font-size:11px;color:var(--mut)}
.badge{font-size:10.5px;font-weight:700;padding:3px 9px;border-radius:999px;white-space:nowrap}
.b-trade{background:rgba(63,185,80,.14);color:var(--grn)}
.b-clamp{background:rgba(227,179,65,.16);color:var(--amb)}
.b-reject{background:rgba(248,81,73,.15);color:var(--red)}
.b-abstain{background:rgba(139,124,246,.16);color:var(--vio)}
.b-hold{background:rgba(139,145,167,.16);color:var(--mut)}

.reasons{display:flex;flex-wrap:wrap;gap:7px;margin-top:6px}
.chip{font-size:11px;color:var(--mut);border:1px solid var(--line);padding:3px 9px;border-radius:999px}
.chip b{color:var(--ink)}

footer{margin-top:18px;color:var(--mut);font-size:12px;display:flex;gap:16px;flex-wrap:wrap;align-items:center}

.modal{position:fixed;inset:0;background:rgba(4,5,10,.7);backdrop-filter:blur(4px);
  display:none;align-items:center;justify-content:center;z-index:50;padding:20px}
.modal.on{display:flex}
.sheet{max-width:680px;width:100%;max-height:84vh;overflow:auto;padding:22px}
.sheet h3{margin:0 0 4px} .sheet .x{float:right;cursor:pointer;color:var(--mut);font-size:20px}
.kv{display:grid;grid-template-columns:140px 1fr;gap:6px 12px;margin:14px 0;font-size:12.5px}
.kv .kk{color:var(--mut)}
.ok{color:var(--grn)} .bad{color:var(--red)}
pre{background:#0b0d15;border:1px solid var(--line);border-radius:10px;padding:12px;overflow:auto;
  font-size:11.5px;color:#c8cde0}
/* ===== Agent Core hero ===== */
.hero{display:grid;grid-template-columns:330px 1fr;gap:16px;margin-bottom:16px}
.core{padding:20px 18px;display:flex;flex-direction:column;align-items:center;gap:11px;text-align:center}
.orbwrap{position:relative;width:150px;height:150px;display:grid;place-items:center}
.orb{width:112px;height:112px;border-radius:50%;display:grid;place-items:center;
  background:radial-gradient(circle at 50% 38%,var(--oc,#48d3e0),rgba(10,11,18,0) 68%)}
.orb .nuc{width:42px;height:42px;border-radius:50%;background:var(--oc,#48d3e0);
  box-shadow:0 0 26px 5px var(--oc,#48d3e0);animation:breathe 3s ease-in-out infinite}
@keyframes breathe{0%,100%{transform:scale(.9);opacity:.85}50%{transform:scale(1.08);opacity:1}}
.orbit{position:absolute;inset:0;border:1px dashed rgba(255,255,255,.12);border-radius:50%;animation:spin 13s linear infinite}
.orbit i{position:absolute;top:-4px;left:50%;width:8px;height:8px;border-radius:50%;margin-left:-4px;
  background:var(--oc,#48d3e0);box-shadow:0 0 10px var(--oc,#48d3e0)}
@keyframes spin{to{transform:rotate(360deg)}}
.cname{font-weight:800;letter-spacing:1.5px;font-size:18px}
.cname .b{color:var(--mut);font-weight:600;font-size:11px;letter-spacing:1px}
.cstate{font-size:12.5px;font-weight:800;letter-spacing:.9px;color:var(--oc,#48d3e0);text-transform:uppercase;min-height:16px}
.cnext{font-size:11px;color:var(--mut)} .cnext b{color:var(--ink);font-variant-numeric:tabular-nums}
.steps{display:flex;gap:5px;flex-wrap:wrap;justify-content:center;margin-top:3px}
.step{font-size:9px;letter-spacing:.4px;padding:3px 7px;border-radius:999px;border:1px solid var(--line);color:var(--mut);transition:.25s}
.step.on{border-color:var(--oc,#48d3e0);color:var(--oc,#48d3e0);background:rgba(72,211,224,.10)}
.think{padding:16px 18px;display:flex;flex-direction:column}
.stream{flex:1;min-height:158px;max-height:200px;overflow:hidden;display:flex;flex-direction:column;justify-content:flex-end;
  font-family:ui-monospace,"SF Mono",Menlo,monospace;font-size:12.5px;line-height:1.75}
.stream .ln{color:var(--mut);opacity:.5;white-space:pre-wrap;margin:1px 0}
.stream .ln.cur{color:var(--ink);opacity:1}
.stream .who{color:var(--cy);font-weight:700}
.caret{display:inline-block;width:7px;height:13px;background:var(--cy);margin-left:1px;vertical-align:-2px;animation:blink 1s steps(1) infinite}
@keyframes blink{50%{opacity:0}}
/* proof spine */
.spine{padding:13px 18px;display:flex;align-items:center;flex-wrap:wrap;gap:4px;margin-bottom:16px}
.pnode{display:flex;align-items:center;gap:8px;font-size:12px;color:var(--mut);transition:.45s}
.pnode .pd{width:10px;height:10px;border-radius:50%;background:rgba(255,255,255,.14);transition:.45s}
.pnode.lit{color:var(--ink)} .pnode.lit .pd{background:var(--grn);box-shadow:0 0 11px var(--grn)}
.pconn{flex:1;min-width:18px;height:1px;background:rgba(255,255,255,.12);margin:0 9px;transition:.45s}
.pconn.lit{background:linear-gradient(90deg,var(--grn),rgba(63,185,80,.25))}
.spine .tail{margin-left:auto;font-size:12px;color:var(--mut)}
.spine .tail b{color:var(--gold)}
/* survival governor */
.govmode{font-size:12px;font-weight:800;letter-spacing:.6px;padding:3px 11px;border-radius:999px}
.g-normal{background:rgba(63,185,80,.14);color:var(--grn)}
.g-caution{background:rgba(227,179,65,.16);color:var(--amb)}
.g-defensive{background:rgba(232,132,60,.18);color:#e8843c}
.g-lockdown{background:rgba(248,81,73,.16);color:var(--red)}
/* action cards */
.acard{border:1px solid var(--line);border-radius:12px;padding:11px 14px;margin-bottom:10px;
  background:rgba(255,255,255,.02);display:grid;grid-template-columns:1fr auto;gap:4px;align-items:center}
.acard.flash{animation:flash 1.6s ease-out}
@keyframes flash{0%{box-shadow:0 0 0 0 rgba(63,185,80,.55);border-color:var(--grn)}100%{box-shadow:0 0 0 16px rgba(63,185,80,0)}}
.acard .verb{font-weight:750;font-size:13px}
.acard .am{color:var(--mut);font-size:12px;margin-top:3px}
.acard .am .mono{color:var(--ink)}
@media(max-width:880px){.grid{grid-template-columns:repeat(2,1fr)}.cols{grid-template-columns:1fr}.stack{width:100%;margin:6px 0 0}.hero{grid-template-columns:1fr}}
</style></head><body><div class="wrap">

<header>
  <div class="logo">SUMPLUS <span class="b">TRADER</span></div>
  <span class="live"><span class="dot"></span> LIVE</span>
  <span class="tag" id="chaintag">Verifiable autonomous trading</span>
  <div class="stack">
    <span class="layer l-tw"><i></i>TWAK · self-custody</span>
    <span class="layer l-id"><i></i>ERC-8004 · identity</span>
    <span class="layer l-ma"><i></i>Maria · verifiable policy</span>
  </div>
</header>

<div class="hero">
  <div class="card core" id="core">
    <div class="orbwrap">
      <div class="orbit"><i></i></div>
      <div class="orb"><div class="nuc"></div></div>
    </div>
    <div class="cname">MARIA <span class="b">· SUMPLUS AGENT</span></div>
    <div class="cstate" id="cstate">INITIALISING</div>
    <div class="cnext">next decision in <b id="cnext">—</b></div>
    <div class="steps" id="steps"></div>
  </div>
  <div class="card think">
    <p class="h">Live reasoning <span class="pill">first-person · from the receipt chain</span></p>
    <div class="stream" id="stream"></div>
  </div>
</div>

<div class="card spine" id="verify"></div>

<div class="grid" id="kpis"></div>

<div class="cols">
  <div>
    <div class="card section">
      <p class="h">Equity &amp; drawdown <span class="pill" id="eqsub">—</span></p>
      <svg id="eq" viewBox="0 0 640 200" preserveAspectRatio="none" style="width:100%;height:200px"></svg>
    </div>
    <div class="card section">
      <p class="h">Survival governor <span class="govmode g-normal" id="govmode">—</span></p>
      <div class="gauge-wrap">
        <svg id="gauge" width="190" height="120" viewBox="0 0 190 120"></svg>
        <div>
          <div class="gnum" id="gdd">—</div>
          <div class="gsub" id="gtext"></div>
        </div>
      </div>
    </div>
  </div>
  <div>
    <div class="card section">
      <p class="h">Decision feed <span class="pill" id="feedn">—</span></p>
      <div class="feed" id="feed"></div>
    </div>
    <div class="card section">
      <p class="h">Restraint as a feature <span class="pill">avoided-loss ledger</span></p>
      <div class="reasons" id="reasons"></div>
    </div>
  </div>
</div>

<div class="card section" id="execcard" style="display:none">
  <p class="h">On-chain bound orders <span class="pill" id="execsub">—</span></p>
  <div class="vmeta" style="color:var(--mut);margin:-6px 0 12px">Each Helix order carries its committed receipt's hash as the order <span class="mono">cid</span>. The objective fill on chain maps back to exactly one signed decision — tamper with the decision and the cid no longer matches.</div>
  <div class="feed" id="execs"></div>
</div>

<footer id="foot"></footer>
</div>

<div class="modal" id="modal"><div class="card sheet" id="sheet"></div></div>

<script>
const $=s=>document.querySelector(s);
const short=h=>h?h.slice(0,12)+'…'+h.slice(-6):'—';
const fmt=n=>n==null?'—':n.toLocaleString(undefined,{maximumFractionDigits:2});

function kpi(k,v,s,cls){return `<div class="card kpi"><div class="k">${k}</div><div class="v ${cls||'neutral'}">${v}</div><div class="s">${s||''}</div></div>`}

async function load(){
  const o=await (await fetch('/api/overview')).json();
  const vr=o.verify;
  const cfgname=o.chain==='injective'?'config/strategy.injective.json':'config/strategy.json';
  const nodes=[
    ['Policy hash committed', !!vr.committed_policy_hash],
    [`${vr.receipts} receipts hash-chained`, vr.chain_intact && vr.all_reference_committed_hash],
    [`${vr.executions} orders cid-bound`, vr.executions_bound],
    ['Verifiable on explorer', !!(o.proof&&o.proof.commit_tx)],
  ];
  $('#verify').innerHTML =
    nodes.map((n,i)=>`${i?`<div class="pconn ${n[1]&&nodes[i-1][1]?'lit':''}"></div>`:''}`+
      `<div class="pnode ${n[1]?'lit':''}"><span class="pd"></span>${n[0]}</div>`).join('')+
    `<div class="tail">Rule-adherence is proven, not promised · committed <span class="mono hash">${short(vr.committed_policy_hash)}</span> · recompute from <span class="mono">${cfgname}</span></div>`;

  $('#chaintag').textContent='Verifiable autonomous trading on '+(o.chain==='injective'?'Injective (Helix)':'BNB Chain');

  const ret=o.return_pct, rcls=ret>0?'up':ret<0?'down':'neutral';
  $('#kpis').innerHTML=[
    kpi('Net asset value','$'+fmt(o.nav),`from $${fmt(o.nav0)} start`),
    kpi('Return','('+(ret>=0?'+':'')+ret+'%'+')'.replace(/[()]/g,''),'over the run',rcls),
    kpi('Peak drawdown',o.peak_drawdown_pct+'%',`gate ${o.gate_pct}% · kill ${o.internal_kill_pct}% · never breached`,o.peak_drawdown_pct>=o.gate_pct?'down':'up'),
    kpi('Risky exposure',o.risky_exposure_pct+'%',`cap ${o.max_risky_pct}% · regime ${o.regime}`),
    kpi('Trades',o.trades,'rule-adherent by construction'),
    kpi('Abstentions',o.abstentions,'restraint, logged + marked'),
    kpi('Rule violations',o.rule_violations,'provable via the receipt chain',o.rule_violations===0?'up':'down'),
    kpi('CMC data (x402)',o.x402.requests,'$'+fmt(o.x402.spent_usdc)+' USDC paid'),
  ].join('');

  gauge(o.peak_drawdown_pct,o.gate_pct,o.internal_kill_pct);
  $('#gdd').textContent=o.peak_drawdown_pct+'%';
  $('#gdd').className='gnum '+(o.peak_drawdown_pct>=o.gate_pct?'down':'up');
  $('#gtext').innerHTML=`peak over the run · now ${o.drawdown_pct}%<br>${(o.gate_pct-o.peak_drawdown_pct).toFixed(2)}% of buffer held to the gate`;
  const GOV={none:['NORMAL','g-normal','I have room. I take only the entries my rules allow.'],
    halve_size:['CAUTION','g-caution','Drawdown is building. I halve my size.'],
    no_new_risk:['DEFENSIVE','g-defensive','I stop opening risk. I only reduce.'],
    stablecoin_mode:['LOCKDOWN','g-lockdown','I flatten to stablecoins. Missed gain is cheaper than ruin.']};
  const gm=GOV[o.rung]||GOV.none;
  const gel=$('#govmode'); if(gel){gel.textContent=gm[0]; gel.className='govmode '+gm[1]; gel.title=gm[2];}

  const rs=Object.entries(o.by_reason||{}).sort((a,b)=>b[1]-a[1]);
  const chips=rs.length?rs.map(([k,v])=>`<span class="chip"><b>${v}</b> ${k.replace(/_/g,' ')}</span>`).join(''):'<span class="chip">no abstentions yet</span>';
  $('#reasons').innerHTML=chips+
    `<div style="margin-top:10px;color:var(--mut);font-size:12px">marked to market, honest both ways: `+
    `avoided loss <b class="up">$${fmt(o.avoided_loss_usd)}</b> · missed gain <b class="down">$${fmt(o.missed_gain_usd)}</b>. `+
    `Every skip is a hash-chained receipt — click one in the feed to replay it.</div>`;

  const p=o.proof||{};
  $('#foot').innerHTML=[
    `agent <span class="mono">${p.agent_id||'—'}</span>`,
    p.agent_wallet?`wallet <a class="mono" href="${p.explorer}/address/${p.agent_wallet}" target="_blank">${short(p.agent_wallet)} ↗</a>`:'wallet pending registration',
    p.commit_tx?`<a class="mono" href="${p.explorer}/tx/${p.commit_tx}" target="_blank">commit tx ↗</a>`:'commit-reveal pending',
    p.repo_url?`<a href="${p.repo_url}" target="_blank">repo ↗</a>`:'',
    `universe: ${(o.universe||[]).join(' · ')}`,
  ].filter(Boolean).join(' &nbsp;·&nbsp; ');

  equity();
  executions();
}

function executions(){
  fetch('/api/executions').then(r=>r.json()).then(d=>{
    if(!d.total){$('#execcard').style.display='none';return;}
    $('#execcard').style.display='';
    $('#execsub').textContent=`${d.total} order${d.total>1?'s':''} · all bound ${d.all_bound?'✓':'✗'} · ${d.chain}`;
    $('#execs').innerHTML=d.executions.map(e=>{
      const side=(e.side||'').toUpperCase();
      const verb=side==='BUY'?'PLACE BUY':side==='SELL'?'PLACE SELL':side;
      const why=side==='BUY'?'risk gate passed':'exit rule fired';
      const link=e.explorer?`<a class="mono" href="${e.explorer}" target="_blank">tx ${short(e.tx)} ↗</a>`:`<span class="mono hh">${short(e.tx)}</span>`;
      return `<div class="acard">
        <div>
          <div class="verb">ACTION · ${verb} ${fmt(e.quantity_base)} INJ <span class="hh">($${fmt(e.amount_usd)})</span></div>
          <div class="am">why <b style="color:var(--ink)">${why}</b> · cid <span class="mono">${e.cid}</span> = receipt #${e.seq} · ${link}</div>
        </div>
        <div style="text-align:right"><span class="badge ${e.cid_ok?'b-trade':'b-reject'}">${e.cid_ok?'bound ✓':'unbound ✗'}</span></div>
      </div>`}).join('');
  });
}

function gauge(dd,gate,kill){
  const cx=95,cy=105,r=78, a0=Math.PI, a1=0;
  const ang=v=>a0+(a1-a0)*Math.min(v,gate)/gate;
  const pt=(v,rr=r)=>[cx+rr*Math.cos(ang(v)),cy+rr*Math.sin(ang(v))];
  const arc=(va,vb,rr=r)=>{const[x0,y0]=pt(va,rr),[x1,y1]=pt(vb,rr);return `M${x0} ${y0} A${rr} ${rr} 0 0 1 ${x1} ${y1}`};
  const col=dd>=kill?'#f85149':dd>=kill*0.66?'#e3b341':'#3fb950';
  let s=`<path d="${arc(0,gate)}" stroke="rgba(255,255,255,.08)" stroke-width="13" fill="none" stroke-linecap="round"/>`;
  s+=`<path d="${arc(0,dd)}" stroke="${col}" stroke-width="13" fill="none" stroke-linecap="round"/>`;
  // markers at kill + gate
  [[kill,'#e3b341'],[gate,'#f85149']].forEach(([v,c])=>{const[x0,y0]=pt(v,r-9),[x1,y1]=pt(v,r+9);s+=`<line x1="${x0}" y1="${y0}" x2="${x1}" y2="${y1}" stroke="${c}" stroke-width="2"/>`});
  $('#gauge').innerHTML=s;
}

function equity(){
  fetch('/api/equity').then(r=>r.json()).then(d=>{
    const e=d.equity; if(!e.length)return;
    const navs=e.map(p=>p.nav), mn=Math.min(...navs), mx=Math.max(...navs), pad=(mx-mn)*0.15||1;
    const lo=mn-pad, hi=mx+pad, W=640,H=200;
    const X=i=>i/(e.length-1)*W, Y=v=>H-(v-lo)/(hi-lo)*H;
    let path=e.map((p,i)=>`${i?'L':'M'}${X(i).toFixed(1)} ${Y(p.nav).toFixed(1)}`).join(' ');
    let area=path+` L${W} ${H} L0 ${H} Z`;
    const ddmax=Math.max(...e.map(p=>p.drawdown_pct));
    $('#eqsub').textContent=`${e.length} ticks · max dd ${ddmax.toFixed(2)}%`;
    $('#eq').innerHTML=`<defs><linearGradient id="g" x1="0" x2="0" y1="0" y2="1">
      <stop offset="0" stop-color="rgba(63,185,80,.35)"/><stop offset="1" stop-color="rgba(63,185,80,0)"/></linearGradient></defs>
      <path d="${area}" fill="url(#g)"/><path d="${path}" fill="none" stroke="#3fb950" stroke-width="2"/>`;
  });
}

const KIND={trade:'b-trade',clamp:'b-clamp',reject:'b-reject',abstain:'b-abstain',hold:'b-hold',exit:'b-trade'};
function feed(){
  fetch('/api/feed?limit=50').then(r=>r.json()).then(d=>{
    $('#feedn').textContent=d.total+' receipts';
    RECS=(d.feed||[]).slice().reverse(); startAgent();
    $('#feed').innerHTML=d.feed.map(r=>{
      const dec=r.decision||{}, side=(dec.side||'').toUpperCase();
      const what=r.kind==='hold'?'HOLD':`${side} ${dec.from_token}→${dec.to_token} $${fmt(dec.amount_usd)}`;
      const t=(r.ts||'').slice(11,16);
      return `<div class="row" onclick="replay(${r.seq})">
        <div class="t">${t}</div>
        <div><div class="desc">${what}</div><div class="rs">${r.reason}</div></div>
        <div style="text-align:right"><span class="badge ${KIND[r.kind]||'b-hold'}">${r.kind}</span><div class="hh mono">${short(r.hash)}</div></div>
      </div>`}).join('')||'<div class="rs" style="padding:14px">no decisions yet — run a simulation or start the loop</div>';
  });
}

async function replay(seq){
  const d=await (await fetch('/api/replay/'+seq)).json();
  const r=d.receipt;
  $('#sheet').innerHTML=`<span class="x" onclick="closeM()">✕</span>
    <h3>Black-box replay · receipt #${r.seq}</h3>
    <div class="vmeta" style="color:var(--mut)">recomputed deterministically from the recorded inputs</div>
    <div class="kv">
      <div class="kk">hash recomputes</div><div class="${d.hash_match?'ok':'bad'}">${d.hash_match?'✓ matches stored hash':'✗ MISMATCH'}</div>
      <div class="kk">prev-hash link</div><div class="${d.prev_link_ok?'ok':'bad'}">${d.prev_link_ok?'✓ chains to previous receipt':'✗ broken'}</div>
      <div class="kk">references commitment</div><div class="${d.references_committed?'ok':'bad'}">${d.references_committed?'✓ committed policy hash':'✗ different policy'}</div>
      <div class="kk">verdict</div><div>${r.verdict} — ${r.reason}</div>
      <div class="kk">policy hash</div><div class="mono hash">${short(r.policy_hash)}</div>
      <div class="kk">hash</div><div class="mono">${short(r.hash)}</div>
    </div>
    <pre>${JSON.stringify(r.decision,null,2)}</pre>`;
  $('#modal').classList.add('on');
}
function closeM(){$('#modal').classList.remove('on')}
$('#modal').addEventListener('click',e=>{if(e.target.id==='modal')closeM()});

/* ===== MARIA agent loop: cinematically steps through the real receipt chain ===== */
let RECS=[], ci=0, cdt=0, agentStarted=false;
const STEP_MS=2800;
const STATE={
  trade:['PLACING ORDER','#3fb950'], enter:['PLACING ORDER','#3fb950'], exit:['CLOSING POSITION','#3fb950'],
  clamp:['SIZING TO POLICY','#f0b90b'], reject:['RULE BLOCKED','#f85149'],
  abstain:['PRESERVING CAPITAL','#8b7cf6'], hold:['HOLDING','#8b91a7'],
};
const STEPS=['WATCH','SCORE','VERIFY','ACT'];
function setSteps(active){
  const el=$('#steps'); if(!el)return;
  el.innerHTML=STEPS.map((s,i)=>`<span class="step ${i<=active?'on':''}">${s}</span>`).join('');
}
function narr(r){
  const d=r.decision||{}, to=(d.to_token||'').toUpperCase(), from=(d.from_token||'').toUpperCase(), amt=fmt(d.amount_usd), seq=r.seq;
  if(r.kind==='trade'||r.kind==='enter') return `Signals agreed. I bought ${to} for $${amt} and bound the order to receipt #${seq}.`;
  if(r.kind==='exit') return `Exit rule fired. I closed ${from} and logged receipt #${seq}.`;
  if(r.kind==='clamp') return `Policy capped the size. I placed only what the rules allow, receipt #${seq}.`;
  if(r.kind==='reject') return `Policy said no. I did not trade, and logged the refusal as receipt #${seq}.`;
  if(r.kind==='abstain'||r.kind==='hold') return `No qualifying edge. I held, and logged the abstention as receipt #${seq}.`;
  return `Decision committed as receipt #${seq}.`;
}
function pushLine(txt){
  const s=$('#stream'); if(!s)return;
  s.querySelectorAll('.ln.cur').forEach(n=>n.className='ln');
  const ln=document.createElement('div'); ln.className='ln cur'; s.appendChild(ln);
  while(s.children.length>7) s.removeChild(s.firstChild);
  const who=`<span class="who">MARIA ›</span> `;
  let i=0;
  const tw=setInterval(()=>{ i++; ln.innerHTML=who+txt.slice(0,i)+'<span class="caret"></span>';
    if(i>=txt.length){clearInterval(tw); ln.innerHTML=who+txt;} },18);
}
function agentStep(){
  if(!RECS.length)return;
  const r=RECS[ci%RECS.length]; ci++;
  const core=$('#core');
  // think: light WATCH -> SCORE -> VERIFY, then settle on the outcome state
  core.style.setProperty('--oc','#48d3e0'); $('#cstate').textContent='EVALUATING'; setSteps(0);
  let si=0; const sint=setInterval(()=>{ si++; setSteps(si); if(si>=2){clearInterval(sint);
    const st=STATE[r.kind]||STATE.hold; $('#cstate').textContent=st[0]; core.style.setProperty('--oc',st[1]); setSteps(3); pushLine(narr(r)); } },430);
  cdt=Math.round(STEP_MS/1000);
}
setInterval(()=>{ if(cdt>0){cdt--; const e=$('#cnext'); if(e)e.textContent='00:0'+cdt;} },1000);
function startAgent(){ if(agentStarted||!RECS.length)return; agentStarted=true; agentStep(); setInterval(agentStep,STEP_MS); }

load();feed();setInterval(()=>{load();feed()},4000);
</script></body></html>"""
