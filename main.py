import asyncio
import platform
import os
import logging
from core.logger_factory import get_logger
import time
import multiprocessing
from api.health import run_fastapi, state
from core.watchdog import watchdog_task
from network.http_client import BinanceRestClient
from network.ws_client import BinanceWsClient
from orderbook.lob import LimitOrderBook
from execution.engine import ExecutionEngine
from core.brain_process import brain_worker
from core.memory_guard import memory_guard_task
from network.circuit_breaker import GlobalCircuitBreaker
from decimal import Decimal
import json

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = get_logger("Main")

# Varsayilan fallback sembol
INITIAL_SYMBOL = "BTCUSDT"

def setup_os_optimizations():
    system = platform.system()
    try:
        if system == "Linux":
            os.sched_setaffinity(0, {0})
            logger.info("Linux OS detected. os.sched_setaffinity set to core 0.")
    except Exception as e:
        logger.warning(f"Failed to apply core pinning: {e}")

def setup_event_loop():
    system = platform.system()
    if system == "Linux":
        try:
            import uvloop
            uvloop.install()
            logger.info("uvloop installed on Linux.")
        except ImportError:
            pass
    elif system == "Windows":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        logger.info("Windows SelectorEventLoopPolicy enabled for aiohttp DNS compatibility.")

async def boot_validation(rest_client: BinanceRestClient, symbol: str):
    logger.info("Starting Boot Validation...")
    try:
        await rest_client.post_signed("/fapi/v1/positionSide/dual", {"dualSidePosition": "true"})
        await rest_client.post_signed("/fapi/v1/marginType", {"symbol": symbol, "marginType": "ISOLATED"})
    except Exception as e:
        msg = str(e).lower()
        if "margintype" in msg or "margin type" in msg or "no need to change" in msg or "multi-assets" in msg or "isolated-margin" in msg:
            logger.info("Margin type validation bypassed (already set or Multi-Asset Mode active).")
        elif "positionside" in msg or "400" in msg:
            logger.critical(f"FATAL BOOT ERROR: Binance hesabi Hedge (Cift Yonlu) moda gecirilemedi! Acik pozisyonlar/emirler olabilir. Hata: {e}")
            logger.critical("SISTEM GUVENLIGI ICIN BOT KENDINI KILITLIYOR. Lutfen Binance hesabinizdaki acik pozisyonlari/emirleri manuel kapatin.")
            raise Exception("Hedge Moda Geçilemedi! (Açık pozisyonunuz olabilir)")
        else:
            raise e

_active_tasks = set()

async def signal_watcher(signal_queue: multiprocessing.Queue, engine: ExecutionEngine, strategy):
    loop = asyncio.get_running_loop()
    while True:
        try:
            payload = await loop.run_in_executor(None, signal_queue.get)
            if payload is None:
                break
                
            cmd = payload[0]
            if cmd in ("VPIN", "ZSCORE", "OBI"):
                val = payload[1]
                strategy.update_signal(cmd.lower(), val)
                if cmd == "VPIN": state.vpin = val
                elif cmd == "ZSCORE": state.zscore = val
                elif cmd == "OBI": state.obi = val
                
                task = asyncio.create_task(strategy.evaluate_market())
                _active_tasks.add(task)
                task.add_done_callback(_active_tasks.discard)
            elif cmd == "TOXIC_FLOW_FLAG":
                engine.toxic_flow_active = payload[1]
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(e)

async def cancel_on_disconnect_heartbeat(rest_client: BinanceRestClient, symbol: str):
    while True:
        try:
            await rest_client.post_signed("/fapi/v1/countdownCancelAll", {"symbol": symbol, "countdownTime": 10000})
        except Exception:
            pass
        await asyncio.sleep(5)

def global_exception_handler(loop, context):
    msg = context.get("exception", context["message"])
    logger.critical(f"FATAL ASYNCIO TRACE: Unhandled Exception in Background Task: {msg}")

async def main(data_queue: multiprocessing.Queue, signal_queue: multiprocessing.Queue, brain_proc: multiprocessing.Process, tg_queue: multiprocessing.Queue):
    loop = asyncio.get_running_loop()
    loop.set_exception_handler(global_exception_handler)
    logger.info("Starting Balina-Bot...")
    try:
        import core.audit
        await core.audit.increment_audit("restart")
    except Exception:
        pass
    
    # ── PM2 DONGU KALKANI: KILIT KONTROLU ──
    lock_file = "core/data_lake/SHUTDOWN_LOCK.txt"
    if os.path.exists(lock_file):
        logger.critical("🛑 SHUTDOWN_LOCK.txt BULUNDU! Idle loop devrede. Kilit silinene kadar bekleniyor...")
        try:
            with open("core/data_lake/bot_state.json", "w") as f:
                json.dump({"lock_status": "AKTIF (SISTEM KILITLI)", "status_msg": "LOCKED", "symbol": "N/A"}, f)
        except Exception:
            pass
        while os.path.exists(lock_file):
            await asyncio.sleep(2)
            while not tg_queue.empty():
                try:
                    cmd_tuple = tg_queue.get_nowait()
                    if cmd_tuple[0] == "TG_CMD" and cmd_tuple[1] == "unlock":
                        if os.path.exists(lock_file):
                            os.remove(lock_file)
                            logger.info("🔓 Kilit acildi, boot devam ediyor...")
                except Exception:
                    pass
        
    state.status = "running"
    state.last_update = time.time()
    
    # AŞAMA 19 (Görev 5): CANLIYA GEÇİŞ GÜVENLİK KAPISI (Go-Live Gate)
    from core.config import DRY_RUN
    if not DRY_RUN:
        logger.warning("DRY_RUN = False algilandi. Canli (Gercek/Testnet Emir) Modu test ediliyor...")
        from core.go_live_gate import GoLiveGate
        if not GoLiveGate.evaluate(min_trades=100, min_win_rate=55.0, min_sharpe=1.5):
            logger.critical("🚫 ONAYSIZ CANLI GECIS ENGELLENDI! Bot simulasyon (DRY_RUN) kistaslarini gecemedi.")
            import sys
            sys.exit("GO_LIVE_GATE_FAILED - Sistem risk almayi reddetti. DRY_RUN=True yapin veya algoritmalarinizi iyilestirin.")
    
    # AŞAMA 16: DİNAMİK SEMBOL SEÇİCİ
    from core.symbol_selector import SymbolSelector
    from core.config import DISABLE_SYMBOL_SELECTOR, SYMBOL
    
    symbol_selector = SymbolSelector()
    if getattr(core.config, "DISABLE_SYMBOL_SELECTOR", False):
        global_state_symbol = getattr(core.config, "SYMBOL", INITIAL_SYMBOL)
        logger.info(f"🚀 GECICI: Symbol Selector DEVRE DISI. Bot starting with fixed Symbol: {global_state_symbol}")
    else:
        await symbol_selector.fetch_initial()
        global_state_symbol = symbol_selector.get_best_symbol() or INITIAL_SYMBOL
        logger.info(f"🚀 Bot starting with Dynamic Symbol: {global_state_symbol}")
    
    # AŞAMA 13: DUAL-ENDPOINT ROUTING
    from core.config import USE_TESTNET, TESTNET_REST_URL, LIVE_REST_URL
    if USE_TESTNET:
        logger.warning("⚠️ TESTNET MODE ACTIVE - Emirler Testnet'e Gonderilecek!")
        rest_client = BinanceRestClient(base_url=TESTNET_REST_URL) # Execution & User Data
        live_rest_client = BinanceRestClient(base_url=LIVE_REST_URL) # LOB Snapshot
    else:
        rest_client = BinanceRestClient(base_url=LIVE_REST_URL)
        live_rest_client = rest_client
        
    lob = LimitOrderBook(global_state_symbol)
    engine = ExecutionEngine(rest_client)
    from core.simulation_reporter import SimulationReporter
    reporter = SimulationReporter()
    from core.trend_filter import TrendFilter
    trend_filter = TrendFilter(global_state_symbol)
    from execution.strategy_alpha import AlphaStrategy
    strategy = AlphaStrategy(engine, lob, reporter=reporter, trend_filter=trend_filter)
    
    # AŞAMA 29: REST Kline Warmup — EMA ve RSI'ın doğru başlaması için geçmiş mumları yükle
    try:
        from core.config import KLINE_WARMUP_COUNT, KLINE_INTERVAL
        logger.info(f"Kline Warmup: {global_state_symbol} icin son {KLINE_WARMUP_COUNT} mum cekiliyor ({KLINE_INTERVAL})...")
        kline_data = await rest_client.get(f"/fapi/v1/klines?symbol={global_state_symbol}&interval={KLINE_INTERVAL}&limit={KLINE_WARMUP_COUNT}")
        if kline_data and isinstance(kline_data, list):
            closes = [float(k[4]) for k in kline_data]   # index 4 = close
            volumes = [float(k[5]) for k in kline_data]   # index 5 = volume
            highs = [float(k[2]) for k in kline_data]     # index 2 = high
            lows = [float(k[3]) for k in kline_data]      # index 3 = low
            strategy.warmup(closes, volumes, highs, lows)
        else:
            logger.warning("Kline Warmup: REST'ten veri alinamadi, WebSocket bekleniyor.")
    except Exception as e:
        logger.error(f"Kline Warmup hatasi: {e}. WebSocket ile dolacak.")
        
    try:
        await boot_validation(rest_client, global_state_symbol)
    except Exception as e:
        error_msg = f"❌ KRİTİK HATA! Binance API başlatılamadı:\n{e}"
        logger.error(error_msg)
        import sys
        sys.exit(1)
        
    logger.info("🟢 Balina-Bot Çekirdeği Başarıyla Başlatıldı.")
    await engine.recover_boot_state(global_state_symbol)
    
    breaker = GlobalCircuitBreaker(rest_client, engine, state)
    
    from network.funding import FundingRateMonitor
    funding_monitor = FundingRateMonitor(rest_client, engine, lob, global_state_symbol)
    
    strategy.funding_monitor = funding_monitor
    
    streams = [
        f"{global_state_symbol.lower()}@depth@100ms",
        f"{global_state_symbol.lower()}@ticker",
        f"{global_state_symbol.lower()}@markPrice",
        f"{global_state_symbol.lower()}@kline_{core.config.KLINE_INTERVAL}"
    ]
    ws_client = BinanceWsClient(streams)
    
    async def ws_message_handler(event: dict):
        try:
            if "data" in event:
                event_data = event["data"]
                now = time.time()
                state.latency_ms = (now * 1000) - event_data.get("E", now * 1000)
                state.last_update = now
                
                event_type = event_data.get("e")
                
                if event_type == "depthUpdate":
                    lob.process_diff(event_data)
                    
                    # --- PHASE 27.15 FIX: Derive Z-Score from LOB mid-price ---
                    # Binance aggTrade stream is blocked on this Oracle IP.
                    # Mid-price from depthUpdate is equally valid for mean-reversion.
                    if lob.state.bids and lob.state.asks:
                        best_bid = max(lob.state.bids.keys())
                        best_ask = min(lob.state.asks.keys())
                        if best_bid > 0 and best_ask > 0:
                            sorted_bids = sorted(lob.state.bids.items(), reverse=True)[:10]
                            sorted_asks = sorted(lob.state.asks.items())[:10]
                            
                            # Weight by Inverse Distance (Closer levels to spread have more weight)
                            # But a simplified volume sum over 10 levels works powerfully as a Gravity Anchor.
                            bid_vol = sum(v for _, v in sorted_bids)
                            ask_vol = sum(v for _, v in sorted_asks)
                            total_vol = bid_vol + ask_vol
                            
                            # --- PHASE 28.6: Volume-Weighted Micro-Price (VWMP) ---
                            # If Buy wall (bid_vol) is immense, true price gravity pulls UP toward Ask.
                            if total_vol > 0.0:
                                micro_price = ((best_bid * ask_vol) + (best_ask * bid_vol)) / total_vol
                            else:
                                micro_price = (best_bid + best_ask) / 2.0
                            
                            is_sell_pressure = ask_vol > bid_vol if total_vol > 0 else False
                            
                            try:
                                q_vol = total_vol / 100.0
                                # Send VWMP to the math core instead of dumb mid_price
                                data_queue.put_nowait(("TRADE", micro_price, q_vol, is_sell_pressure))
                                breaker.add_volume(q_vol)
                                breaker.check_volume_spike()
                            except multiprocessing.queues.Full:
                                pass
                    
                    try:
                        data_queue.put_nowait(("OBI", lob.get_order_book_imbalance(10)))
                    except multiprocessing.queues.Full:
                        pass
                        
                elif event_type == "markPriceUpdate":
                    lob.process_mark_price(event_data)
                
                elif event_type == "kline":
                    k = event_data.get("k", {})
                    if k:
                        task = asyncio.create_task(strategy.process_kline(k))
                        _active_tasks.add(task)
                        task.add_done_callback(_active_tasks.discard)
        except Exception as e:
            logger.error(f"WS Handler Error: {e}")
            
    ws_client.on_message_callback = ws_message_handler
    
    from network.user_ws import UserDataStream
    
    # AŞAMA 13: TESTNET WS ROUTING
    if USE_TESTNET:
        user_ws_url = "wss://stream.binancefuture.com/ws"
    else:
        user_ws_url = "wss://fstream.binance.com/ws"
        
    user_stream = UserDataStream(rest_client, base_url=user_ws_url)
    
    async def account_update_hook(data):
        nonlocal global_state_symbol
        try:
            positions = data.get("a", {}).get("P", [])
            for pos in positions:
                if pos.get("s") == global_state_symbol:
                    engine.position_amt = Decimal(pos.get("pa", "0"))
                    engine.unrealized_pnl = Decimal(pos.get("up", "0"))
                    state.unrealized_pnl = float(engine.unrealized_pnl)
            balances = data.get("a", {}).get("B", [])
            for bal in balances:
                if bal.get("a") == "USDT":
                    engine.wallet_balance = Decimal(bal.get("cw", "0"))
                    state.wallet_balance = float(engine.wallet_balance)
        except Exception as e:
            logger.error(f"Account update parse error: {e}")
            
    async def adl_update_hook(data):
        nonlocal global_state_symbol
        try:
            quants = data.get("a", {})
            for symbol_key, quant in quants.items():
                if symbol_key == global_state_symbol:
                    adl_dict = quant.get("ADLQuantile", {})
                    # 4 is the worst percentile (80-100% highest risk of ADL). We evacuate at 4.
                    if int(adl_dict.get("LONG", 0)) >= 4 or int(adl_dict.get("SHORT", 0)) >= 4:
                        logger.critical(f"⚠️ ADL QUANTILE RISK EXTREME (Percentile 4) DETECTED! Evacuating {global_state_symbol}!")
                        engine.toxic_flow_active = True
                        actual_pos = abs(engine.position_amt)
                        if actual_pos > Decimal("0"):
                            await engine.smart_slice_exit(global_state_symbol, actual_pos, "SELL" if engine.position_amt > 0 else "BUY", lob)
                        logger.info("ADL EVACUATION SUCCESSFUL.")
        except Exception as e:
            logger.error(f"ADL Parse Error: {e}")
            
    async def order_update_hook(data):
        try:
            o = data.get("o", {})
            client_id = o.get("c", "")
            status = o.get("X", "")
            side = o.get("S", "")
            qty = o.get("q", "")
            rpnl = o.get("rp", "0")
            
            if status in ("FILLED", "CANCELED", "EXPIRED", "REJECTED"):
                engine.remove_from_tracking(client_id)
                if status == "FILLED":
                    msg = f"🟢 İŞLEM ONAYLANDI (FILLED)\nYön: {side}\nMiktar: {qty}\nGerçekleşen Kâr/Zarar: ${rpnl}"
                    logger.info(msg.replace('\n', ' | '))
            elif status in ("NEW", "PARTIALLY_FILLED"):
                # Track roughly
                pass
            state.open_orders = len(engine.open_orders)
        except Exception as e:
            logger.error(f"Order Update parse error: {e}")

    user_stream.on_account_update = account_update_hook
    user_stream.on_adl_update = adl_update_hook
    user_stream.on_order_update = order_update_hook
    
    # Dinamik sembol görevlerini tutan liste
    symbol_specific_tasks = []
    
    def start_symbol_tasks(sym: str):
        nonlocal symbol_specific_tasks
        for t in symbol_specific_tasks:
            t.cancel()
        symbol_specific_tasks.clear()
        
        t1 = asyncio.create_task(cancel_on_disconnect_heartbeat(rest_client, sym))
        t2 = asyncio.create_task(engine.commission_rate_task(sym))
        t3 = asyncio.create_task(engine.wallet_sync_loop(sym))
        symbol_specific_tasks.extend([t1, t2, t3])
        
    start_symbol_tasks(global_state_symbol)
    
    tasks = [
        asyncio.create_task(watchdog_task(brain_proc, tolerance_sec=0.1)),
        asyncio.create_task(run_fastapi()),
        asyncio.create_task(ws_client.connect_and_listen()),
        asyncio.create_task(user_stream.connect_and_listen()),
        asyncio.create_task(signal_watcher(signal_queue, engine, strategy)),
        asyncio.create_task(strategy.forced_flush_daemon()),
        asyncio.create_task(memory_guard_task(3600)),
        asyncio.create_task(breaker.maintenance_monitor()),
        asyncio.create_task(breaker.silent_death_monitor()),
        asyncio.create_task(funding_monitor.monitor_loop()),
        asyncio.create_task(engine.stale_order_sweeper()),
        asyncio.create_task(rest_client.time_sync_loop()),
        asyncio.create_task(engine.dust_sweeper_task()),
        asyncio.create_task(trend_filter.update_loop()), # AŞAMA 15: Arka plan döngüsü
        asyncio.create_task(symbol_selector.update_loop()) # AŞAMA 16: Arka plan döngüsü
    ]
    
    async def dashboard_push_daemon():
        """Sürekli olarak arkaplandaki FastAPI sunucusuna State objesini yollar (Dashboard icin)"""
        import aiohttp
        async with aiohttp.ClientSession() as session:
            while True:
                try:
                    # Sinyal istatistiklerini hesapla
                    signal_hist = getattr(strategy, 'signal_buffer', [])
                    buy_count = sum(1 for s in signal_hist if s['signal'] == 'BUY')
                    sell_count = sum(1 for s in signal_hist if s['signal'] == 'SELL')
                    
                    payload = {
                        "status": state.status,
                        "latency_ms": state.latency_ms,
                        "wallet_balance": float(engine.wallet_balance),
                        "open_orders": len(engine.open_orders),
                        "unrealized_pnl": float(engine.unrealized_pnl),
                        
                        # Yeni Metrikler
                        "total_signals": len(signal_hist),
                        "buy_signals": buy_count,
                        "sell_signals": sell_count,
                        "none_signals": strategy.tick_count - len(signal_hist),
                        "current_ema_short": getattr(strategy, '_ema_short', 0.0),
                        "current_ema_long": getattr(strategy, '_ema_long', 0.0),
                        "current_rsi": getattr(strategy, '_last_rsi', 50.0),
                        "current_adx": getattr(strategy, '_last_adx', 50.0),
                        "last_signal_time": str(getattr(strategy, '_last_signal', 'NONE'))
                    }
                    async with session.post("http://localhost:8000/update", json=payload, timeout=2) as resp:
                        await resp.text()
                except Exception:
                    pass
                await asyncio.sleep(1.0)
                
    async def lob_sync_daemon():
        """Otonom Self-Healing Daemon: Sürekli çalışan arka plan tarayıcısı"""
        nonlocal global_state_symbol
        while True:
            try:
                # LOB durumu True (Kopuk) kaldıysa REST üzerinden anında taze snapshot çeker.
                if lob.syncing:
                    logger.warning(f"LOB Daemonsuz kaldı veya senkronizasyon koptu! {global_state_symbol} REST Snapshot çekiliyor...")
                    # AŞAMA 13: LOB Snapshot KESİNLİKLE canlıdan alınmalı!
                    snapshot = await live_rest_client.get_depth_snapshot(global_state_symbol, limit=1000)
                    lob.process_snapshot(snapshot)
            except Exception as e:
                logger.error(f"LOB Snapshot Healer arızası: {e}")
            await asyncio.sleep(1.0)
            
    async def symbol_switch_daemon():
        """AŞAMA 16: En iyi pariteyi izler ve eger pozisyon yoksa gecis yapar"""
        nonlocal global_state_symbol
        while True:
            await asyncio.sleep(60) # Her dakika kontrol et (selector 5dk da bir gunceller)
            try:
                best_sym = symbol_selector.get_best_symbol()
                if best_sym and best_sym != global_state_symbol:
                    if engine.position_amt == Decimal("0"):
                        logger.warning(f"🔄 [SYMBOL SWITCH] {global_state_symbol} -> {best_sym}")
                        global_state_symbol = best_sym
                        
                        await boot_validation(rest_client, best_sym)
                        await engine.recover_boot_state(best_sym)
                        
                        lob.symbol = best_sym
                        lob.syncing = True
                        trend_filter.symbol = best_sym
                        funding_monitor.symbol = best_sym
                        
                        new_streams = [
                            f"{best_sym.lower()}@depth@100ms",
                            f"{best_sym.lower()}@ticker",
                            f"{best_sym.lower()}@markPrice",
                            f"{best_sym.lower()}@kline_{core.config.KLINE_INTERVAL}"
                        ]
                        await ws_client.switch_streams(new_streams)
                        start_symbol_tasks(best_sym)
                        
                    else:
                        logger.info(f"🔄 [SYMBOL SWITCH] {best_sym} bulundu ama mevcut pozisyon var. Gecis ertelendi.")
            except Exception as e:
                logger.error(f"Symbol Switch Daemon Hatasi: {e}")
            
    async def data_lake_compaction_task():
        """Phase 20: Small-File Syndrome Prevention via Pandas"""
        logger.info("Pandas Data Lake Compaction Tracker Online. Triggering daily.")
        import glob
        import pandas as pd
        while True:
            await asyncio.sleep(24 * 3600)
            try:
                files = glob.glob("core/data_lake/balina_warmup_*.parquet")
                files = [f for f in files if "COMPILED" not in f]
                if len(files) > 50:
                    logger.info(f"Squashing {len(files)} micro-files into single Parquet shard.")
                    import pyarrow.parquet as pq
                    schema = pq.read_schema(files[0])
                    final_filename = f"core/data_lake/COMPILED_balina_warmup_{int(time.time())}.parquet"
                    tmp_filename = f"{final_filename}.tmp"
                    try:
                        with pq.ParquetWriter(tmp_filename, schema) as writer:
                            for f in files:
                                table = pq.read_table(f)
                                writer.write_table(table)
                        os.rename(tmp_filename, final_filename)
                        for f in files:
                            os.remove(f)
                        logger.info("Data Lake Compaction SUCCESSFUL. Cleaned footprint.")
                    except Exception as atomic_err:
                        if os.path.exists(tmp_filename):
                            os.remove(tmp_filename)
                        raise atomic_err
            except Exception as e:
                logger.error(f"Compaction failed: {e}")
                
    async def shutdown_lock_clear_daemon():
        """Her gece 00:00 UTC'de PM2 kilit dosyasini siler"""
        import datetime
        while True:
            now = datetime.datetime.now(datetime.timezone.utc)
            tomorrow = now + datetime.timedelta(days=1)
            midnight = datetime.datetime(tomorrow.year, tomorrow.month, tomorrow.day, tzinfo=datetime.timezone.utc)
            seconds_until_midnight = (midnight - now).total_seconds()
            await asyncio.sleep(seconds_until_midnight + 1) # Gece yarisini 1 saniye gece
            
            lock_file = "core/data_lake/SHUTDOWN_LOCK.txt"
            if os.path.exists(lock_file):
                try:
                    os.remove(lock_file)
                    logger.info("🔓 Gece yarisi (00:00 UTC) oldu, SHUTDOWN_LOCK temizlendi. Bot serbest.")
                except Exception as e:
                    pass

    async def system_monitoring_daemon():
        import psutil
        import shutil
        import glob
        import json
        while True:
            await asyncio.sleep(3600)  # Saatte bir calisir
            try:
                total, used, free = shutil.disk_usage("/")
                free_gb = free / (2**30)
                
                ram = psutil.virtual_memory()
                ram_pct = ram.percent
                
                now = time.time()
                files = glob.glob("core/data_lake/*.parquet")
                recent_files = [f for f in files if now - os.path.getmtime(f) <= 3600]
                estimated_rows = len(recent_files) * 50000
                
                lock_file = "core/data_lake/SHUTDOWN_LOCK.txt"
                lock_status = "AKTIF (SISTEM KILITLI)" if os.path.exists(lock_file) else "PASIF (TEMIZ)"
                
                logger.info("========================================")
                logger.info("🛸 24 SAATLIK STABILITE RAPORU (CANLI)")
                logger.info("========================================")
                logger.info(f"💾 Kalan Disk Alani  : {free_gb:.2f} GB")
                logger.info(f"🧠 RAM Kullanimi     : %{ram_pct:.1f}")
                logger.info(f"📊 Son 1 Saatte Veri : ~{estimated_rows:,} Satir (Multi-Pair WebSocket)")
                logger.info(f"🛑 SHUTDOWN_LOCK     : {lock_status}")
                
                # WARMUP DURUMU
                warmup_file = "core/data_lake/warmup_state.json"
                if os.path.exists(warmup_file):
                    try:
                        import aiofiles
                        async with aiofiles.open(warmup_file, "r") as f:
                            content = await f.read()
                            warmups = json.loads(content)
                        logger.info("🔥 WARMUP (ISINMA) DURUMLARI:")
                        for sym, ticks in warmups.items():
                            if ticks >= 3000:
                                logger.info(f"   [{sym}: {ticks}/3000 Tick - PUSUDA READY]")
                            else:
                                logger.info(f"   [{sym}: {ticks}/3000 Tick - ISINIYOR]")
                    except Exception:
                        pass
                        
                logger.info("========================================")
            except Exception as e:
                logger.error(f"Monitoring Daemon Hatasi: {e}")

    async def state_exporter_daemon():
        while True:
            await asyncio.sleep(2.0)
            try:
                import glob
                data_lake_dir = "core/data_lake"
                lake_files = 0
                lake_size = 0.0
                if os.path.exists(data_lake_dir):
                    dir_list = await asyncio.to_thread(os.listdir, data_lake_dir)
                    for f in dir_list:
                        if f.endswith(".parquet"):
                            lake_files += 1
                            filepath = os.path.join(data_lake_dir, f)
                            f_size = await asyncio.to_thread(os.path.getsize, filepath)
                            lake_size += f_size / (1024*1024)
                            
                trend = trend_filter.get_trend() if trend_filter else "N/A"
                lock_file = "core/data_lake/SHUTDOWN_LOCK.txt"
                lock_status = "AKTIF (SISTEM KILITLI)" if os.path.exists(lock_file) else "PASIF (TEMIZ)"
                
                state_dict = {
                    "symbol": global_state_symbol,
                    "wallet_balance": float(engine.wallet_balance),
                    "position_amt": float(engine.position_amt),
                    "zscore": state.zscore,
                    "obi": state.obi,
                    "vpin": state.vpin,
                    "trend": trend,
                    "tick_count": strategy.tick_count,
                    "lake_files": lake_files,
                    "lake_size": lake_size,
                    "status_msg": "⏸ PAUSED" if strategy.paused else "▶️ RUNNING",
                    "lock_status": lock_status,
                    "ema_short": getattr(strategy, '_ema_short', 0.0),
                    "ema_long": getattr(strategy, '_ema_long', 0.0),
                    "rsi": getattr(strategy, '_last_rsi', 50.0),
                    "adx": getattr(strategy, '_last_adx', 50.0),
                    "signal": getattr(strategy, '_last_signal', 'NONE'),
                    "kline_ready": getattr(strategy, 'kline_ready', False),
                    "total_signals": len(getattr(strategy, 'signal_buffer', [])),
                    "buy_signals": sum(1 for s in getattr(strategy, 'signal_buffer', []) if s['signal'] == 'BUY'),
                    "sell_signals": sum(1 for s in getattr(strategy, 'signal_buffer', []) if s['signal'] == 'SELL'),
                    "none_signals": strategy.tick_count - len(getattr(strategy, 'signal_buffer', [])),
                }
                
                # Ağ Kopma ve Yeniden Başlama Takipçisi (Audit Daemon Metrics)
                try:
                    import core.audit
                    if os.path.exists(core.audit.AUDIT_FILE):
                        async with aiofiles.open(core.audit.AUDIT_FILE, "r") as f:
                            content = await f.read()
                            if content.strip():
                                audit_data = json.loads(content)
                                state_dict["restart_count"] = audit_data.get("restarts", 0)
                                state_dict["disconnect_count"] = audit_data.get("disconnects", 0)
                except Exception:
                    pass
                    
                import aiofiles
                async with aiofiles.open("core/data_lake/bot_state.json", "w") as f:
                    await f.write(json.dumps(state_dict))
            except Exception as e:
                logger.error(f"State exporter fault: {e}")

    async def tg_queue_listener_daemon():
        while True:
            await asyncio.sleep(0.5)
            try:
                while not tg_queue.empty():
                    cmd_tuple = tg_queue.get_nowait()
                    if cmd_tuple[0] == "TG_CMD":
                        cmd = cmd_tuple[1]
                        if cmd == "pause":
                            strategy.paused = True
                        elif cmd == "resume":
                            strategy.paused = False
                        elif cmd == "close":
                            pos = engine.position_amt
                            if pos != 0:
                                side = "SELL" if pos > 0 else "BUY"
                                from core.config import DRY_RUN
                                if DRY_RUN:
                                    asyncio.create_task(strategy._sim_exit_trade("MANUAL_CLOSE", float(lob.get_best_bid() if side=="SELL" else lob.get_best_ask())))
                                else:
                                    asyncio.create_task(engine.emergency_market_exit(lob.symbol, abs(pos), side))
                        elif cmd == "reload_ml":
                            strategy._load_ml_config()
            except Exception as e:
                logger.error(f"Telegram queue listener fault: {e}")

    asyncio.create_task(data_lake_compaction_task())
    asyncio.create_task(lob_sync_daemon())
    asyncio.create_task(symbol_switch_daemon()) # AŞAMA 16: Switch Daemon
    asyncio.create_task(dashboard_push_daemon())
    asyncio.create_task(shutdown_lock_clear_daemon())
    asyncio.create_task(system_monitoring_daemon())
    asyncio.create_task(state_exporter_daemon())
    asyncio.create_task(tg_queue_listener_daemon())
    try:
        await asyncio.gather(*tasks)
    except asyncio.CancelledError:
        logger.critical("SIGINT/SIGTERM (Kapanis) Algilandi!")
    finally:
        logger.critical("🛑 GRACEFUL SHUTDOWN PROTOKOLÜ BAŞLATILIYOR...")
        try:
            if 'engine' in locals():
                await engine.cancel_all_open_orders(global_state_symbol)
        except Exception as e:
            logger.error(f"Shutdown emir iptal hatası: {e}")
            
        try:
            import aiofiles
            state_dict = {
                "status_msg": "🛑 SHUTDOWN",
                "lock_status": "AKTIF (SISTEM KILITLI)"
            }
            async with aiofiles.open("core/data_lake/bot_state.json", "w") as f:
                await f.write(json.dumps(state_dict))
        except:
            pass
            
        logger.info("Main Event Loop Shutting Down: Tearing down active sockets securely...")
        await ws_client.close()
        await user_stream.close()
        await rest_client.close()
        if USE_TESTNET:
            await live_rest_client.close()

if __name__ == "__main__":
    import signal
    def sig_handler(sig, frame):
        raise KeyboardInterrupt()
    try:
        signal.signal(signal.SIGINT, sig_handler)
        signal.signal(signal.SIGTERM, sig_handler)
    except Exception:
        pass
        
    multiprocessing.set_start_method("spawn")
    setup_os_optimizations()
    setup_event_loop()
    
    data_queue = multiprocessing.Queue(maxsize=50000)
    signal_queue = multiprocessing.Queue(maxsize=100)
    tg_queue = multiprocessing.Queue(maxsize=100)
    
    brain_proc = multiprocessing.Process(target=brain_worker, args=(data_queue, signal_queue), daemon=True)
    brain_proc.start()
    
    from ctx_telegram import telegram_worker
    telegram_proc = multiprocessing.Process(target=telegram_worker, args=(tg_queue,), daemon=True)
    telegram_proc.start()
    
    try:
        asyncio.run(main(data_queue, signal_queue, brain_proc, tg_queue))
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot shutting down...")
    finally:
        data_queue.put(None)
        brain_proc.join(timeout=1.0)
        if brain_proc.is_alive():
            brain_proc.terminate()
        telegram_proc.join(timeout=1.0)
        if telegram_proc.is_alive():
            telegram_proc.terminate()

