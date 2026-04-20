"""
Chanakya v3 — Option Chain Engine
Angel One SmartAPI varun real option chain fetch
"""
import requests, logging, time
from datetime import datetime
import pytz

logger = logging.getLogger(__name__)
IST = pytz.timezone("Asia/Kolkata")

INSTRUMENT_URL = "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"

EXCHANGE_MAP = {
    "NIFTY":      "NFO",
    "BANKNIFTY":  "NFO",
    "FINNIFTY":   "NFO",
    "CRUDEOIL":   "MCX",
    "NATURALGAS": "MCX",
}

INTERVALS = {
    "NIFTY":      50,
    "BANKNIFTY":  100,
    "FINNIFTY":   50,
    "CRUDEOIL":   100,
    "NATURALGAS": 10,
}

# Instrument cache — refresh daily
_instr_cache = None
_instr_time  = None

def _get_instruments():
    global _instr_cache, _instr_time
    now = datetime.now(IST)
    if _instr_cache and _instr_time and (now - _instr_time).seconds < 3600:
        return _instr_cache
    try:
        r = requests.get(INSTRUMENT_URL, timeout=20)
        _instr_cache = r.json()
        _instr_time  = now
        logger.info(f"Instruments: {len(_instr_cache)} loaded")
    except Exception as e:
        logger.error(f"Instrument fetch: {e}")
    return _instr_cache or []

def get_near_expiry(symbol, instruments):
    """Get nearest future expiry date for symbol"""
    now = datetime.now(IST)
    exchange = EXCHANGE_MAP.get(symbol.upper(), "NFO")
    inst_type = "OPTIDX" if exchange == "NFO" else "OPTFUT"

    expiries = set()
    for item in instruments:
        if (item.get("name","") == symbol and
            item.get("exch_seg","") == exchange and
            item.get("instrumenttype","") == inst_type):
            try:
                exp = datetime.strptime(item["expiry"], "%d%b%Y")
                exp = IST.localize(exp)
                if exp > now:
                    expiries.add(item["expiry"])
            except Exception:
                continue

    if not expiries:
        return None

    # Sort by date — nearest first
    sorted_exp = sorted(expiries, key=lambda x: datetime.strptime(x, "%d%b%Y"))
    return sorted_exp[0]

def get_option_chain(broker_api, symbol, expiry=None, num_strikes=5):
    """
    Fetch full option chain — CE + PE both sides
    Returns DataFrame-like list of dicts
    """
    instruments = _get_instruments()
    exchange     = EXCHANGE_MAP.get(symbol.upper(), "NFO")
    interval     = INTERVALS.get(symbol.upper(), 50)
    inst_type    = "OPTIDX" if exchange == "NFO" else "OPTFUT"

    # Auto-detect nearest expiry
    if not expiry:
        expiry = get_near_expiry(symbol, instruments)
        if not expiry:
            logger.warning(f"No expiry found for {symbol}")
            return []

    logger.info(f"Option chain: {symbol} {expiry}")

    # Filter options
    option_list = []
    for item in instruments:
        if (item.get("name","") == symbol and
            item.get("expiry","") == expiry and
            item.get("exch_seg","") == exchange and
            item.get("instrumenttype","") == inst_type):
            option_list.append({
                "symbol":   item["symbol"],
                "strike":   float(item.get("strike",0)) / 100,
                "token":    item["token"],
                "lotsize":  int(item.get("lotsize",1)),
                "opt_type": "CE" if "CE" in item["symbol"] else "PE",
            })

    if not option_list:
        logger.warning(f"No options for {symbol} {expiry}")
        return []

    # Sort by strike
    option_list.sort(key=lambda x: x["strike"])

    # Get LTP for each — with rate limit protection
    for opt in option_list:
        try:
            r = broker_api.ltpData(exchange, opt["symbol"], opt["token"])
            opt["ltp"] = float(r["data"]["ltp"]) if r and r.get("data") else 0.0
            time.sleep(0.1)  # Rate limit protection
        except Exception as e:
            opt["ltp"] = 0.0
            logger.debug(f"LTP {opt['symbol']}: {e}")

    return option_list

def get_atm_options(broker_api, symbol, spot_ltp, num_strikes=3):
    """
    Get ATM + nearby strikes with LTP
    Returns: {atm, CE: [...], PE: [...], expiry}
    """
    instruments = _get_instruments()
    exchange     = EXCHANGE_MAP.get(symbol.upper(), "NFO")
    interval     = INTERVALS.get(symbol.upper(), 50)
    inst_type    = "OPTIDX" if exchange == "NFO" else "OPTFUT"

    expiry = get_near_expiry(symbol, instruments)
    if not expiry:
        return None

    atm = round(spot_ltp / interval) * interval

    # Strikes to fetch
    strikes = [atm + i*interval for i in range(-num_strikes, num_strikes+1)]

    ce_opts = []
    pe_opts = []

    for item in instruments:
        if (item.get("name","") != symbol): continue
        if (item.get("expiry","") != expiry): continue
        if (item.get("exch_seg","") != exchange): continue
        if (item.get("instrumenttype","") != inst_type): continue

        strike = float(item.get("strike",0)) / 100
        if strike not in strikes: continue

        opt_data = {
            "symbol":   item["symbol"],
            "strike":   strike,
            "token":    item["token"],
            "lotsize":  int(item.get("lotsize",1)),
            "ltp":      0.0,
        }

        try:
            r = broker_api.ltpData(exchange, item["symbol"], item["token"])
            opt_data["ltp"] = float(r["data"]["ltp"]) if r and r.get("data") else 0.0
            time.sleep(0.05)
        except Exception:
            pass

        if "CE" in item["symbol"]:
            ce_opts.append(opt_data)
        elif "PE" in item["symbol"]:
            pe_opts.append(opt_data)

    ce_opts.sort(key=lambda x: x["strike"])
    pe_opts.sort(key=lambda x: x["strike"])

    return {
        "symbol":   symbol,
        "expiry":   expiry,
        "spot":     spot_ltp,
        "atm":      atm,
        "CE":       ce_opts,
        "PE":       pe_opts,
        "exchange": exchange,
    }

def get_best_option(broker_api, symbol, spot_ltp, opt_type, regime="SIDEWAYS"):
    """
    Get best strike option LTP based on regime
    TRENDING → ITM, SIDEWAYS → ATM, VOLATILE → OTM
    """
    instruments = _get_instruments()
    exchange     = EXCHANGE_MAP.get(symbol.upper(), "NFO")
    interval     = INTERVALS.get(symbol.upper(), 50)
    inst_type    = "OPTIDX" if exchange == "NFO" else "OPTFUT"

    expiry = get_near_expiry(symbol, instruments)
    if not expiry:
        return None

    atm = round(spot_ltp / interval) * interval

    if regime in ("TRENDING_UP","TRENDING_DOWN"):
        strike = atm - interval if opt_type=="CE" else atm + interval
        stype  = "ITM"
    elif regime == "VOLATILE":
        strike = atm + interval if opt_type=="CE" else atm - interval
        stype  = "OTM"
    else:
        strike = atm
        stype  = "ATM"

    # Find token
    best = None
    for item in instruments:
        if (item.get("name","") == symbol and
            item.get("expiry","") == expiry and
            item.get("exch_seg","") == exchange and
            item.get("instrumenttype","") == inst_type and
            opt_type in item.get("symbol","")):
            item_strike = float(item.get("strike",0)) / 100
            if abs(item_strike - strike) < 0.01:
                best = item
                break

    if not best:
        return None

    try:
        r = broker_api.ltpData(exchange, best["symbol"], best["token"])
        opt_ltp = float(r["data"]["ltp"]) if r and r.get("data") else 0.0
    except Exception:
        opt_ltp = 0.0

    return {
        "symbol":       best["symbol"],
        "token":        best["token"],
        "strike":       strike,
        "strike_type":  stype,
        "atm_strike":   atm,
        "option_ltp":   opt_ltp,
        "expiry":       expiry,
        "exchange":     exchange,
        "lotsize":      int(best.get("lotsize",1)),
    }
