# System Architecture

## Event Loop Design
The core of Balina-Bot relies on Python's `asyncio` for non-blocking I/O. The main event loop handles WebSocket streams from Binance (LOB, Ticker, MarkPrice, Klines) simultaneously, passing messages to handlers instantly.

## Multi-Process Architecture
To avoid the Global Interpreter Lock (GIL) and prevent CPU-intensive math from blocking the WebSocket stream, the bot employs `multiprocessing`:
- **Main Process**: Handles network I/O, WebSockets, and rapid decision-making.
- **Brain Process**: (Currently isolated) Can be used for heavy ML/AI inference and quantitative calculations without slowing down the data stream.
- **Telegram Process**: A separate daemon to handle long-polling updates from the Telegram bot API so user interactions do not interrupt trading logic.
- **Data Collector**: A standalone process saving Parquet files to the Data Lake.

## WebSocket Data Pipeline
1. `wss://fstream.binance.com/stream` is connected with multiple combined streams.
2. Messages are unpacked directly from JSON.
3. Relevant handlers (`process_kline`, `process_lob`) immediately process the tick.
4. Circuit Breakers evaluate trading volume anomalies in O(1) time.

## Order Execution Flow
1. Strategy triggers a `BUY` or `SELL`.
2. Risk management (Kelly Criterion) verifies wallet balance.
3. Ed25519 payload is signed locally.
4. Asynchronous HTTP POST is fired to Binance.
5. Latency is tracked; positions are managed.

## Risk Management Layers
1. **VPIN Toxic Flow**: Identifies aggressive, one-sided order flow imbalances.
2. **Global Circuit Breaker**: Disables trading during sudden volume spikes.
3. **Kelly Criterion**: Dynamic position sizing based on win rate and R/R.
4. **Max Drawdown Lock**: Hard limit on portfolio loss.
