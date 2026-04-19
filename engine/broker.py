"""
Chanakya v3 — AngelOne SmartAPI Connector
Auto-reconnect + daily session refresh
"""
import logging, time, threading, pyotp
from datetime import datetime, timedelta
import pytz
from config import config

logger = logging.getLogger(__name__)
IST = pytz.timezone("Asia/Kolkata")

class BrokerAPI:
    def __init__(self):
        self.api        = None
        self.connected  = False
        self.user_name  = ""
        self.auth_token = ""
        self._last_connected = None
        self._lock = threading.Lock()

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
                    self.connected  = True
                    self.auth_token = data["data"]["jwtToken"]
                    self._last_connected = datetime.now(IST)
                    profile = self.api.getProfile(data["data"]["refreshToken"])
                    self.user_name = profile.get("data",{}).get("name","Unknown")
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

    def ensure_connected(self):
        """Auto-reconnect if session expired (>12 hours)"""
        with self._lock:
            if not self.connected or self.api is None:
                logger.info("Broker disconnected — reconnecting...")
                return self.connect()
            # Check session age
            if self._last_connected:
                age = (datetime.now(IST) - self._last_connected).total_seconds()
                if age > 43200:  # 12 hours
                    logger.info(f"Session {age/3600:.1f}h old — refreshing...")
                    return self.connect()
            # Quick health check
            try:
                r = self.api.rmsLimit()
                if not r or not r.get("status"):
                    logger.info("Session invalid — reconnecting...")
                    return self.connect()
            except Exception:
                logger.info("Session check failed — reconnecting...")
                return self.connect()
            return True

    def get_ltp(self, exchange, symbol, token):
        self.ensure_connected()
        try:
            d = self.api.ltpData(exchange, symbol, token)
            if d and d.get("status") and d.get("data"):
                return float(d["data"]["ltp"])
        except Exception as e:
            logger.debug(f"LTP error {symbol}: {e}")
        return 0.0

    def get_funds(self):
        self.ensure_connected()
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
        self.ensure_connected()
        try:
            resp = self.api.placeOrder(params)
            if resp and resp.get("status"):
                return resp["data"]["orderid"]
        except Exception as e:
            logger.error(f"Order error: {e}")
        return None

    def get_positions(self):
        self.ensure_connected()
        try:
            d = self.api.position()
            if d and d.get("data"):
                return d["data"]
        except Exception:
            pass
        return []

    def start_session_refresh(self):
        """Background thread — refresh session at 8 AM daily"""
        def _refresh_loop():
            while True:
                try:
                    now = datetime.now(IST)
                    # Refresh at 8:15 AM (market open time)
                    next_refresh = now.replace(hour=8, minute=15, second=0)
                    if now >= next_refresh:
                        next_refresh += timedelta(days=1)
                    sleep_secs = (next_refresh - now).total_seconds()
                    logger.info(f"Next session refresh in {sleep_secs/3600:.1f}h")
                    time.sleep(sleep_secs)
                    logger.info("🔄 Scheduled session refresh...")
                    self.connect()
                except Exception as e:
                    logger.error(f"Session refresh error: {e}")
                    time.sleep(3600)  # retry in 1 hour

        t = threading.Thread(target=_refresh_loop, daemon=True)
        t.start()
        logger.info("✅ Session refresh scheduler started")

broker = BrokerAPI()
