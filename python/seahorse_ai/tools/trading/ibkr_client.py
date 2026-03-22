import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Try to import ib_insync, but don't crash if it's not installed yet
try:
    from ib_insync import IB

    HAS_IB_INSYNC = True
except ImportError:
    HAS_IB_INSYNC = False
    logger.warning(
        "ib_insync is not installed. IBKR features will be mock/disabled. Run: pip install ib_insync"
    )


class IBKRClientManager:
    """Singleton manager for the Interactive Brokers connection."""

    _instance: Optional["IBKRClientManager"] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._ib = None
            cls._instance._is_connected = False
        return cls._instance

    async def get_connection(self):
        """Returns the active IB connection or connects if unavailable."""
        if not HAS_IB_INSYNC:
            raise ImportError(
                "ib_insync is required for Interactive Brokers integration. Please run `pip install ib_insync`."
            )

        if self._ib is None:
            self._ib = IB()

        if not self._ib.isConnected():
            logger.info(
                "IBKR: Attempting to connect to TWS/Gateway on 127.0.0.1:4002 (Paper Trading)..."
            )
            try:
                # 4002 is default for IB Gateway Paper. TWS Paper is 7497. TWS Live is 7496. Gateway Live is 4001.
                # clientId=1 is standard, but must be unique per connected application.
                import ib_insync.util

                ib_insync.util.patchAsyncio()
                await self._ib.connectAsync("127.0.0.1", 4002, clientId=1)
                self._is_connected = True
                logger.info("IBKR: Connected successfully.")
            except Exception as e:
                logger.error(f"IBKR Connection failed: {e}")
                raise ConnectionError(
                    f"Could not connect to IBKR TWS/Gateway on port 4002/7497. Is it running? Error: {e}"
                ) from e

        return self._ib

    def disconnect(self):
        if self._ib and self._ib.isConnected():
            self._ib.disconnect()
            self._is_connected = False
            logger.info("IBKR: Disconnected.")


# Global instance
ibkr_manager = IBKRClientManager()
