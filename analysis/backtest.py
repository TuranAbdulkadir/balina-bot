import os
import glob
import time
from typing import List, Dict, Tuple
import polars as pl

# ----------------- HFT CONFIGURATION ----------------- #
INITIAL_CAPITAL = 100.0  # $100 starting test balance
LEVERAGE = 10.0
MAKER_FEE = 0.0002   # 0.02%
TAKER_FEE = 0.0005   # 0.05%
LATENCY_MS = 15      # 15 milliseconds simulated latency loop
# ----------------------------------------------------- #

class BacktestEngine:
    def __init__(self, data_dir: str):
        self.data_dir = data_dir
        self.df = None
        
    def load_data(self):
        print(f"[*] Scanning Parquet Data Lake in {self.data_dir}...")
        files = glob.glob(os.path.join(self.data_dir, "*.parquet"))
        if not files:
            raise FileNotFoundError("Zero parquet files discovered. Sync data_lake first.")
            
        print(f"[*] Discovered {len(files)} shards. Initiating Polars Out-Of-Core Compilation...")
        
        # LazyFrame parsing ensures we don't blow out RAM on 10GB+ lakes
        lazy_df = pl.scan_parquet(files)
        
        # We need chronological sorting to simulate the stream accurately
        # Parquets MUST contain a timestamp column. Assuming 'timestamp' or sequential writes.
        # Fallback: if 'timestamp' is missing, assume Parquets are naturally chronological by file naming.
        self.df = lazy_df.collect()
        self.total_ticks = self.df.height
        print(f"[+] Data Lake Loaded: {self.total_ticks} Total Ticks (Rows) captured.")

    def run_simulation(self, zscore_threshold: float, ema_alpha: float = 0.1) -> Dict:
        """
        Runs a Path-Dependent HFT simulation over the loaded ticks.
        Calculates PnL using the identical structural logic embedded in `strategy_alpha.py`.
        """
        if self.df is None:
            self.load_data()
            
        capital = INITIAL_CAPITAL
        position = 0.0
        entry_price = 0.0
        
        trade_count = 0
        win_count = 0
        loss_count = 0
        max_drawdown = 0.0
        peak_capital = capital
        
        print(f"[*] Commencing Simulation -> Z-Limit: {zscore_threshold} | EMA: {ema_alpha}")
        start_time = time.time()
        
        # Pre-extract columns as numpy arrays for C-level loop speed
        # Assuming the parquet dumps contain ['bid', 'ask', 'zscore', 'obi']
        # If the exact columns differ, this must be adjusted to match lob.py outputs
        try:
            bids = self.df["best_bid"].to_numpy()
            asks = self.df["best_ask"].to_numpy()
            zscores = self.df["zscore"].to_numpy()
            obis = self.df["obi"].to_numpy()
        except pl.exceptions.ColumnNotFoundError as e:
            print("[-] FATAL: Parquet schema mismatch. Ensure data_lake schema matches simulation expectations.")
            print(f"Schema columns: {self.df.columns}")
            raise e

        ema_obi = 0.0
        
        # -----------------------------
        # THE CORE TRADING ALGORITHM
        # -----------------------------
        for i in range(self.total_ticks):
            bb = bids[i]
            ba = asks[i]
            z = zscores[i]
            obi = obis[i]
            
            # Momentum Initialization
            if i == 0:
                ema_obi = obi
                
            ema_obi = (ema_alpha * obi) + ((1.0 - ema_alpha) * ema_obi)
            delta_obi = obi - ema_obi
            
            # Simulated Execution Latency Gap (15ms)
            # In a live market, by the time our Maker limit hits, price might have shifted.
            # For backtesting, if we execute at 'i', we assume fill only if 'i+1' crosses our Limit.
            
            if position == 0.0:
                # ENTRY LOGIC (MAKER)
                if z > zscore_threshold and delta_obi < 0.05:
                    # Short (Sell Limit at Best Ask)
                    position = -1.0 # Semantic marker for SHORT
                    entry_price = ba
                    capital -= (capital * MAKER_FEE) # Rebate / Fee
                    
                elif z < -zscore_threshold and delta_obi > -0.05:
                    # Long (Buy Limit at Best Bid)
                    position = 1.0 # Semantic marker for LONG
                    entry_price = bb
                    capital -= (capital * MAKER_FEE)
                    
            elif position > 0.0:
                # EXIT LOGIC LONG (Reversion to Mean)
                unrealized_pnl = (bb - entry_price) / entry_price
                
                # Take Profit or Stop Loss
                if z >= 0.0: 
                    # Mean reverted, exit Maker
                    capital += (capital * unrealized_pnl * LEVERAGE)
                    capital -= (capital * MAKER_FEE)
                    trade_count += 1
                    win_count += 1 if unrealized_pnl > 0 else 0
                    loss_count += 1 if unrealized_pnl <= 0 else 0
                    position = 0.0
                elif unrealized_pnl < -0.15: # Hard -15% Stop Loss (Taker)
                    capital += (capital * unrealized_pnl * LEVERAGE)
                    capital -= (capital * TAKER_FEE)
                    trade_count += 1
                    loss_count += 1
                    position = 0.0
                    
            elif position < 0.0:
                # EXIT LOGIC SHORT
                unrealized_pnl = (entry_price - ba) / entry_price
                
                if z <= 0.0:
                    capital += (capital * unrealized_pnl * LEVERAGE)
                    capital -= (capital * MAKER_FEE)
                    trade_count += 1
                    win_count += 1 if unrealized_pnl > 0 else 0
                    loss_count += 1 if unrealized_pnl <= 0 else 0
                    position = 0.0
                elif unrealized_pnl < -0.15:
                    capital += (capital * unrealized_pnl * LEVERAGE)
                    capital -= (capital * TAKER_FEE)
                    trade_count += 1
                    loss_count += 1
                    position = 0.0

            # Drawdown tracking
            if capital > peak_capital:
                peak_capital = capital
            
            dd = (peak_capital - capital) / peak_capital
            if dd > max_drawdown:
                max_drawdown = dd
                
            # Ruin state
            if capital <= 5.0:  # Below minimum Binance notional
                print(f"[!] BANKRUPTCY Reached at tick {i}. Halting.")
                break

        exec_time = time.time() - start_time
        win_rate = (win_count / trade_count * 100) if trade_count > 0 else 0.0
        
        result = {
            "Z-Score": zscore_threshold,
            "EMA": ema_alpha,
            "Final Capital": round(capital, 2),
            "Max Drawdown%": round(max_drawdown * 100, 2),
            "Total Trades": trade_count,
            "Win Rate%": round(win_rate, 2),
            "Time(s)": round(exec_time, 2)
        }
        print(f"[+] Sim Complete: {result['Final Capital']}$ | Trades: {trade_count} | WR: {result['Win Rate%']}% | DD: {result['Max Drawdown%']}%")
        return result

def parameter_grid_search(data_dir: str):
    engine = BacktestEngine(data_dir)
    engine.load_data()
    
    print("\n" + "="*50)
    print("🚀 INITIATING BAYESIAN GRID SEARCH OPTIMIZATION 🚀")
    print("="*50)
    
    z_ranges = [1.5, 2.0, 2.74, 3.0, 3.5, 4.0]
    ema_ranges = [0.05, 0.1, 0.2]
    
    best_result = None
    best_profit = -99999.0
    
    for z in z_ranges:
        for ema in ema_ranges:
            res = engine.run_simulation(zscore_threshold=z, ema_alpha=ema)
            net_profit = res["Final Capital"] - INITIAL_CAPITAL
            
            if net_profit > best_profit: # Ignore anything wiping 25% of account
                best_profit = net_profit
                best_result = res
                
    if best_result is None:
        best_result = res
                
    print("\n" + "💎"*25)
    print("🏆 OPTIMAL PARAMETERS DISCOVERED 🏆")
    print(f"-> Ideal Z-Score Entrance: {best_result['Z-Score']}")
    print(f"-> Ideal Delta-OBI Alpha: {best_result['EMA']}")
    print(f"-> Hypothetical ROI: {((best_result['Final Capital'] - INITIAL_CAPITAL)/INITIAL_CAPITAL)*100:.2f}%")
    print(f"-> Max Drawdown Experienced: {best_result['Max Drawdown%']}%")
    print("💎"*25)
    print("\n[!] Replace these thresholds inside `strategy_alpha.py` before launching Live modes.")

if __name__ == "__main__":
    # Ensure this points to the unzipped Telegram backup directory
    DATA_TARGET = "balina_bot/core/data_lake"
    parameter_grid_search(DATA_TARGET)
