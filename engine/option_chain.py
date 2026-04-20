"""
Chanakya v3 — Option Chain Engine
Real option LTP fetch + ATM/ITM/OTM selection
"""
import requests, logging
from datetime import datetime
import pytz

logger = logging.getLogger(__name__)
IST = pytz.timezone("Asia/Kolkata")

INSTRUMENT_URL = "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"

# Exchange mapping
EXCHANGE_MAP = {
    "NIFTY":      "NFO",
    "BANKNIFTY":  "NFO",
    "FINNIFTY":   "NFO",
    "CRUDEOIL":   "MCX",
    "NATURALGAS": "MCX",
}

# Strike intervals
INTERVALS = {
    "NIFTY":      50,
    "BANKNIFTY":  100,
    "FINNIFTY":   50,
    "CRUDEOIL":   100,
    "NATURALGAS": 10,
}

_instruments_cache = None
_cache_time = None

def get_instruments():
    global _instruments_cache, _cache_time
    now = datetime.now(IST)
    if _instruments_cache and _cache_time and (now - _cache_time).seconds < 3600:
        return _instruments_cache
    try:
        r = requests.get(INSTRUMENT_URL, timeout=15)
        _instruments_cache = r.json()
        _cache_time = now
        logger.info(f"Instruments loaded: {len(_instruments_cache)}")
    except Exception as e:
        logger.error(f"Instrument fetch: {e}")
    return _instruments_cache or []

def get_option_chain(broker, symbol, ltp, num_strikes=5):
    """
    Get option chain for symbol near ATM
    Returns list of {strike, CE_token, PE_token, CE_ltp, PE_ltp}
    """
    instruments = get_instruments()
    exchange = EXCHANGE_MAP.get(symbol.upper(), "NFO")
    interval = INTERVALS.get(symbol.upper(), 50)
    atm = round(ltp / interval) * interval
    now = datetime.now(IST)

    # Filter options
    opts = {}  # {(strike, opt_type): {token, symbol, expiry}}
    for inst in instruments:
        if inst.get("exch_seg","") != exchange:
            continue
        if inst.get("name","").upper() != symbol.upper():
            continue
        inst_type = inst.get("instrumenttype","")
        if exchange == "NFO" and inst_type not in ("OPTIDX","OPTSTK"):
            continue
        if exchange == "MCX" and "OPT" not in inst_type:
            continue

        try:
            strike = float(inst.get("strike",0)) / 100
            if abs(strike - atm) > interval * num_strikes:
                continue
            exp = datetime.strptime(inst["expiry"], "%d%b%Y")
            exp = IST.localize(exp)
            if exp <= now:
                continue
            sym_name = inst.get("symbol","")
            opt_type = "CE" if "CE" in sym_name else "PE" if "PE" in sym_name else None
            if not opt_type:
                continue

            key = (strike, opt_type)
            existing = opts.get(key)
            if not existing or exp < existing["expiry"]:
                opts[key] = {
                    "token":   inst["token"],
                    "symbol":  sym_name,
                    "expiry":  exp,
                    "exp_str": inst["expiry"],
                }
        except Exception:
            continue

    if not opts:
        return []

    # Get LTP for each option
    strikes = sorted(set(k[0] for k in opts.keys()))
    chain = []
    for strike in strikes:
        row = {"strike": strike}
        for opt_type in ["CE","PE"]:
            key = (strike, opt_type)
            if key in opts:
                info = opts[key]
                try:
                    if broker and broker.api:
                        r = broker.api.ltpData(exchange, info["symbol"], info["token"])
                        if r and r.get("data"):
                            ltp_val = float(r["data"]["ltp"])
                        else:
                            ltp_val = 0
                    else:
                        ltp_val = 0
                    row[opt_type] = {
                        "ltp":     ltp_val,
                        "token":   info["token"],
                        "symbol":  info["symbol"],
                        "expiry":  info["exp_str"],
                    }
                except Exception as e:
                    logger.debug(f"LTP {info['symbol']}: {e}")
                    row[opt_type] = {"ltp":0,"token":info["token"],"symbol":info["symbol"],"expiry":info["exp_str"]}
        chain.append(row)

    chain.sort(key=lambda x: x["strike"])
    return chain

def get_best_option(broker, symbol, ltp, opt_type, regime="SIDEWAYS"):
    """
    Get best option for trading — proper LTP
    Returns: {token, symbol, strike, strike_type, option_ltp, expiry}
    """
    instruments = get_instruments()
    exchange = EXCHANGE_MAP.get(symbol.upper(), "NFO")
    interval = INTERVALS.get(symbol.upper(), 50)
    atm = round(ltp / interval) * interval
    now = datetime.now(IST)

    # Strike selection based on regime
    if regime in ("TRENDING_UP","TRENDING_DOWN"):
        strike = atm - interval if opt_type=="CE" else atm + interval
        strike_type = "ITM"
    elif regime == "VOLATILE":
        strike = atm + interval if opt_type=="CE" else atm - interval
        strike_type = "OTM"
    else:
        strike = atm
        strike_type = "ATM"

    # Find option token
    best = None
    best_exp = None
    for inst in instruments:
        if inst.get("exch_seg","") != exchange: continue
        if inst.get("name","").upper() != symbol.upper(): continue
        sym_name = inst.get("symbol","")
        if opt_type not in sym_name: continue
        try:
            inst_strike = float(inst.get("strike",0))/100
            if abs(inst_strike - strike) > 0.01: continue
            exp = datetime.strptime(inst["expiry"], "%d%b%Y")
            exp = IST.localize(exp)
            if exp <= now: continue
            if best_exp is None or exp < best_exp:
                best = inst
                best_exp = exp
        except Exception:
            continue

    if not best:
        return None

    # Get option LTP
    try:
        r = broker.api.ltpData(exchange, best["symbol"], best["token"])
        opt_ltp = float(r["data"]["ltp"]) if r and r.get("data") else 0
    except Exception:
        opt_ltp = 0

    return {
        "token":       best["token"],
        "symbol":      best["symbol"],
        "strike":      strike,
        "strike_type": strike_type,
        "atm_strike":  atm,
        "option_ltp":  opt_ltp,
        "expiry":      best["expiry"],
        "exchange":    exchange,
        "lot_size":    INTERVALS.get(symbol.upper(), 1),
    }
