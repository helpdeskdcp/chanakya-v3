"""
Chanakya v3 — File-based Signal Store
Scanner writes → Flask reads (shared file)
"""
import json, os, threading, time
import logging
logger = logging.getLogger(__name__)

STORE_FILE = "data/signal_cache.json"
_lock = threading.Lock()

def update(username, signals):
    """Scanner writes signals to file"""
    try:
        with _lock:
            data = {}
            if os.path.exists(STORE_FILE):
                with open(STORE_FILE) as f:
                    data = json.load(f)
            data[username] = {
                "signals": signals,
                "ts": time.time()
            }
            with open(STORE_FILE, "w") as f:
                json.dump(data, f)
    except Exception as e:
        logger.debug(f"Signal store write: {e}")

def get(username, fallback="avinash"):
    """Flask reads signals from file"""
    try:
        if not os.path.exists(STORE_FILE):
            return []
        with open(STORE_FILE) as f:
            data = json.load(f)
        # Try user first, then fallback
        entry = data.get(username) or data.get(fallback)
        if not entry:
            return []
        # Max 5 min old
        if time.time() - entry.get("ts", 0) > 300:
            return []
        return entry.get("signals", [])
    except Exception as e:
        logger.debug(f"Signal store read: {e}")
        return []

def get_all():
    try:
        if not os.path.exists(STORE_FILE):
            return {}
        with open(STORE_FILE) as f:
            return json.load(f)
    except Exception:
        return {}
