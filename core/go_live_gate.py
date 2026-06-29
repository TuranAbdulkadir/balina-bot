import os
import glob
import csv
import statistics
from core.logger_factory import get_logger

logger = get_logger("GoLiveGate")

class GoLiveGate:
    @staticmethod
    def evaluate(min_trades=100, min_win_rate=55.0, min_sharpe=1.5):
        """
        AŞAMA 19 (Görev 5): Bot DRY_RUN=False ile baslatilmadan once
        gecmis simulasyon sonuclarini denetler. Eger HFT algoritmamiz
        matematiksel olarak kanitlanmamissa botun gercek parayla calismasina izin vermez.
        """
        data_dir = "core/simulation_results"
        csv_files = glob.glob(os.path.join(data_dir, "sim_*.csv"))
        
        if not csv_files:
            logger.critical("🚨 GO-LIVE REDDEDILDI: Hic simulasyon (Dry-Run) gecmisi bulunamadi!")
            return False
            
        trade_count = 0
        win_count = 0
        pnl_history = []
        
        for file_path in csv_files:
            try:
                with open(file_path, mode="r", encoding="utf-8") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        net_pnl = float(row.get("net_pnl", 0))
                        trade_count += 1
                        pnl_history.append(net_pnl)
                        if net_pnl > 0:
                            win_count += 1
            except Exception as e:
                logger.error(f"Error reading {file_path}: {e}")
                
        if trade_count < min_trades:
            logger.critical(f"🚨 GO-LIVE REDDEDILDI: Yetersiz islem! Hedef: {min_trades}, Mevcut: {trade_count}")
            return False
            
        win_rate = (win_count / trade_count) * 100
        if win_rate < min_win_rate:
            logger.critical(f"🚨 GO-LIVE REDDEDILDI: Win Rate cok dusuk! Hedef: %{min_win_rate}, Mevcut: %{win_rate:.2f}")
            return False
            
        avg_pnl = sum(pnl_history) / trade_count
        stdev = statistics.stdev(pnl_history) if len(pnl_history) > 1 else 0
        sharpe = (avg_pnl / stdev) * (trade_count ** 0.5) if stdev > 0 else 0
        
        if sharpe < min_sharpe:
            logger.critical(f"🚨 GO-LIVE REDDEDILDI: Sharpe Ratio cok dusuk (Asiri Riskli)! Hedef: {min_sharpe}, Mevcut: {sharpe:.2f}")
            return False
            
        logger.info(f"✅ GO-LIVE ONAYLANDI: {trade_count} islem, %{win_rate:.2f} Win-Rate, {sharpe:.2f} Sharpe Ratio!")
        return True
