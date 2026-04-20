"""
Chanakya v3 — Auto Token Manager
Near-month expiry tokens automatically detect karto
"""
import requests, logging
from datetime import datetime
import pytz

logger = logging.getLogger(__name__)
IST = pytz.timezone("Asia/Kolkata")

INSTRUMENT_URL = "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"

# Static tokens — fallback
STATIC_TOKENS = {
    "NIFTY":       {"token": "99926000", "exchange": "NSE"},
    "BANKNIFTY":   {"token": "99926009", "exchange": "NSE"},
    "FINNIFTY":    {"token": "99926037", "exchange": "NSE"},
    "CRUDEOIL":    {"token": "486502",   "exchange": "MCX"},
    "NATURALGAS":  {"token": "487465",   "exchange": "MCX"},
}

_cache = {}
_last_refresh = None

def _fetch_instruments():
    """Download Angel One instrument master"""
    try:
        r = requests.get(INSTRUMENT_URL, timeout=15)
        return r.json()
    except Exception as e:
        logger.error(f"Instrument fetch error: {e}")
        return []

def get_near_month_token(symbol, exchange="MCX"):
    """
    Auto-detect nearest expiry token for MCX futures
    Returns token string
    """
    global _cache, _last_refresh
    now = datetime.now(IST)

    # Refresh cache daily
    if _last_refresh is None or (now - _last_refresh).total_seconds() > 86400:
        logger.info("Refreshing instrument master...")
        instruments = _fetch_instruments()
        if instruments:
            _cache["instruments"] = instruments
            _last_refresh = now
            logger.info(f"Loaded {len(instruments)} instruments")

    instruments = _cache.get("instruments", [])
    if not instruments:
        logger.warning("No instruments — using static token")
        return STATIC_TOKENS.get(symbol, {}).get("token", "")

    # Filter by symbol + exchange
    candidates = []
    for inst in instruments:
        if (inst.get("exch_seg","") == exchange and
            inst.get("name","").upper() == symbol.upper() and
            inst.get("instrumenttype","") in ("FUTCOM","FUTSTK","")):

            exp_str = inst.get("expiry","")
            if not exp_str:
                continue
            try:
                # Parse expiry — format: 20APR2026 or 26MAY2026
                exp = datetime.strptime(exp_str, "%d%b%Y")
                exp = IST.localize(exp)
                if exp > now:  # Future only
                    candidates.append({
                        "token": inst.get("token",""),
                        "name":  inst.get("name",""),
                        "expiry": exp,
                        "exp_str": exp_str,
                        "lotsize": inst.get("lotsize",1),
                    })
            except Exception:
                continue

    if not candidates:
        logger.warning(f"No candidates for {symbol} — using static")
        return STATIC_TOKENS.get(symbol, {}).get("token","")

    # Sort by expiry — nearest first
    candidates.sort(key=lambda x: x["expiry"])
    nearest = candidates[0]
    logger.info(f"Auto-token {symbol}: {nearest['token']} exp={nearest['exp_str']}")
    return nearest["token"]


def get_all_tokens(broker=None):
    """
    Get all correct tokens — auto + verify with LTP
    Returns dict: {symbol: {token, exchange, ltp}}
    """
    result = {}
    now = datetime.now(IST)

    # LTP cache — shared
    global _ltp_cache
    if not hasattr(get_all_tokens, '_ltp_cache'):
        get_all_tokens._ltp_cache = {}

    # NSE Index tokens — static (correct)
    nse_symbols = {
        "NIFTY":     {"token":"99926000", "exchange":"NSE"},
        "BANKNIFTY": {"token":"99926009", "exchange":"NSE"},
        "FINNIFTY":  {"token":"99926037", "exchange":"NSE"},
    }

    for sym, info in nse_symbols.items():
        result[sym] = info.copy()
        if broker and broker.connected:
            try:
                ltp = broker.api.ltpData(info["exchange"], sym, info["token"])
                if ltp and ltp.get("data"):
                    result[sym]["ltp"] = float(ltp["data"]["ltp"])
                get_all_tokens._ltp_cache[sym] = result[sym]["ltp"]
            except Exception:
                pass

    # MCX — auto-detect near month
    mcx_symbols = ["CRUDEOIL", "NATURALGAS"]
    for sym in mcx_symbols:
        token = get_near_month_token(sym, "MCX")
        result[sym] = {"token": token, "exchange": "MCX"}

        if broker and broker.connected and token:
            try:
                ltp = broker.api.ltpData("MCX", sym, token)
                if ltp and ltp.get("data"):
                    result[sym]["ltp"] = float(ltp["data"]["ltp"])
                get_all_tokens._ltp_cache[sym] = result[sym]["ltp"]
            except Exception:
                pass

    return result


def refresh_mcx_tokens():
    """Call this daily at market open — refresh MCX tokens"""
    global _last_refresh
    _last_refresh = None  # Force refresh
    logger.info("MCX tokens refreshing...")
    tokens = get_all_tokens()
    for sym, info in tokens.items():
        logger.info(f"  {sym}: token={info['token']} ltp={info.get('ltp',0)}")
    return tokens
