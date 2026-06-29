import asyncio
import time
from decimal import Decimal
from core.logger_factory import get_logger

logger = get_logger("FundingRate")

class FundingRateMonitor:
    def __init__(self, rest_client, engine, lob, symbol="BTCUSDT"):
        self.rest = rest_client
        self.engine = engine
        self.lob = lob
        self.symbol = symbol
        self.current_funding_rate = Decimal("0") # AŞAMA 19: Anlik funding oranini tutar

    def is_entry_safe(self, side: str) -> bool:
        """AŞAMA 19 - Funding Rate Filtresi"""
        threshold = Decimal("0.0001") # %0.01
        
        if side == "BUY" and self.current_funding_rate > threshold:
            logger.warning(f"⚠️ [FUNDING BLOCK] LONG acilamaz. Funding Rate ({self.current_funding_rate}) > +%0.01 (Long tutmak zararli)")
            return False
            
        if side == "SELL" and self.current_funding_rate < -threshold:
            logger.warning(f"⚠️ [FUNDING BLOCK] SHORT acilamaz. Funding Rate ({self.current_funding_rate}) < -%0.01 (Short tutmak zararli)")
            return False
            
        return True

    async def monitor_loop(self):
        """
        Continuously polls /fapi/v1/premiumIndex to extract nextFundingTime.
        Blocks trading 2 minutes prior, smart slices all chunks, and restores trading 1 min after.
        """
        logger.info("Funding Rate Evacuation Protocol initialized.")
        while True:
            try:
                # fetch premium index which includes nextFundingTime
                res = await self.rest.get_signed("/fapi/v1/premiumIndex", {"symbol": self.symbol})
                if isinstance(res, dict) and "nextFundingTime" in res:
                    next_funding_time = int(res["nextFundingTime"])
                    self.current_funding_rate = Decimal(str(res.get("lastFundingRate", "0.0"))) # AŞAMA 19: Orani guncelle
                    
                    now_ms = int(time.time() * 1000)
                    ms_until_funding = next_funding_time - now_ms
                    
                    # Check if we are inside the 2-minute danger zone before funding
                    if 0 < ms_until_funding <= (2 * 60 * 1000):
                        cost_of_funding = (Decimal(str(res.get("lastFundingRate", "0.0"))) * self.engine.position_amt * Decimal(res.get("markPrice", "0"))).copy_abs()
                        unrealized_profit = self.engine.unrealized_pnl
                        
                        logger.warning(f"FUNDING EVENT IMMINENT ({ms_until_funding/1000:.0f}s). Unrealized PnL: {unrealized_profit}, Est Funding Cost: {cost_of_funding}")
                        
                        if unrealized_profit > Decimal("0") and unrealized_profit > (cost_of_funding * Decimal("2.0")):
                            logger.info("HOLD PROTOCOL OVERRIDE: Position is structurally profitable enough to absorb the funding tax. Holding.")
                            await asyncio.sleep(min(ms_until_funding / 1000, 10))
                            continue
                            
                        logger.warning("EVACUATING POSITIONS: Funding penalty outweighs mathematical hold edge!")
                        # Lock engine
                        self.engine.toxic_flow_active = True
                        
                        # Smart Slice all positions.
                        actual_pos = abs(self.engine.position_amt)
                        if actual_pos > Decimal("0"):
                            await self.engine.smart_slice_exit(self.symbol, actual_pos, "SELL" if self.engine.position_amt > Decimal("0") else "BUY", self.lob)
                        
                        # Wait out the funding time plus 1 minute safety buffer
                        wait_time_sec = (ms_until_funding / 1000) + 60.0
                        logger.warning(f"Sleeping for {wait_time_sec:.0f}s to bridge through funding impact.")
                        
                        await asyncio.sleep(wait_time_sec)
                        
                        # Unlock engine
                        logger.info("Funding event passed. Restoring market making capacity.")
                        self.engine.toxic_flow_active = False
                    else:
                        # Sleep halfway between now and the danger zone (but test at least every 5 mins)
                        safe_sleep = min(300, max(1, (ms_until_funding - 2 * 60 * 1000) / 1000 / 2))
                        await asyncio.sleep(safe_sleep)
                else:
                    await asyncio.sleep(60)
            except Exception as e:
                logger.error(f"Funding Rate Monitor faulted: {e}")
                await asyncio.sleep(60)
