"""
Chanakya AI — Data Fetcher
Auto fetch + store candles
Market open/close aware
"""
import logging, time, threading
from datetime import datetime, timedelta
import pytz

logger = logging.getLogger(__name__)
IST = pytz.timezone("Asia/Kolkata")

from engine.candle_db import (
    SYMBOLS, INTERVALS, HISTORY_DAYS,
    store_candles, get_last_ts, is_market_open
)

_running  = False
_thread   = None
_fetching = False

def fetch_symbol_interval(broker, symbol, token, exchange, interval, days=None):
    """Fetch and store candles for one symbol+interval"""
    from engine.candles import get_candles_direct, get_candles

    if days is None:
        days = HISTORY_DAYS.get(interval, 30)

    # Check last stored ts — only fetch new
    last_ts = get_last_ts(symbol, interval)
    if last_ts:
        # Only fetch missing data
        from datetime import datetime
        last_dt = datetime.fromtimestamp(last_ts, IST)
        gap_days = (datetime.now(IST) - last_dt).days + 1
        days = min(gap_days + 1, days)

    # Try direct API first (better history), fallback to library
    raw = get_candles_direct(broker, token, exchange=exchange,
                             interval=interval, days=days)
    if not raw:
        raw = get_candles(broker, token, exchange=exchange,
                         interval=interval, days=days)
    if raw:
        saved = store_candles(symbol, exchange, interval, raw)
        logger.info(f"Fetched {len(raw)} candles, saved {saved} new: {symbol} {interval}")
        return saved
    return 0

def initial_load(broker):
    """
    One-time: Load full history for all symbols+intervals
    Safe: 300ms between calls, skip if already loaded
    """
    global _fetching
    if _fetching:
        return
    _fetching = True

    logger.info("🔄 Starting initial candle load...")
    total_saved = 0

    for sym_info in SYMBOLS:
        sym      = sym_info["symbol"]
        token    = sym_info["token"]
        exchange = sym_info["exchange"]

        for interval in INTERVALS:
            try:
                saved = fetch_symbol_interval(
                    broker, sym, token, exchange, interval
                )
                total_saved += saved
                time.sleep(0.3)  # Rate limit protection
            except Exception as e:
                logger.warning(f"Fetch {sym} {interval}: {e}")
                time.sleep(1)

    logger.info(f"✅ Initial load complete: {total_saved} candles saved")
    _fetching = False
    return total_saved

def live_update(broker):
    """
    Fetch latest candles during market hours
    Called every 1 min
    """
    for sym_info in SYMBOLS:
        sym      = sym_info["symbol"]
        token    = sym_info["token"]
        exchange = sym_info["exchange"]

        if not is_market_open(exchange):
            continue

        try:
            # Only fetch last 2 days to get latest candles
            for interval in ["ONE_MINUTE","FIVE_MINUTE","FIFTEEN_MINUTE"]:
                fetch_symbol_interval(
                    broker, sym, token, exchange, interval, days=2
                )
                time.sleep(0.3)
        except Exception as e:
            logger.debug(f"Live update {sym}: {e}")

def start_data_engine(broker):
    """Start background data collection"""
    global _running, _thread

    if _running:
        return

    _running = True

    def _loop():
        # Initial load first
        try:
            initial_load(broker)
        except Exception as e:
            logger.error(f"Initial load: {e}")

        # Live update loop
        while _running:
            try:
                nse_open = is_market_open("NSE")
                mcx_open = is_market_open("MCX")

                if nse_open or mcx_open:
                    live_update(broker)
                    time.sleep(60)  # Every 1 min during market
                else:
                    time.sleep(300) # Every 5 min when closed
            except Exception as e:
                logger.error(f"Data engine: {e}")
                time.sleep(60)

    _thread = threading.Thread(target=_loop, daemon=True, name="DataFetcher")
    _thread.start()
    logger.info("✅ Data fetcher started")

def stop_data_engine():
    global _running
    _running = False
