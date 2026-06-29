import asyncio
import aiohttp
import time
from core.logger_factory import get_logger

logger = get_logger("SymbolSelector")

class SymbolSelector:
    def __init__(self):
        self.best_symbol = "BTCUSDT"
        self.top_symbols = ["BTCUSDT"]
        self.url = "https://fapi.binance.com/fapi/v1/ticker/24hr"

    async def fetch_initial(self):
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(self.url, timeout=5.0) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        self._calculate_scores(data)
                        logger.info(f"Ilk dinamik sembol secimi yapildi: {self.best_symbol}")
                    else:
                        logger.warning("Ilk sembol cekilemedi, varsayilan BTCUSDT kullanilacak.")
            except Exception as e:
                logger.error(f"Ilk sembol cekim hatasi: {e}")

    async def update_loop(self):
        logger.info("SymbolSelector arka plan dongusu basladi.")
        async with aiohttp.ClientSession() as session:
            while True:
                await asyncio.sleep(300) # Her 5 dakikada bir guncelle
                try:
                    async with session.get(self.url, timeout=5.0) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            self._calculate_scores(data)
                except Exception as e:
                    logger.error(f"SymbolSelector hatasi: {e}")

    def _calculate_scores(self, tickers: list):
        scored = []
        for t in tickers:
            symbol = t.get("symbol", "")
            if not symbol.endswith("USDT"): continue
            
            try:
                high = float(t.get("highPrice", 0.0))
                low = float(t.get("lowPrice", 0.0))
                vol = float(t.get("quoteVolume", 0.0))
                
                # Sadece yuksek hacimli pariteler dikkate alinir
                if low <= 0 or vol < 15000000: continue
                
                volatility = (high - low) / low
                score = vol * volatility
                scored.append((symbol, score))
            except Exception:
                continue
                
        scored.sort(key=lambda x: x[1], reverse=True)
        if scored:
            self.top_symbols = [s[0] for s in scored[:3]]
            self.best_symbol = self.top_symbols[0]
            
    def get_best_symbol(self) -> str:
        return self.best_symbol
        
    def get_top_symbols(self, n: int=3) -> list:
        return self.top_symbols[:n]
