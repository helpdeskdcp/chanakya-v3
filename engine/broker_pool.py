"""
Chanakya v3 — Per-User Broker Pool
Each user gets their own Angel One connection
"""
import logging, threading
import pytz
from datetime import datetime

logger = logging.getLogger(__name__)
IST = pytz.timezone("Asia/Kolkata")

# Cache — {username: BrokerInstance}
_pool = {}
_lock = threading.Lock()

class UserBroker:
    """Individual broker instance per user"""
    def __init__(self, username):
        self.username  = username
        self.api       = None
        self.connected = False
        self.user_name = ""
        self.client_id = ""
        self.capital   = 0.0
        self.last_sync = None

    def connect(self, api_key, client_id, password, totp_key):
        try:
            import pyotp
            from SmartApi import SmartConnect
            self.api = SmartConnect(api_key=api_key)
            totp = pyotp.TOTP(totp_key).now()
            resp = self.api.generateSession(client_id, password, totp)
            if resp and resp.get("status"):
                data = resp.get("data", {})
                self.user_name = data.get("name", client_id)
                self.client_id = client_id
                self.connected = True
                self.last_sync = datetime.now(IST)
                self._fetch_capital()
                logger.info(f"✅ {self.username} broker: {self.user_name}")
                return True
            else:
                logger.warning(f"❌ {self.username} broker: {resp.get('message','')}")
                return False
        except Exception as e:
            logger.error(f"Broker connect {self.username}: {e}")
            return False

    def _fetch_capital(self):
        try:
            rms = self.api.rmsLimit()
            if rms and rms.get("data"):
                self.capital = float(
                    rms["data"].get("availablecash") or
                    rms["data"].get("net") or 0
                )
        except Exception:
            pass

    def get_funds(self):
        self._fetch_capital()
        return self.capital

    def get_ltp(self, exchange, symbol, token):
        try:
            d = self.api.ltpData(exchange, symbol, token)
            if d and d.get("data"):
                return float(d["data"]["ltp"])
        except Exception:
            pass
        return 0.0

    def refresh(self, api_key, client_id, password, totp_key):
        """Reconnect if session expired"""
        return self.connect(api_key, client_id, password, totp_key)


def get_broker(username):
    """Get or create broker instance for user"""
    with _lock:
        if username in _pool and _pool[username].connected:
            return _pool[username]

    # Try to connect with user's credentials
    try:
        from data.users import get_broker_credentials
        creds = get_broker_credentials(username)
        if not creds or not creds.get("api_key"):
            return None

        ub = UserBroker(username)
        ok = ub.connect(
            creds["api_key"],
            creds["client_id"],
            creds["password"],
            creds["totp_key"],
        )
        if ok:
            with _lock:
                _pool[username] = ub
            return ub
    except Exception as e:
        logger.error(f"get_broker {username}: {e}")
    return None


def get_broker_info(username):
    """Get broker name + capital for a user"""
    ub = get_broker(username)
    if ub and ub.connected:
        return {
            "connected":  True,
            "user_name":  ub.user_name,
            "client_id":  ub.client_id,
            "capital":    ub.get_funds(),
            "last_sync":  ub.last_sync.isoformat() if ub.last_sync else None,
        }
    return {
        "connected": False,
        "user_name": "",
        "client_id": "",
        "capital":   0.0,
        "last_sync": None,
    }


def clear_broker(username):
    """Remove user from pool (on logout)"""
    with _lock:
        _pool.pop(username, None)
