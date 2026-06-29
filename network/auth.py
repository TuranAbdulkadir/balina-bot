import time
import base64
import urllib.parse
from core.logger_factory import get_logger
from cryptography.hazmat.primitives import serialization
from core.config import BINANCE_ED25519_PRIVATE_KEY, BINANCE_API_KEY
import os

logger = get_logger("Auth")

class BinanceEd25519Auth:
    def __init__(self):
        self.api_key = BINANCE_API_KEY
        self.private_key = self._load_private_key()
        self.time_offset_ms = 0

    def _load_private_key(self):
        try:
            pem_data = b""
            if BINANCE_ED25519_PRIVATE_KEY:
                pem_data = BINANCE_ED25519_PRIVATE_KEY.replace('\\n', '\n').encode('utf-8')
            else:
                logger.error("No Ed25519 key provided in environment!")
                return None
            private_key = serialization.load_pem_private_key(pem_data, password=None)
            logger.info("Ed25519 Private Key successfully loaded.")
            return private_key
        except Exception as e:
            logger.error(f"Failed to load Ed25519 private key: {e}")
            return None

    def sign_request_query(self, params: dict) -> str:
        if not self.private_key:
            raise ValueError("Ed25519 Private key not loaded! Cannot sign request.")

        payload = params.copy() if params else {}
        payload["timestamp"] = int(time.time() * 1000) + self.time_offset_ms
        payload["recvWindow"] = 5000

        query_string = urllib.parse.urlencode(sorted(payload.items()))
        signature_bytes = self.private_key.sign(query_string.encode('utf-8'))
        signature_b64 = base64.b64encode(signature_bytes).decode('utf-8')
        return f"{query_string}&signature={urllib.parse.quote(signature_b64)}"

    def get_headers(self) -> dict:
        return {
            "X-MBX-APIKEY": self.api_key,
            "Content-Type": "application/x-www-form-urlencoded"
        }
