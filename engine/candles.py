"""Chanakya v3 — Candle Data Fetcher"""
import logging
from datetime import datetime, timedelta
import pytz

logger = logging.getLogger(__name__)
IST = pytz.timezone("Asia/Kolkata")

def get_candles(broker, token, exchange="NFO", interval="FIVE_MINUTE", days=5):
    """Fetch OHLCV candles from AngelOne"""
    try:
        now  = datetime.now(IST)
        from_dt = (now - timedelta(days=days)).strftime("%Y-%m-%d %H:%M")
        to_dt   = now.strftime("%Y-%m-%d %H:%M")
        params = {
            "exchange":    exchange,
            "symboltoken": token,
            "interval":    interval,
            "fromdate":    from_dt,
            "todate":      to_dt,
        }
        resp = broker.api.getCandleData(params)
        if resp and resp.get("status") and resp.get("data"):
            raw = resp["data"]
            candles = []
            for c in raw:
                # [timestamp, open, high, low, close, volume]
                ts = c[0] if isinstance(c[0], (int,float)) else 0
                candles.append([ts, float(c[1]), float(c[2]),
                                float(c[3]), float(c[4]),
                                float(c[5]) if len(c) > 5 else 0])
            return candles
    except Exception as e:
        logger.debug(f"Candle fetch {token}: {e}")
    return []
