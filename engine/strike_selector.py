"""
Chanakya v3 — Smart Strike Selector
ATM/ITM/OTM madhe best profitable strike select karo
"""
import logging
logger = logging.getLogger(__name__)

# Strike intervals per symbol
STRIKE_INTERVALS = {
    "NIFTY":      50,
    "BANKNIFTY":  100,
    "FINNIFTY":   50,
    "CRUDEOIL":   100,
    "NATURALGAS": 10,
}

def get_atm_strike(ltp, symbol):
    interval = STRIKE_INTERVALS.get(symbol.upper(), 50)
    return round(ltp / interval) * interval

def select_best_strike(broker, symbol, exchange, opt_type, ltp, vix=18, regime="SIDEWAYS"):
    """
    Best strike select karo:
    - TRENDING strong → ITM (delta ~0.7) — more profit
    - SIDEWAYS        → ATM (delta ~0.5) — balanced
    - VOLATILE        → OTM (delta ~0.3) — cheap premium
    """
    interval = STRIKE_INTERVALS.get(symbol.upper(), 50)
    atm = round(ltp / interval) * interval

    # Regime based selection
    if regime in ("TRENDING_UP", "TRENDING_DOWN"):
        # ITM — 1 strike in the money
        if opt_type == "CE":
            strike = atm - interval  # ITM CE
        else:
            strike = atm + interval  # ITM PE
        strike_type = "ITM"
    elif regime in ("VOLATILE",):
        # OTM — 1 strike out of the money
        if opt_type == "CE":
            strike = atm + interval  # OTM CE
        else:
            strike = atm - interval  # OTM PE
        strike_type = "OTM"
    else:
        # ATM — at the money
        strike = atm
        strike_type = "ATM"

    # Get option LTP from broker
    option_ltp = 0
    option_symbol = ""
    try:
        if broker and broker.connected:
            # Search correct option token
            option_ltp, option_symbol = _get_option_ltp(
                broker, symbol, exchange, opt_type, strike
            )
    except Exception as e:
        logger.debug(f"Option LTP error: {e}")

    return {
        "strike":       strike,
        "strike_type":  strike_type,
        "atm_strike":   atm,
        "opt_type":     opt_type,
        "option_ltp":   option_ltp,
        "option_symbol": option_symbol,
        "interval":     interval,
    }

def _get_option_ltp(broker, symbol, exchange, opt_type, strike):
    """Get option LTP from Angel One"""
    try:
        import requests
        from datetime import datetime, timedelta
        import pytz
        IST = pytz.timezone("Asia/Kolkata")
        now = datetime.now(IST)

        # Get instrument master
        url = "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"
        r = requests.get(url, timeout=10)
        instruments = r.json()

        # Find matching option
        sym_upper = symbol.upper()
        candidates = []
        for inst in instruments:
            if inst.get("exch_seg","") != exchange:
                continue
            name = inst.get("name","").upper()
            if sym_upper not in name:
                continue
            inst_type = inst.get("instrumenttype","")
            if exchange == "MCX" and "OPT" not in inst_type:
                continue
            if exchange == "NSE" and inst_type not in ("OPTIDX","OPTSTK"):
                continue

            # Strike match
            inst_strike = float(inst.get("strike", 0)) / 100
            if abs(inst_strike - strike) < 0.01:
                opt_sym = inst.get("symbol","")
                if opt_type in opt_sym:
                    exp_str = inst.get("expiry","")
                    try:
                        exp = datetime.strptime(exp_str, "%d%b%Y")
                        exp = IST.localize(exp)
                        if exp > now:
                            candidates.append({
                                "token":  inst.get("token",""),
                                "symbol": opt_sym,
                                "expiry": exp,
                            })
                    except Exception:
                        continue

        if not candidates:
            return 0.0, ""

        # Nearest expiry
        candidates.sort(key=lambda x: x["expiry"])
        best = candidates[0]

        # Get LTP
        ltp_resp = broker.api.ltpData(exchange, best["symbol"], best["token"])
        if ltp_resp and ltp_resp.get("data"):
            ltp = float(ltp_resp["data"]["ltp"])
            return ltp, best["symbol"]
    except Exception as e:
        logger.debug(f"Option LTP fetch: {e}")
    return 0.0, ""


def calculate_option_levels(option_ltp, opt_type, atr_pct=0.02, rr=1.5):
    """
    Option entry/target/SL based on option LTP
    atr_pct — underlying ATR as % of price
    """
    if option_ltp <= 0:
        return None

    # Option moves ~delta * underlying move
    # ATM delta ~0.5, ITM ~0.7, OTM ~0.3
    sl_pct    = max(0.25, atr_pct * 0.8)   # SL = 25-30% of option price
    tgt_pct   = sl_pct * rr                 # Target = SL * R:R

    if opt_type == "CE":
        sl     = round(option_ltp * (1 - sl_pct), 2)
        target = round(option_ltp * (1 + tgt_pct), 2)
    else:
        sl     = round(option_ltp * (1 - sl_pct), 2)
        target = round(option_ltp * (1 + tgt_pct), 2)

    sl     = max(0.05, sl)
    target = max(option_ltp + 0.05, target)

    return {
        "entry":  option_ltp,
        "target": target,
        "sl":     sl,
        "rr":     round(tgt_pct / sl_pct, 2),
        "sl_pct": round(sl_pct * 100, 1),
        "tgt_pct": round(tgt_pct * 100, 1),
    }
