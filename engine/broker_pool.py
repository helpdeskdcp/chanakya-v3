"""
Chanakya v3 — Per-User Broker Pool
Thread-safe, auto-reconnect, isolated per user
"""
import logging, threading, time, pytz
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)
IST = pytz.timezone("Asia/Kolkata")

_pool = {}
_lock = threading.Lock()

class UserBroker:
    def __init__(self, username):
        self.username   = username
        self.api        = None
        self.connected  = False
        self.user_name  = ""
        self.client_id  = ""
        self.capital    = 0.0
        self.last_sync  = None
        self._creds     = {}  # Store creds for auto-reconnect
        self._sess_lock = threading.Lock()

    def connect(self, api_key, client_id, password, totp_key):
        with self._sess_lock:
            try:
                import pyotp
                from SmartApi import SmartConnect
                self._creds = {
                    "api_key":api_key,"client_id":client_id,
                    "password":password,"totp_key":totp_key
                }
                self.api = SmartConnect(api_key=api_key)
                totp = pyotp.TOTP(totp_key).now()
                resp = self.api.generateSession(client_id, password, totp)
                if resp and resp.get("status"):
                    data = resp.get("data", {})
                    self.user_name  = data.get("name", client_id)
                    self.client_id  = client_id
                    self.connected  = True
                    self.last_sync  = datetime.now(IST)
                    self._fetch_capital()
                    logger.info(f"✅ {self.username}: {self.user_name}")
                    return True
                else:
                    logger.warning(f"❌ {self.username}: {resp.get('message','')}")
                    self.connected = False
                    return False
            except Exception as e:
                logger.error(f"Broker {self.username}: {e}")
                self.connected = False
                return False

    def ensure_connected(self):
        """Auto-reconnect if session expired"""
        if not self.connected or self.api is None:
            if self._creds:
                return self.connect(**self._creds)
            return False
        # Session age check — 12 hours
        if self.last_sync:
            age = (datetime.now(IST) - self.last_sync).total_seconds()
            if age > 43200:
                logger.info(f"{self.username} session expired — reconnecting")
                if self._creds:
                    return self.connect(**self._creds)
        return True

    def _fetch_capital(self):
        try:
            rms = self.api.rmsLimit()
            if rms and rms.get("data"):
                self.capital = float(
                    rms["data"].get("availablecash") or
                    rms["data"].get("net") or 0
                )
        except Exception:
            self.capital = 0.0

    def get_funds(self):
        self.ensure_connected()
        self._fetch_capital()
        return self.capital

    def get_ltp(self, exchange, symbol, token):
        self.ensure_connected()
        try:
            d = self.api.ltpData(exchange, symbol, token)
            if d and d.get("data"):
                return float(d["data"]["ltp"])
        except Exception as e:
            logger.debug(f"LTP {symbol}: {e}")
        return 0.0

    def place_order(self, params, paper_mode=True):
        """Place order — isolated per user"""
        if paper_mode:
            import time as _t
            logger.info(f"PAPER {self.username}: {params.get('tradingsymbol','')} {params.get('transactiontype','')}")
            return f"PAPER_{int(_t.time())}"
        self.ensure_connected()
        try:
            resp = self.api.placeOrder(params)
            if resp and resp.get("status"):
                return resp["data"]["orderid"]
        except Exception as e:
            logger.error(f"Order {self.username}: {e}")
        return None

    def get_positions(self):
        """Get positions — isolated per user"""
        self.ensure_connected()
        try:
            d = self.api.position()
            if d and d.get("data"):
                return d["data"]
        except Exception:
            pass
        return []


def get_broker(username):
    """Get or create broker — thread safe"""
    with _lock:
        ub = _pool.get(username)
        if ub and ub.connected:
            return ub

    try:
        from data.users import get_broker_credentials
        creds = get_broker_credentials(username)
        if not creds or not creds.get("api_key"):
            return None

        ub = UserBroker(username)
        ok = ub.connect(
            creds["api_key"], creds["client_id"],
            creds["password"], creds["totp_key"],
        )
        if ok:
            with _lock:
                _pool[username] = ub
            return ub
    except Exception as e:
        logger.error(f"get_broker {username}: {e}")
    return None


def get_broker_info(username):
    """Cache-only status — no fresh connect"""
    with _lock:
        ub = _pool.get(username)
    if ub and ub.connected:
        return {
            "connected": True,
            "user_name": ub.user_name,
            "client_id": ub.client_id,
            "capital":   ub.capital,
            "last_sync": ub.last_sync.isoformat() if ub.last_sync else None,
        }
    return {"connected":False,"user_name":"","client_id":"","capital":0.0}


def keep_alive_all():
    """Background thread — keep all active brokers alive"""
    while True:
        time.sleep(3600)  # Every hour
        with _lock:
            users = list(_pool.keys())
        for username in users:
            try:
                with _lock:
                    ub = _pool.get(username)
                if ub:
                    ub.ensure_connected()
            except Exception:
                pass


def clear_broker(username):
    with _lock:
        _pool.pop(username, None)


# Start keep-alive thread
_ka = threading.Thread(target=keep_alive_all, daemon=True)
_ka.start()
