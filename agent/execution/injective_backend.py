"""Injective execution backend — places Helix spot MARKET orders via SpotExecutor.

The Injective analogue of TwakBackend. Same contract as every backend (get_quote /
execute_swap on USD amounts); the decision + policy clamp already happened upstream.

What it does differently from the BSC AMM path:
  - Helix is an order book, not an AMM. "Spend $50 of USDT on INJ" becomes a spot
    market BUY: quantity = $50 / ref_price (base units), price = ref_price * (1+slip)
    as the worst acceptable price (slippage bound). A market SELL is the mirror.
  - Orders go through the SpotExecutor contract (direct mode), not an EOA, because an
    EOA cannot call the Exchange precompile directly.
  - Funds live in the contract's exchange subaccount (deposited once at setup), so the
    per-trade path is just: size -> placeSpotMarketOrder -> read back the subaccount.

Reference price comes from the live Helix order book (Injective indexer REST), so we
size against real depth. If the book is unreachable we FAIL CLOSED (return an error so
the agent holds) rather than trade against a guessed price, matching onchain.py's rule.

dry_run (default whenever the contract/RPC/key is not configured) returns the exact
call that WOULD be sent, so the integration is inspectable offline with zero keys.
"""
from __future__ import annotations

import json
import os
from decimal import Decimal
from pathlib import Path
from typing import Any, Optional

from agent.execution.backend import ExecutionBackend
from agent.ops import injective_market as mkt
from agent.types import ExecutionResult

_ABI_PATH = Path(os.environ.get(
    "INJ_EXECUTOR_ABI_PATH",
    str(Path(__file__).resolve().parent.parent.parent / "abi" / "spot_executor.json"),
))

_DEFAULT_INDEXER = "https://sentry.exchange.grpc-web.injective.network"


def _indexer_url() -> str:
    """Read at call time (not import) so the env override applies after launch and under tests."""
    return os.environ.get("INJ_INDEXER_URL", _DEFAULT_INDEXER).rstrip("/")


class InjectiveError(Exception):
    pass


class InjectiveBackend(ExecutionBackend):
    # The agent's receipt hash rides along as the order cid, so the on-chain order is bound to the
    # exact committed decision. The Executor only forwards a cid to backends that opt in here.
    accepts_cid = True

    def __init__(self, dry_run: Optional[bool] = None, default_subaccount_index: int = 1):
        self.rpc_url = os.environ.get("INJ_RPC", "")
        self.executor_addr = os.environ.get("INJ_EXECUTOR_ADDRESS", "")
        self._pk = os.environ.get("AGENT_WALLET_PRIVATE_KEY", "")
        self.fee_recipient = os.environ.get("INJ_FEE_RECIPIENT", "")  # "" => chain default
        self.subaccount_index = int(os.environ.get("INJ_SUBACCOUNT_INDEX", default_subaccount_index))
        # Fail-closed reference price override for offline/illiquid books (USD per base).
        self._ref_price_env = os.environ.get("INJ_REF_PRICE_INJ", "")
        # Default to dry-run unless fully wired for a live broadcast.
        configured = bool(self.rpc_url and self.executor_addr and self._pk)
        self.dry_run = (not configured) if dry_run is None else dry_run

    # ---- pricing -----------------------------------------------------------

    def _ref_price(self, base: str, quote: str, side: str) -> Decimal:
        """USD price per base unit from the live Helix book: best ask for a buy, best
        bid for a sell. Falls back to INJ_REF_PRICE_INJ only if explicitly set."""
        try:
            mid = mkt.market_id(base, quote)
            _bd, base_dec = mkt.token(base)
            _qd, quote_dec = mkt.token(quote)
            ask, bid = self._orderbook_top(mid, base_dec, quote_dec)
            px = ask if side == "buy" else bid
            if px and px > 0:
                return px
            raise InjectiveError("empty order book side")
        except Exception as e:  # noqa: BLE001 — any failure -> try fallback, else fail closed
            if self._ref_price_env:
                return Decimal(self._ref_price_env)
            raise InjectiveError(f"no reference price for {base}/{quote}: {e}") from e

    def _orderbook_top(self, market_id: str, base_dec: int, quote_dec: int
                       ) -> tuple[Decimal | None, Decimal | None]:
        """Return (best_ask, best_bid) as HUMAN prices from the indexer (v2), or (None, None).

        The indexer quotes price in CHAIN format: quote-per-base in raw token units, i.e. scaled by
        10^(quoteDec - baseDec). Multiply by 10^(baseDec - quoteDec) to get the human price
        (e.g. INJ/USDT chain 0.00000000002 -> human 20)."""
        import httpx

        scale = Decimal(10) ** (base_dec - quote_dec)
        url = f"{_indexer_url()}/api/exchange/spot/v2/orderbook/{market_id}"
        last: Exception | None = None
        for _ in range(3):  # the testnet indexer is intermittently flaky
            try:
                r = httpx.get(url, timeout=15)
                r.raise_for_status()
                book = r.json().get("orderbook", {})
                ask = self._best_price(book.get("sells") or [], want_min=True, scale=scale)
                bid = self._best_price(book.get("buys") or [], want_min=False, scale=scale)
                return ask, bid
            except Exception as e:  # noqa: BLE001 — retry transient errors
                last = e
        raise last if last else InjectiveError("orderbook unavailable")

    @staticmethod
    def _best_price(levels: list[dict[str, Any]], want_min: bool, scale: Decimal) -> Decimal | None:
        prices = [Decimal(str(lvl["price"])) * scale for lvl in levels if lvl.get("price") is not None]
        if not prices:
            return None
        return min(prices) if want_min else max(prices)

    # ---- sizing ------------------------------------------------------------

    def _size(self, base: str, quote: str, side: str, amount_usd: str,
              slippage_bps: int) -> dict[str, Any]:
        ref = self._ref_price(base, quote, side)
        usd = Decimal(str(amount_usd))
        quantity_base = usd / ref  # base units to trade
        slip = Decimal(slippage_bps) / Decimal(10_000)
        worst = ref * (1 + slip) if side == "buy" else ref * (1 - slip)
        return {
            "ref_price": float(ref),
            "worst_price": float(worst),
            "quantity_base": float(quantity_base),
            "price_ufixed": mkt.to_ufixed(worst),
            "quantity_ufixed": mkt.to_ufixed(quantity_base),
            "amount_usd": float(usd),
        }

    # ---- ExecutionBackend --------------------------------------------------

    async def get_quote(self, chain: str, from_token: str, to_token: str, amount: str,
                        slippage_bps: int = 50) -> dict[str, Any]:
        plan = mkt.classify_swap(from_token, to_token)
        sizing = self._size(plan["base"], plan["quote"], plan["side"], amount, slippage_bps)
        return {
            "source": "injective",
            "chain": chain or "injective",
            "market": f"{plan['base']}/{plan['quote']}",
            "side": plan["side"],
            "slippage_bps": slippage_bps,
            **sizing,
        }

    async def execute_swap(self, chain: str, from_token: str, to_token: str, amount: str,
                           slippage_bps: int = 50, cid: str = "") -> ExecutionResult:
        plan = mkt.classify_swap(from_token, to_token)
        sizing = self._size(plan["base"], plan["quote"], plan["side"], amount, slippage_bps)
        market = mkt.market_id(plan["base"], plan["quote"])
        # The committed receipt hash (passed by core.tick) is the cid we put on chain; fall back to
        # a static env only for standalone/manual sends.
        order_cid = cid or os.environ.get("INJ_CID", "")

        # Skip orders below the market's min notional (they revert on-chain). The loop holds.
        if sizing["amount_usd"] < mkt.MIN_NOTIONAL_USD:
            return ExecutionResult(
                executed=False, dry_run=self.dry_run,
                detail={"source": "injective", "skipped": "below_min_notional",
                        "min_notional_usd": mkt.MIN_NOTIONAL_USD, "cid": order_cid, **sizing},
            )

        if self.dry_run:
            return ExecutionResult(
                executed=False, dry_run=True,
                detail={"source": "injective", "mode": "dry_run",
                        "would_call": "SpotExecutor.placeSpotMarketOrder",
                        "market": market, "order_type": plan["order_type"],
                        "cid": order_cid, **sizing},
            )

        try:
            tx_hash, order_hash = self._send_order(
                market_id=market, order_type=plan["order_type"],
                price_ufixed=sizing["price_ufixed"], quantity_ufixed=sizing["quantity_ufixed"],
                cid=order_cid,
            )
        except Exception as e:  # noqa: BLE001 — surface, let the loop fail closed
            return ExecutionResult(executed=False, dry_run=False,
                                   detail={"source": "injective", "cid": order_cid, **sizing},
                                   error=str(e))

        # Injective matches spot orders in a batch at end-of-block, so the order is placed here but
        # the fill lands in the subaccount after the block. We report the placement (tx + orderHash);
        # the reconcile-first loop reads the actual fill from the subaccount on the next tick.
        return ExecutionResult(
            executed=bool(tx_hash), dry_run=False,
            detail={"source": "injective", "tx": tx_hash, "order_hash": order_hash,
                    "market": market, "order_type": plan["order_type"],
                    "cid": order_cid, "fill": "via_reconcile", **sizing},
        )

    # ---- on-chain ----------------------------------------------------------

    def _contract(self):
        from web3 import Web3

        w3 = Web3(Web3.HTTPProvider(self.rpc_url))
        abi = json.loads(_ABI_PATH.read_text())["abi"]
        addr = w3.to_checksum_address(self.executor_addr)
        return w3, w3.eth.contract(address=addr, abi=abi)

    def _subaccount(self) -> str:
        return mkt.subaccount_id(self.executor_addr, self.subaccount_index)

    def _send_order(self, market_id: str, order_type: str, price_ufixed: int,
                    quantity_ufixed: int, cid: str) -> tuple[str, str]:
        w3, c = self._contract()
        acct = w3.eth.account.from_key(self._pk)
        fn = c.functions.placeSpotMarketOrder(
            market_id, self._subaccount(), self.fee_recipient,
            int(price_ufixed), int(quantity_ufixed), cid, order_type,
        )
        tx = fn.build_transaction({
            "from": acct.address,
            "nonce": w3.eth.get_transaction_count(acct.address),
            "gas": int(os.environ.get("INJ_GAS_LIMIT", "2000000")),
            "gasPrice": w3.eth.gas_price,
            "chainId": mkt.CHAIN_ID,
        })
        signed = acct.sign_transaction(tx)
        tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
        if receipt.status != 1:
            raise InjectiveError(f"order tx reverted: {tx_hash.hex()}")
        return tx_hash.hex(), self._read_order_hash(c, receipt)

    @staticmethod
    def _read_order_hash(contract, receipt) -> str:
        """The orderHash from SpotMarketOrderPlaced — the join key between the committed decision
        (carried in cid) and the objective fill (read later from the subaccount / exchange records).
        The fill is not in this receipt: Injective matches at end-of-block, after this tx returns."""
        try:
            evs = contract.events.SpotMarketOrderPlaced().process_receipt(receipt)
            if evs:
                return evs[0]["args"].get("orderHash", "")
        except Exception:  # noqa: BLE001 — event decode is best-effort
            pass
        return ""

    def read_subaccount_balances(self, symbols: list[str]) -> dict[str, float]:
        """On-chain NAV truth: available balance per symbol in the contract's subaccount.
        Used by the reconcile loop the same way onchain.read_token_balances is on BSC."""
        _w3, c = self._contract()
        sub = self._subaccount()
        out: dict[str, float] = {}
        for sym in symbols:
            denom, decimals = mkt.token(sym)
            available, _total = c.functions.subaccountBalance(sub, denom).call()
            out[sym.upper()] = float(mkt.from_chain_amount(int(available), decimals))
        return out
