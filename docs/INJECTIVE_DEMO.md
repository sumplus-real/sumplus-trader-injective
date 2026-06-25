# Injective testnet demo — every decision independently verifiable

This is the Injective Nova deployment of the Sumplus survival-first trading agent. It runs the same
verifiable-decision core as the BNB build, retuned for the INJ/USDT spot market on Helix (the
Exchange precompile `0x0000000000000000000000000000000000000065`, called through our `SpotExecutor`
contract). The one claim it makes that nobody else on Injective makes: **every decision the agent
takes is bound to an on-chain order anyone can independently verify against a policy the agent
published before it started trading.**

## The two-part proof

1. **Commit-reveal.** Before code-lock the agent publishes the SHA-256 of its strategy config on
   chain (a 0-value self-transaction whose calldata carries the hash). The rules are fixed before the
   market moves. Anyone recomputes the hash from the public config and checks it against that tx.

2. **cid-bound receipts.** Every tick produces a hash-chained decision receipt. The receipt's hash
   prefix is carried as the Helix order's `cid`. So the objective order the exchange recorded points
   back to exactly one signed decision. Tamper with the decision and its receipt hash changes, so the
   cid no longer matches the order on chain. Commit + chain + cid together turn "the agent obeyed its
   rules" from a promise into something a stranger can check.

The committed policy hash for this deployment is
`sha256:59991a59d3ffdc77948313df6ab495cc4124bc027f10fa1b8044fb9313efc83b`, taken over
`config/strategy.injective.json` (canonicalised: sorted keys, whitespace stripped, `_`-prefixed keys
dropped). That config is frozen; changing it requires re-publishing the commit.

## Verified on-chain artifacts (Injective EVM testnet, chain 1439)

| What | Identifier |
|---|---|
| Commit-reveal tx | `a3c8707bf53621eb98a5f5d616b3c708b1a9434ca74ee2328fbfd8eb31b53484` |
| Real bound BUY tx | `d31ba264e47d10c714ae166e072d0e8b814b44636dd475bf762ab979ce964db7` |
| BUY order hash | `0x80041737f38a8dd57e09771376fa3517e5ddbcb1965acb27bb404f99eebc2ac8` |
| BUY cid == receipt #0 prefix | `299b3af44f0570b926d0afdbc3ae63a4` |
| Earlier bound SELL tx | `c7a9ab47d584f932757b349cbc7fd14f006159fa9c4006e8539c7566243ed06e` |

Cross-check any order: read its `SpotMarketOrderPlaced` event `cid` on the explorer, then confirm it
equals the first 32 hex of the matching receipt's hash in `receipts.jsonl`. `verify_live` does this
for the whole run at once.

> Explorer domain for the EVM testnet is still being finalised; the dashboard's tx links use
> `INJ_EXPLORER_TX` (default `https://testnet.blockscout.injective.network/tx/`). Set that env var if
> the canonical domain differs.

## Reproduce the run

All Injective-specific defaults in the code are MAINNET values, so the testnet env must be set
explicitly. Put the testnet wiring in a sourced env file (wallet key is read from the gitignored
keystore at `contracts/injective/.testnet_wallet.json`, never printed):

```sh
export INJ_RPC="https://k8s.testnet.json-rpc.injective.network/"
export INJ_CHAIN_ID="1439"
export INJ_EXECUTOR_ADDRESS="0xC15fC0c5E10bdc4aa5E8C8693ae6c3C9e99107e1"
export INJ_DENOM_USDT="peggy0x87aB3B4C8661e07D6372361211B96ed4Dc36B1B5"
export INJ_SPOT_MARKET_INJ_USDT="0x0611780ba69656949525013d947713300f56c37b6175e02f26bffa495c3208fe"
export INJ_INDEXER_URL="https://k8s.testnet.exchange.grpc-web.injective.network"
export STRATEGY_CONFIG="config/strategy.injective.json"
export EXECUTION_BACKEND="injective"
export AGENT_WALLET_ADDRESS="$(python3 -c "import json;print(json.load(open('contracts/injective/.testnet_wallet.json'))[0]['address'])")"
export AGENT_WALLET_PRIVATE_KEY="$(python3 -c "import json;print(json.load(open('contracts/injective/.testnet_wallet.json'))[0]['private_key'])")"
export SUMPLUS_DATA_DIR="$PWD/.demo_injective"   # isolate this run's receipt chain
```

1. **Publish the commit** (skip if the config is unchanged — the hash above is already on chain):
   ```sh
   python -m agent.identity.commit_publish --chain injective --send
   ```

2. **Run the agent over the demo tape.** `tools/inj_demo_run.py` drives the exact production path
   (reconcile-first from the SpotExecutor subaccount → `core.tick` → cid-bound order → execution log)
   on a cadence we control, over a scripted INJ tape. The committed policy is loaded and enforced
   unchanged; only the timing and the market the brain sees are scripted, exactly as the backtester
   does. Dry first, then live:
   ```sh
   python -m tools.inj_demo_run --ticks 10 --interval 2          # dry: no on-chain tx
   python -m tools.inj_demo_run --ticks 14 --interval 90 --live  # real Helix orders
   ```
   The tape is a mild INJ uptrend (an ENTER that buys to the 20% exposure cap), then a plateau where
   new entries are held or rate-limited (restraint, logged), then a take-profit spike that exits the
   position. The `min_trade_interval` of 900s means a second on-chain order lands ~15 minutes after
   the first — visible in the feed as `reject: rate limit ... < 900s` until the window clears.

3. **Verify the whole run** (the on-camera moment):
   ```sh
   python -m agent.policy.commit
   ```
   Expect `chain_intact: true`, `all_reference_committed_hash: true`, `executions_bound: true`,
   `executions_bad: []`.

4. **Dashboard:**
   ```sh
   python -m agent.cli web 8801   # http://127.0.0.1:8801
   ```
   The header reads "on Injective (Helix)", the verify banner shows the committed hash, and the
   **On-chain bound orders** panel lists each Helix order with its `cid == receipt` badge and an
   explorer link. Click any receipt in the decision feed to replay its hash deterministically.

## One-command recording

`tools/inj_demo_record.sh` is a read-only, no-key walkthrough for the screen recording: it opens the
dashboard, then narrates the commit hash, `verify_live`, the cid==receipt bindings, and a live
on-chain cross-check, with captions and pauses so no voiceover or clicking is needed. It reads the
committed artifacts in `demo/injective/` (a real testnet run, see `demo/injective/README.md`), so it
works on a fresh clone:

```sh
bash tools/inj_demo_record.sh   # ~2.5 min, self-paced
```

## Why the agent only trades ~1 USD at a time

The testnet subaccount holds a small NAV, and the committed config caps risky exposure at 20% with a
1 USDT Helix minimum notional. The verifiable property is identical at any size: the point of the
demo is that each decision is checkable, not that the position is large.
