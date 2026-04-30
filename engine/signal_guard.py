"""
Chanakya AI — Signal Guard v2.0
Universal: NSE Options + MCX Commodities + NSE Equity
Segment-aware rules
"""
import logging
logger = logging.getLogger(__name__)

SEGMENT_RULES = {
    "NSE_OPTIONS": {
        "min_score": 72, "min_rr": 2.5, "min_net_profit": 150,
        "max_sl_pct": 30, "min_volume_ratio": 1.3,
        "rsi_buy": (48, 68), "rsi_sell": (32, 52),
        "max_vix": 22, "block_sideways": True, "ml_min_conf": 0.55,
        "min_price": 5, "max_price": 500,
    },
    "MCX_OPTIONS": {
        "min_score": 70, "min_rr": 2.0, "min_net_profit": 200,
        "max_sl_pct": 35, "min_volume_ratio": 1.2,
        "rsi_buy": (45, 70), "rsi_sell": (30, 55),
        "max_vix": 25, "block_sideways": True, "ml_min_conf": 0.52,
        "min_price": 0.5, "max_price": 2000,
    },
    "NSE_EQUITY": {
        "min_score": 65, "min_rr": 2.0, "min_net_profit": 100,
        "max_sl_pct": 2.0, "min_volume_ratio": 1.5,
        "rsi_buy": (50, 68), "rsi_sell": (32, 50),
        "max_vix": 20, "block_sideways": True, "ml_min_conf": 0.55,
        "min_price": 50, "max_price": 5000,
    },
}

MCX_SYMBOLS  = {"CRUDEOIL","NATURALGAS","GOLD","SILVER","COPPER","ZINC","LEAD"}
NSE_SYMBOLS  = {"NIFTY","BANKNIFTY","FINNIFTY","MIDCPNIFTY"}

def detect_segment(d):
    exch   = str(d.get("exchange","")).upper()
    sym    = str(d.get("symbol","")).upper()
    stype  = str(d.get("type","")).upper()
    opt    = d.get("opt_type","")

    if stype == "EQUITY" or (exch == "NSE" and not opt):
        return "NSE_EQUITY"
    if exch == "MCX" or sym in MCX_SYMBOLS:
        return "MCX_OPTIONS"
    return "NSE_OPTIONS"

def check_all(signal_data, market_data=None):
    passed = []; failed = []
    d = signal_data; m = market_data or {}

    seg   = detect_segment(d)
    rules = SEGMENT_RULES[seg]

    entry      = float(d.get("entry", d.get("ltp", 0)))
    sl         = float(d.get("sl", d.get("sl_price", 0)))
    target     = float(d.get("target", d.get("target_price", 0)))
    score      = float(d.get("score_pct", d.get("score", 0)))
    if score < 1: score *= 100
    rsi        = float(d.get("rsi", 50))
    vol_ratio  = float(d.get("vol_ratio", 1))
    net_profit = float(d.get("net_profit", 0))
    direction  = str(d.get("direction", d.get("opt_type", "BUY"))).upper()
    vix        = float(m.get("vix", d.get("vix", 18)))
    regime     = str(m.get("regime", d.get("regime","SIDEWAYS"))).upper()
    ml_conf    = float(d.get("ml_conf", 0.5))
    ltp        = float(d.get("ltp", entry))

    passed.append(f"Segment:{seg}")

    # G1: Score
    if score >= rules["min_score"]: passed.append(f"Score {score:.0f}% ✅")
    else: failed.append(f"Score {score:.0f}%<{rules['min_score']}% ❌")

    # G2: RR
    rr = 0
    if entry > 0 and sl > 0 and target > 0:
        if direction in ("BUY","CE"):
            rr = (target-entry)/(entry-sl) if (entry-sl) > 0 else 0
        else:
            rr = (entry-target)/(sl-entry) if (sl-entry) > 0 else 0
        rr = round(rr, 2)
    if rr >= rules["min_rr"]: passed.append(f"RR {rr} ✅")
    else: failed.append(f"RR {rr}<{rules['min_rr']} ❌")

    # G3: Net Profit
    if net_profit <= 0: passed.append("Net not calc — skip")
    elif net_profit >= rules["min_net_profit"]: passed.append(f"Net Rs{net_profit} ✅")
    else: failed.append(f"Net Rs{net_profit}<Rs{rules['min_net_profit']} ❌")

    # G4: SL%
    if entry > 0 and sl > 0:
        sl_pct = abs(entry-sl)/entry*100
        if sl_pct <= rules["max_sl_pct"]: passed.append(f"SL {sl_pct:.1f}% ✅")
        else: failed.append(f"SL {sl_pct:.1f}%>{rules['max_sl_pct']}% ❌")

    # G5: Volume
    if vol_ratio >= rules["min_volume_ratio"]: passed.append(f"Vol {vol_ratio}x ✅")
    elif vol_ratio == 1.0: passed.append("Vol skip")
    else: failed.append(f"Vol {vol_ratio}x<{rules['min_volume_ratio']}x ❌")

    # G6: RSI
    rng = rules["rsi_buy"] if direction in ("BUY","CE") else rules["rsi_sell"]
    if rng[0] <= rsi <= rng[1]: passed.append(f"RSI {rsi} ✅")
    else: failed.append(f"RSI {rsi} out {rng} ❌")

    # G7: Regime
    if rules["block_sideways"] and regime == "SIDEWAYS":
        failed.append("Regime SIDEWAYS ❌")
    elif direction in ("BUY","CE") and regime in ("TRENDING_UP","BULLISH"):
        passed.append(f"Regime {regime} ✅")
    elif direction in ("SELL","PE") and regime in ("TRENDING_DOWN","BEARISH"):
        passed.append(f"Regime {regime} ✅")
    else:
        passed.append(f"Regime {regime} neutral")

    # G8: VIX
    if vix <= rules["max_vix"]: passed.append(f"VIX {vix} ✅")
    else: failed.append(f"VIX {vix}>{rules['max_vix']} ❌")

    # G9: ML
    if ml_conf >= rules["ml_min_conf"]: passed.append(f"ML {ml_conf:.2f} ✅")
    else: passed.append(f"ML {ml_conf:.2f} skip")

    # G10: Segment-specific
    if seg == "NSE_EQUITY":
        from datetime import datetime
        import pytz
        now = datetime.now(pytz.timezone("Asia/Kolkata"))
        h,mn = now.hour, now.minute
        if (9,30) <= (h,mn) <= (15,25): passed.append("NSE open ✅")
        elif (9,15) <= (h,mn) < (9,30): failed.append("No-trade 9:15-9:30 ❌")
        else: failed.append("NSE closed ❌")
        if rules["min_price"] <= ltp <= rules["max_price"]: passed.append(f"Price ✅")
        else: failed.append(f"Price Rs{ltp} range ❌")

    elif seg == "MCX_OPTIONS":
        from datetime import datetime
        import pytz
        now = datetime.now(pytz.timezone("Asia/Kolkata"))
        h,mn = now.hour, now.minute
        if (9,0) <= (h,mn) <= (23,30): passed.append("MCX open ✅")
        else: failed.append("MCX closed ❌")

    elif seg == "NSE_OPTIONS":
        if rules["min_price"] <= ltp <= rules["max_price"]: passed.append(f"Price ✅")
        else: failed.append(f"Price Rs{ltp} range ❌")

    # Critical check
    critical = ["Score","RR","SL","RSI","Regime"]
    crit_fail = [f for f in failed if any(k in f for k in critical)]
    all_ok = len(crit_fail) == 0

    v = "✅ APPROVED" if all_ok else f"❌ BLOCKED"
    logger.info(f"[{seg}] {d.get('symbol','')} {v} p={len(passed)} f={len(failed)}")
    if failed: logger.debug(f"  Failed: {failed}")

    return all_ok, passed, failed

def filter_signals(signals, market_data=None):
    approved = []
    for sig in signals:
        ok, p, f = check_all(sig, market_data)
        sig["guard_passed"]  = ok
        sig["guard_reasons"] = p
        sig["guard_failed"]  = f
        sig["segment"]       = detect_segment(sig)
        if ok: approved.append(sig)
    logger.info(f"Guard: {len(approved)}/{len(signals)} approved")
    return approved
