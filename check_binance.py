import asyncio
import os
from dotenv import load_dotenv
from network.http_client import BinanceRestClient
from core.config import BINANCE_API_KEY, BINANCE_ED25519_PRIVATE_KEY

async def main():
    rest = BinanceRestClient()
    print("=== RECENT TRADES ===")
    trades = await rest.get_signed("/fapi/v1/userTrades", {"symbol": "BTCUSDT", "limit": "100"})
    if trades and isinstance(trades, list):
        for t in trades[-10:]:
            print(f"{t.get('time')} | {t.get('side')} {t.get('qty')} @ {t.get('price')} (Realized PnL: {t.get('realizedPnl')})")
    else:
        print(trades)
        
    print("\n=== OPEN ORDERS ===")
    orders = await rest.get_signed("/fapi/v1/openOrders", {"symbol": "BTCUSDT"})
    print(orders)

    print("\n=== INCOME ===")
    income = await rest.get_signed("/fapi/v1/income", {"symbol": "BTCUSDT", "limit": "100"})
    if income and isinstance(income, list):
        for i in income[-10:]:
            print(f"{i.get('time')} | {i.get('incomeType')} | {i.get('income')}")
    else:
        print(income)

if __name__ == "__main__":
    asyncio.run(main())

