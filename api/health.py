import os
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
import uvicorn
import time

app = FastAPI(title="Balina-Bot Micro Endpoint", version="1.0.0")

class BotState:
    last_update: float = 0.0
    start_time: float = time.time()
    status: str = "starting"
    latency_ms: float = 0.0
    wallet_balance: float = 0.0
    open_orders: int = 0
    unrealized_pnl: float = 0.0
    
    # Yeni Strateji Metrikleri
    total_signals: int = 0
    buy_signals: int = 0
    sell_signals: int = 0
    none_signals: int = 0
    current_ema_short: float = 0.0
    current_ema_long: float = 0.0
    current_rsi: float = 0.0
    current_adx: float = 0.0
    last_signal_time: str = ""

state = BotState()
state.last_update = time.time()

@app.get("/telemetry")
async def get_telemetry():
    now = time.time()
    return {
        "status": state.status,
        "uptime": now - state.last_update,
        "latency_ms": state.latency_ms,
        "wallet_balance": state.wallet_balance,
        "open_orders": state.open_orders,
        "unrealized_pnl": state.unrealized_pnl
    }

@app.get("/performance")
async def get_performance():
    from core.config import DRY_RUN
    now = time.time()
    uptime_hours = (now - state.start_time) / 3600.0
    
    return {
        "dry_run": DRY_RUN,
        "total_signals": state.total_signals,
        "buy_signals": state.buy_signals,
        "sell_signals": state.sell_signals,
        "none_signals": state.none_signals,
        "current_ema_short": state.current_ema_short,
        "current_ema_long": state.current_ema_long,
        "current_rsi": state.current_rsi,
        "current_adx": state.current_adx,
        "last_signal_time": state.last_signal_time,
        "uptime_hours": round(uptime_hours, 2)
    }

@app.post("/update")
async def update_telemetry(data: dict):
    state.status = data.get("status", state.status)
    state.latency_ms = data.get("latency_ms", state.latency_ms)
    state.wallet_balance = data.get("wallet_balance", state.wallet_balance)
    state.open_orders = data.get("open_orders", state.open_orders)
    state.unrealized_pnl = data.get("unrealized_pnl", state.unrealized_pnl)
    
    # Yeni Metrikler
    state.total_signals = data.get("total_signals", state.total_signals)
    state.buy_signals = data.get("buy_signals", state.buy_signals)
    state.sell_signals = data.get("sell_signals", state.sell_signals)
    state.none_signals = data.get("none_signals", state.none_signals)
    state.current_ema_short = data.get("current_ema_short", state.current_ema_short)
    state.current_ema_long = data.get("current_ema_long", state.current_ema_long)
    state.current_rsi = data.get("current_rsi", state.current_rsi)
    state.current_adx = data.get("current_adx", state.current_adx)
    state.last_signal_time = data.get("last_signal_time", state.last_signal_time)
    
    state.last_update = time.time()
    return {"ok": True}

@app.get("/dashboard", response_class=HTMLResponse)
async def serve_dashboard():
    dashboard_path = os.path.join(os.path.dirname(__file__), "dashboard.html")
    try:
        with open(dashboard_path, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return "<h1>Dashboard UI Constructing... Please wait.</h1>"

async def run_fastapi():
    # loop="none" tells uvicorn to use current running asyncio loop instead of creating a new one
    config = uvicorn.Config(app, host="0.0.0.0", port=8000, log_level="warning", loop="none")
    server = uvicorn.Server(config)
    await server.serve()
