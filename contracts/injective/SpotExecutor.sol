// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "./IExchange.sol";

/// @title SpotExecutor
/// @notice Thin, owner-gated execution contract for the Sumplus trading agent on
/// Injective native EVM. It trades the agent's OWN capital on Helix spot markets
/// via the Exchange precompile (0x65) using the "direct access" pattern: the
/// contract is the sender, so it manages only its own subaccount and needs NO
/// authz grant.
///
/// This is the Injective analogue of the BSC TWAK swap path. The decision authority
/// (Maria's policy engine) and the verifiable layer (commit-reveal strategy hash +
/// hash-chained receipts) live OFF-chain and are unchanged; this contract is just
/// the on-chain hands that place an already-approved order.
///
/// Funds custody: capital sits in this contract's exchange subaccount. Only `owner`
/// (the agent's dedicated EOA) can move it or trade. `withdraw` returns funds from
/// the subaccount to the contract's bank balance; recovery to the owner is an
/// owner-only operation (see contracts/injective/README.md).
contract SpotExecutor {
    address public constant EXCHANGE = 0x0000000000000000000000000000000000000065;
    IExchangeModule constant exchange = IExchangeModule(EXCHANGE);

    address public owner;

    event Deposited(string subaccountID, string denom, uint256 amount);
    event Withdrawn(string subaccountID, string denom, uint256 amount);
    // Order PLACEMENT, not fill. Injective matches spot orders in a batch at end-of-block, so the
    // precompile's synchronous return carries no fill. This event records the on-chain commitment:
    // the orderHash plus the cid (our hash-chained receipt id) links the committed decision to the
    // order. The actual fill is objective chain state — read from the subaccount by the reconcile
    // loop, and from the exchange trade record (keyed by orderHash) by anyone verifying.
    event SpotMarketOrderPlaced(
        string orderHash,
        string marketID,
        string orderType,
        uint256 price,
        uint256 quantity,
        string cid
    );
    event OwnerTransferred(address indexed previousOwner, address indexed newOwner);

    modifier onlyOwner() {
        require(msg.sender == owner, "SpotExecutor: not owner");
        _;
    }

    constructor() {
        owner = msg.sender;
        emit OwnerTransferred(address(0), msg.sender);
    }

    /// @notice Accept native INJ so the owner can fund the contract's bank balance with a
    /// plain value transfer (INJ is unified with the bank `inj` denom on Injective). From
    /// there, `deposit("inj", ...)` moves it into the exchange subaccount.
    receive() external payable {}

    function transferOwnership(address newOwner) external onlyOwner {
        require(newOwner != address(0), "SpotExecutor: zero owner");
        emit OwnerTransferred(owner, newOwner);
        owner = newOwner;
    }

    /// @notice Move funds from this contract's bank balance into its exchange subaccount.
    /// @param amount CHAIN FORMAT (native token decimals: USDT 6, INJ 18).
    function deposit(
        string calldata subaccountID,
        string calldata denom,
        uint256 amount
    ) external onlyOwner returns (bool) {
        try exchange.deposit(address(this), subaccountID, denom, amount) returns (bool ok) {
            emit Deposited(subaccountID, denom, amount);
            return ok;
        } catch Error(string memory reason) {
            revert(string(abi.encodePacked("SpotExecutor.deposit: ", reason)));
        } catch {
            revert("SpotExecutor.deposit: unknown error");
        }
    }

    /// @notice Move funds from the exchange subaccount back to this contract's bank balance.
    function withdraw(
        string calldata subaccountID,
        string calldata denom,
        uint256 amount
    ) external onlyOwner returns (bool) {
        try exchange.withdraw(address(this), subaccountID, denom, amount) returns (bool ok) {
            emit Withdrawn(subaccountID, denom, amount);
            return ok;
        } catch Error(string memory reason) {
            revert(string(abi.encodePacked("SpotExecutor.withdraw: ", reason)));
        } catch {
            revert("SpotExecutor.withdraw: unknown error");
        }
    }

    /// @notice Place a spot MARKET order on Helix from this contract's subaccount.
    /// @param marketID   Helix spot market id (e.g. INJ/USDT).
    /// @param subaccountID This contract's subaccount (address + 24-hex index).
    /// @param feeRecipient bech32 inj address for fee rebate, or "" for default.
    /// @param price      Worst acceptable price as UFixed256x18 (slippage bound).
    ///                   Market buy: max price to pay. Market sell: min price to accept.
    /// @param quantity   BASE asset amount as UFixed256x18 (e.g. INJ count).
    /// @param cid        Client order id; we pass our receipt hash for on-chain traceability.
    /// @param orderType  "buy" or "sell".
    /// @return orderHash The exchange order hash, echoed in the event.
    function placeSpotMarketOrder(
        string calldata marketID,
        string calldata subaccountID,
        string calldata feeRecipient,
        uint256 price,
        uint256 quantity,
        string calldata cid,
        string calldata orderType
    ) external onlyOwner returns (string memory orderHash) {
        IExchangeModule.SpotOrder memory order = IExchangeModule.SpotOrder({
            marketID: marketID,
            subaccountID: subaccountID,
            feeRecipient: feeRecipient,
            price: ExchangeTypes.UFixed256x18.wrap(price),
            quantity: ExchangeTypes.UFixed256x18.wrap(quantity),
            cid: cid,
            orderType: orderType,
            triggerPrice: ExchangeTypes.UFixed256x18.wrap(0)
        });

        try exchange.createSpotMarketOrder(address(this), order) returns (
            IExchangeModule.CreateSpotMarketOrderResponse memory resp
        ) {
            emit SpotMarketOrderPlaced(resp.orderHash, marketID, orderType, price, quantity, cid);
            return resp.orderHash;
        } catch Error(string memory reason) {
            revert(string(abi.encodePacked("SpotExecutor.placeSpotMarketOrder: ", reason)));
        } catch {
            revert("SpotExecutor.placeSpotMarketOrder: unknown error");
        }
    }

    event SpotLimitOrderPlaced(
        string orderHash,
        string marketID,
        string orderType,
        uint256 price,
        uint256 quantity,
        string cid
    );

    /// @notice Place a spot LIMIT order on Helix from this contract's subaccount. Same
    /// arg shape as the market order; rests on the book and locks margin until filled or
    /// cancelled. Useful for passive entries and (on an empty book) for verifying the
    /// quantity/price encoding by observing locked balance.
    function placeSpotLimitOrder(
        string calldata marketID,
        string calldata subaccountID,
        string calldata feeRecipient,
        uint256 price,
        uint256 quantity,
        string calldata cid,
        string calldata orderType
    ) external onlyOwner returns (string memory orderHash) {
        IExchangeModule.SpotOrder memory order = IExchangeModule.SpotOrder({
            marketID: marketID,
            subaccountID: subaccountID,
            feeRecipient: feeRecipient,
            price: ExchangeTypes.UFixed256x18.wrap(price),
            quantity: ExchangeTypes.UFixed256x18.wrap(quantity),
            cid: cid,
            orderType: orderType,
            triggerPrice: ExchangeTypes.UFixed256x18.wrap(0)
        });

        try exchange.createSpotLimitOrder(address(this), order) returns (
            IExchangeModule.CreateSpotLimitOrderResponse memory resp
        ) {
            emit SpotLimitOrderPlaced(resp.orderHash, marketID, orderType, price, quantity, cid);
            return resp.orderHash;
        } catch Error(string memory reason) {
            revert(string(abi.encodePacked("SpotExecutor.placeSpotLimitOrder: ", reason)));
        } catch {
            revert("SpotExecutor.placeSpotLimitOrder: unknown error");
        }
    }

    /// @notice Read this contract's available + total balance for a denom in a subaccount.
    /// The reconcile loop treats this as the on-chain truth source for NAV.
    function subaccountBalance(
        string calldata subaccountID,
        string calldata denom
    ) external view returns (uint256 available, uint256 total) {
        return exchange.subaccountDeposit(subaccountID, denom);
    }
}
