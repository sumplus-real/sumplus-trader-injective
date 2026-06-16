"""Single entrypoint: python -m agent.cli <command>

  demo     run the guardrail enforcement demo (offline, no keys)
  tick     run one autonomous decision cycle and print it (offline-capable)
  loop     run the autonomous loop forever
  chat     open the conversational control surface
  register register the agent wallet as an ERC-8004 identity (needs wallet + RPC)
"""
from __future__ import annotations

import asyncio
import sys


def main(argv: list[str] | None = None) -> int:
    args = (argv if argv is not None else sys.argv[1:]) or ["demo"]
    cmd = args[0]

    if cmd == "demo":
        from agent.demo.guardrail_demo import main as demo_main
        demo_main()
    elif cmd == "tick":
        from agent.loop import tick, make_brain, make_backend, Executor, _effective_cfg
        from agent import runtime
        cfg = _effective_cfg()
        backend = make_backend(cfg.get("mode", "mock"))
        execu = Executor(backend, mode=cfg.get("mode", "mock"))
        steps = asyncio.run(tick(make_brain(), backend, execu,
                                 portfolio_value_usd=runtime.load()["portfolio_value_usd"]))
        for s in steps:
            d = s["decision"]
            print(f"{d['side']:4} {d['from_token']}->{d['to_token']:5} ${d['amount_usd']:<6g} | {s['verdict']}")
        if not steps:
            print("(no enabled pairs — check config/strategy.json chains)")
    elif cmd == "loop":
        from agent.loop import run_forever
        asyncio.run(run_forever())
    elif cmd == "chat":
        from agent.chat import repl
        repl()
    elif cmd == "web":
        import uvicorn
        port = int(args[1]) if len(args) > 1 else 8800
        print(f"Open http://127.0.0.1:{port}")
        uvicorn.run("agent.web:app", host="127.0.0.1", port=port, log_level="warning")
    elif cmd == "register":
        from agent.identity.register_8004 import register, REGISTRY_BSC
        import os
        out = register(rpc_url=os.environ["BSC_RPC"], registry_addr=REGISTRY_BSC,
                       private_key=os.environ["AGENT_WALLET_PRIVATE_KEY"],
                       agent_domain=os.environ.get("AGENT_DOMAIN", "sumplus.xyz"))
        print(out)
    else:
        print(__doc__)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
