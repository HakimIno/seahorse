import logging
from typing import Any

from seahorse_ai.tools.base import tool
from seahorse_ai.tools.trading.ibkr_client import HAS_IB_INSYNC, ibkr_manager

logger = logging.getLogger(__name__)


@tool("Get the current live bid/ask/last price for a Futures contract from Interactive Brokers.")
async def get_futures_live_price(
    symbol: str, expiry: str = "", exchange: str = "CME"
) -> dict[str, Any]:
    """Get the current live bid/ask/last price for a Futures contract (e.g., 'ES', 'NQ') from Interactive Brokers.
    Specify expiry mainly for specific months like '202312', otherwise the continuous front-month contract will be used."""
    if not HAS_IB_INSYNC:
        return {"error": "ib_insync package not installed. Cannot connect to IBKR."}

    try:
        from ib_insync import ContFuture, Future

        ib = await ibkr_manager.get_connection()

        if expiry:
            contract = Future(symbol, expiry, exchange)
        else:
            # Continuous (front month)
            contract = ContFuture(symbol, exchange)

        await ib.qualifyContractsAsync(contract)

        # Request market data stream
        ticker = ib.reqMktData(contract, "", False, False)
        import asyncio

        # Wait up to 5 seconds for data
        for _ in range(50):
            if ticker.last or ticker.bid or ticker.ask:
                break
            await asyncio.sleep(0.1)

        ib.cancelMktData(contract)

        return {
            "symbol": symbol,
            "exchange": exchange,
            "bid": ticker.bid,
            "ask": ticker.ask,
            "last": ticker.last,
            "volume": ticker.volume,
            "high": ticker.high,
            "low": ticker.low,
            "close": ticker.close,
        }
    except Exception as e:
        logger.error(f"IBKR get_futures_live_price error: {e}")
        return {"error": str(e)}


@tool("Get the Level 2 Market Depth (Order Book) for a given Futures contract.")
async def get_futures_market_depth(
    symbol: str, exchange: str = "CME", rows: int = 5
) -> dict[str, Any]:
    """Get the Level 2 Market Depth (Order Book) for a given Futures contract to gauge immediate Order Flow.
    Requires Level 2 market data subscriptions in your IBKR account."""
    if not HAS_IB_INSYNC:
        return {"error": "ib_insync missing."}

    try:
        from ib_insync import ContFuture

        ib = await ibkr_manager.get_connection()
        contract = ContFuture(symbol, exchange)
        await ib.qualifyContractsAsync(contract)

        # Subscribe to order book depth
        ticker = ib.reqMktDepth(contract, numRows=rows)
        import asyncio

        await asyncio.sleep(1.0)  # Wait a moment for depth book to populate

        ib.cancelMktDepth(contract)

        bids = [{"price": b.price, "size": b.size} for b in ticker.domBids]
        asks = [{"price": a.price, "size": a.size} for a in ticker.domAsks]

        bids_vol = sum(b["size"] for b in bids)
        asks_vol = sum(a["size"] for a in asks)
        pressure = "Buying (Bids > Asks)" if bids_vol > asks_vol else "Selling (Asks > Bids)"

        return {
            "symbol": symbol,
            "book_depth": rows,
            "dominant_pressure": pressure,
            "bids_volume": bids_vol,
            "asks_volume": asks_vol,
            "bids_distribution": bids,
            "asks_distribution": asks,
        }
    except Exception as e:
        return {"error": str(e)}


@tool(
    "Get the current live bid/ask/last price for a Stock (e.g., 'AAPL', 'TSLA') from Interactive Brokers."
)
async def get_stock_live_price(
    symbol: str, exchange: str = "SMART", currency: str = "USD"
) -> dict[str, Any]:
    """Get real-time price for a Stock.
    - symbol: e.g., 'AAPL'
    - exchange: 'SMART' is recommended for best execution.
    """
    if not HAS_IB_INSYNC:
        return {"error": "ib_insync missing."}
    try:
        from ib_insync import Stock

        ib = await ibkr_manager.get_connection()
        contract = Stock(symbol, exchange, currency)
        await ib.qualifyContractsAsync(contract)

        ticker = ib.reqMktData(contract, "", False, False)
        import asyncio

        for _ in range(50):
            if ticker.last or ticker.bid or ticker.ask:
                break
            await asyncio.sleep(0.1)
        ib.cancelMktData(contract)

        return {
            "symbol": symbol,
            "last": ticker.last,
            "bid": ticker.bid,
            "ask": ticker.ask,
            "close": ticker.close,
        }
    except Exception as e:
        return {"error": str(e)}


@tool("Get the current live bid/ask/last price for a Forex pair (e.g., 'EURUSD').")
async def get_forex_live_price(symbol: str, currency: str = "USD") -> dict[str, Any]:
    """Get real-time price for a Forex pair.
    - symbol: e.g., 'EUR'
    - currency: e.g., 'USD' for EURUSD
    """
    if not HAS_IB_INSYNC:
        return {"error": "ib_insync missing."}
    try:
        from ib_insync import Forex

        ib = await ibkr_manager.get_connection()
        # IBKR Forex symbol is usually the base currency, and currency is the quote
        contract = Forex(f"{symbol}{currency}")
        await ib.qualifyContractsAsync(contract)

        ticker = ib.reqMktData(contract, "", False, False)
        import asyncio

        for _ in range(50):
            if ticker.last or ticker.bid or ticker.ask:
                break
            await asyncio.sleep(0.1)
        ib.cancelMktData(contract)

        return {
            "pair": f"{symbol}{currency}",
            "last": ticker.last or (ticker.bid + ticker.ask) / 2
            if (ticker.bid and ticker.ask)
            else None,
            "bid": ticker.bid,
            "ask": ticker.ask,
        }
    except Exception as e:
        return {"error": str(e)}
