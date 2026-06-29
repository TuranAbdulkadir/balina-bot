import asyncio
try:
    import orjson as json
except ImportError:
    import json

from core.logger_factory import get_logger
import aiohttp
from network.http_client import BinanceRestClient

logger = get_logger("UserWs")

class UserDataStream:
    """Listens to Binance Futures user data stream via ListenKey."""
    def __init__(self, rest_client: BinanceRestClient, base_url: str = "wss://fstream.binance.com/ws"):
        self.rest_client = rest_client
        self.base_url = base_url
        self.listen_key = None
        self._session = None
        self._ws = None
        self.on_order_update = None
        self.on_account_update = None

    async def _get_listen_key(self) -> str:
        # POST /fapi/v1/listenKey
        res = await self.rest_client.post_signed("/fapi/v1/listenKey")
        return res.get("listenKey", "")

    async def _keep_alive_task(self):
        """Extends listenKey validity every 50 minutes."""
        while True:
            await asyncio.sleep(50 * 60) # 50 minutes
            max_retries = 5
            base_delay = 5.0
            
            for attempt in range(max_retries):
                try:
                    logger.info("Renewing ListenKey (Keep-Alive)...")
                    # PUT /fapi/v1/listenKey
                    await self.rest_client.put_signed("/fapi/v1/listenKey")
                    logger.info("ListenKey renewed successfully.")
                    break
                except Exception as e:
                    logger.warning(f"ListenKey renewal failed (attempt {attempt+1}/{max_retries}): {e}")
                    if attempt < max_retries - 1:
                        await asyncio.sleep(base_delay * (2 ** attempt))
                    else:
                        logger.critical("Failed to renew ListenKey! User Data Stream might disconnect.")
            
    async def connect_and_listen(self):
        self._session = aiohttp.ClientSession()
        retry_delay = 1.0
        max_delay = 60.0
        
        while True:
            try:
                self.listen_key = await self._get_listen_key()
                if not self.listen_key:
                    raise Exception("Failed to retrieve listen key!")
                    
                url = f"{self.base_url}/{self.listen_key}"
                logger.info("Connecting to User Data WS...")
                
                keep_alive = asyncio.create_task(self._keep_alive_task())
                
                async with self._session.ws_connect(
                    url,
                    receive_timeout=300.0,
                    autoping=True,
                    heartbeat=15.0
                ) as ws:
                    self._ws = ws
                    logger.info("User Data WebSocket connected successfully.")
                    retry_delay = 1.0
                    
                    async for msg in ws:
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            try:
                                data = json.loads(msg.data)
                                event_type = data.get("e")
                                
                                if event_type == "ORDER_TRADE_UPDATE":
                                    if self.on_order_update:
                                        await self.on_order_update(data)
                                elif event_type == "ACCOUNT_UPDATE":
                                    if self.on_account_update:
                                        await self.on_account_update(data)
                                elif event_type == "positionADLQuantileUpdate":
                                    if getattr(self, "on_adl_update", None):
                                        await self.on_adl_update(data)
                                elif "ping" in data:
                                    await ws.send_json({"pong": data["ping"]})
                                    
                            except json.JSONDecodeError as je:
                                logger.error(f"User WS JSON Error: {je}")
                            except Exception as e:
                                logger.error(f"User WS Callback Error: {e}")
                        elif msg.type in (aiohttp.WSMsgType.ERROR, aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSED):
                            break
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"User Data WebSocket error: {e}")
            finally:
                if 'keep_alive' in locals():
                    keep_alive.cancel()
                    
            logger.warning(f"Reconnecting User WS in {retry_delay} seconds...")
            try:
                import core.audit
                await core.audit.increment_audit("disconnect")
            except Exception:
                pass
            await asyncio.sleep(retry_delay)
            retry_delay = min(retry_delay * 2, max_delay)

    async def close(self):
        if self._ws and not self._ws.closed:
            await self._ws.close()
        if self._session and not self._session.closed:
            await self._session.close()
