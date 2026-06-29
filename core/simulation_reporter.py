import os
import csv
import time
import asyncio
from datetime import datetime
from core.logger_factory import get_logger
import statistics

logger = get_logger("SimReporter")

class SimulationReporter:
    def __init__(self, data_dir="core/simulation_results"):
        self.data_dir = data_dir
        os.makedirs(self.data_dir, exist_ok=True)
        self.lock = asyncio.Lock()
        
        self.trade_count = 0
        self.win_count = 0
        self.total_net_pnl = 0.0
        self.max_win = 0.0
        self.max_loss = 0.0
        self.total_slippage = 0.0
        self.pnl_history = []
        
        # AŞAMA 19: Gunluk kümülatif PnL gecmisini yukle (Kelly Kriteri icin)
        self._load_daily_history()

    def _load_daily_history(self):
        import csv
        today_str = datetime.utcnow().strftime("%Y%m%d")
        file_path = os.path.join(self.data_dir, f"sim_{today_str}.csv")
        if os.path.exists(file_path):
            try:
                with open(file_path, mode="r", encoding="utf-8") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        net_pnl = float(row.get("net_pnl", 0))
                        self.trade_count += 1
                        self.total_net_pnl += net_pnl
                        self.pnl_history.append(net_pnl)
                        if net_pnl > 0:
                            self.win_count += 1
                            if net_pnl > self.max_win:
                                self.max_win = net_pnl
                        else:
                            if net_pnl < self.max_loss:
                                self.max_loss = net_pnl
                logger.info(f"💾 Bugunun CSV'sinden {self.trade_count} islem yuklendi (Kelly & Reporter icin).")
            except Exception as e:
                logger.error(f"Daily history yukleme hatasi: {e}")

    async def log_trade(self, trade_data: dict):
        today_str = datetime.utcnow().strftime("%Y%m%d")
        file_path = os.path.join(self.data_dir, f"sim_{today_str}.csv")
        file_exists = os.path.isfile(file_path)
        
        fieldnames = [
            "timestamp", "symbol", "side", "entry_price", "exit_price", "qty",
            "gross_pnl", "fee", "net_pnl", "slippage", "exit_reason", 
            "zscore_at_entry", "vpin_at_entry", "obi_at_entry"
        ]
        
        async with self.lock:
            await asyncio.to_thread(self._write_csv, file_path, fieldnames, file_exists, trade_data)
            
            self.trade_count += 1
            net_pnl = trade_data.get("net_pnl", 0.0)
            self.total_net_pnl += net_pnl
            self.total_slippage += trade_data.get("slippage", 0.0)
            self.pnl_history.append(net_pnl)
            
            if net_pnl > 0:
                self.win_count += 1
                if net_pnl > self.max_win:
                    self.max_win = net_pnl
            else:
                if net_pnl < self.max_loss:
                    self.max_loss = net_pnl
                    
            if self.trade_count % 50 == 0:
                self._print_stats()

    def _write_csv(self, file_path, fieldnames, file_exists, trade_data):
        with open(file_path, mode="a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            if not file_exists:
                writer.writeheader()
            writer.writerow(trade_data)
            
    def _print_stats(self):
        win_rate = (self.win_count / self.trade_count) * 100 if self.trade_count > 0 else 0
        avg_pnl = self.total_net_pnl / self.trade_count if self.trade_count > 0 else 0
        avg_slip = self.total_slippage / self.trade_count if self.trade_count > 0 else 0
        
        sharpe = 0.0
        if len(self.pnl_history) > 1:
            stdev = statistics.stdev(self.pnl_history)
            if stdev > 0:
                sharpe = (avg_pnl / stdev) * (min(self.trade_count, 50) ** 0.5) 
                
        logger.info("========================================")
        logger.info(f"📈 SIMULATION / LIVE STATS (Trades: {self.trade_count})")
        logger.info("========================================")
        logger.info(f"Win Rate        : %{win_rate:.2f}")
        logger.info(f"Ortalama Net PnL: ${avg_pnl:.4f}")
        logger.info(f"Toplam Net PnL  : ${self.total_net_pnl:.4f}")
        logger.info(f"En Buyuk Kazanc : ${self.max_win:.4f}")
        logger.info(f"En Buyuk Kayip  : ${self.max_loss:.4f}")
        logger.info(f"Ort. Slippage   : ${avg_slip:.4f}")
        logger.info(f"Sharpe Ratio    : {sharpe:.2f}")
        logger.info("========================================")
