"""The Injective verifiable layer: cid binds each on-chain order to its committed receipt.

These cover the new P2 wiring without any network:
  - receipt_cid derivation (the join key the chain sees),
  - the Executor only forwards a cid to a cid-aware backend,
  - InjectiveBackend (dry-run) carries the cid through,
  - the execution log binds back to the receipt chain, and the public verifier catches tampering,
  - the Injective commit publishes the hash of the Injective config (not the BNB one).
"""
import asyncio

from decimal import Decimal

from agent.execution.executor import Executor
from agent.execution.injective_backend import InjectiveBackend
from agent.ops import injective_market as mkt
from agent.policy.receipt import ReceiptChain, receipt_cid, CID_HEX_LEN
from agent.policy import execlog
from agent.types import Decision, ExecutionResult


def test_receipt_cid_is_hash_prefix_without_scheme():
    h = "sha256:" + "ab" * 32
    cid = receipt_cid(h)
    assert cid == ("ab" * 32)[:CID_HEX_LEN]
    assert len(cid) == CID_HEX_LEN
    assert ":" not in cid  # the "sha256:" scheme is dropped so the cid is pure hex


class _CidAwareBackend:
    accepts_cid = True

    def __init__(self):
        self.seen_cid = None

    async def get_quote(self, **kw):
        return {}

    async def execute_swap(self, *, chain, from_token, to_token, amount, slippage_bps=50, cid=""):
        self.seen_cid = cid
        return ExecutionResult(executed=True, dry_run=False,
                               detail={"source": "injective", "cid": cid})


class _PlainBackend:
    # no accepts_cid → must never be handed a cid kwarg (would TypeError)
    def __init__(self):
        self.called = False

    async def get_quote(self, **kw):
        return {}

    async def execute_swap(self, *, chain, from_token, to_token, amount, slippage_bps=50):
        self.called = True
        return ExecutionResult(executed=True, dry_run=False, detail={"source": "mock"})


def _decision():
    return Decision("buy", "injective", "USDT", "INJ", 2.0, 0.7, "test")


def test_executor_forwards_cid_only_to_cid_aware_backend():
    aware = _CidAwareBackend()
    ex = Executor(aware, mode="live")
    asyncio.run(ex.execute(_decision(), 2.0, cid="deadbeef"))
    assert aware.seen_cid == "deadbeef"

    plain = _PlainBackend()
    ex2 = Executor(plain, mode="live")
    # must not raise even though a cid is passed: the executor drops it for non-cid backends
    asyncio.run(ex2.execute(_decision(), 2.0, cid="deadbeef"))
    assert plain.called


def test_injective_backend_dry_run_carries_cid():
    be = InjectiveBackend(dry_run=True)
    res = asyncio.run(be.execute_swap(chain="injective", from_token="USDT", to_token="INJ",
                                      amount="2", slippage_bps=50, cid="cafef00d"))
    assert res.detail["source"] == "injective"
    assert res.detail["cid"] == "cafef00d"


def test_execution_log_binds_to_receipt_and_detects_tampering(tmp_path):
    receipts = tmp_path / "r.jsonl"
    execs = tmp_path / "e.jsonl"
    ch = ReceiptChain(receipts)
    ph = "sha256:abc"
    # an allowed trade receipt → an on-chain order is allowed to reference it
    r = ch.append(policy_hash=ph, kind="trade", decision={"side": "buy"}, verdict="allow",
                  reason="ok", inputs_digest="d", ts="t0")
    cid = receipt_cid(r.hash)
    execlog.record_execution(receipt_seq=r.seq, receipt_hash=r.hash, cid=cid, ts="t0",
                             executed=True,
                             detail={"source": "injective", "tx": "0x1", "order_hash": "0x2",
                                     "market": "INJ/USDT"},
                             path=execs)

    recs = ch.read_all()
    res = execlog.verify_executions(execlog.read_all(execs), recs)
    assert res["ok"] and res["cid_ok"] and res["receipt_ok"]

    # a forged execution whose cid does not match any receipt hash prefix is caught
    bad = execlog.verify_executions(
        [{"receipt_seq": 0, "receipt_hash": r.hash, "cid": "0000", "executed": True}], recs)
    assert not bad["ok"] and not bad["cid_ok"]

    # an execution pointing at a receipt that the policy did NOT allow (a hold) is caught
    h = ch.append(policy_hash=ph, kind="hold", decision={}, verdict="hold", reason="r",
                  inputs_digest="d", ts="t1")
    held = execlog.verify_executions(
        [{"receipt_seq": h.seq, "receipt_hash": h.hash, "cid": receipt_cid(h.hash),
          "executed": True}], ch.read_all())
    assert not held["ok"] and not held["receipt_ok"]


def test_snap_to_tick_respects_market_ticks():
    # Helix rejects price/quantity that is not a whole multiple of the tick. A buy's worst price
    # rounds up (still an acceptable cap), a sell's rounds down, quantity floors.
    tick = Decimal("0.001")
    assert mkt.snap_to_tick("19.8005", tick, "up") == Decimal("19.801")
    assert mkt.snap_to_tick("19.8005", tick, "down") == Decimal("19.800")
    assert mkt.snap_to_tick("0.06030150753", tick, "down") == Decimal("0.060")
    # already aligned values are unchanged; a zero/negative tick is a no-op
    assert mkt.snap_to_tick("19.800", tick, "up") == Decimal("19.800")
    assert mkt.snap_to_tick("19.8005", Decimal("0"), "down") == Decimal("19.8005")


def test_injective_commit_hashes_injective_config():
    # The Injective commit must publish the hash of strategy.injective.json, distinct from the
    # frozen BNB commitment, and never accidentally fall back to the BNB config.
    from agent.identity import commit_publish
    from agent.policy.canonical import committed_policy_hash

    out = commit_publish.publish(dry_run=True, chain="injective")
    assert out["chain"] == "injective" and out["chain_id"] == 1439
    inj_hash = committed_policy_hash("config/strategy.injective.json")
    bnb_hash = committed_policy_hash("config/strategy.json")
    assert out["policy_hash"] == inj_hash
    assert inj_hash != bnb_hash
    assert out["tag"].endswith(inj_hash)
