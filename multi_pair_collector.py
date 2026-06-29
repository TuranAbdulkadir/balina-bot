import asyncio
import websockets
import json
import time
import os
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import logging
import glob
import traceback

# Ultra-High-Frequency Logging ayarları
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

# Top 10 Hacimli Binance Futures Pariteleri
PAIRS = ["btcusdt", "ethusdt", "solusdt", "bnbusdt", "xrpusdt", "dogeusdt", "adausdt", "avaxusdt", "maticusdt", "linkusdt"]

# Hem sipariş defteri (bookTicker) hem gerçekleşen işlemler (aggTrade) streamleri oluşturulur
STREAMS = [f"{p}@bookTicker" for p in PAIRS] + [f"{p}@aggTrade" for p in PAIRS]
STREAM_URL = "wss://fstream.binance.com/stream?streams=" + "/".join(STREAMS)

DATA_DIR = "core/data_lake"
os.makedirs(DATA_DIR, exist_ok=True)

# ── aggTrade Dedicated Collection ──
AGGTRADE_DIR = os.path.join(DATA_DIR, "aggtrade")
os.makedirs(AGGTRADE_DIR, exist_ok=True)
AGGTRADE_BUFFER_LIMIT = 10000  # Her 10.000 aggTrade eventinde bir Parquet dosyası oluştur
aggtrade_buffer = []
aggtrade_file_counter = 0

# RAM Tamponu ve Warmup Takibi
buffer = []
tick_counts = {}
try:
    with open(os.path.join(DATA_DIR, "warmup_state.json"), "r") as f:
        tick_counts = json.load(f)
        logging.info("HOT-LOAD: warmup_state.json basariyla yuklendi, kümülütif sayaclar devralindi!")
except Exception:
    logging.warning("HOT-LOAD: warmup_state.json bulunamadi, sifirdan baslaniyor.")
    
BUFFER_LIMIT = 50000  # 50 bin satırda bir diske yazılır (I/O Optimizasyonu)

async def flush_buffer():
    global buffer
    if not buffer:
        return
    
    # Tamponun kopyasını alıp orijinali hemen boşaltıyoruz (Sıfır Lock beklemesi)
    chunk = buffer[:]
    buffer.clear()
    
    df = pd.DataFrame(chunk)
    filename = os.path.join(DATA_DIR, f"multipair_ticks_{int(time.time())}.parquet")
    
    try:
        table = pa.Table.from_pandas(df)
        pq.write_table(table, filename, compression='snappy')
        logging.info(f"[SUCCESS] {len(chunk)} satir Parquet formatinda diske basildi: {filename}")
    except Exception as e:
        err_msg = traceback.format_exc()
        logging.critical(f"DATA LAKE WRITE ERROR: {err_msg}")
        try:
            with open("error.log", "a", encoding="utf-8") as err_f:
                err_f.write(f"{time.ctime()} - DATA LAKE WRITE ERROR:\n{err_msg}\n")
        except:
            pass

async def forced_flush_daemon():
    """Gerçek Zaman Bazlı Zorunlu Döküm (Thread-Safe Robust Flush)"""
    while True:
        await asyncio.sleep(60)
        try:
            await flush_buffer()
        except Exception as e:
            logging.error(f"Forced Flush Daemon Fault: {e}")
        try:
            with open(os.path.join(DATA_DIR, "warmup_state.json"), "w") as f:
                json.dump(tick_counts, f)
        except Exception:
            pass

async def data_lake_garbage_collector():
    """Data Lake Backpressure: 48 saatten (2 gun) eski Parquet dosyalarini asenkron olarak siler."""
    logging.info("Garbage Collector aktif. 48 saatten eski veriler temizlenecek.")
    while True:
        try:
            now = time.time()
            # Asenkron I/O bloklanmamasi icin glob'u ayri cagirmasak da glob cok hizlidir.
            files = glob.glob(os.path.join(DATA_DIR, "*.parquet"))
            for f in files:
                try:
                    file_age = now - os.path.getmtime(f)
                    if file_age > 172800: # 48 saat
                        # KESINLIKLE to_thread ile silinir (Non-blocking Purge)
                        await asyncio.to_thread(os.remove, f)
                        logging.info(f"[PURGE] Eski veri dosyasi silindi: {f}")
                except Exception as ex:
                    pass
        except Exception as e:
            logging.error(f"Garbage Collector Hatasi: {e}")
        
        await asyncio.sleep(3600) # Her saat basi calisir

async def connect():
    global buffer
    logging.info(f"Baglaniliyor... {len(PAIRS)} Parite izleniyor.")
    logging.info(f"Stream URL Hazir: {len(STREAMS)} kanal aciliyor.")
    
    while True:
        try:
            async with websockets.connect(STREAM_URL, ping_interval=20, ping_timeout=20, max_size=10_000_000) as ws:
                logging.info("Binance Futures WebSocket'e baglanildi! Veri akiyor...")
                while True:
                    msg = await ws.recv()
                    data = json.loads(msg)
                    stream = data.get("stream", "")
                    payload = data.get("data", {})
                    
                    row = {
                        "stream": stream,
                        "local_ts": time.time(),
                        "symbol": payload.get("s", ""),
                        "server_ts": payload.get("E", payload.get("T", 0))
                    }
                    
                    if stream:
                        row.update({
                            "type": "bookTicker" if "bookTicker" in stream else "aggTrade",
                        })
                        if "bookTicker" in stream:
                            row.update({
                                "bid_price": float(payload.get("b", 0)),
                                "bid_qty": float(payload.get("B", 0)),
                                "ask_price": float(payload.get("a", 0)),
                                "ask_qty": float(payload.get("A", 0))
                            })
                        elif "aggTrade" in stream:
                            trade_price = float(payload.get("p", 0))
                            trade_qty = float(payload.get("q", 0))
                            is_buyer_maker = payload.get("m", False)
                            row.update({
                                "trade_price": trade_price,
                                "trade_qty": trade_qty,
                                "is_buyer_maker": is_buyer_maker
                            })
                            
                            # ── Dedicated aggTrade collection (btcusdt only) ──
                            if "btcusdt" in stream:
                                aggtrade_row = {
                                    "timestamp": int(payload.get("T", payload.get("E", 0))),
                                    "symbol": "BTCUSDT",
                                    "price": trade_price,
                                    "qty": trade_qty,
                                    "side": "SELL" if is_buyer_maker else "BUY",
                                    "is_market_maker": bool(is_buyer_maker)
                                }
                                aggtrade_buffer.append(aggtrade_row)
                                
                                if len(aggtrade_buffer) >= AGGTRADE_BUFFER_LIMIT:
                                    await flush_aggtrade_buffer()
                            
                    sym = payload.get("s", "")
                    if sym:
                        tick_counts[sym] = tick_counts.get(sym, 0) + 1
                        
                    buffer.append(row)
                    
                    # Buffer dolduysa Parquet kaydet
                    if len(buffer) >= BUFFER_LIMIT:
                        await flush_buffer()
        except websockets.exceptions.ConnectionClosed as cc:
            logging.error(f"WebSocket Ping/Pong koptu (Heartbeat failure): {cc}. 3 saniye icinde Zero-Loss ile baglanti yenileniyor...")
            await asyncio.sleep(3)
        except Exception as e:
            logging.error(f"Beklenmeyen baglanti hatasi: {e}. 3 saniye sonra yeniden baglanilacak...")
            await asyncio.sleep(3)

async def main():
    asyncio.create_task(forced_flush_daemon())
    asyncio.create_task(data_lake_garbage_collector())
    await connect()

if __name__ == "__main__":
    asyncio.run(main())
