import asyncio
import aiohttp
import time
import base64
import os
from cryptography.hazmat.primitives.serialization import load_pem_private_key
from dotenv import load_dotenv

load_dotenv()
api_key = os.environ.get('BINANCE_API_KEY')
key_data = os.environ.get('BINANCE_ED25519_PRIVATE_KEY', '').replace('\\n', '\n').strip('"')

if not api_key:
    print("API Key missing")
    exit(1)

pk = load_pem_private_key(key_data.encode(), password=None)

async def req(session, endpoint, params=""):
    ts = str(int(time.time() * 1000))
    qs = f"recvWindow=5000&symbol=BTCUSDT&timestamp={ts}"
    if params:
        qs = f"{params}&{qs}"
    
    sig = base64.b64encode(pk.sign(qs.encode())).decode()
    url = f"https://fapi.binance.com{endpoint}?{qs}&signature={sig}"
    
    async with session.get(url, headers={'X-MBX-APIKEY': api_key}) as r:
        return await r.json()

async def main():
    async with aiohttp.ClientSession() as s:
        print("Fetching trades...")
        trades = await req(s, '/fapi/v1/userTrades', "limit=100")
        print("Fetching open orders...")
        orders = await req(s, '/fapi/v1/openOrders')
        print("Fetching positions...")
        pos = await req(s, '/fapi/v2/positionRisk')
        
        print('\n=== POSITIONS ===')
        if isinstance(pos, list):
            for p in pos:
                if float(p.get('positionAmt', 0)) != 0:
                    print(f"{p['symbol']} - {p['positionAmt']} @ {p['entryPrice']} (Lev: {p['leverage']}x)")
        
        print('\n=== RECENT TRADES ===')
        if isinstance(trades, list):
            for t in trades[-10:]:
                print(f"{t.get('time')} | {t.get('side')} {t.get('qty')} @ {t.get('price')} (Realized PnL: {t.get('realizedPnl')})")
        else:
            print(trades)
            
        print('\n=== OPEN ORDERS ===')
        print(orders)

if __name__ == "__main__":
    asyncio.run(main())
