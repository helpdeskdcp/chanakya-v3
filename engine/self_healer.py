import time, logging, threading, requests
from functools import wraps
logger = logging.getLogger(__name__)

# Retry with exponential backoff
def retry(max_attempts=3, base_delay=2, exceptions=(Exception,)):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            for attempt in range(max_attempts):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    if attempt == max_attempts-1:
                        logger.error(f"{func.__name__} failed after {max_attempts} attempts: {e}")
                        raise
                    delay = base_delay * (2**attempt)
                    logger.warning(f"{func.__name__} attempt {attempt+1} failed: {e} — retry in {delay}s")
                    time.sleep(delay)
        return wrapper
    return decorator

# Self-healing broker reconnect
class SelfHealingBroker:
    def __init__(self, broker, max_retries=3):
        self.broker = broker
        self.max_retries = max_retries
        self._lock = threading.Lock()
        self._last_reconnect = 0
        self._reconnect_cooldown = 300

    def safe_ltp(self, exchange, symbol, token):
        for attempt in range(self.max_retries):
            try:
                r = self.broker.api.ltpData(exchange, symbol, str(token))
                if r and r.get("data"): return float(r["data"]["ltp"])
            except Exception as e:
                logger.warning(f"LTP fail {symbol} attempt {attempt+1}: {e}")
                if attempt < self.max_retries-1:
                    time.sleep(2**attempt)
                    self._try_reconnect()
        return None

    def safe_place_order(self, params):
        for attempt in range(self.max_retries):
            try:
                r = self.broker.api._postRequest("api.order.place", params)
                if r and r.get("status"): return r
                logger.warning(f"Order fail: {r}")
            except Exception as e:
                logger.error(f"Order error attempt {attempt+1}: {e}")
                if attempt < self.max_retries-1:
                    time.sleep(2**attempt)
        return None

    def safe_cancel_order(self, order_id, variety="NORMAL"):
        for attempt in range(self.max_retries):
            try:
                r = self.broker.api.cancelOrder(order_id, variety)
                if r and r.get("status"): return True
            except Exception as e:
                logger.error(f"Cancel error: {e}")
                time.sleep(2**attempt)
        return False

    def _try_reconnect(self):
        now = time.time()
        with self._lock:
            if now - self._last_reconnect < self._reconnect_cooldown:
                return False
            self._last_reconnect = now
        try:
            self.broker.connected = False
            self.broker.connect()
            logger.info(f"Self-heal reconnect: {self.broker.connected}")
            return self.broker.connected
        except Exception as e:
            logger.error(f"Reconnect failed: {e}")
            return False

# Safe data fetch with fallback
def safe_fetch_candles(broker, token, exchange, interval="FIVE_MINUTE", days=2):
    for attempt in range(3):
        try:
            from engine.candles import get_candles
            candles = get_candles(broker, token, exchange=exchange, interval=interval, days=days)
            if candles and len(candles) >= 10: return candles
        except Exception as e:
            logger.warning(f"Candle fetch fail attempt {attempt+1}: {e}")
            time.sleep(2**attempt)
    logger.error(f"Candle fetch failed — skipping token {token}")
    return []

# System health check
def health_check(broker, db_path="data/chanakya_v3.db"):
    issues = []
    # Broker connected?
    if not broker.connected: issues.append("broker_disconnected")
    # DB accessible?
    try:
        import sqlite3
        conn = sqlite3.connect(db_path)
        conn.execute("SELECT 1").fetchone()
        conn.close()
    except Exception as e:
        issues.append(f"db_error:{e}")
    # Memory ok?
    try:
        import psutil
        mem = psutil.virtual_memory().percent
        if mem > 90: issues.append(f"high_memory:{mem}%")
    except: pass
    if issues: logger.warning(f"Health issues: {issues}")
    else: logger.debug("Health: OK")
    return len(issues)==0, issues
