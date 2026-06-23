"""TWAK execution backend — thin adapter over the Trust Wallet Agent Kit CLI.

Per the winning architecture, TWAK is kept THIN: it is the official self-custody SIGNER + the
on-chain spend fence, not the decision authority (that is Maria's policy engine, which has
already allowed/clamped the trade before we get here). This adapter just turns an approved
Decision into a `twak` swap call and reads the result.

Real execution needs the `twak` CLI installed (npm @trustwallet/cli, Node >= 22.14), a wallet
created (`twak wallet create`) and registered (`twak compete register`), and funds in it. Until
then, dry_run returns the exact command that WOULD run, so the integration is inspectable offline
and finalised by Jakob when he installs TWAK (see docs/HUMAN_STEPS.md).
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from typing import Any

from agent.execution.backend import ExecutionBackend
from agent.types import ExecutionResult

TWAK_BIN = os.environ.get("TWAK_BIN", "twak")

# BSC token registry. twak resolves USDT/USDC/WBNB/ETH by symbol but NOT BTCB/CAKE, so we map
# every universe + quote symbol to its canonical BSC contract address and always pass addresses.
# Keyed per chain; the hackathon trades BSC only.
_TOKEN_ADDRESSES = {
    "bsc": {
        "USDT": "0x55d398326f99059fF775485246999027B3197955",
        "USDC": "0x8AC76a51cc950d9822D68b83fE1Ad97B32Cd580d",
        "WBNB": "0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c",
        "BTCB": "0x7130d2A12B9BCbFAe4f2634d864A1Ee1Ce3Ead9c",
        "ETH": "0x2170Ed0880ac9A755fd29B2688956BD959F933F8",
        "CAKE": "0x0E09FaBB73Bd3Ade0a17ECC321fD13a19e81cE82",
    },
}


def _resolve_token(chain: str, token: str) -> str:
    # Pass raw addresses through; map known symbols to addresses; otherwise let twak try the symbol.
    if token.startswith("0x"):
        return token
    return _TOKEN_ADDRESSES.get(chain, {}).get(token.upper(), token)


class TwakBackend(ExecutionBackend):
    def __init__(self, chain_default: str = "bsc", dry_run: bool | None = None):
        self.chain_default = chain_default
        # default to dry-run whenever the CLI is not on PATH, so nothing silently no-ops
        self.dry_run = (shutil.which(TWAK_BIN) is None) if dry_run is None else dry_run

    def _cmd(self, action: str, chain: str, from_token: str, to_token: str,
             amount: str, slippage_bps: int) -> list[str]:
        # Real twak swap CLI: `twak swap <from> <to> --usd <amt> --chain <c> --slippage <pct> [--quote-only] --json`
        # `amount` is a USD value (the executor reasons in USD), so --usd handles the from-token
        # conversion correctly on both entries (USDT->risky) and exits (risky->USDT). Slippage is a
        # percent, not bps. Execution is the default; --quote-only is the only modifier.
        slippage_pct = f"{slippage_bps / 100.0:g}"
        cmd = [
            TWAK_BIN, "swap",
            _resolve_token(chain, from_token), _resolve_token(chain, to_token),
            "--usd", amount,
            "--chain", chain, "--slippage", slippage_pct,
            "--json",
        ]
        if action == "get_quote":
            cmd.append("--quote-only")
        return cmd

    def _run(self, cmd: list[str]) -> dict[str, Any]:
        if self.dry_run:
            return {"dry_run": True, "would_run": " ".join(cmd), "source": "twak"}
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
        if proc.returncode != 0:
            raise TwakError(proc.returncode, proc.stderr.strip() or proc.stdout.strip())
        try:
            return json.loads(proc.stdout)
        except json.JSONDecodeError:
            return {"raw": proc.stdout.strip(), "source": "twak"}

    async def get_quote(self, chain: str, from_token: str, to_token: str, amount: str,
                        slippage_bps: int = 50) -> dict[str, Any]:
        return self._run(self._cmd("get_quote", chain or self.chain_default,
                                    from_token, to_token, amount, slippage_bps))

    async def execute_swap(self, chain: str, from_token: str, to_token: str, amount: str,
                           slippage_bps: int = 50) -> ExecutionResult:
        out = self._run(self._cmd("execute_swap", chain or self.chain_default,
                                   from_token, to_token, amount, slippage_bps))
        if out.get("dry_run"):
            return ExecutionResult(executed=False, dry_run=True, detail=out)
        # twak returns the broadcast tx under "hash" (with an "explorer" URL); accept legacy keys too.
        tx = out.get("hash") or out.get("txHash") or out.get("transactionHash")
        return ExecutionResult(
            executed=bool(tx or out.get("executed")),
            dry_run=False,
            detail={"tx": tx, "source": "twak", **out},
        )


class TwakError(Exception):
    def __init__(self, code: int, detail: str):
        self.code = code
        self.detail = detail
        super().__init__(f"twak error {code}: {detail}")
