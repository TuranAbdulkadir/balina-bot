import asyncio
try:
    import orjson as json
except ImportError:
    import json

from core.logger_factory import get_logger
import aiohttp

logger = get_logger("WsClient")

class BinanceWsClient:
    """WebSocket Client for Binance Futures with Multi-Stream and explicitly handling Ping/Pong."""
    
    def __init__(self, streams: list[str], base_url: str = "wss://fstream.binance.com/stream"):
        self.streams = streams
        self.base_url = base_url
        self.url = f"{self.base_url}?streams={'/'.join(self.streams)}"
        self._session = None
        self._ws = None
        self.on_message_callback = None

    async def switch_streams(self, new_streams: list[str]):
        """AŞAMA 16: Dinamik sembol degisimi icin streamleri gunceller ve baglantiyi keser (otomatik yeniden baglanir)"""
        self.streams = new_streams
        self.url = f"{self.base_url}?streams={'/'.join(self.streams)}"
        if self._ws and not self._ws.closed:
            await self._ws.close()
            logger.info("WS baglantisi bilerek kesildi, yeni streamler ile yeniden baglanilacak...")

    async def connect_and_listen(self):
        self._session = aiohttp.ClientSession()
        
        retry_delay = 1.0
        max_delay = 60.0
        
        while True:
            try:
                logger.info(f"Connecting to WS: {self.url}")
                # autoping=False to manually control ping/pong if necessary, but aiohttp's autoping
                # handles control frames automatically. Binance also uses application-level ping-pong.
                async with self._session.ws_connect(
                    self.url,
                    receive_timeout=30.0,
                    autoping=True,
                    heartbeat=15.0  # Application level keep-alive
                ) as ws:
                    self._ws = ws
                    logger.info("WebSocket connected successfully.")
                    retry_delay = 1.0  # Reset backoff on success
                    
                    async for msg in ws:
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            try:
                                data = json.loads(msg.data)
                                # Handle Binance application-level ping-pong (ping in payload)
                                if "ping" in data:
                                    await ws.send_json({"pong": data["ping"]})
                                    continue
                                
                                # Standard stream payload processing
                                if self.on_message_callback:
                                    await self.on_message_callback(data)
                            except json.JSONDecodeError as je:
                                logger.error(f"WS JSON Decode Error: {je}")
                            except Exception as e:
                                logger.error(f"WS Callback Error: {e}")
                        elif msg.type == aiohttp.WSMsgType.ERROR:
                            logger.error(f"WS connection closed with exception {ws.exception()}")
                            break
                        elif msg.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSED):
                            logger.warning(f"WS connection closed by server.")
                            break
            except asyncio.CancelledError:
                logger.info("WS connection task cancelled.")
                break
            except Exception as e:
                logger.error(f"WebSocket error: {e}")
            
            logger.warning(f"Reconnecting WS in {retry_delay} seconds...")
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
