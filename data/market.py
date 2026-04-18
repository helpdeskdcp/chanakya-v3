"""
Chanakya v3 — Market Data Module
VIX, PCR, FII/DII, NSE indices, market status
"""
import logging, time, requests
from datetime import datetime
import pytz

logger = logging.getLogger(__name__)
IST = pytz.timezone("Asia/Kolkata")

# ── Cache ──────────────────────────────────────────────
_cache = {}
CACHE_TTL = {
    "vix":    300,   # 5 min
    "fii":    3600,  # 1 hour
    "pcr":    300,   # 5 min
    "nifty":  30,    # 30 sec
    "status": 60,    # 1 min
}
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept":     "application/json",
    "Referer":    "https://www.nseindia.com",
}

def _cached(key, fn, ttl=300):
    now = time.time()
    if key in _cache and now - _cache[key]["ts"] < ttl:
        return _cache[key]["val"]
    try:
        val = fn()
        if val is not None:
            _cache[key] = {"val": val, "ts": now}
            return val
    except Exception as e:
        logger.debug(f"Cache fetch {key}: {e}")
    return _cache.get(key, {}).get("val")  # Return stale if available

# ── VIX ───────────────────────────────────────────────
def get_vix():
    def fetch():
        r = requests.get(
            "https://www.nseindia.com/api/allIndices",
            headers=HEADERS, timeout=8
        )
        for idx in r.json().get("data", []):
            if idx.get("index") == "India VIX":
                return float(idx["last"])
        return None
    return _cached("vix", fetch, CACHE_TTL["vix"]) or 18.0

# ── PCR ───────────────────────────────────────────────
def get_pcr(symbol="NIFTY"):
    def fetch():
        r = requests.get(
            f"https://www.nseindia.com/api/option-chain-indices?symbol={symbol}",
            headers=HEADERS, timeout=10
        )
        data = r.json()
        ce_oi, pe_oi = 0, 0
        for rec in data.get("records", {}).get("data", []):
            ce_oi += rec.get("CE", {}).get("openInterest", 0)
            pe_oi += rec.get("PE", {}).get("openInterest", 0)
        if ce_oi > 0:
            return round(pe_oi / ce_oi, 3)
        return None
    return _cached(f"pcr_{symbol}", fetch, CACHE_TTL["pcr"]) or 1.0

# ── FII/DII ───────────────────────────────────────────
def get_fii_dii():
    def fetch():
        r = requests.get(
            "https://www.nseindia.com/api/fiidiiTradeReact",
            headers=HEADERS, timeout=10
        )
        fii_net, dii_net = 0.0, 0.0
        for row in r.json():
            cat = row.get("category", "")
            val = float(str(row.get("netVal","0")).replace(",","") or 0)
            if "FII" in cat or "FPI" in cat:
                fii_net += val
            elif "DII" in cat:
                dii_net += val
        bias = ("STRONG_BULL" if fii_net > 2000 else
                "BULLISH"     if fii_net > 500  else
                "STRONG_BEAR" if fii_net < -2000 else
                "BEARISH"     if fii_net < -500  else "NEUTRAL")
        return {
            "fii_net":  round(fii_net, 2),
            "dii_net":  round(dii_net, 2),
            "combined": round(fii_net + dii_net, 2),
            "bias":     bias,
            "fii_flow": "INFLOW" if fii_net > 0 else "OUTFLOW",
        }
    return _cached("fii", fetch, CACHE_TTL["fii"]) or {
        "fii_net": 0, "dii_net": 0, "combined": 0,
        "bias": "NEUTRAL", "fii_flow": "NEUTRAL"
    }

# ── Nifty Spot ────────────────────────────────────────
def get_index_price(broker, symbol="NIFTY"):
    from config import config
    token = config.INDEX_TOKENS.get(symbol)
    if not token:
        return 0.0
    try:
        return broker.get_ltp("NSE", symbol, token) or 0.0
    except Exception:
        return 0.0

# ── Market Status ─────────────────────────────────────
def get_market_status():
    now = datetime.now(IST)
    dow = now.weekday()  # 0=Mon, 6=Sun
    h, m = now.hour, now.minute
    t = h * 60 + m

    nse_open = (dow < 5) and (555 <= t <= 930)
    mcx_open = (dow < 5) and (540 <= t <= 1410)
    pre_open = (dow < 5) and (549 <= t < 555)
    expiry_day = _is_expiry_day(now)

    session = ("PRE_OPEN"  if pre_open  else
               "OPEN"      if nse_open  else
               "CLOSED")

    return {
        "nse_open":    nse_open,
        "mcx_open":    mcx_open,
        "pre_open":    pre_open,
        "session":     session,
        "expiry_day":  expiry_day,
        "time":        now.strftime("%H:%M:%S"),
        "date":        now.strftime("%d %b %Y"),
        "day":         now.strftime("%A"),
        "timestamp":   now.isoformat(),
    }

def _is_expiry_day(dt=None):
    """Check if today is NSE weekly expiry (Thursday)"""
    dt = dt or datetime.now(IST)
    return dt.weekday() == 3  # Thursday

# ── Market Regime ─────────────────────────────────────
def get_market_regime(vix=None, pcr=None, fii_net=None):
    """
    Determine market regime for position sizing.
    Returns: BULL / BEAR / VOLATILE / SIDEWAYS / CAUTION
    """
    vix     = vix     or get_vix()
    pcr     = pcr     or get_pcr()
    fii_net = fii_net or get_fii_dii().get("fii_net", 0)

    score = 0  # Positive = bullish, negative = bearish

    # VIX signals
    if vix > 25:    return "VOLATILE"   # Override — high risk
    if vix > 20:    score -= 2
    elif vix < 14:  score += 2
    elif vix < 16:  score += 1

    # PCR signals
    if pcr > 1.4:   score -= 2   # Extreme fear = bearish
    elif pcr > 1.2: score -= 1
    elif pcr < 0.7: score += 2   # Extreme greed = bullish
    elif pcr < 0.9: score += 1

    # FII signals
    if fii_net > 2000:   score += 3
    elif fii_net > 500:  score += 1
    elif fii_net < -2000: score -= 3
    elif fii_net < -500:  score -= 1

    if score >= 3:    return "BULL"
    if score <= -3:   return "BEAR"
    if score >= 1:    return "MILD_BULL"
    if score <= -1:   return "MILD_BEAR"
    return "SIDEWAYS"

# ── Size Multiplier ───────────────────────────────────
def get_size_multiplier(regime, vix):
    """Adjust position size based on market regime"""
    multipliers = {
        "BULL":      1.0,
        "MILD_BULL": 0.9,
        "SIDEWAYS":  0.7,
        "MILD_BEAR": 0.8,
        "BEAR":      0.9,
        "VOLATILE":  0.5,
        "CAUTION":   0.3,
    }
    base = multipliers.get(regime, 0.7)
    # Extra VIX penalty
    if vix > 22: base *= 0.75
    return round(base, 2)

# ── Full Market Summary ───────────────────────────────
def get_market_summary(broker=None):
    """Complete market snapshot"""
    vix     = get_vix()
    fii     = get_fii_dii()
    status  = get_market_status()
    pcr     = get_pcr()
    regime  = get_market_regime(vix, pcr, fii["fii_net"])
    size_m  = get_size_multiplier(regime, vix)

    result = {
        "vix":           vix,
        "pcr":           pcr,
        "fii_net":       fii["fii_net"],
        "dii_net":       fii["dii_net"],
        "fii_bias":      fii["bias"],
        "market_status": status,
        "regime":        regime,
        "size_multiplier": size_m,
        "nse_open":      status["nse_open"],
        "mcx_open":      status["mcx_open"],
    }

    if broker:
        from config import config
        for sym in ["NIFTY", "BANKNIFTY"]:
            result[sym.lower()] = get_index_price(broker, sym)

    return result
