"""Chanakya v3 — FII/DII Data"""
import logging
logger = logging.getLogger(__name__)

_cache = {"data": None, "ts": 0}

def get_fii_data():
    import time, requests
    if _cache["data"] and time.time() - _cache["ts"] < 3600:
        return _cache["data"]
    try:
        r = requests.get(
            "https://www.nseindia.com/api/fiidiiTradeReact",
            headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"},
            timeout=8
        )
        data = r.json()
        fii_net, dii_net = 0, 0
        for row in data:
            cat = row.get("category", "")
            if "FII" in cat or "FPI" in cat:
                fii_net += float(str(row.get("netVal", "0")).replace(",","") or 0)
            elif "DII" in cat:
                dii_net += float(str(row.get("netVal", "0")).replace(",","") or 0)
        bias = "BULLISH" if fii_net > 500 else "BEARISH" if fii_net < -500 else "NEUTRAL"
        result = {"fii_net": round(fii_net,2), "dii_net": round(dii_net,2), "bias": bias}
        _cache.update({"data": result, "ts": time.time()})
        return result
    except Exception as e:
        logger.debug(f"FII fetch: {e}")
        return {"fii_net": 0, "dii_net": 0, "bias": "NEUTRAL"}
