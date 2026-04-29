"""
Angel One API Rate Limiter
Enforces per-API throttling limits as per Angel One documentation
"""
import time
import threading
from collections import deque
import logging

logger = logging.getLogger(__name__)

# Angel One rate limits
LIMITS = {
    "login":        {"per_sec": 1,  "per_min": None, "per_hour": None},
    "generateToken":{"per_sec": 1,  "per_min": None, "per_hour": 1000},
    "getProfile":   {"per_sec": 3,  "per_min": None, "per_hour": 1000},
    "logout":       {"per_sec": 1,  "per_min": None, "per_hour": None},
    "getRMS":       {"per_sec": 2,  "per_min": None, "per_hour": None},
    "placeOrder":   {"per_sec": 9,  "per_min": 500,  "per_hour": 1000},
    "modifyOrder":  {"per_sec": 9,  "per_min": 500,  "per_hour": 1000},
    "cancelOrder":  {"per_sec": 9,  "per_min": 500,  "per_hour": 1000},
    "orderBook":    {"per_sec": 1,  "per_min": None, "per_hour": None},
    "ltpData":      {"per_sec": 10, "per_min": 500,  "per_hour": 5000},
    "position":     {"per_sec": 1,  "per_min": None, "per_hour": None},
    "tradeBook":    {"per_sec": 1,  "per_min": None, "per_hour": None},
    "candleData":   {"per_sec": 3,  "per_min": 180,  "per_hour": 5000},
    "default":      {"per_sec": 2,  "per_min": None, "per_hour": None},
}

# Combined order limit (place+modify+cancel = 9/sec total)
ORDER_APIS = {"placeOrder", "modifyOrder", "cancelOrder"}


class RateLimiter:
    def __init__(self):
        self._lock   = threading.Lock()
        self._calls  = {}   # api_name -> deque of timestamps
        self._order_calls = deque()  # combined order tracking

    def _clean(self, dq, window):
        cutoff = time.time() - window
        while dq and dq[0] < cutoff:
            dq.popleft()

    def wait_if_needed(self, api_name):
        """Block until rate limit allows the call"""
        limit = LIMITS.get(api_name, LIMITS["default"])
        api_key = api_name

        with self._lock:
            now = time.time()

            # Init deque
            if api_key not in self._calls:
                self._calls[api_key] = {
                    "sec":  deque(),
                    "min":  deque(),
                    "hour": deque(),
                }
            dqs = self._calls[api_key]

            # Per second check
            if limit["per_sec"]:
                self._clean(dqs["sec"], 1.0)
                if len(dqs["sec"]) >= limit["per_sec"]:
                    wait = 1.0 - (now - dqs["sec"][0])
                    if wait > 0:
                        logger.debug(f"Rate limit {api_name}: wait {wait:.2f}s")
                        time.sleep(wait + 0.05)
                dqs["sec"].append(time.time())

            # Per minute check
            if limit["per_min"]:
                self._clean(dqs["min"], 60.0)
                if len(dqs["min"]) >= limit["per_min"]:
                    wait = 60.0 - (now - dqs["min"][0])
                    if wait > 0:
                        logger.warning(f"Rate limit {api_name}: wait {wait:.0f}s (min limit)")
                        time.sleep(wait + 0.1)
                dqs["min"].append(time.time())

            # Combined order limit (9/sec total)
            if api_name in ORDER_APIS:
                self._clean(self._order_calls, 1.0)
                if len(self._order_calls) >= 9:
                    wait = 1.0 - (time.time() - self._order_calls[0])
                    if wait > 0:
                        logger.debug(f"Order combined limit: wait {wait:.2f}s")
                        time.sleep(wait + 0.05)
                self._order_calls.append(time.time())

    def can_call(self, api_name):
        """Check if call is possible without waiting"""
        limit = LIMITS.get(api_name, LIMITS["default"])
        with self._lock:
            if api_name not in self._calls:
                return True
            dqs = self._calls[api_name]
            self._clean(dqs["sec"], 1.0)
            if limit["per_sec"] and len(dqs["sec"]) >= limit["per_sec"]:
                return False
            return True


# Singleton
_rate_limiter = RateLimiter()


def get_rate_limiter():
    return _rate_limiter
