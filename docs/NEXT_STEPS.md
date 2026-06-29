# 🗺️ Balina-Bot — Development Roadmap

## 📅 30-Day Milestone (Data Collection & Validation Phase)

### Goals
1. **aggTrade VPIN Backtest**: Use 30 days of real aggTrade data to calculate true VPIN (buyer/seller aggressor-based) and backtest whether VPIN filtering improves signal quality.
2. **Signal Log Analysis**: Compare signal logs against actual price movements to measure:
   - How many BUY signals led to >0.5% upward movement within 30 minutes?
   - How many SELL signals led to >0.5% downward movement within 30 minutes?
   - What is the "theoretical win rate" if we had perfect exits?
3. **Go/No-Go Decision**:
   - ✅ **Win rate ≥ 45%** → Proceed to live testing with minimal capital (50 USDT, no leverage)
   - ❌ **Win rate < 45%** → Pivot strategy (consider mean-reversion, funding rate arbitrage, or ML-based approach)

### Key Metrics to Track
- Signal accuracy (predicted direction vs. actual movement)
- Average favorable excursion (how far price moves in our favor before reversing)
- Average adverse excursion (how far price moves against us before reversing)
- VPIN correlation with losing trades

---

## 📅 60-Day Milestone (Live Validation Phase)

### Goals
1. **Evaluate Live Performance**: Review 30 days of live trading results (or extended DRY_RUN results).
2. **Capital Scaling Decision**:
   - ✅ **Profitable after fees** → Scale to 200 USDT with 2x leverage
   - ❌ **Unprofitable** → Return to DRY_RUN, iterate on strategy
3. **Infrastructure Hardening**:
   - Add automated daily performance reports via Telegram
   - Implement position reconciliation (compare bot state vs. exchange state)
   - Add database persistence for trade history (SQLite or PostgreSQL)

### Key Metrics to Track
- Realized PnL (net of all fees)
- Sharpe Ratio (target: > 1.0)
- Max Drawdown (target: < 10%)
- Win Rate (target: > 40%)
- Average trade duration

---

## 📅 90-Day Milestone (Growth Phase)

### Goals
1. **Data-Driven Decision**: Comprehensive review of 90 days of data.
2. **Capital Injection**: If profitable, allocate additional capital from freelance income.
3. **Multi-Strategy Exploration**:
   - Test a second strategy running in parallel (e.g., funding rate arbitrage)
   - Evaluate multi-pair trading (ETH, SOL alongside BTC)
4. **Advanced Features**:
   - Machine Learning signal enhancement (XGBoost/LightGBM on collected features)
   - Dynamic position sizing based on Kelly Criterion + regime detection
   - Trailing stop implementation using ATR

### Capital Allocation Plan
| Scenario | Action |
|----------|--------|
| Consistent profit, Sharpe > 1.5 | Scale to 500 USDT + 3x leverage |
| Marginal profit, Sharpe 0.5-1.5 | Stay at 200 USDT, continue optimizing |
| Break-even or slight loss | Keep at 50 USDT, pivot strategy |
| Significant loss | Full stop, return to research mode |

---

## 🔬 Research Backlog (No Timeline)

These are ideas to explore when time permits:

- [ ] **Funding Rate Arbitrage**: Exploit periodic funding rate payments on perpetual futures
- [ ] **Cross-Exchange Spread**: Monitor price differences between Binance and other exchanges
- [ ] **Order Flow Imbalance**: Use LOB depth imbalance as a short-term predictor
- [ ] **Sentiment Analysis**: Integrate Fear & Greed Index or social media sentiment
- [ ] **Regime Detection**: HMM (Hidden Markov Model) to classify market states automatically
- [ ] **Portfolio Optimization**: Multi-asset portfolio with correlation-based allocation

---

> ⚠️ **Reminder**: Never risk more than you can afford to lose. Always maintain a financial safety net outside of trading capital. This is a learning project first, a potential income source second.
