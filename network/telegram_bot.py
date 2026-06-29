import asyncio
import aiohttp
import time
import os
import json
import pandas as pd
from datetime import datetime
from core.logger_factory import get_logger
from multiprocessing import Queue

logger = get_logger("TelegramBot")

class TelegramBot:
    def __init__(self, token: str, allowed_user: str, tg_queue: Queue):
        self.token = token
        self.allowed_user = str(allowed_user)
        self.tg_queue = tg_queue
        self.base_url = f"https://api.telegram.org/bot{self.token}"
        self.offset = 0
        self.state_cache = {}
        self.ml_training_active = False

    async def _state_sync_loop(self):
        state_file = "core/data_lake/bot_state.json"
        while True:
            try:
                if os.path.exists(state_file):
                    with open(state_file, "r") as f:
                        self.state_cache = json.load(f)
            except Exception:
                pass
            await asyncio.sleep(2.0)

    async def send_message(self, text: str):
        if not self.token or not self.allowed_user:
            return
            
        url = f"{self.base_url}/sendMessage"
        payload = {
            "chat_id": self.allowed_user,
            "text": text,
            "parse_mode": "HTML"
        }
        
        async with aiohttp.ClientSession() as session:
            try:
                async with session.post(url, json=payload, timeout=5.0) as resp:
                    pass
            except Exception as e:
                logger.error(f"Telegram send error: {e}")

    async def poll(self):
        if not self.token or not self.allowed_user:
            logger.warning("Telegram Bot devredisi (Token veya UserID eksik).")
            return
            
        logger.info("Telegram Bot etkilesimli (long-polling) modunda basladi.")
        asyncio.create_task(self._state_sync_loop())
        asyncio.create_task(self._daily_report_loop())
        url = f"{self.base_url}/getUpdates"
        
        async with aiohttp.ClientSession() as session:
            while True:
                try:
                    params = {"offset": self.offset, "timeout": 30}
                    async with session.get(url, params=params, timeout=35.0) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            if data.get("ok"):
                                for update in data.get("result", []):
                                    self.offset = update["update_id"] + 1
                                    await self._handle_update(update)
                            else:
                                logger.warning(f"Telegram API Error: {data}")
                                await asyncio.sleep(5)
                        else:
                            logger.error(f"Telegram HTTP Error {resp.status}. Sleeping 5s to prevent loop spam.")
                            await asyncio.sleep(5)
                except asyncio.TimeoutError:
                    pass
                except Exception as e:
                    logger.error(f"Telegram polling error: {e}")
                    await asyncio.sleep(5)

    def _push_cmd(self, cmd: str, args=None):
        try:
            self.tg_queue.put_nowait(("TG_CMD", cmd, args))
        except Exception as e:
            logger.error(f"Queue push failed: {e}")

    async def _handle_update(self, update: dict):
        message = update.get("message", {})
        chat_id = str(message.get("chat", {}).get("id", ""))
        text = message.get("text", "")
        
        if chat_id != self.allowed_user:
            return
            
        if not text.startswith("/"):
            return
            
        cmd = text.split()[0].lower()
        
        if cmd in ["/status", "/panel"]:
            if not self.state_cache:
                await self.send_message("⚠️ Ana bot çevrimdışı veya durum dosyası (bot_state.json) henüz oluşmadı!")
                return
                
            msg = (
                f"📊 <b>ANLIK DURUM</b>\n"
                f"Sembol: {self.state_cache.get('symbol', 'N/A')}\n"
                f"Bakiye: ${self.state_cache.get('wallet_balance', 0):.2f}\n"
                f"Açık Poz: {self.state_cache.get('position_amt', 0)}\n"
                f"Z-Score: {self.state_cache.get('zscore', 0):.2f}\n"
                f"OBI: {self.state_cache.get('obi', 0):.2f}\n"
                f"VPIN: {self.state_cache.get('vpin', 0):.2f}\n"
                f"Makro Trend: {self.state_cache.get('trend', 'N/A')}\n"
                f"📈 Toplanan Veri: {self.state_cache.get('tick_count', 0)} Tick\n"
                f"🗃️ Veri Havuzu: {self.state_cache.get('lake_files', 0)} Dosya ({self.state_cache.get('lake_size', 0):.1f} MB)\n"
                f"🔄 Restart Sayısı: {self.state_cache.get('restart_count', 0)}\n"
                f"🔌 Ağ Kopma Sayısı: {self.state_cache.get('disconnect_count', 0)}\n"
                f"Bot Durumu: {self.state_cache.get('status_msg', 'UNKNOWN')}\n"
                f"Lock Durumu: {self.state_cache.get('lock_status', 'TEMIZ')}"
            )
            await self.send_message(msg)
            
        elif cmd in ["/pnl", "/report", "/rapor"]:
            today_str = datetime.utcnow().strftime("%Y%m%d")
            sim_file = f"core/simulation_results/sim_{today_str}.csv"
            if os.path.exists(sim_file):
                try:
                    df = pd.read_csv(sim_file)
                    net = df['net_pnl'].sum()
                    wins = (df['net_pnl'] > 0).sum()
                    win_rate = (wins / len(df)) * 100 if len(df) > 0 else 0
                    msg = f"💰 <b>Bugünkü PnL (CSV)</b>\nToplam İşlem: {len(df)}\nNet PnL: ${net:.4f}\nWin Rate: %{win_rate:.2f}"
                except Exception as e:
                    msg = "CSV okunurken hata oluştu."
            else:
                msg = "Bugün için henüz işlem verisi yok."
            await self.send_message(msg)
            
        elif cmd == "/pause":
            self._push_cmd("pause")
            await self.send_message("⏸ Bot yeni işlem açmayı <b>DURDURDU</b> komutu merkeze iletildi.")
            
        elif cmd == "/resume":
            self._push_cmd("resume")
            await self.send_message("▶️ Bot tekrar <b>AKTİF</b> komutu merkeze iletildi.")
            
        elif cmd == "/close":
            self._push_cmd("close")
            await self.send_message("🚨 Emergency Close tetiklendi! Merkeze iletiliyor...")
                
        elif cmd == "/symbol":
            await self.send_message(f"🔄 Mevcut Sembol: <b>{self.state_cache.get('symbol', 'N/A')}</b>")
            
        elif cmd == "/threshold":
            await self.send_message(f"🧠 Mevcut ML Z-Score Eşiği: <b>{self.state_cache.get('black_swan_z', 4.5)}</b>")
            
        elif cmd == "/unlock":
            lock_file = "core/data_lake/SHUTDOWN_LOCK.txt"
            if os.path.exists(lock_file):
                try:
                    os.remove(lock_file)
                    await self.send_message("🔓 SHUTDOWN_LOCK silindi! Merkeze yeniden başlama sinyali gönderiliyor...")
                    self._push_cmd("unlock")
                except Exception as e:
                    await self.send_message(f"❌ Kilit silinirken hata: {e}")
            else:
                await self.send_message("✅ Sistemde aktif bir kilit dosyası yok.")
            
        elif cmd == "/ml":
            if self.ml_training_active:
                await self.send_message("⚠️ Model eğitimi zaten arka planda devam ediyor, sunucu işlemcisini korumak için mükerrer istek iptal edildi!")
            else:
                self.ml_training_active = True
                await self.send_message("⏳ ML Optimizasyonu arka planda başlatılıyor...")
                asyncio.create_task(self._run_ml_optimizer())
            
        elif cmd == "/help":
            help_text = (
                "🤖 <b>KOMUTLAR</b>\n"
                "/status - Anlık bakiye ve sinyaller\n"
                "/pnl - Bugünkü simülasyon/gerçek CSV özeti\n"
                "/pause - İşlem açmayı durdur\n"
                "/resume - İşlem açmayı aktifleştir\n"
                "/close - Açık pozisyonu Market Exit ile kapat\n"
                "/symbol - Mevcut pariteyi göster\n"
                "/threshold - Z-Score eşiğini göster\n"
                "/unlock - SHUTDOWN_LOCK kilidini açar\n"
                "/ml - Offline ML modelini eğit ve güncelle\n"
                "/help - Komutları listele"
            )
            await self.send_message(help_text)
            
        else:
            await self.send_message(f"❌ Bilinmeyen Komut: {cmd}\nMevcut komutları görmek için /help yazabilirsiniz.")

    async def _run_ml_optimizer(self):
        try:
            process = await asyncio.create_subprocess_shell(
                "python core/ml_optimizer.py",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await process.communicate()
            if process.returncode == 0:
                self._push_cmd("reload_ml")
                await self.send_message(f"✅ Yeni AI Beyni Eğitildi! Merkeze Hot-Reload sinyali gönderildi.")
            else:
                await self.send_message(f"❌ ML Optimizasyonu Hatası:\n<pre>{stderr.decode()}</pre>")
        except Exception as e:
            await self.send_message(f"❌ ML Subprocess Hatası: {e}")
        finally:
            self.ml_training_active = False

    async def _daily_report_loop(self):
        import glob
        last_sent_date = ""
        while True:
            await asyncio.sleep(60)
            now_utc = datetime.utcnow()
            
            # UTC 00:00 - 00:05 arasinda ve bugun gonderilmediyse
            if now_utc.hour == 0 and now_utc.minute < 5:
                today_str = now_utc.strftime("%Y-%m-%d")
                if last_sent_date != today_str:
                    try:
                        # 1. aggTrade Verilerini Oku
                        aggtrade_dir = "core/data_lake/aggtrade"
                        today_files = glob.glob(f"{aggtrade_dir}/*.parquet")
                        
                        aggtrade_count = 0
                        real_vpin = 0.0
                        
                        if today_files:
                            try:
                                dfs = [pd.read_parquet(f) for f in today_files[-5:]] # Son 5 dosya (veya tumu)
                                if dfs:
                                    df = pd.concat(dfs, ignore_index=True)
                                    aggtrade_count = len(df)
                                    buy_vol = df[~df['is_market_maker']]['qty'].sum()
                                    sell_vol = df[df['is_market_maker']]['qty'].sum()
                                    total_vol = buy_vol + sell_vol
                                    if total_vol > 0:
                                        real_vpin = abs(buy_vol - sell_vol) / total_vol
                            except Exception as e:
                                logger.error(f"Daily report pandas error: {e}")
                                
                        # 2. State Cache Verilerini Al
                        s = self.state_cache
                        
                        # 3. Uptime hesapla
                        from core.config import DRY_RUN
                        
                        msg = (
                            f"📊 <b>Günlük Rapor</b>\n"
                            f"━━━━━━━━━━━━━━\n"
                            f"📅 Tarih: {today_str}\n"
                            f"⏱ Çalışma Süresi: {s.get('uptime', 0):.1f} saat\n\n"
                            
                            f"📈 <b>Sinyal İstatistikleri:</b>\n"
                            f"- Toplam Sinyal: {s.get('total_signals', 0)}\n"
                            f"- BUY: {s.get('buy_signals', 0)}\n"
                            f"- SELL: {s.get('sell_signals', 0)}\n"
                            f"- NONE: {s.get('none_signals', 0)}\n\n"
                            
                            f"📊 <b>Güncel İndikatörler:</b>\n"
                            f"- EMA9: {s.get('ema_short', 0.0):.2f}\n"
                            f"- EMA21: {s.get('ema_long', 0.0):.2f}\n"
                            f"- RSI: {s.get('rsi', 50.0):.1f}\n"
                            f"- ADX: {s.get('adx', 50.0):.1f}\n\n"
                            
                            f"🔬 Real VPIN: {real_vpin:.4f}\n"
                            f"💾 aggTrade Kayıtları: {aggtrade_count:,}\n\n"
                        )
                        
                        if DRY_RUN:
                            msg += "⚠️ <b>DRY RUN — Gerçek işlem yok</b>"
                        
                        await self.send_message(msg)
                        last_sent_date = today_str
                        logger.info("Daily report sent to Telegram.")
                    except Exception as e:
                        logger.error(f"Daily report failed: {e}")
