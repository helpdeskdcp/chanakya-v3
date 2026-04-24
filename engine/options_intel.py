"""
Chanakya AI v4.0 — Options Intelligence Engine
OI Analysis + PCR + Max Pain + IV Percentile
"Option Chain = Smart Money Footprint"
"""
import logging, time
import requests

logger = logging.getLogger(__name__)

INSTRUMENT_URL = "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"
_instr_cache = None
_instr_time  = None


def _get_instruments():
    global _instr_cache, _instr_time
    import time as t
    now = t.time()
    if _instr_cache and _instr_time and (now - _instr_time) < 3600:
        return _instr_cache
    try:
        r = requests.get(INSTRUMENT_URL, timeout=20)
        _instr_cache = r.json()
        _instr_time  = now
    except Exception as e:
        logger.error(f"Instrument fetch: {e}")
    return _instr_cache or []


def get_option_chain_data(broker_api, symbol, spot_ltp, num_strikes=10):
    """
    Fetch full option chain with OI data
    Returns structured chain data
    """
    from engine.option_chain import get_near_expiry, EXCHANGE_MAP, INTERVALS
    instruments = _get_instruments()
    exchange     = EXCHANGE_MAP.get(symbol.upper(), "NFO")
    interval     = INTERVALS.get(symbol.upper(), 50)
    inst_type    = "OPTIDX" if exchange == "NFO" else "OPTFUT"

    expiry = get_near_expiry(symbol, instruments)
    if not expiry:
        return None

    atm = round(spot_ltp / interval) * interval
    strikes = [atm + i*interval for i in range(-num_strikes, num_strikes+1)]

    chain = {}
    for item in instruments:
        if (item.get("name","") != symbol): continue
        if (item.get("expiry","") != expiry): continue
        if (item.get("exch_seg","") != exchange): continue
        if (item.get("instrumenttype","") != inst_type): continue

        strike = float(item.get("strike",0)) / 100
        if strike not in strikes: continue

        opt_type = "CE" if "CE" in item.get("symbol","") else "PE"
        key = (strike, opt_type)

        try:
            r = broker_api.ltpData(exchange, item["symbol"], item["token"])
            ltp = float(r["data"]["ltp"]) if r and r.get("data") else 0
            time.sleep(0.1)
        except Exception:
            ltp = 0

        chain[key] = {
            "symbol":  item["symbol"],
            "token":   item["token"],
            "strike":  strike,
            "opt_type": opt_type,
            "ltp":     ltp,
            "oi":      0,      # OI not available via ltpData
            "volume":  0,
        }

    return {
        "symbol":   symbol,
        "expiry":   expiry,
        "spot":     spot_ltp,
        "atm":      atm,
        "chain":    chain,
        "exchange": exchange,
    }


def calculate_max_pain(chain_data):
    """
    Max Pain = strike where total option loss is maximum
    Market tends to close near max pain on expiry
    """
    if not chain_data or not chain_data.get("chain"):
        return 0

    chain = chain_data["chain"]
    strikes = sorted(set(k[0] for k in chain.keys()))

    if not strikes:
        return 0

    min_pain = float("inf")
    max_pain_strike = strikes[0]

    for exp_price in strikes:
        total_loss = 0
        for (strike, opt_type), data in chain.items():
            if opt_type == "CE":
                # CE holders lose if expiry < strike
                intrinsic = max(0, exp_price - strike)
                ltp = data.get("ltp", 0)
                pain = max(0, ltp - intrinsic)
                total_loss += pain
            else:
                # PE holders lose if expiry > strike
                intrinsic = max(0, strike - exp_price)
                ltp = data.get("ltp", 0)
                pain = max(0, ltp - intrinsic)
                total_loss += pain

        if total_loss < min_pain:
            min_pain = total_loss
            max_pain_strike = exp_price

    return max_pain_strike


def calculate_pcr(chain_data):
    """
    Put-Call Ratio based on LTP
    PCR > 1.2 = Bullish (more put buying = hedging)
    PCR < 0.8 = Bearish (more call buying)
    PCR 0.8-1.2 = Neutral
    """
    if not chain_data or not chain_data.get("chain"):
        return 1.0

    chain = chain_data["chain"]
    atm   = chain_data.get("atm", 0)

    # ATM ±3 strikes PCR
    ce_ltp = sum(d["ltp"] for (s,t),d in chain.items() if t=="CE" and abs(s-atm)<=150)
    pe_ltp = sum(d["ltp"] for (s,t),d in chain.items() if t=="PE" and abs(s-atm)<=150)

    if ce_ltp == 0:
        return 1.0
    return round(pe_ltp / ce_ltp, 2)


def find_oi_levels(chain_data):
    """
    Find key support/resistance from OI
    Highest Call OI = Resistance
    Highest Put OI  = Support
    Note: Using LTP as proxy since OI not in ltpData
    """
    if not chain_data or not chain_data.get("chain"):
        return {"resistance": 0, "support": 0}

    chain = chain_data["chain"]
    atm   = chain_data.get("atm", 0)

    # Find highest premium strikes (proxy for OI)
    ce_levels = [(s, d["ltp"]) for (s,t),d in chain.items() if t=="CE" and s >= atm]
    pe_levels = [(s, d["ltp"]) for (s,t),d in chain.items() if t=="PE" and s <= atm]

    resistance = max(ce_levels, key=lambda x: x[1])[0] if ce_levels else atm
    support    = max(pe_levels, key=lambda x: x[1])[0] if pe_levels else atm

    return {
        "resistance": resistance,
        "support":    support,
        "atm":        atm,
    }


def get_iv_signal(chain_data):
    """
    IV Signal from ATM option pricing
    Low IV  → Good time to buy options (cheap)
    High IV → Avoid buying, consider selling
    """
    if not chain_data or not chain_data.get("chain"):
        return "NEUTRAL", 0

    chain = chain_data["chain"]
    atm   = chain_data.get("atm", 0)

    # ATM CE + PE average premium
    atm_ce = chain.get((atm, "CE"), {}).get("ltp", 0)
    atm_pe = chain.get((atm, "PE"), {}).get("ltp", 0)
    avg_premium = (atm_ce + atm_pe) / 2

    spot = chain_data.get("spot", atm)

    # IV proxy = premium / spot * 100
    iv_proxy = (avg_premium / spot * 100) if spot > 0 else 0

    if iv_proxy < 0.5:
        signal = "LOW_IV_BUY"    # Cheap options
    elif iv_proxy > 2.0:
        signal = "HIGH_IV_AVOID" # Expensive options
    else:
        signal = "NORMAL_IV"

    return signal, round(iv_proxy, 2)


def full_options_analysis(broker_api, symbol, spot_ltp):
    """
    Complete options intelligence report
    """
    try:
        chain_data = get_option_chain_data(broker_api, symbol, spot_ltp)
        if not chain_data:
            return None

        max_pain   = calculate_max_pain(chain_data)
        pcr        = calculate_pcr(chain_data)
        oi_levels  = find_oi_levels(chain_data)
        iv_signal, iv_val = get_iv_signal(chain_data)

        # Interpretation
        if pcr > 1.2:
            pcr_bias = "BULLISH"   # More puts = hedging = institutions bullish
        elif pcr < 0.8:
            pcr_bias = "BEARISH"
        else:
            pcr_bias = "NEUTRAL"

        result = {
            "symbol":      symbol,
            "spot":        spot_ltp,
            "expiry":      chain_data["expiry"],
            "atm":         chain_data["atm"],
            "max_pain":    max_pain,
            "pcr":         pcr,
            "pcr_bias":    pcr_bias,
            "resistance":  oi_levels["resistance"],
            "support":     oi_levels["support"],
            "iv_signal":   iv_signal,
            "iv_proxy":    iv_val,
        }

        logger.info(f"OI Intel {symbol}: PCR={pcr}({pcr_bias}) MaxPain={max_pain} IV={iv_signal}")
        return result

    except Exception as e:
        logger.error(f"Options intel {symbol}: {e}")
        return None
