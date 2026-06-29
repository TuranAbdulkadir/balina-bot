import aiohttp
import asyncio
import time
from core.logger_factory import get_logger

logger = get_logger("HttpClient")

try:
    import aiodns
except ImportError:
    aiodns = None

class BinanceRestClient:
    """REST Client for Binance Futures using aiohttp with aiodns resolver and Token Bucket."""
    
    def __init__(self, base_url: str = "https://fapi.binance.com"):
        self.base_url = base_url
        self._session = None
        self.local_weight_1m = 0
        self.last_weight_reset_time = int(time.time() // 60) * 60
        
        from network.auth import BinanceEd25519Auth
        self.auth = BinanceEd25519Auth()

    async def get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            connector_kwargs = {
                "limit": 100,
                "keepalive_timeout": 60,
                "force_close": False,
                "enable_cleanup_closed": True,
                "use_dns_cache": False
            }
            # if aiodns is not None:
            #     connector_kwargs["resolver"] = aiohttp.AsyncResolver()
            connector = aiohttp.TCPConnector(**connector_kwargs)
            self._session = aiohttp.ClientSession(connector=connector)
        return self._session

    async def time_sync_loop(self):
        """Monitors Binance Server Time adjusting local Ed25519 payload offsets mitigating Clock Drift."""
        logger.info("Clock drift synchronization online.")
        while True:
            try:
                # Direct request bypassing signed framework recursively
                session = await self.get_session()
                async with session.get(f"{self.base_url}/fapi/v1/time", timeout=5.0) as response:
                    if response.status == 200:
                        res = await response.json()
                        server_time = res["serverTime"]
                        local_time = int(time.time() * 1000)
                        self.auth.time_offset_ms = server_time - local_time
                        logger.info(f"Clock Drift Offset Adjusted: {self.auth.time_offset_ms}ms")
            except Exception as e:
                logger.error(f"Failed to sync clock offset: {e}")
            await asyncio.sleep(30 * 60)  # Pulse every 30 minutes

    async def _check_rate_limit(self, weight_cost: int = 1):
        """Monitors local weight expenditure and forces throttle before breaking Binance Futures 2400 Limit/min."""
        now = time.time()
        current_minute = int(now // 60) * 60
        
        if current_minute > self.last_weight_reset_time:
            self.local_weight_1m = 0
            self.last_weight_reset_time = current_minute
            
        if self.local_weight_1m + weight_cost >= 2300:
            sleep_duration = 60.0 - (now % 60.0)
            logger.warning(f"LOCAL TOKEN BUCKET LIMIT (2300) HIT! Halting requests for {sleep_duration:.2f}s... Preventing 429 Ban!")
            await asyncio.sleep(sleep_duration)
            self.local_weight_1m = 0
            self.last_weight_reset_time = int(time.time() // 60) * 60
            
        self.local_weight_1m += weight_cost

    async def _request_signed(self, method: str, endpoint: str, params: dict = None, weight_cost: int = 1) -> dict:
        await self._check_rate_limit(weight_cost)
        session = await self.get_session()
        params = params or {}
        signed_query = self.auth.sign_request_query(params)
        headers = self.auth.get_headers()
        url = f"{self.base_url}{endpoint}"
        
        try:
            async with session.request(method, url, data=signed_query, headers=headers) as response:
                # 4. Desync Risk: Sync internal weight tracker with live Binance headers
                used_weight_1m = response.headers.get('X-MBX-USED-WEIGHT-1M')
                if used_weight_1m and used_weight_1m.isdigit():
                    self.local_weight_1m = max(self.local_weight_1m, int(used_weight_1m))
                
                try:
                    res = await response.json()
                except Exception:
                    res = {"code": response.status, "msg": await response.text()}
                
                if response.status != 200 and res.get("code") not in (-4059, -4046):
                    logger.error(f"{method} {endpoint} failed: {res}")
                    response.raise_for_status()
                return res
        except (asyncio.TimeoutError, aiohttp.ClientError) as e:
            logger.error(f"Network Disconnect/Timeout detected on {method} {endpoint}: {e}")
            raise

    async def post_signed(self, endpoint: str, params: dict = None, weight_cost: int = 1) -> dict:
        return await self._request_signed("POST", endpoint, params, weight_cost)

    async def put_signed(self, endpoint: str, params: dict = None, weight_cost: int = 1) -> dict:
        return await self._request_signed("PUT", endpoint, params, weight_cost)
        
    async def delete_signed(self, endpoint: str, params: dict = None, weight_cost: int = 1) -> dict:
        return await self._request_signed("DELETE", endpoint, params, weight_cost)
        
    async def get_signed(self, endpoint: str, params: dict = None, weight_cost: int = 1) -> dict:
        await self._check_rate_limit(weight_cost)
        session = await self.get_session()
        params = params or {}
        signed_query = self.auth.sign_request_query(params)
        headers = self.auth.get_headers()
        url = f"{self.base_url}{endpoint}"
        
        query_str = signed_query
        
        async with session.get(f"{url}?{query_str}", headers=headers) as response:
            used_weight_1m = response.headers.get('X-MBX-USED-WEIGHT-1M')
            if used_weight_1m and used_weight_1m.isdigit():
                self.local_weight_1m = max(self.local_weight_1m, int(used_weight_1m))
                
            try:
                res = await response.json()
            except Exception:
                res = {"code": response.status, "msg": await response.text()}
            if response.status != 200:
                logger.error(f"GET {endpoint} failed: {res}")
                response.raise_for_status()
            return res

    async def get_depth_snapshot(self, symbol: str, limit: int = 1000) -> dict:
        """Fetch Limit Order Book snapshot. Uses weight=2"""
        await self._check_rate_limit(2)
        session = await self.get_session()
        url = f"{self.base_url}/fapi/v1/depth"
        params = {"symbol": symbol, "limit": limit}
        
        max_retries = 3
        base_delay = 1.0
        
        for attempt in range(max_retries):
            try:
                async with session.get(url, params=params, timeout=5.0) as response:
                    response.raise_for_status()
                    return await response.json()
            except Exception as e:
                logger.warning(f"Failed to fetch depth for {symbol} (attempt {attempt+1}/{max_retries}): {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(base_delay * (2 ** attempt))
                else:
                    raise

    async def get(self, endpoint: str, weight_cost: int = 1) -> dict | list:
        """Unsigned public GET (klines, exchangeInfo gibi imza gerektirmeyen endpointler icin)."""
        await self._check_rate_limit(weight_cost)
        session = await self.get_session()
        url = f"{self.base_url}{endpoint}"
        try:
            async with session.get(url, timeout=10.0) as response:
                response.raise_for_status()
                return await response.json()
        except Exception as e:
            logger.error(f"Public GET failed ({endpoint}): {e}")
            return []

    async def close(self):
        """Teardown active socket pool securely preventing Port Exhaustion."""
        if self._session and not self._session.closed:
            await self._session.close()
            # Enforce connector release
            if self._session.connector:
                await asyncio.sleep(0.250)
                self._session.connector.close()

