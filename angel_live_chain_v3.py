"""
Chanakya AI — Enhanced Option Chain Fetcher
Full Greeks: IV, Delta, Gamma, Theta, Vega
NSE + MCX support with conflict-free token mapping
"""
import requests, logging, json, os, time
from datetime import datetime
import pytz

logger = logging.getLogger(__name__)
IST = pytz.timezone("Asia/Kolkata")

_instruments_cache = None
_cache_time = 0
CACHE_TTL = 86400  # 24 hours

# ── Exchange-specific step sizes ───────────────────────
STRIKE_STEPS = {
    "NIFTY": 50, "BANKNIFTY": 100, "FINNIFTY": 50,
    "MIDCPNIFTY": 25, "SENSEX": 100,
    "CRUDEOIL": 50, "NATURALGAS": 10,
    "GOLD": 100, "SILVER": 100,
}

# ── Lot sizes ──────────────────────────────────────────
LOT_SIZES = {
    "NIFTY": 75, "BANKNIFTY": 30, "FINNIFTY": 60,
    "MIDCPNIFTY": 120,
    "CRUDEOIL": 100, "NATURALGAS": 1250,
    "GOLD": 1, "SILVER": 30,
}


def load_instruments(force=False):
    global _instruments_cache, _cache_time
    now = time.time()
    cache_file = "/root/ai_trading_real/instruments_cache.json"

    if _instruments_cache and not force and (now - _cache_time) < CACHE_TTL:
        return _instruments_cache

    # Try local cache first
    if os.path.exists(cache_file) and not force:
        age = now - os.path.getmtime(cache_file)
        if age < CACHE_TTL:
            try:
                with open(cache_file) as f:
                    _instruments_cache = json.load(f)
                    _cache_time = now
                    logger.info(f"✅ Instruments from cache: {len(_instruments_cache)}")
                    return _instruments_cache
            except Exception:
                pass

    try:
        r = requests.get(
            "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json",
            timeout=30
        )
        _instruments_cache = r.json()
        _cache_time = now
        with open(cache_file, "w") as f:
            json.dump(_instruments_cache, f)
        logger.info(f"✅ Instruments fetched: {len(_instruments_cache)}")
    except Exception as e:
        logger.error(f"Instrument fetch error: {e}")
        _instruments_cache = []
    return _instruments_cache


def get_nearest_expiry(instruments, symbol, exchange="NFO"):
    """Get nearest expiry date for symbol"""
    now = datetime.now(IST)
    expiries = set()
    for inst in instruments:
        if (inst.get("exch_seg", "") == exchange and
            inst.get("name", "").upper() == symbol.upper() and
            inst.get("instrumenttype") in ("OPTIDX", "OPTFUT", "OPTSTK")):
            exp_str = inst.get("expiry", "")
            if exp_str:
                try:
                    exp = datetime.strptime(exp_str, "%d%b%Y")
                    exp_ist = IST.localize(exp.replace(hour=15, minute=30))
                    if exp_ist > now:
                        expiries.add(exp_str)
                except Exception:
                    pass
    if not expiries:
        return None
    # Sort and return nearest
    def parse_exp(e):
        try: return datetime.strptime(e, "%d%b%Y")
        except: return datetime(2099, 1, 1)
    return sorted(expiries, key=parse_exp)[0]


def get_strike_tokens(instruments, symbol, expiry, exchange="NFO"):
    """
    Get all strike tokens for a symbol/expiry.
    Returns dict: {strike: {"CE": {token, ltp, ...}, "PE": {...}}}
    Conflict-free: uses exact symbol match + expiry match.
    """
    token_map = {}
    for inst in instruments:
        if (inst.get("exch_seg", "") == exchange and
            inst.get("name", "").upper() == symbol.upper() and
            inst.get("expiry", "") == expiry and
            inst.get("instrumenttype") in ("OPTIDX", "OPTFUT", "OPTSTK")):

            try:
                strike = int(float(inst.get("strike", 0)) / 100)
                opt_type = "CE" if inst.get("symbol", "").endswith("CE") else "PE"
                if strike not in token_map:
                    token_map[strike] = {}
                token_map[strike][opt_type] = {
                    "token":          inst.get("token", ""),
                    "trading_symbol": inst.get("symbol", ""),
                    "lot_size":       int(inst.get("lotsize", LOT_SIZES.get(symbol, 1))),
                    "tick_size":      float(inst.get("tick_size", 0.05)),
                }
            except Exception:
                pass
    return token_map


def fetch_ltp_bulk(angel_api, tokens_dict, exchange="NFO"):
    """
    Fetch LTP for multiple tokens.
    tokens_dict: {strike: {"CE": {"token": "..."}, "PE": {...}}}
    Returns updated dict with ltp added.
    """
    for strike, opts in tokens_dict.items():
        for opt_type, data in opts.items():
            token = data.get("token", "")
            if not token:
                continue
            try:
                ltp_data = angel_api.get_ltp(exchange, data.get("trading_symbol", ""), token)
                if ltp_data and ltp_data > 0:
                    data["ltp"] = ltp_data
                else:
                    data["ltp"] = 0
            except Exception:
                data["ltp"] = 0
    return tokens_dict


def calculate_chain_greeks(token_map, spot, expiry_str, r=0.07):
    """
    Add full Greeks to each strike/opt_type.
    """
    from bs_calculator import calc_iv_newton, calc_all_greeks, get_time_to_expiry, get_moneyness

    t = get_time_to_expiry(expiry_str)

    for strike, opts in token_map.items():
        for opt_type, data in opts.items():
            ltp = data.get("ltp", 0)
            if ltp <= 0 or spot <= 0:
                data.update({"iv": 0, "delta": 0.5 if opt_type=="CE" else -0.5,
                             "gamma": 0, "theta": 0, "vega": 0, "moneyness": "OTM"})
                continue

            # IV calculation
            iv = calc_iv_newton(ltp, spot, strike, t, r, opt_type)
            iv_pct = round(iv * 100, 2)

            # All Greeks
            if iv > 0:
                greeks = calc_all_greeks(spot, strike, t, r, iv, opt_type)
            else:
                # Use historical vol estimate (20% default)
                greeks = calc_all_greeks(spot, strike, t, r, 0.20, opt_type)

            moneyness = get_moneyness(spot, strike, opt_type)

            data.update({
                "iv":         iv_pct,
                "iv_raw":     iv,
                "delta":      greeks["delta"],
                "gamma":      greeks["gamma"],
                "theta":      greeks["theta"],
                "vega":       greeks["vega"],
                "theo_price": greeks["theo_price"],
                "moneyness":  moneyness,
                "t":          round(t * 365, 2),  # days to expiry
            })
    return token_map


def calculate_pcr(token_map):
    """Put-Call Ratio based on OI"""
    total_ce_oi = sum(opts.get("CE", {}).get("oi", 0) for opts in token_map.values())
    total_pe_oi = sum(opts.get("PE", {}).get("oi", 0) for opts in token_map.values())
    if total_ce_oi > 0:
        return round(total_pe_oi / total_ce_oi, 3)
    return 1.0


def find_max_pain(token_map):
    """
    Max Pain: strike where total option sellers' loss is minimum.
    Returns max_pain strike price.
    """
    strikes = sorted(token_map.keys())
    if not strikes:
        return 0

    pain = {}
    for s in strikes:
        total = 0
        for k, opts in token_map.items():
            ce_ltp = opts.get("CE", {}).get("ltp", 0)
            pe_ltp = opts.get("PE", {}).get("ltp", 0)
            ce_oi  = opts.get("CE", {}).get("oi", 0)
            pe_oi  = opts.get("PE", {}).get("oi", 0)
            # CE loss at expiry price s
            total += max(0, s - k) * ce_oi
            # PE loss at expiry price s
            total += max(0, k - s) * pe_oi
        pain[s] = total

    if pain:
        return min(pain, key=pain.get)
    return strikes[len(strikes) // 2]


def get_real_option_chain(angel_api, symbol, spot=None, num_strikes=8):
    """
    Main function: returns complete option chain with Greeks.
    """
    try:
        symbol = symbol.upper()
        exchange = "MCX" if symbol in ("CRUDEOIL","NATURALGAS","GOLD","SILVER","COPPER") else "NFO"
        step = STRIKE_STEPS.get(symbol, 50)

        # Load instruments
        instruments = load_instruments()
        if not instruments:
            logger.error("No instruments loaded")
            return None

        # Get spot price
        if not spot:
            try:
                # Try to get index price
                from angel_real import AngelOneAPI
                spot_data = angel_api.get_ltp(exchange, symbol, "")
                spot = spot_data if spot_data else 0
            except Exception:
                spot = 0

        if not spot:
            logger.warning(f"No spot price for {symbol}")
            return None

        # ATM strike
        atm = round(spot / step) * step

        # Get nearest expiry
        expiry = get_nearest_expiry(instruments, symbol, exchange)
        if not expiry:
            logger.warning(f"No expiry found for {symbol}")
            return None

        # Get strike tokens
        token_map = get_strike_tokens(instruments, symbol, expiry, exchange)
        if not token_map:
            logger.warning(f"No tokens for {symbol} {expiry}")
            return None

        # Filter to num_strikes around ATM
        all_strikes = sorted(token_map.keys())
        atm_idx = min(range(len(all_strikes)), key=lambda i: abs(all_strikes[i] - atm))
        start = max(0, atm_idx - num_strikes)
        end   = min(len(all_strikes), atm_idx + num_strikes + 1)
        selected_strikes = all_strikes[start:end]
        token_map = {s: token_map[s] for s in selected_strikes}

        # Fetch LTPs
        token_map = fetch_ltp_bulk(angel_api, token_map, exchange)

        # Calculate Greeks
        token_map = calculate_chain_greeks(token_map, spot, expiry)

        # Build chain list
        chain = []
        for strike in sorted(token_map.keys()):
            opts = token_map[strike]
            ce = opts.get("CE", {})
            pe = opts.get("PE", {})
            chain.append({
                "strike": strike,
                "is_atm": strike == atm,
                "ce": {
                    "ltp":        ce.get("ltp", 0),
                    "iv":         ce.get("iv", 0),
                    "delta":      ce.get("delta", 0),
                    "gamma":      ce.get("gamma", 0),
                    "theta":      ce.get("theta", 0),
                    "vega":       ce.get("vega", 0),
                    "oi":         ce.get("oi", 0),
                    "token":      ce.get("token", ""),
                    "moneyness":  ce.get("moneyness", ""),
                    "theo_price": ce.get("theo_price", 0),
                },
                "pe": {
                    "ltp":        pe.get("ltp", 0),
                    "iv":         pe.get("iv", 0),
                    "delta":      pe.get("delta", 0),
                    "gamma":      pe.get("gamma", 0),
                    "theta":      pe.get("theta", 0),
                    "vega":       pe.get("vega", 0),
                    "oi":         pe.get("oi", 0),
                    "token":      pe.get("token", ""),
                    "moneyness":  pe.get("moneyness", ""),
                    "theo_price": pe.get("theo_price", 0),
                },
            })

        # PCR + Max Pain
        pcr       = calculate_pcr(token_map)
        max_pain  = find_max_pain(token_map)

        return {
            "symbol":   symbol,
            "exchange": exchange,
            "spot":     spot,
            "atm":      atm,
            "expiry":   expiry,
            "pcr":      pcr,
            "max_pain": max_pain,
            "chain":    chain,
            "lot_size": LOT_SIZES.get(symbol, 1),
            "step":     step,
        }

    except Exception as e:
        logger.error(f"Chain error for {symbol}: {e}")
        import traceback
        logger.debug(traceback.format_exc())
        return None
