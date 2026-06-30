import time
import base64
import os
import requests
from dotenv import load_dotenv
from cryptography.hazmat.primitives.serialization import load_pem_private_key
from urllib.parse import urlencode

load_dotenv()
API_KEY = os.environ.get('BINANCE_API_KEY')
priv_key_str = os.environ.get('BINANCE_ED25519_PRIVATE_KEY', '').replace('\\n', '\n').strip('"')
pk = load_pem_private_key(priv_key_str.encode(), password=None)

def req(method, endpoint, params):
    params['recvWindow'] = 5000
    params['timestamp'] = int(time.time() * 1000)
    
    # Sort parameters to ensure Binance accepts them
    sorted_params = dict(sorted(params.items()))
    query_string = urlencode(sorted_params)
    
    # Sign
    signature = base64.b64encode(pk.sign(query_string.encode())).decode()
    
    url = f"https://fapi.binance.com{endpoint}?{query_string}&signature={signature}"
    headers = {'X-MBX-APIKEY': API_KEY}
    
    if method == "GET":
        r = requests.get(url, headers=headers)
    elif method == "DELETE":
        r = requests.delete(url, headers=headers)
    return r.json()

print("=== OPEN ORDERS ===")
orders = req("GET", "/fapi/v1/openOrders", {"symbol": "BTCUSDT"})
print(orders)

print("\n=== CANCEL ALL ===")
if orders and isinstance(orders, list) and len(orders) > 0:
    cancel = req("DELETE", "/fapi/v1/allOpenOrders", {"symbol": "BTCUSDT"})
    print(cancel)
else:
    print("No open orders to cancel.")

print("\n=== USER TRADES (Last 10) ===")
trades = req("GET", "/fapi/v1/userTrades", {"symbol": "BTCUSDT", "limit": 10})
if isinstance(trades, list):
    for t in trades:
        print(f"Time: {t.get('time')} | {t.get('side')} {t.get('qty')} @ {t.get('price')} | PnL: {t.get('realizedPnl')}")
else:
    print(trades)

print("\n=== INCOME (Last 10) ===")
income = req("GET", "/fapi/v1/income", {"symbol": "BTCUSDT", "limit": 10})
if isinstance(income, list):
    for i in income:
        print(f"Time: {i.get('time')} | Type: {i.get('incomeType')} | Asset: {i.get('asset')} | Amt: {i.get('income')}")
else:
    print(income)
