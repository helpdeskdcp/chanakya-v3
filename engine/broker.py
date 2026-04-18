"""
Chanakya v3 — AngelOne SmartAPI Connector
Auto-reconnect + retry logic
"""
import logging, time, pyotp
from config import config

logger = logging.getLogger(__name__)

class BrokerAPI:
    def __init__(self):
        self.api      = None
        self.connected = False
        self.user_name = ""
        self.auth_token = ""

    def connect(self, max_retries=3):
        from SmartApi import SmartConnect
        delays = [30, 60, 90]
        for attempt in range(max_retries):
            try:
                self.api = SmartConnect(api_key=config.ANGEL_API_KEY)
                totp = pyotp.TOTP(config.ANGEL_TOTP_KEY).now()
                data = self.api.generateSession(
                    config.ANGEL_CLIENT_ID,
                    config.ANGEL_PASSWORD,
                    totp
                )
                if data.get("status"):
                    self.connected = True
                    self.auth_token = data["data"]["jwtToken"]
                    profile = self.api.getProfile(data["data"]["refreshToken"])
                    self.user_name = profile.get("data", {}).get("name", "Unknown")
                    logger.info(f"✅ Connected: {self.user_name} (attempt {attempt+1})")
                    return True
                else:
                    logger.warning(f"Login failed: {data.get('message')}")
            except Exception as e:
                logger.error(f"Connect error attempt {attempt+1}: {e}")
                if attempt < max_retries - 1:
                    time.sleep(delays[attempt])
        self.connected = False
        return False

    def get_ltp(self, exchange, symbol, token):
        try:
            d = self.api.ltpData(exchange, symbol, token)
            if d and d.get("status") and d.get("data"):
                return float(d["data"]["ltp"])
        except Exception as e:
            logger.debug(f"LTP error {symbol}: {e}")
        return 0.0

    def get_funds(self):
        try:
            d = self.api.rmsLimit()
            if d and d.get("data"):
                return float(d["data"].get("availablecash", 0))
        except Exception:
            pass
        return config.PAPER_CAPITAL

    def place_order(self, params):
        if config.PAPER_MODE:
            logger.info(f"📝 PAPER ORDER: {params}")
            return f"PAPER_{int(time.time())}"
        try:
            resp = self.api.placeOrder(params)
            if resp and resp.get("status"):
                return resp["data"]["orderid"]
        except Exception as e:
            logger.error(f"Order error: {e}")
        return None

    def get_positions(self):
        try:
            d = self.api.position()
            if d and d.get("data"):
                return d["data"]
        except Exception:
            pass
        return []

broker = BrokerAPI()
