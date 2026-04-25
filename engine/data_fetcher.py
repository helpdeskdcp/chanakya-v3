"""
Chanakya AI — Data Fetcher
Auto fetch + store candles — market hours aware
NSE: 9:15-15:30 | MCX: 9:00-23:30
"""
import logging, time, threading
from datetime import datetime, timedelta
import pytz

logger = logging.getLogger(__name__)
IST = pytz.timezone("Asia/Kolkata")

from engine.candle_db import (
    SYMBOLS, INTERVALS, store_candles,
    get_last_ts, is_market_open, _is_market_hours
)

_running  = False
_thread   = None

def fetch_and_store(broker, sym, token, exch, interval, days=5):
    """Fetch candles and store — market hours filtered"""
    from engine.candles import get_candles_direct, get_candles

    raw = get_candles_direct(broker, token, exch, interval, days)
    if not raw:
        raw = get_candles(broker, token, exchange=exch, interval=interval, days=days)
    if not raw:
        return 0

    # Filter market hours (not for daily)
    if interval != "ONE_DAY":
        raw = [c for c in raw if _is_market_hours(c[0], exch)]

    if not raw:
        return 0

    saved = store_candles(sym, exch, interval, raw)
    return saved

def initial_load(broker):
    """One-time full history load"""
    logger.info("🔄 Initial candle load starting...")
    total = 0
    DAYS = {
        "ONE_MINUTE":5, "FIVE_MINUTE":30, "FIFTEEN_MINUTE":60,
        "THIRTY_MINUTE":90, "ONE_HOUR":180, "ONE_DAY":365
    }
    for sym_info in SYMBOLS:
        sym   = sym_info["symbol"]
        token = sym_info["token"]
        exch  = sym_info["exchange"]
        for interval in INTERVALS:
            try:
                saved = fetch_and_store(broker, sym, token, exch,
                                        interval, DAYS.get(interval,30))
                total += saved
                time.sleep(0.35)
            except Exception as e:
                logger.warning(f"Fetch {sym} {interval}: {e}")
                time.sleep(1)

    logger.info(f"✅ Initial load: {total} candles saved")
    return total

def live_update(broker):
    """Fetch latest candles — called every 1 min during market"""
    for sym_info in SYMBOLS:
        sym   = sym_info["symbol"]
        token = sym_info["token"]
        exch  = sym_info["exchange"]
        if not is_market_open(exch):
            continue
        try:
            for interval in ["ONE_MINUTE","FIVE_MINUTE","FIFTEEN_MINUTE"]:
                fetch_and_store(broker, sym, token, exch, interval, days=2)
                time.sleep(0.3)
        except Exception as e:
            logger.debug(f"Live update {sym}: {e}")

def start_data_engine(broker):
    """Start background data collection thread"""
    global _running, _thread
    if _running:
        return
    _running = True

    def _loop():
        # Initial load
        try:
            initial_load(broker)
        except Exception as e:
            logger.error(f"Initial load: {e}")

        # Live update loop
        while _running:
            try:
                nse = is_market_open("NSE")
                mcx = is_market_open("MCX")
                if nse or mcx:
                    live_update(broker)
                    time.sleep(60)
                else:
                    time.sleep(300)
            except Exception as e:
                logger.error(f"Data engine: {e}")
                time.sleep(60)

    _thread = threading.Thread(target=_loop, daemon=True, name="DataFetcher")
    _thread.start()
    logger.info("✅ Data fetcher started")

def stop_data_engine():
    global _running
    _running = False
