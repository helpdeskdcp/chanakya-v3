"""Chanakya v3 — Candle Data Fetcher"""
import logging
from datetime import datetime, timedelta
import pytz

logger = logging.getLogger(__name__)
IST = pytz.timezone("Asia/Kolkata")


def _parse_ts(dt_str):
    """Parse datetime string to unix timestamp"""
    try:
        if "T" in str(dt_str):
            from datetime import datetime
            import pytz
            dt = datetime.fromisoformat(str(dt_str))
            if dt.tzinfo is None:
                dt = IST.localize(dt)
            return int(dt.timestamp())
        return int(dt_str)
    except:
        import time
        return int(time.time())

def get_candles_direct(broker, token, exchange="NSE", interval="FIVE_MINUTE", days=30):
    """
    Direct REST API fetch — real timestamps, better history
    Uses access_token from broker
    """
    import requests
    from datetime import datetime, timedelta
    try:
        api = broker.api
        now = datetime.now(IST)
        frm = (now - timedelta(days=days)).strftime("%Y-%m-%d %H:%M")
        to  = now.strftime("%Y-%m-%d %H:%M")

        headers = {
            "Authorization":    f"Bearer {api.access_token}",
            "Content-Type":     "application/json",
            "Accept":           "application/json",
            "X-UserType":       "USER",
            "X-SourceID":       "WEB",
            "X-ClientLocalIP":  "127.0.0.1",
            "X-ClientPublicIP": getattr(api, "clientPublicIP", "127.0.0.1"),
            "X-MACAddress":     getattr(api, "clientMacAddress", "00:00:00:00:00:00"),
            "X-PrivateKey":     getattr(api, "api_key", "ArXRGu0v"),
        }

        r = requests.post(
            "https://apiconnect.angelone.in/rest/secure/angelbroking/historical/v1/getCandleData",
            headers=headers,
            json={"exchange":exchange,"symboltoken":token,
                  "interval":interval,"fromdate":frm,"todate":to},
            timeout=20
        )
        d = r.json()
        if d.get("status") and d.get("data"):
            raw = d["data"]
            candles = []
            for c in raw:
                ts = _parse_ts(c[0])
                candles.append([ts, float(c[1]), float(c[2]),
                                float(c[3]), float(c[4]),
                                int(c[5]) if len(c) > 5 else 0])
            logger.info(f"Direct fetch {token} {interval}: {len(candles)} candles")
            return candles
    except Exception as e:
        logger.debug(f"Direct fetch {token}: {e}")
    return []

def get_oi_direct(broker, token, exchange="NFO", interval="FIVE_MINUTE", days=30):
    """Fetch OI data — for option chain analysis"""
    import requests
    from datetime import datetime, timedelta
    try:
        api = broker.api
        now = datetime.now(IST)
        frm = (now - timedelta(days=days)).strftime("%Y-%m-%d %H:%M")
        to  = now.strftime("%Y-%m-%d %H:%M")

        headers = {
            "Authorization":    f"Bearer {api.access_token}",
            "Content-Type":     "application/json",
            "Accept":           "application/json",
            "X-UserType":       "USER",
            "X-SourceID":       "WEB",
            "X-ClientLocalIP":  "127.0.0.1",
            "X-ClientPublicIP": getattr(api, "clientPublicIP", "127.0.0.1"),
            "X-MACAddress":     getattr(api, "clientMacAddress", "00:00:00:00:00:00"),
            "X-PrivateKey":     getattr(api, "api_key", "ArXRGu0v"),
        }

        r = requests.post(
            "https://apiconnect.angelone.in/rest/secure/angelbroking/historical/v1/getOIData",
            headers=headers,
            json={"exchange":exchange,"symboltoken":token,
                  "interval":interval,"fromdate":frm,"todate":to},
            timeout=20
        )
        d = r.json()
        if d.get("status") and d.get("data"):
            return d["data"]
    except Exception as e:
        logger.debug(f"OI fetch {token}: {e}")
    return []

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
