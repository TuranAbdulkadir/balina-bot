import os
import sys
from core.logger_factory import get_logger
from dotenv import load_dotenv

logger = get_logger("Config")

load_dotenv()

BINANCE_API_KEY = os.getenv("BINANCE_API_KEY", "").strip()
BINANCE_ED25519_PRIVATE_KEY = os.getenv("BINANCE_ED25519_PRIVATE_KEY", "").strip()
TG_TOKEN = os.getenv("TG_TOKEN", "").strip()
TG_USER_ID = os.getenv("TG_USER_ID", "").strip()
# AŞAMA 18: Yetkili kullanıcı ID'si
TELEGRAM_ALLOWED_USER_ID = os.getenv("TELEGRAM_ALLOWED_USER_ID", TG_USER_ID).strip()

# WARMUP_MODE enabled defaults allowing Data Lake generation offline mimicking physical tests without executing real capital constraints
WARMUP_MODE = False  # GERÇEK TİCARETE GEÇİŞ YAPILDI (Güvenlik ağları aktifken parayı piyasaya sürüyoruz)
DRY_RUN = True       # GERÇEK PARA RİSKE ATILIYOR! ⚠️

# AŞAMA 19: Zaman ve Max Drawdown Kilitleri
MAX_POSITION_HOLD_SECONDS = 300
MAX_DRAWDOWN_PCT = 0.008 # %0.8

# AŞAMA 29: Trend Following (EMA + RSI) Stratejisi
EMA_SHORT = 21
EMA_LONG = 50
RSI_PERIOD = 14
RSI_BUY_MIN = 60
RSI_SELL_MAX = 40
TAKE_PROFIT_PCT = 0.015
STOP_LOSS_PCT = 0.005
KLINE_WARMUP_COUNT = 50
KLINE_INTERVAL = "5m"
VOLUME_MULTIPLIER = 2.0

# GECICI: Sembol Sabitleme
SYMBOL = "BTCUSDT"
DISABLE_SYMBOL_SELECTOR = True

# AŞAMA 13: TESTNET DUAL-ENDPOINT MİMARİSİ
USE_TESTNET = False
LIVE_WS_URL = "wss://fstream.binance.com/ws"
LIVE_REST_URL = "https://fapi.binance.com"
TESTNET_REST_URL = "https://testnet.binancefuture.com"

if not BINANCE_API_KEY or not BINANCE_ED25519_PRIVATE_KEY:
    logger.critical("Kritik Hata: BINANCE_API_KEY veya BINANCE_ED25519_PRIVATE_KEY .env dosyasinda bulunamadi!")
    sys.exit(1)
