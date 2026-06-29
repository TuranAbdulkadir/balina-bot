import asyncio
import time
from collections import deque
from core.logger_factory import get_logger
from network.http_client import BinanceRestClient

logger = get_logger("CircuitBreaker")

class GlobalCircuitBreaker:
    """Consolidated module intercepting structural anomalies via Volumetric and Latency triggers."""
    def __init__(self, rest_client: BinanceRestClient, engine, state):
        self.rest = rest_client
        self.engine = engine
        self.state = state
        self._volume_window = deque()
        self._locked_until = 0

    def add_volume(self, vol: float):
        """Append fresh trade volumes and purge those exceeding 60s window using O(1) deque pops."""
        now = time.time()
        self._volume_window.append((now, vol))
        while self._volume_window and (now - self._volume_window[0][0] > 60.0):
            self._volume_window.popleft()

    def check_volume_spike(self):
        """Detects whether recent 1-sec volume breached extreme 3.5x norms."""
        if time.time() < self._locked_until:
            return True
            
        if len(self._volume_window) < 10:
            return False
            
        total_vol = sum(v for t, v in self._volume_window)
        avg_vol_per_sec = total_vol / 60.0
        
        last_1s_vol = 0.0
        now = time.time()
        for t, v in reversed(self._volume_window):
            if now - t <= 1.0:
                last_1s_vol += v
            else:
                break
                
        if avg_vol_per_sec > 0 and last_1s_vol > (avg_vol_per_sec * 3.5):
            logger.critical(f"Global Circuit Breaker Tripped! Volume Spike 1s={last_1s_vol:.2f} Avg={avg_vol_per_sec:.2f}")
            self._locked_until = time.time() + (15 * 60)
            self.engine.toxic_flow_active = True
            return True
            
        return False

    async def maintenance_monitor(self):
        """Checks API Health every 5 mins."""
        while True:
            await asyncio.sleep(300)
            try:
                await self.rest.get_signed("/fapi/v1/ping")
            except Exception as e:
                logger.error(f"Maintenance Cycle Hit. API is unstable: {e}")

    async def silent_death_monitor(self):
        """
        Monitors WebSocket state globally for extended packet loss.
        Uses a cooldown to prevent infinite panic loops.
        Only fires ONCE per incident, then waits for recovery.
        """
        cooldown_until = 0.0
        
        while True:
            await asyncio.sleep(5)
            
            if self.state.status != "running" or self.state.last_update == 0:
                continue
            
            now = time.time()
            
            # If we are in cooldown, check if data has resumed
            if now < cooldown_until:
                # Data resumed? Reset toxic flag
                if now - self.state.last_update < 10.0:
                    self.engine.toxic_flow_active = False
                    cooldown_until = 0.0
                    logger.info("SILENT DEATH RECOVERED: WS data flow resumed. Toxic lock released.")
                continue
                
            gap = now - self.state.last_update
            if gap > 30.0:
                logger.critical(f"SILENT DEATH WS TIMEOUT ({gap:.0f}s gap). CANCELLING ALL ORDERS.")
                try:
                    await self.rest.delete_signed("/fapi/v1/allOpenOrders", {"symbol": "BTCUSDT"})
                    logger.info("SILENT DEATH: All Limit Orders Revoked.")
                except Exception as e:
                    logger.error(f"WS Timeout Order Revocation Failed: {e}")
                    
                self.engine.toxic_flow_active = True
                # Set 60-second cooldown to prevent spam loop
                cooldown_until = now + 60.0
