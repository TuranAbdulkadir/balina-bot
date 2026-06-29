import aiohttp
import asyncio
from core.logger_factory import get_logger
import os
import signal
from decimal import Decimal

logger = get_logger("TelegramPanic")

class TelegramPanicHandler:
    def __init__(self, token: str, allowed_user: str, engine, lob):
        self.token = token
        self.allowed_user = str(allowed_user)
        self.engine = engine
        self.lob = lob
        if self.token:
            self.base_url = f"https://api.telegram.org/bot{self.token}"

    async def send_message(self, text: str):
        if not self.base_url or not self.allowed_user:
            return
        logger.info(f"Telegram Push: {text}")
        payload = {"chat_id": self.allowed_user, "text": text}
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(f"{self.base_url}/sendMessage", json=payload, timeout=5) as resp:
                    res_text = await resp.text()
                    if resp.status != 200:
                        logger.error(f"Telegram API rejected message: {res_text}")
        except Exception as e:
            logger.error(f"Telegram send failed: {e}")

    async def poll(self):
        if not getattr(self, "base_url", None) or not self.allowed_user:
            logger.warning("Telegram Emergency Module bypassed. Discrepant Configs.")
            return

        offset = 0
        connection_failures = 0
        
        while True:
            try:
                # Create a fresh TCP session per block of requests to avoid half-open socket deadlocks
                async with aiohttp.ClientSession() as session:
                    logger.info("Telegram Long-Polling connected.")
                    while True:
                        try:
                            url = f"{self.base_url}/getUpdates?offset={offset}&timeout=30"
                            async with session.get(url, timeout=aiohttp.ClientTimeout(total=40)) as resp:
                                if resp.status == 200:
                                    connection_failures = 0
                                    data = await resp.json()
                                    for update in data.get("result", []):
                                        offset = update["update_id"] + 1
                                        message = update.get("message", {})
                                        text = message.get("text", "")
                                        user_id = str(message.get("from", {}).get("id", ""))
        
                                        if user_id == self.allowed_user:
                                            if text == "/ACILKAPAT":
                                                logger.critical("🚨 TELEGRAM RED BUTTON PRESSED! FIRING EMERGENCY CASCADE!")
                                                asyncio.create_task(self.panic_exit())
                                            elif text == "/RAPOR":
                                                asyncio.create_task(self.send_report())
                                else:
                                    await asyncio.sleep(2)
                        except asyncio.TimeoutError:
                            # Expected timeout for long-polling (no new messages)
                            pass
                        except Exception as e:
                            logger.error(f"Telegram connection instability: {e}")
                            connection_failures += 1
                            if connection_failures > 3:
                                logger.warning("TCP socket deadlock suspected. Rebuilding ClientSession...")
                                break # break inner loop to recreate session
                            await asyncio.sleep(5)
            except Exception as outer_e:
                logger.error(f"Telegram critical session fault: {outer_e}")
                await asyncio.sleep(10)

    async def send_report(self):
        try:
            import os
            import subprocess
            import pyarrow.parquet as pq
            
            files = os.listdir("data_lake") if os.path.exists("data_lake") else []
            
            def calculate_lake_size(files_list):
                size = 0
                for f in files_list:
                    if f.endswith(".parquet"):
                        try:
                            filepath = os.path.join("data_lake", f)
                            meta = pq.read_metadata(filepath)
                            size += meta.num_rows
                        except Exception:
                            pass
                return size

            # Defend the ASIC Event Loop by spinning disk operations into a background thread
            lake_size = await asyncio.to_thread(calculate_lake_size, files)
            
            if lake_size > 0:
                msg_text = f"📊 **Balina-Bot Raporu**\n- İslem Goren LOB Verisi: ~**{lake_size:,}**\n- Parquet Dosya Sayisi: {len(files)}\n\nWARM-UP Modu basariyla kayit aliyor.\n_Not: Telegram 50MB asim limiti sebebiyle Dosya gonderimi devre disi._"
                async with aiohttp.ClientSession() as session:
                    url = f"{self.base_url}/sendMessage"
                    await session.post(url, data={"chat_id": self.allowed_user, "text": msg_text})
            else:
                msg_text = "📊 **Balina-Bot Canlı Mod**\nLOB Verisi şu an RAM üzerinde tutuluyor.\n_(SSD Gecikmesini önlemek için disk yazımı Kapalı)_"
                async with aiohttp.ClientSession() as session:
                    url = f"{self.base_url}/sendMessage"
                    await session.post(url, data={"chat_id": self.allowed_user, "text": msg_text})
        except Exception as e:
            logger.error(f"Rapor gonderme basarisiz: {e}")

    async def panic_exit(self):
        try:
            logger.critical("INITIATING SMART SLICING PANIC EXIT ALGORITHM...")
            await self.engine.smart_slice_exit("BTCUSDT", Decimal("1.0"), "SELL", self.lob)
            logger.critical("SUCCESS: PANIC EXIT PORTFOLIO LIQUIDATED. SENDING SIGINT TO OS...")
        except Exception as e:
            logger.critical(f"Panic Slicing Faulted: {e}")
        finally:
            os.kill(os.getpid(), signal.SIGINT)
