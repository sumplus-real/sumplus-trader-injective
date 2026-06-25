# Injective spot execution layer

The on-chain hands for the Sumplus trading agent on **Injective native EVM** (chain
1776, 0.64s finality). Everything else in the agent — the policy engine, the
commit-reveal strategy hash, the hash-chained receipts, the CMC data feed, the
watchdog — is chain-agnostic and unchanged. This directory is the only chain-specific
new work for the Injective port.

## Why a contract (and not just an EOA)

On Injective, spot trades go through the **Exchange precompile** at
`0x0000000000000000000000000000000000000065` (Helix is an order book, not an AMM). An
EOA cannot call the precompile directly. The official pattern (`exchange-direct`) is a
contract that trades from **its own subaccount** as `sender = address(this)`, which
needs no authz grant. `SpotExecutor` is that contract, kept thin and `onlyOwner`.

- `IExchange.sol` — minimal vendored slice of the precompile interface (spot only).
- `SpotExecutor.sol` — deposit / withdraw / `placeSpotMarketOrder` / read subaccount,
  all owner-gated, with the agent's receipt hash carried as the order `cid`.

## Number formats (easy to get wrong)

- **CHAIN FORMAT** (native decimals) for `deposit` / `withdraw` amounts and subaccount
  balance reads. USDT = 6 decimals, INJ = 18.
- **API FORMAT** = `UFixed256x18`, the human value × 1e18, for order `price` and
  `quantity`, regardless of token decimals.

`agent/ops/injective_market.py` holds both converters plus the subaccount-id builder
(`address + 24-hex index`) and the spot market-id registry.

## Spot market order semantics

A spot **market buy** of INJ/USDT takes `quantity` in **base** units (INJ count) and
`price` as the **worst** acceptable price (slippage bound). `InjectiveBackend` sizes a
USD amount against the live Helix book: `quantity = usd / ref_price`,
`price = ref_price × (1 ± slippage)`. Market sell is the mirror. If the book is
unreachable it fails closed (the agent holds) rather than guessing a price.

## Build & deploy (testnet)

```sh
# 1. install Foundry: curl -L https://foundry.paradigm.xyz | bash && foundryup
cp .deploy.env.example .deploy.env      # fill in RPC, keystore account, denom
forge build
./deploy.sh                              # deploys + seeds the subaccount, prints env wiring
```

Then point the agent at it:

```sh
EXECUTION_BACKEND=injective
INJ_RPC=<testnet evm rpc>
INJ_EXECUTOR_ADDRESS=<deployed SpotExecutor>
INJ_SUBACCOUNT_INDEX=1
INJ_DENOM_USDT=<testnet USDT denom>
INJ_SPOT_MARKET_INJ_USDT=<testnet INJ/USDT spot market id>   # injectived q exchange spot-markets
```

`EXECUTION_BACKEND` defaults to dry-run until `INJ_RPC` + `INJ_EXECUTOR_ADDRESS` +
`AGENT_WALLET_PRIVATE_KEY` are all set, so the full loop runs offline with zero keys.

## Testnet validation (2026-06-25, on-chain)

The full path was exercised on Injective EVM testnet (chain 1439) with real
transactions, not a simulation:

- Deployed `SpotExecutor`, funded it with INJ (plain EVM transfer into the contract's
  bank balance via `receive()`), deposited into its exchange subaccount, read the
  balance back. All worked.
- **`quantity` is base (token count) for both sides — measured by the locked balance:**
  - SELL limit `quantity = 0.1 INJ`: subaccount INJ available dropped from 0.25 to
    exactly 0.15, locking the 0.1 INJ specified.
  - BUY limit `quantity = 2, price = 1.5`: subaccount USDT available dropped from 5 to
    exactly 2, locking 3 USDT = `quantity × price`. A quote-denominated quantity would
    have locked 2 USDT; it locked 3. So buy `quantity` is base, and
    `InjectiveBackend`'s `quantity = usd / price` sizing is correct for both sides.

Verified testnet values (mainnet differs — re-pull before mainnet):

- RPC `https://k8s.testnet.json-rpc.injective.network/`, chain id `1439`
- INJ/USDT spot market `0x0611780ba69656949525013d947713300f56c37b6175e02f26bffa495c3208fe`
- USDT denom `peggy0x87aB3B4C8661e07D6372361211B96ed4Dc36B1B5` (6 decimals)

Architecture note: an EOA can call the Exchange precompile (0x65) directly for its own
subaccount (deposit + place order both succeed), so the contract is not strictly
required to trade. The contract is kept for the on-chain execution events
(`SpotMarketOrderResult` carries the actual fill), owner gating, and the self-custodial
vault model — the verifiable-execution anchor we want on-chain.

## Still to do before mainnet (real money)

- Re-pull `INJ_SPOT_MARKET_INJ_USDT` + `INJ_DENOM_USDT` for mainnet (the committed
  defaults are mainnet, but confirm against `injectived q exchange spot-markets`).
- Redeploy from the production agent wallet (the testnet run used a throwaway wallet).
- Funds recovery: `withdraw` returns subaccount funds to the contract's bank balance;
  sweeping back to the owner EOA is an owner-only bank send (add if needed).
