import logging
from typing import Any

from seahorse_ai.tools.base import tool
from seahorse_ai.tools.trading.ibkr_client import HAS_IB_INSYNC, ibkr_manager

logger = logging.getLogger(__name__)


@tool(
    "Fetch the real-time Net Liquidation Value, Buying Power, and Margin from the connected Interactive Brokers account."
)
async def get_ibkr_account_summary() -> dict[str, Any]:
    """Fetch the real-time Net Liquidation Value, Buying Power, and Margin from the connected Interactive Brokers account."""
    if not HAS_IB_INSYNC:
        return {"error": "ib_insync package not installed. Cannot connect to IBKR."}

    try:
        ib = await ibkr_manager.get_connection()
        summary = await ib.accountSummaryAsync()

        result = {}
        for item in summary:
            if item.tag in (
                "NetLiquidation",
                "AvailableFunds",
                "MaintMarginReq",
                "GrossPositionValue",
            ):
                result[item.tag] = {"value": float(item.value), "currency": item.currency}

        return result if result else {"error": "No account summary data returned from IBKR."}
    except Exception as e:
        logger.error(f"IBKR get_ibkr_account_summary error: {e}")
        return {"error": str(e)}


@tool("Fetch all currently open positions in the Interactive Brokers account.")
async def get_ibkr_open_positions() -> dict[str, Any]:
    """Fetch all currently open positions in the Interactive Brokers account."""
    if not HAS_IB_INSYNC:
        return {"error": "ib_insync missing."}

    try:
        ib = await ibkr_manager.get_connection()
        positions = await ib.positionsAsync()

        if not positions:
            return {"status": "No open positions"}

        pos_list = []
        for p in positions:
            pos_list.append(
                {
                    "symbol": p.contract.symbol,
                    "secType": p.contract.secType,
                    "position": float(p.position),
                    "avgCost": float(p.avgCost),
                }
            )

        return {"total_positions": len(pos_list), "positions": pos_list}
    except Exception as e:
        return {"error": str(e)}


@tool("Execute a Market Order on Interactive Brokers. Requires explicit human confirmation.")
async def place_ibkr_order(
    symbol: str,
    action: str,
    quantity: float,
    secType: str = "CASH",
    exchange: str = "IDEALPRO",
    currency: str = "USD",
) -> dict[str, Any]:
    """Execute a Market Order for Stock (STK), Forex (CASH), or Futures (FUT).
    Inputs:
    - symbol: e.g., 'EUR' (for EURUSD), 'AAPL', 'ES'
    - action: 'BUY' or 'SELL'
    - quantity: Number of units or lots
    - secType: 'STK', 'CASH', 'FUT'
    - exchange: 'IDEALPRO' (Forex), 'SMART' (Stocks), 'CME' (Futures)
    - currency: 'USD', 'EUR', etc.
    """
    if not HAS_IB_INSYNC:
        return {"error": "ib_insync package not installed."}

    try:
        from ib_insync import Forex, Future, MarketOrder, Stock

        ib = await ibkr_manager.get_connection()

        # Define contract based on secType
        if secType == "STK":
            contract = Stock(symbol, exchange, currency)
        elif secType == "CASH":
            contract = Forex(f"{symbol}{currency}")
        elif secType == "FUT":
            contract = Future(symbol, exchange=exchange, currency=currency)
        else:
            return {"error": f"Unsupported secType: {secType}"}

        await ib.qualifyContractsAsync(contract)

        # Create and place order
        order = MarketOrder(action, quantity)
        trade = ib.placeOrder(contract, order)

        # Wait a few seconds for execution
        import asyncio

        for _ in range(30):
            if trade.isDone():
                break
            await asyncio.sleep(0.1)

        # Check for Common Error 321 (Read-Only)
        for log in trade.log:
            if "Read-Only mode" in log.message or "321" in str(log.errorCode):
                return {
                    "status": "FAILED",
                    "reason": "IBKR is in Read-Only mode. Please go to TWS/Gateway -> Settings -> API and uncheck 'Read-Only API' to allow trading.",
                    "log": log.message,
                }

        return {
            "status": trade.orderStatus.status,
            "orderId": trade.order.orderId,
            "filled": trade.orderStatus.filled,
            "avgFillPrice": trade.orderStatus.avgFillPrice,
            "remaining": trade.orderStatus.remaining,
        }
    except Exception as e:
        logger.error(f"IBKR place_ibkr_order error: {e}")
        return {"error": str(e)}
