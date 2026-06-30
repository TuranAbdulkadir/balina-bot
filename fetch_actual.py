import os
from dotenv import load_dotenv
from binance.um_futures import UMFutures

load_dotenv()
api_key = os.environ.get('BINANCE_API_KEY')
# binance-futures-connector supports ed25519 by just passing the private key string or path
# but actually wait, binance-futures-connector takes private_key. Let's see.
# The user's env has BINANCE_ED25519_PRIVATE_KEY inline.
private_key = os.environ.get('BINANCE_ED25519_PRIVATE_KEY', '').replace('\\n', '\n').strip('"')

client = UMFutures(key=api_key, private_key=private_key)

print("=== OPEN ORDERS ===")
try:
    print(client.get_orders(symbol="BTCUSDT"))
except Exception as e:
    print(f"Error fetching orders: {e}")

print("\n=== RECENT TRADES ===")
try:
    trades = client.get_account_trades(symbol="BTCUSDT", limit=100)
    for t in trades[-10:]:
        print(f"{t.get('time')} | {t.get('side')} {t.get('qty')} @ {t.get('price')} (Realized PnL: {t.get('realizedPnl')})")
except Exception as e:
    print(f"Error fetching trades: {e}")

print("\n=== INCOME ===")
try:
    income = client.get_income_history(symbol="BTCUSDT", limit=100)
    for i in income[-10:]:
        print(f"{i.get('time')} | {i.get('incomeType')} | {i.get('income')}")
except Exception as e:
    print(f"Error fetching income: {e}")
