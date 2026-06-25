// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

// Minimal vendored interface for the Injective Exchange precompile (0x65).
// Only the spot-trading surface SpotExecutor needs is declared here, copied
// verbatim from InjectiveLabs/solidity-contracts (src/Exchange.sol +
// src/ExchangeTypes.sol). Vendoring the slice keeps the contract self-contained
// (no foundry lib dependency on the full injective package).

library ExchangeTypes {
    /// @dev Fixed-point decimal with 18 places. Order price/quantity are passed
    /// in API FORMAT: the human value scaled by 10^18 (e.g. "1.5" -> 1.5e18).
    /// deposit/withdraw amounts use CHAIN FORMAT instead (native token decimals).
    type UFixed256x18 is uint256;
}

interface IExchangeModule {
    struct SpotOrder {
        string marketID;
        string subaccountID;
        string feeRecipient;
        ExchangeTypes.UFixed256x18 price;
        ExchangeTypes.UFixed256x18 quantity;
        string cid;
        string orderType; // "buy" | "sell" | "buyPO" | "sellPO" | "takeProfit" | ...
        ExchangeTypes.UFixed256x18 triggerPrice;
    }

    struct CreateSpotMarketOrderResponse {
        string orderHash;
        string cid;
        ExchangeTypes.UFixed256x18 quantity;
        ExchangeTypes.UFixed256x18 price;
        ExchangeTypes.UFixed256x18 fee;
    }

    struct CreateSpotLimitOrderResponse {
        string orderHash;
        string cid;
    }

    function deposit(
        address sender,
        string calldata subaccountID,
        string calldata denom,
        uint256 amount
    ) external returns (bool success);

    function withdraw(
        address sender,
        string calldata subaccountID,
        string calldata denom,
        uint256 amount
    ) external returns (bool success);

    function subaccountDeposit(
        string calldata subaccountID,
        string calldata denom
    ) external view returns (uint256 availableBalance, uint256 totalBalance);

    function createSpotMarketOrder(
        address sender,
        SpotOrder calldata order
    ) external returns (CreateSpotMarketOrderResponse memory response);

    function createSpotLimitOrder(
        address sender,
        SpotOrder calldata order
    ) external returns (CreateSpotLimitOrderResponse memory response);
}
