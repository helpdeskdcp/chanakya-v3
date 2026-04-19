
def detect_market_regime(candles):
    """
    Market regime detect karo:
    TRENDING_UP, TRENDING_DOWN, SIDEWAYS, VOLATILE
    """
    if len(candles) < 20:
        return "SIDEWAYS"

    closes = [c["close"] for c in candles[-20:]]
    highs  = [c["high"]  for c in candles[-20:]]
    lows   = [c["low"]   for c in candles[-20:]]

    # EMA trend
    e9  = sum(closes[-9:])  / 9
    e21 = sum(closes[-21:]) / 21 if len(closes) >= 21 else sum(closes) / len(closes)
    last = closes[-1]

    # ATR for volatility
    trs = [max(highs[i]-lows[i],
               abs(highs[i]-(closes[i-1] if i>0 else closes[i])),
               abs(lows[i]-(closes[i-1] if i>0 else closes[i])))
           for i in range(len(candles[-20:]))]
    atr = sum(trs) / len(trs) if trs else 0
    atr_pct = (atr / last * 100) if last > 0 else 0

    # Price range
    price_range = (max(closes) - min(closes)) / min(closes) * 100 if min(closes) > 0 else 0

    if atr_pct > 2.0:
        return "VOLATILE"
    elif e9 > e21 * 1.002 and last > e9:
        return "TRENDING_UP"
    elif e9 < e21 * 0.998 and last < e9:
        return "TRENDING_DOWN"
    else:
        return "SIDEWAYS"


# Strategy priority per regime
REGIME_STRATEGIES = {
    "TRENDING_UP":   ["EMA_CROSS", "SUPERTREND", "MACD_MOMENTUM", "SMC_SCALP"],
    "TRENDING_DOWN": ["EMA_CROSS", "SUPERTREND", "MACD_MOMENTUM", "RSI_REVERSAL"],
    "SIDEWAYS":      ["RSI_REVERSAL", "BB_SQUEEZE", "VWAP_BOUNCE", "SMC_SCALP"],
    "VOLATILE":      ["SMC_SCALP", "BB_SQUEEZE", "VWAP_BOUNCE", "RSI_REVERSAL"],
    "MCX":           ["MCX_AUTO", "EMA_CROSS", "SUPERTREND"],
}

def ai_select_strategy(candles, opt_type, symbol="", vix=18, pcr=1.0, ml_conf=0):
    """
    AI auto-select best strategy based on:
    1. Market regime
    2. ML confidence
    3. Confluence scoring
    """
    from engine.strategies import STRATEGY_MAP, adaptive_tpsl, _atr

    # Detect regime
    is_mcx = symbol.upper() in ("CRUDEOIL","NATURALGAS","CRUDE","NATGAS")
    if is_mcx:
        regime = "MCX"
    else:
        regime = detect_market_regime(candles)

    priority = REGIME_STRATEGIES.get(regime, REGIME_STRATEGIES["SIDEWAYS"])

    best_signal = None
    best_score  = 0
    all_signals = []

    for strat_name in priority:
        strat = STRATEGY_MAP.get(strat_name)
        if not strat:
            continue
        if len(candles) < strat.min_candles:
            continue
        try:
            sig = strat.analyze(candles, opt_type, vix, pcr)
            if sig and sig.get("score", 0) >= 0.55:
                # ML boost
                if ml_conf > 0.6:
                    sig["score"] = min(0.95, sig["score"] + ml_conf * 0.08)
                all_signals.append(sig)
                if sig["score"] > best_score:
                    best_score  = sig["score"]
                    best_signal = sig
        except Exception:
            continue

    if not best_signal:
        return None

    # Confluence bonus
    if len(all_signals) >= 3:
        best_signal["score"] = min(0.95, best_signal["score"] + 0.08)
        best_signal["confluence"] = "HIGH"
    elif len(all_signals) >= 2:
        best_signal["score"] = min(0.95, best_signal["score"] + 0.04)
        best_signal["confluence"] = "MEDIUM"
    else:
        best_signal["confluence"] = "LOW"

    best_signal["regime"]         = regime
    best_signal["strategies_tried"] = [s["strategy"] for s in all_signals]
    best_signal["ml_conf"]        = round(ml_conf, 3)

    return best_signal
