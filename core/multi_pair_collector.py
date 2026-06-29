import asyncio
import json
import time
import os
import websockets
import pandas as pd

# Data Lake paths
DATA_LAKE_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "core", "data_lake", "aggtrade")
os.makedirs(DATA_LAKE_PATH, exist_ok=True)

class MultiPairCollector:
    def __init__(self):
        self.ws_url = "wss://fstream.binance.com/stream?streams=btcusdt@aggTrade/btcusdt@bookTicker"
        self.buffer = []
        self.buffer_limit = 10000

    def flush_buffer(self):
        if not self.buffer:
            return
        
        df = pd.DataFrame(self.buffer)
        timestamp_start = self.buffer[0]['timestamp']
        filename = f"aggtrade_BTCUSDT_{timestamp_start}.parquet"
        filepath = os.path.join(DATA_LAKE_PATH, filename)
        
        df.to_parquet(filepath, engine='pyarrow')
        print(f"[Collector] Saved {len(self.buffer)} events to {filepath}")
        self.buffer = []

    async def run(self):
        print(f"[Collector] Connecting to {self.ws_url}")
        async for websocket in websockets.connect(self.ws_url):
            try:
                async for message in websocket:
                    data = json.loads(message)
                    if "data" not in data:
                        continue
                    
                    event = data["data"]
                    event_type = event.get("e")
                    
                    if event_type == "aggTrade":
                        # Parse aggTrade
                        # {
                        #   "e": "aggTrade",  // Event type
                        #   "E": 123456789,   // Event time
                        #   "s": "BTCUSDT",    // Symbol
                        #   "a": 5933014,     // Aggregate trade ID
                        #   "p": "0.001",     // Price
                        #   "q": "100",       // Quantity
                        #   "f": 100,         // First trade ID
                        #   "l": 105,         // Last trade ID
                        #   "T": 123456785,   // Trade time
                        #   "m": true,        // Is the buyer the market maker?
                        # }
                        record = {
                            "timestamp": int(event["T"]),
                            "symbol": event["s"],
                            "price": float(event["p"]),
                            "qty": float(event["q"]),
                            "side": "SELL" if event["m"] else "BUY",
                            "is_market_maker": event["m"]
                        }
                        
                        self.buffer.append(record)
                        
                        if len(self.buffer) >= self.buffer_limit:
                            self.flush_buffer()

            except websockets.ConnectionClosed:
                print("[Collector] Connection closed, reconnecting...")
                self.flush_buffer()
                await asyncio.sleep(2)
            except Exception as e:
                print(f"[Collector] Error: {e}")
                self.flush_buffer()
                await asyncio.sleep(2)

if __name__ == "__main__":
    collector = MultiPairCollector()
    try:
        asyncio.run(collector.run())
    except KeyboardInterrupt:
        collector.flush_buffer()
        print("[Collector] Shutdown.")
