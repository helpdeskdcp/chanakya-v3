"""
Chanakya AI — Candle Database Engine
Permanent SQLite storage for all candles
No duplicate, timestamp-sorted, ML-ready
"""
import sqlite3, logging, time, threading
from datetime import datetime, timedelta
import pytz

logger = logging.getLogger(__name__)
IST  = pytz.timezone("Asia/Kolkata")
DB   = "data/candles.db"
_lock = threading.Lock()

# Symbol config
SYMBOLS = [
    {"symbol":"NIFTY",      "token":"99926000","exchange":"NSE"},
    {"symbol":"BANKNIFTY",  "token":"99926009","exchange":"NSE"},
    {"symbol":"FINNIFTY",   "token":"99926037","exchange":"NSE"},
    {"symbol":"CRUDEOIL",   "token":"488290",  "exchange":"MCX"},
    {"symbol":"NATURALGAS", "token":"487465",  "exchange":"MCX"},
]

# Market hours
NSE_START  = (9, 15)
NSE_END    = (15, 30)
MCX_START  = (9,  0)
MCX_END    = (23, 30)

# Intervals to store
INTERVALS = ["ONE_MINUTE","FIVE_MINUTE","FIFTEEN_MINUTE",
             "THIRTY_MINUTE","ONE_HOUR","ONE_DAY"]

# Days of history per interval
HISTORY_DAYS = {
    "ONE_MINUTE":    30,
    "FIVE_MINUTE":   60,
    "FIFTEEN_MINUTE":90,
    "THIRTY_MINUTE": 120,
    "ONE_HOUR":      180,
    "ONE_DAY":       365,
}

def init_db():
    """Create candle DB if not exists"""
    with _lock:
        conn = sqlite3.connect(DB)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS candles (
                symbol    TEXT NOT NULL,
                exchange  TEXT NOT NULL,
                interval  TEXT NOT NULL,
                ts        INTEGER NOT NULL,
                open      REAL,
                high      REAL,
                low       REAL,
                close     REAL,
                volume    INTEGER,
                PRIMARY KEY (symbol, interval, ts)
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_candles_sym_int_ts
            ON candles (symbol, interval, ts DESC)
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS fetch_log (
                symbol   TEXT,
                interval TEXT,
                last_ts  INTEGER,
                updated  TEXT,
                PRIMARY KEY (symbol, interval)
            )
        """)
        conn.commit()
        conn.close()
    logger.info("✅ Candle DB initialized")

def _parse_ts(dt_str):
    """Parse Angel One datetime → Unix timestamp"""
    # Already integer timestamp
    if isinstance(dt_str, (int, float)):
        return int(dt_str)
    try:
        s = str(dt_str)
        if "T" in s:
            dt = datetime.fromisoformat(s)
        elif s.isdigit():
            return int(s)
        else:
            dt = datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
        if dt.tzinfo is None:
            dt = IST.localize(dt)
        return int(dt.timestamp())
    except Exception:
        return int(time.time())

def store_candles(symbol, exchange, interval, raw_candles):
    """
    Store candles to DB — no duplicates
    raw_candles: [[datetime, open, high, low, close, volume], ...]
    """
    if not raw_candles:
        return 0

    rows = []
    for c in raw_candles:
        try:
            ts  = _parse_ts(c[0])
            rows.append((symbol, exchange, interval, ts,
                         float(c[1]), float(c[2]),
                         float(c[3]), float(c[4]),
                         int(c[5]) if len(c) > 5 else 0))
        except Exception as e:
            logger.debug(f"Parse candle: {e}")

    if not rows:
        return 0

    with _lock:
        conn = sqlite3.connect(DB)
        try:
            conn.executemany("""
                INSERT OR IGNORE INTO candles
                (symbol,exchange,interval,ts,open,high,low,close,volume)
                VALUES (?,?,?,?,?,?,?,?,?)
            """, rows)
            conn.commit()
            saved = conn.total_changes

            # Update fetch log
            max_ts = max(r[3] for r in rows)
            conn.execute("""
                INSERT OR REPLACE INTO fetch_log (symbol,interval,last_ts,updated)
                VALUES (?,?,?,?)
            """, (symbol, interval, max_ts,
                  datetime.now(IST).isoformat()))
            conn.commit()
        finally:
            conn.close()

    logger.debug(f"Stored {saved} new candles: {symbol} {interval}")
    return saved

def get_candles_db(symbol, interval, limit=500, days=None):
    """
    Fetch candles from DB — fast SQLite query
    Returns: [{ts, open, high, low, close, volume}, ...]
    """
    with _lock:
        conn = sqlite3.connect(DB)
        conn.row_factory = sqlite3.Row
        try:
            if days:
                since = int((datetime.now(IST) - timedelta(days=days)).timestamp())
                rows = conn.execute("""
                    SELECT ts,open,high,low,close,volume
                    FROM candles
                    WHERE symbol=? AND interval=? AND ts >= ?
                    ORDER BY ts ASC
                    LIMIT ?
                """, (symbol, interval, since, limit*10)).fetchall()
            else:
                rows = conn.execute("""
                    SELECT ts,open,high,low,close,volume
                    FROM candles
                    WHERE symbol=? AND interval=?
                    ORDER BY ts DESC
                    LIMIT ?
                """, (symbol, interval, limit)).fetchall()
                rows = list(reversed(rows))
        finally:
            conn.close()

    return [dict(r) for r in rows]

def get_last_ts(symbol, interval):
    """Get last stored timestamp for symbol+interval"""
    with _lock:
        conn = sqlite3.connect(DB)
        try:
            r = conn.execute("""
                SELECT last_ts FROM fetch_log
                WHERE symbol=? AND interval=?
            """, (symbol, interval)).fetchone()
            return r[0] if r else None
        finally:
            conn.close()

def get_db_stats():
    """Get DB statistics"""
    with _lock:
        conn = sqlite3.connect(DB)
        try:
            stats = {}
            rows = conn.execute("""
                SELECT symbol, interval, COUNT(*) as cnt,
                       MIN(ts) as first_ts, MAX(ts) as last_ts
                FROM candles
                GROUP BY symbol, interval
                ORDER BY symbol, interval
            """).fetchall()
            for r in rows:
                key = f"{r[0]}_{r[1]}"
                stats[key] = {
                    "count":    r[2],
                    "first":    datetime.fromtimestamp(r[3], IST).strftime("%Y-%m-%d") if r[3] else "",
                    "last":     datetime.fromtimestamp(r[4], IST).strftime("%Y-%m-%d %H:%M") if r[4] else "",
                }
            return stats
        finally:
            conn.close()

def is_market_open(exchange="NSE"):
    """Check if market is open"""
    now = datetime.now(IST)
    if now.weekday() >= 5:  # Saturday=5, Sunday=6
        return False
    h, m = now.hour, now.minute
    if exchange == "NSE":
        return (h, m) >= NSE_START and (h, m) < NSE_END
    elif exchange == "MCX":
        return (h, m) >= MCX_START and (h, m) < MCX_END
    return False

init_db()
