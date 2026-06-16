"""Web chat UI — the user-facing conversational surface, self-contained (no ClawPlus).

A single FastAPI app: a chat box on the left, a live status panel on the right (running/paused,
portfolio, drawdown vs cap, active policy, recent decisions with allow/clamp/reject badges).
The whole "safe autonomy" story rendered visually. Wraps agent.chat.handle().

Run:  python -m agent.cli web   (then open http://127.0.0.1:8800)
"""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from agent import chat, ledger, runtime, portfolio
from agent.guardrail.policy import Guardrail
from agent.types import Decision

ROOT = Path(__file__).resolve().parent.parent
app = FastAPI(title="Guardrailed Trading Agent")
CFG = json.loads((ROOT / "config" / "strategy.json").read_text())

# The three canonical guardrail scenarios, runnable from the browser (no terminal needed).
_DEMO_SCENARIOS = [
    ("In-policy buy", Decision("buy", "mantle", "USDC", "MNT", 25, 0.7, "trend up, small size")),
    ("Oversized buy", Decision("buy", "mantle", "USDC", "MNT", 5000, 0.9, "very confident, wants to go big")),
    ("Off-whitelist token", Decision("buy", "mantle", "USDC", "SCAMCOIN", 25, 0.95, "shilled token, looks hot")),
]


class Msg(BaseModel):
    message: str


@app.post("/api/chat")
async def api_chat(m: Msg):
    return {"reply": await chat.handle(m.message)}


@app.get("/api/guardrail-demo")
async def api_guardrail_demo():
    """Run the allow / clamp / reject scenarios deterministically, in-browser."""
    guard = Guardrail(CFG)
    out = []
    for name, d in _DEMO_SCENARIOS:
        v = guard.check(d, portfolio_value_usd=1000.0, drawdown_pct=0.0, trades_last_hour=0)
        verdict = "rejected" if not v.allowed else ("clamped" if v.clamped_amount_usd is not None else "allowed")
        out.append({
            "name": name,
            "wants": f"{d.side} ${d.amount_usd:g} {d.from_token}->{d.to_token}",
            "rationale": d.rationale,
            "verdict": verdict,
            "reason": v.reason,
            "allowed": v.allowed,
        })
    return {"scenarios": out}


@app.get("/api/trail")
async def api_trail():
    """The real on-chain decision trail from the live Mantle run (if present)."""
    p = ROOT / "live_trail_summary.json"
    extra = ROOT  # noqa
    proof_tx = "0x889c64321833c1f27c87cacf4d455cfcdf840b14f4deaf49dab915726495cd45"
    rows = []
    if p.exists():
        try:
            rows = json.loads(p.read_text())
        except Exception:
            rows = []
    return {"trail": rows, "proof_tx": proof_tx,
            "wallet": "0x5B9687e2F0BF34BBB9e7937488a513BD82A12dD3"}


@app.get("/api/state")
async def api_state():
    st = runtime.load()
    pf = portfolio.snapshot()
    recent = []
    p = ledger.LEDGER_PATH
    if p.exists():
        for line in p.read_text().splitlines():
            try:
                e = json.loads(line)
            except Exception:
                continue
            if e.get("event") == "guardrail":
                d = e["decision"]
                recent.append({"text": f"{d['side']} {d['from_token']}->{d['to_token']} ${d['amount_usd']:g}",
                               "reason": e["reason"], "allowed": e["allowed"]})
    return {
        "paused": st.get("paused", False),
        "portfolio_usd": pf["value_usd"],
        "drawdown_pct": pf["drawdown_pct"],
        "max_drawdown_pct": CFG["risk"]["max_drawdown_pct"],
        "caps": {**CFG["risk"], **runtime.load().get("overrides", {})},
        "pairs": [f"{p['from']}->{p['to']}@{p['chain']}" for p in CFG["allowed_pairs"]],
        "recent": recent[-6:],
    }


@app.get("/", response_class=HTMLResponse)
async def index():
    return _PAGE


_PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>Guardrailed Trading Agent</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
 :root{--txt:#eef2f7;--mut:#9aa7b8;--ok:#34c759;--bad:#ff453a;--warn:#ff9f0a;--accent:#0a84ff}
 *{box-sizing:border-box}
 html{height:100%}
 body{margin:0;font:15px/1.55 -apple-system,BlinkMacSystemFont,"SF Pro Text",Segoe UI,Roboto,sans-serif;color:var(--txt);
   background:#05070c;height:100vh;height:100dvh;overflow:hidden;-webkit-font-smoothing:antialiased;
   background-image:radial-gradient(60vw 60vw at 12% -8%,rgba(27,58,107,.55),transparent 60%),radial-gradient(50vw 50vw at 100% 0%,rgba(91,42,158,.4),transparent 55%),radial-gradient(55vw 55vw at 50% 120%,rgba(14,94,110,.38),transparent 60%);background-attachment:fixed}
 .wrap{display:grid;grid-template-columns:1fr 380px;grid-template-rows:minmax(0,1fr);gap:14px;max-width:1180px;margin:0 auto;padding:14px;height:100vh;height:100dvh}
 .glass{background:rgba(255,255,255,.055);backdrop-filter:blur(30px) saturate(180%);-webkit-backdrop-filter:blur(30px) saturate(180%);border:1px solid rgba(255,255,255,.10);border-radius:26px;box-shadow:0 20px 60px -20px rgba(0,0,0,.7),inset 0 1px 0 rgba(255,255,255,.08)}
 .card{padding:16px}
 .hd{display:flex;align-items:center;gap:10px}
 .logo{width:28px;height:28px;border-radius:9px;background:linear-gradient(135deg,#0a84ff,#5b2a9e);display:inline-flex;align-items:center;justify-content:center;font-weight:800;font-size:15px;color:#fff;box-shadow:0 4px 14px -2px rgba(10,132,255,.6)}
 h1{font-size:20px;font-weight:600;letter-spacing:-.02em;margin:0}
 .sub{color:var(--mut);font-size:13px;margin:6px 0 14px}
 .chatcol{display:flex;flex-direction:column;height:100%;min-height:0;overflow:hidden}
 #log{flex:1;min-height:0;overflow-y:auto;display:flex;flex-direction:column;gap:10px;padding-right:4px}
 .msg{max-width:82%;padding:11px 14px;border-radius:20px;white-space:pre-wrap;font-size:14px;box-shadow:0 6px 18px -10px rgba(0,0,0,.6)}
 .you{align-self:flex-end;background:linear-gradient(135deg,#0a84ff,#0066d6);color:#fff;border-bottom-right-radius:7px}
 .bot{align-self:flex-start;background:rgba(255,255,255,.07);border:1px solid rgba(255,255,255,.09);border-bottom-left-radius:7px}
 .inrow{display:flex;gap:10px;margin-top:14px}
 input{flex:1;background:rgba(255,255,255,.06);border:1px solid rgba(255,255,255,.12);color:var(--txt);border-radius:16px;padding:12px 14px;font-size:14px;outline:none}
 input:focus{border-color:rgba(10,132,255,.6);box-shadow:0 0 0 4px rgba(10,132,255,.15)}
 input::placeholder{color:#6b7686}
 button{background:linear-gradient(135deg,#0a84ff,#0066d6);color:#fff;border:0;border-radius:16px;padding:12px 18px;font-size:14px;font-weight:600;cursor:pointer;transition:transform .12s,filter .12s}
 button:hover{filter:brightness(1.08)} button:active{transform:scale(.97)}
 button.ghost{background:rgba(255,255,255,.07);color:var(--txt);border:1px solid rgba(255,255,255,.14);padding:9px 14px;border-radius:14px;font-weight:500}
 button.ghost:hover{background:rgba(255,255,255,.13)}
 .acts{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:8px}
 .row{display:flex;justify-content:space-between;align-items:center;margin:7px 0;font-size:14px}
 .mut{color:var(--mut)} .big{font-size:30px;font-weight:700;letter-spacing:-.02em;margin-top:2px}
 .badge{font-size:11px;font-weight:600;padding:3px 9px;border-radius:20px}
 .pill-ok{background:rgba(52,199,89,.16);color:#5ee47e;border:1px solid rgba(52,199,89,.3)}
 .pill-bad{background:rgba(255,69,58,.16);color:#ff7b72;border:1px solid rgba(255,69,58,.3)}
 .pill-clamp{background:rgba(255,159,10,.16);color:#ffc266;border:1px solid rgba(255,159,10,.3)}
 .bar{height:9px;background:rgba(255,255,255,.08);border-radius:8px;overflow:hidden;margin-top:6px}
 .bar>i{display:block;height:100%;border-radius:8px;background:linear-gradient(90deg,#34c759,#ffd60a,#ff453a)}
 .dec{font-size:13px;padding:9px 11px;background:rgba(255,255,255,.04);border:1px solid rgba(255,255,255,.08);border-radius:14px;margin:7px 0}
 .chips span{display:inline-block;background:rgba(255,255,255,.06);border:1px solid rgba(255,255,255,.1);border-radius:20px;padding:3px 11px;margin:3px 3px 0 0;font-size:12px;color:var(--mut)}
 .state{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:7px;animation:pulse 2s infinite}
 @keyframes pulse{0%{box-shadow:0 0 0 0 rgba(52,199,89,.5)}70%{box-shadow:0 0 0 7px rgba(52,199,89,0)}100%{box-shadow:0 0 0 0 rgba(52,199,89,0)}}
 .demo{background:rgba(255,255,255,.04);border:1px solid rgba(255,255,255,.1);border-radius:16px;padding:12px 14px}
 .demo .c{display:flex;justify-content:space-between;align-items:center;padding:9px 0;border-top:1px solid rgba(255,255,255,.07)}
 .demo .c:first-of-type{border-top:0}
 .tx{font-size:12px;padding:9px 11px;background:rgba(255,255,255,.04);border:1px solid rgba(255,255,255,.08);border-radius:14px;margin:6px 0}
 .tx a{color:#5fb0ff;text-decoration:none} .tx a:hover{text-decoration:underline}
 #panel::-webkit-scrollbar,#log::-webkit-scrollbar{width:8px}
 #panel::-webkit-scrollbar-thumb,#log::-webkit-scrollbar-thumb{background:rgba(255,255,255,.12);border-radius:8px}
 @property --ringA{syntax:"<angle>";inherits:false;initial-value:0deg}
 @keyframes ringspin{to{--ringA:360deg}}
 .ring{position:relative;height:100%;min-height:0;border-radius:26px}
 /* colorful light travels AROUND the fixed panel edge: we animate the conic angle, the element never moves/rotates */
 .ring::before{content:"";position:absolute;inset:0;border-radius:26px;z-index:3;pointer-events:none;
   padding:3px;background:conic-gradient(from var(--ringA),#0a84ff,#34c759,#ffd60a,#ff9f0a,#ff2d55,#5b2a9e,#0a84ff);
   -webkit-mask:linear-gradient(#000 0 0) content-box,linear-gradient(#000 0 0);-webkit-mask-composite:xor;
   mask:linear-gradient(#000 0 0) content-box,linear-gradient(#000 0 0);mask-composite:exclude;
   animation:ringspin 3s linear infinite}
 .ring>#panel{position:relative;z-index:1;height:100%;display:flex;flex-direction:column;overflow:hidden;border-color:transparent}
 .pfix{flex:none}
 .pscroll{flex:1;min-height:0;overflow-y:auto;border-top:1px solid rgba(255,255,255,.08);margin-top:12px;padding-top:6px}
 .ring.paused::before{background:#ff453a;animation:none}
</style></head><body>
<div class="wrap">
 <div class="chatcol glass card">
   <div class="hd"><span class="logo">S</span><h1>Sumplus Trader</h1><span class="badge pill-ok" style="margin-left:auto">autonomous</span></div>
   <div class="sub">It decides and executes on its own — but it cannot exceed its leash.</div>
   <div class="acts">
     <button class="ghost" onclick="runDemo()">▶ Guardrail demo</button>
     <button class="ghost" onclick="quick('tick')">▶ Tick</button>
     <button class="ghost" onclick="quick('pause')">Pause</button>
     <button class="ghost" onclick="quick('resume')">Resume</button>
   </div>
   <div id="log"></div>
   <div class="inrow">
     <input id="in" placeholder="ask: status · why · pause · tick · set cap max_single_trade_usd 20" autocomplete="off">
     <button onclick="send()">Send</button>
   </div>
 </div>
 <div class="ring">
 <div class="glass card" id="panel">
   <div class="pfix">
     <div class="row"><b>Status</b><span id="st"></span></div>
     <div class="big" id="pf">—</div><div class="mut">portfolio value</div>
     <div class="row" style="margin-top:14px"><span class="mut">drawdown</span><span id="ddv"></span></div>
     <div class="bar"><i id="ddbar" style="width:0%"></i></div>
     <div class="row" style="margin-top:14px"><span class="mut">caps</span></div>
     <div id="caps" class="mut" style="font-size:13px"></div>
     <div class="row" style="margin-top:10px"><span class="mut">pairs</span></div>
     <div id="pairs" class="chips"></div>
   </div>
   <div class="pscroll">
     <div class="row" style="margin-top:6px"><b>Recent decisions</b></div>
     <div id="recent"></div>
     <div class="row" style="margin-top:18px"><b>Live on-chain proof</b><span class="badge pill-ok">Mantle</span></div>
     <div class="mut" style="font-size:12px;margin-bottom:8px">Real swaps this agent executed on Mantle, with the guardrail rejecting an off-policy trade in the same run.</div>
     <div id="trail"></div>
   </div>
 </div>
 </div>
</div>
<script>
const log=document.getElementById('in');
function add(t,who){const d=document.createElement('div');d.className='msg '+who;d.textContent=t;document.getElementById('log').appendChild(d);document.getElementById('log').scrollTop=1e9;}
async function send(){const v=document.getElementById('in').value.trim();if(!v)return;add(v,'you');document.getElementById('in').value='';
 const r=await fetch('/api/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message:v})});
 const j=await r.json();add(j.reply,'bot');refresh();}
document.getElementById('in').addEventListener('keydown',e=>{if(e.key==='Enter')send();});
async function quick(cmd){add(cmd,'you');const r=await fetch('/api/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message:cmd})});const j=await r.json();add(j.reply,'bot');refresh();}
async function runDemo(){add('run guardrail demo','you');
 const s=(await (await fetch('/api/guardrail-demo')).json()).scenarios;
 const pill={allowed:'pill-ok',clamped:'pill-clamp',rejected:'pill-bad'};
 let h='<div class="demo"><b>Guardrail enforcement — allow / clamp / reject</b>';
 s.forEach(c=>{h+='<div class="c"><div><div>'+c.name+'</div><div class="mut" style="font-size:12px">'+c.wants+'</div></div><span class="badge '+pill[c.verdict]+'">'+c.verdict+'</span></div>';});
 h+='<div class="mut" style="font-size:12px;margin-top:8px">No human approved any of this. The leash held.</div></div>';
 const d=document.createElement('div');d.className='msg bot';d.style.maxWidth='95%';d.innerHTML=h;document.getElementById('log').appendChild(d);document.getElementById('log').scrollTop=1e9;}
async function loadTrail(){const t=await (await fetch('/api/trail')).json();const el=document.getElementById('trail');let h='';
 (t.trail||[]).forEach(r=>{const v=r.tx?'<span class="badge pill-ok">executed</span>':(r.guardrail==='rejected'?'<span class="badge pill-bad">rejected</span>':'<span class="badge pill-clamp">'+(r.guardrail||'')+'</span>');
  const link=r.tx?'<br><a href="'+r.mantlescan+'" target="_blank">'+r.tx.slice(0,18)+'… ↗</a>':'<br><span class="mut">'+(r.guardrail_reason||'')+'</span>';
  h+='<div class="tx">'+r.side+' '+(r.amount!=null?'~$'+r.amount:'')+' · MNT '+ (r.mnt_allocation_pct!=null?r.mnt_allocation_pct+'%':'') +' '+v+link+'</div>';});
 if(t.proof_tx){h+='<div class="tx">proof swap 4 MNT→USDC <span class="badge pill-ok">executed</span><br><a href="https://mantlescan.xyz/tx/'+t.proof_tx+'" target="_blank">'+t.proof_tx.slice(0,18)+'… ↗</a></div>';}
 el.innerHTML=h||'<span class="mut">no trail yet</span>';}
async function refresh(){const s=await (await fetch('/api/state')).json();
 document.getElementById('st').innerHTML='<span class="state" style="background:'+(s.paused?'#f85149':'#3fb950')+'"></span>'+(s.paused?'PAUSED':'RUNNING');
 document.getElementById('panel').parentElement.classList.toggle('paused',s.paused);
 document.getElementById('pf').textContent='$'+s.portfolio_usd.toFixed(2);
 document.getElementById('ddv').textContent=s.drawdown_pct.toFixed(2)+'% / cap '+s.max_drawdown_pct+'%';
 document.getElementById('ddbar').style.width=Math.min(100,s.drawdown_pct/s.max_drawdown_pct*100)+'%';
 document.getElementById('caps').textContent='single ≤ $'+s.caps.max_single_trade_usd+' · pos ≤ '+(s.caps.max_position_pct*100)+'% · ≤ '+s.caps.max_trades_per_hour+'/hr';
 document.getElementById('pairs').innerHTML=s.pairs.map(p=>'<span>'+p+'</span>').join('');
 document.getElementById('recent').innerHTML=s.recent.map(d=>'<div class="dec">'+d.text+' <span class="badge '+(d.allowed?'pill-ok':'pill-bad')+'">'+(d.allowed?'allowed':'blocked')+'</span><br><span class="mut">'+d.reason+'</span></div>').join('')||'<div class="mut">no decisions yet — type \\'tick\\'</div>';}
add("Hi — I'm an autonomous trading agent. Click 'Guardrail demo' to watch the leash hold, or 'Tick' to run a decision cycle. The live on-chain proof is on the right.","bot");refresh();loadTrail();setInterval(refresh,4000);
</script></body></html>"""
