# Trading Strategy

> **Note**: This strategy is under active development. Current implementations are experimental and are continuously backtested.

## Current Strategy: EMA Crossover + RSI + ADX Trend Filter
Balina-Bot operates on a 5-minute timeframe (BTCUSDT) utilizing a classic trend-following strategy heavily filtered by momentum and trend strength indicators.

### Indicators & Parameters
- **EMA Short (21) & EMA Long (50)**: Used for identifying the primary trend direction and crossover entry signals.
- **RSI (14)**: Momentum filter. 
  - Buy requires RSI > 60. 
  - Sell requires RSI < 40.
- **ADX (14)**: Pure Python implementation of Wilder's DMI. Entries are restricted unless ADX > 25, cutting out sideways "chop" and whipsaws.
- **Volume Anomaly**: A trade is only taken if the current candle's volume is > 2.0x the 20-period Simple Moving Average of volume.

### Risk / Reward
- **Take Profit (TP)**: 1.5%
- **Stop Loss (SL)**: 0.5%
- Risk-to-Reward ratio is mathematically 1:3.

### Recent Backtest Results (180 Days, 5m TF)
* **Total Candles processed**: 51,840
* **Train Set (120 Days)**: 375 trades, 29.60% Win Rate, -111.38 USDT PnL
* **Test Set (60 Days)**: 199 trades, 25.63% Win Rate, -140.24 USDT PnL
* **Market Regimes**: Strong Downtrends (29% WR), Strong Uptrends (29% WR). 

### Known Issues & Planned Improvements
Currently, the fixed Take Profit (1.5%) is rarely hit, resulting in the strategy bleeding capital through Stop Losses (0.5%) and Reversals. 
- **Next steps**: Implement trailing stop-losses based on ATR (Average True Range) and introduce machine-learning based entry classifications to improve the win rate above the 35% breakeven threshold.
