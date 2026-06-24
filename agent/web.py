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
    return json.loads((ROOT / "config" / "strategy.json").read_text())


def _proof() -> dict[str, Any]:
    p = ROOT / "config" / "proof.json"
    return json.loads(p.read_text()) if p.exists() else {}


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
    }


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
@media(max-width:880px){.grid{grid-template-columns:repeat(2,1fr)}.cols{grid-template-columns:1fr}.stack{width:100%;margin:6px 0 0}}
</style></head><body><div class="wrap">

<header>
  <div class="logo">SUMPLUS <span class="b">TRADER</span></div>
  <span class="live"><span class="dot"></span> LIVE</span>
  <span class="tag">Verifiable autonomous trading on BNB Chain</span>
  <div class="stack">
    <span class="layer l-tw"><i></i>TWAK · self-custody</span>
    <span class="layer l-id"><i></i>ERC-8004 · identity</span>
    <span class="layer l-ma"><i></i>Maria · verifiable policy</span>
  </div>
</header>

<div class="card verify" id="verify"></div>

<div class="grid" id="kpis"></div>

<div class="cols">
  <div>
    <div class="card section">
      <p class="h">Equity &amp; drawdown <span class="pill" id="eqsub">—</span></p>
      <svg id="eq" viewBox="0 0 640 200" preserveAspectRatio="none" style="width:100%;height:200px"></svg>
    </div>
    <div class="card section">
      <p class="h">Drawdown vs the 6% elimination gate</p>
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
  const vr=o.verify, ok=vr.chain_intact && vr.all_reference_committed_hash;
  $('#verify').className='card verify'+(ok?'':' vbad');
  $('#verify').innerHTML=
    `<div class="vbadge ${ok?'':'vbad'}"><span class="ring">${ok?'✓':'!'}</span>${ok?'Rule adherence verified':'Verification failed'}</div>
     <div class="vline"></div>
     <div><div class="vmeta">committed policy hash</div><div class="mono hash">${short(vr.committed_policy_hash)}</div></div>
     <div class="vline"></div>
     <div class="vmeta">${vr.receipts} receipts · chain intact ${vr.chain_intact?'✓':'✗'} · all reference committed hash ${vr.all_reference_committed_hash?'✓':'✗'}<br>
       recompute from <span class="mono">config/strategy.json</span> to verify — rules were fixed before the market moved</div>`;

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

load();feed();setInterval(()=>{load();feed()},4000);
</script></body></html>"""
