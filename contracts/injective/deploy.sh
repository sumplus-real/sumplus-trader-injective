#!/bin/sh
# Deploy SpotExecutor to Injective native EVM, compute its subaccount, and seed it
# with quote (USDT) so the agent can place its first spot market order.
#
# Adapted from InjectiveLabs/solidity-contracts demos/exchange-direct/demo.sh.
# Requires Foundry (forge/cast). Reads ./.deploy.env (see .deploy.env.example).
set -e

if [ -f ./.deploy.env ]; then
    . ./.deploy.env
else
    echo "Error: .deploy.env not found (copy .deploy.env.example)"; exit 1
fi

echo "1) Building..."
forge build >/dev/null

echo "2) Deploying SpotExecutor..."
create_res=$(forge create SpotExecutor.sol:SpotExecutor \
    -r "$ETH_URL" \
    --account "$DEPLOYER_ACCOUNT" --password "$DEPLOYER_PWD" \
    --gas-limit "$GAS_LIMIT" --gas-price "$GAS_PRICE" \
    --broadcast --legacy --json)
contract=$(echo "$create_res" | jq -r '.deployedTo')
subaccount="${contract}$(printf '%024x' "$SUBACCOUNT_INDEX")"
echo "   SpotExecutor: $contract"
echo "   subaccount:   $subaccount"

echo "3) Funding contract bank balance (send $DEPOSIT_AMOUNT $QUOTE_DENOM to $contract)..."
echo "   NOTE: send quote to the contract's INJECTIVE bank address first."
echo "   inj address: $(injectived q exchange inj-address-from-eth-address "$contract" 2>/dev/null || echo '<run injectived to resolve>')"

echo "4) deposit() into the contract's exchange subaccount..."
cast send -r "$ETH_URL" \
    --account "$DEPLOYER_ACCOUNT" --password "$DEPLOYER_PWD" \
    --gas-limit "$GAS_LIMIT" --gas-price "$GAS_PRICE" --legacy \
    "$contract" "deposit(string,string,uint256)" \
    "$subaccount" "$QUOTE_DENOM" "$DEPOSIT_AMOUNT"

echo ""
echo "Done. Wire the agent:"
echo "  EXECUTION_BACKEND=injective"
echo "  INJ_EXECUTOR_ADDRESS=$contract"
echo "  INJ_SUBACCOUNT_INDEX=$SUBACCOUNT_INDEX"
echo "  INJ_RPC=$ETH_URL"
echo "  INJ_DENOM_USDT=$QUOTE_DENOM"
echo "  INJ_SPOT_MARKET_INJ_USDT=<testnet INJ/USDT spot market id>"
