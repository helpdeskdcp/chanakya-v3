"""
Chanakya v3 — LTP Polling Engine
WebSocket blocked — REST polling with SSE push
"""
import threading, time, logging
logger = logging.getLogger(__name__)

_ltp_cache = {}   # {symbol: ltp}
_ltp_lock  = threading.Lock()
_running   = False
_thread    = None

def get_ltp(symbol):
    with _ltp_lock:
        return _ltp_cache.get(symbol.upper(), 0)

def get_all():
    with _ltp_lock:
        return dict(_ltp_cache)

def _update(symbol, ltp):
    with _ltp_lock:
        _ltp_cache[symbol.upper()] = ltp

def start_polling(broker, interval=3):
    """Poll LTP every N seconds — background thread"""
    global _running, _thread

    if _running:
        return

    _running = True

    def _loop():
        from engine.token_manager import get_all_tokens
        logger.info("✅ LTP polling started")
        while _running:
            try:
                if not broker.connected:
                    broker.connect()
                tokens = get_all_tokens(broker)
                for sym, info in tokens.items():
                    if sym == "VIX": continue
                    try:
                        r = broker.api.ltpData(
                            info["exchange"], sym, info["token"]
                        )
                        if r and r.get("data"):
                            ltp = float(r["data"]["ltp"])
                            _update(sym, ltp)
                            logger.debug(f"{sym}={ltp}")
                        time.sleep(0.3)  # Rate limit protection
                    except Exception as e:
                        logger.debug(f"LTP {sym}: {e}")
            except Exception as e:
                logger.error(f"Poll loop: {e}")
            time.sleep(interval)

    _thread = threading.Thread(target=_loop, daemon=True, name="LTPPoll")
    _thread.start()
    logger.info("LTP poll thread started")

def stop():
    global _running
    _running = False
