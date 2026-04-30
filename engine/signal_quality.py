"""
Chanakya AI — Signal Quality Filter
Win rate boost: MTF + ADX + IV + No-trade zones
"""
import logging
from datetime import datetime
import pytz

logger = logging.getLogger(__name__)
IST = pytz.timezone("Asia/Kolkata")

# No-trade time zones (IST)
NO_TRADE_ZONES = [
    ("09:15", "09:30"),  # Opening noise
    ("11:30", "12:00"),  # Lunch lull
    ("15:00", "15:30"),  # Closing noise
]

# Minimum requirements
MIN_ADX        = 25     # Strong trend only
MIN_SCORE      = 80     # Strict filter (was 70)
MIN_CANDLES_1M = 20     # Min 1m candles needed
MAX_IV_PCT     = 35.0   # Avoid expensive options
MIN_IV_PCT     = 8.0    # Avoid dead options


def is_no_trade_time():
    """Check if current time is in no-trade zone"""
    now = datetime.now(IST).strftime("%H:%M")
    for start, end in NO_TRADE_ZONES:
        if start <= now <= end:
            return True, f"{start}-{end}"
    return False, ""


def is_market_sideways(adx_val, vix=None):
    """Detect sideways/choppy market"""
    if adx_val < MIN_ADX:
        return True, f"ADX {adx_val} < {MIN_ADX}"
    if vix and vix > 25:
        return True, f"VIX {vix} > 25"
    return False, ""


def check_mtf_alignment(broker, symbol, token, exchange):
    """
    Check 15m + 5m + 1m trend alignment
    Returns: (aligned, opt_type, strength)
    """
    try:
        from engine.candle_db import get_candles_db
        from engine.mtf_engine import get_trend, calc_rsi

        # Get candles from DB
        c15 = get_candles_db(symbol, "FIFTEEN_MINUTE", days=10)
        c5  = get_candles_db(symbol, "FIVE_MINUTE",    days=5)
        c1  = get_candles_db(symbol, "ONE_MINUTE",     days=2)

        if len(c15) < 51 or len(c5) < 25:
            return False, "NONE", 0

        def to_ohlc(rows):
            return [{"open":r['open'],"high":r['high'],"low":r['low'],
                     "close":r['close'],"volume":r.get('volume',0)}
                    for r in rows]

        t15, i15 = get_trend(to_ohlc(c15), "15m")
        t5,  i5  = get_trend(to_ohlc(c5),  "5m")

        # Both timeframes must agree
        if t15 == t5 == "TRENDING_UP":
            opt_type = "CE"
            strength = (i15.get('adx',0) + i5.get('adx',0)) / 2
        elif t15 == t5 == "TRENDING_DOWN":
            opt_type = "PE"
            strength = (i15.get('adx',0) + i5.get('adx',0)) / 2
        else:
            return False, "NONE", 0

        # 1m entry timing
        if len(c1) >= 15:
            rsi_1m = calc_rsi([c['close'] for c in c1])
            if opt_type == "CE" and rsi_1m > 70:
                return False, "NONE", 0  # Overbought — skip
            if opt_type == "PE" and rsi_1m < 30:
                return False, "NONE", 0  # Oversold — skip

        return True, opt_type, round(strength, 1)

    except Exception as e:
        logger.debug(f"MTF check: {e}")
        return False, "NONE", 0


def enhanced_score(mtf_data, opts_intel=None, opt_type="CE", vix=18.0):
    """
    Enhanced scoring 0-100 with strict filters
    """
    score   = 0
    reasons = []
    penalty = 0

    if not mtf_data:
        return 0, ["No data"]

    master     = mtf_data.get("master_trend","SIDEWAYS")
    rsi_val    = mtf_data.get("rsi_1m", 50)
    above_vwap = mtf_data.get("above_vwap", False)
    vol_spike  = mtf_data.get("vol_spike", False)
    vol_ratio  = mtf_data.get("vol_ratio", 1.0)
    adx_val    = mtf_data.get("adx", 0)
    trend_15m  = mtf_data.get("trend_15m","SIDEWAYS")
    trend_5m   = mtf_data.get("trend_5m","SIDEWAYS")

    # 1. MTF Trend Alignment (+35 max)
    if opt_type == "CE":
        if trend_15m == trend_5m == "TRENDING_UP":
            score += 35
            reasons.append("15m+5m UP +35")
        elif master == "TRENDING_UP":
            score += 15
            reasons.append("Partial UP +15")
        else:
            penalty += 30
            reasons.append("No UP trend -30")
    else:
        if trend_15m == trend_5m == "TRENDING_DOWN":
            score += 35
            reasons.append("15m+5m DOWN +35")
        elif master == "TRENDING_DOWN":
            score += 15
            reasons.append("Partial DOWN +15")
        else:
            penalty += 30
            reasons.append("No DOWN trend -30")

    # 2. ADX Strength (+15 max)
    if adx_val >= 30:
        score += 15
        reasons.append(f"ADX {adx_val} strong +15")
    elif adx_val >= 25:
        score += 10
        reasons.append(f"ADX {adx_val} +10")
    elif adx_val < 20:
        penalty += 20
        reasons.append(f"ADX {adx_val} weak -20")

    # 3. RSI Signal (+20 max)
    if opt_type == "CE":
        if rsi_val < 35:
            score += 20; reasons.append(f"RSI oversold {rsi_val} +20")
        elif rsi_val < 45:
            score += 10; reasons.append(f"RSI low {rsi_val} +10")
        elif rsi_val > 70:
            penalty += 15; reasons.append(f"RSI overbought {rsi_val} -15")
    else:
        if rsi_val > 65:
            score += 20; reasons.append(f"RSI overbought {rsi_val} +20")
        elif rsi_val > 55:
            score += 10; reasons.append(f"RSI high {rsi_val} +10")
        elif rsi_val < 30:
            penalty += 15; reasons.append(f"RSI oversold {rsi_val} -15")

    # 4. VWAP (+15 max)
    if opt_type == "CE" and above_vwap:
        score += 15; reasons.append("Above VWAP +15")
    elif opt_type == "PE" and not above_vwap:
        score += 15; reasons.append("Below VWAP +15")
    else:
        penalty += 10; reasons.append("VWAP opposing -10")

    # 5. Volume Spike (+15 max)
    if vol_spike and vol_ratio >= 2.0:
        score += 15; reasons.append(f"Vol {vol_ratio}x +15")
    elif vol_spike:
        score += 8;  reasons.append(f"Vol {vol_ratio}x +8")

    # 6. VIX Filter
    if vix > 25:
        penalty += 15; reasons.append(f"VIX {vix} high -15")
    elif vix < 15:
        score += 5; reasons.append(f"VIX {vix} low +5")

    # 7. Options Intel (+10 max)
    if opts_intel:
        iv = opts_intel.get("iv_proxy", 0)
        pcr_bias = opts_intel.get("pcr_bias","NEUTRAL")
        iv_signal = opts_intel.get("iv_signal","NORMAL_IV")

        if iv_signal == "HIGH_IV_AVOID":
            penalty += 20; reasons.append("High IV -20")
        elif iv_signal == "LOW_IV_BUY":
            score += 10; reasons.append("Low IV +10")

        if opt_type=="CE" and pcr_bias=="BULLISH":
            score += 5; reasons.append("PCR bull +5")
        elif opt_type=="PE" and pcr_bias=="BEARISH":
            score += 5; reasons.append("PCR bear +5")

    final = max(0, min(100, score - penalty))
    return final, reasons


def _get_ml_boost(mtf_data, opt_type="CE"):
    """Get ML confidence boost from XGBoost"""
    try:
        from ai.ml_engine import get_brain
        brain = get_brain()
        if not brain or not brain.is_trained:
            return 0.5
        rsi = mtf_data.get("rsi", 50)
        macd = mtf_data.get("macd_hist", 0)
        ema9 = mtf_data.get("ema9", 0)
        ema21 = mtf_data.get("ema21", 0)
        ltp  = mtf_data.get("ltp", 1)
        feats = [
            rsi/100, macd/ltp if ltp>0 else 0,
            (ema9-ema21)/ema21 if ema21>0 else 0,
            1.0 if opt_type=="CE" else 0.0,
            0.5, 18/50, 1/3,
        ] + [0]*35
        prob = float(brain.predict_proba([feats[:42]])[0][1])
        return prob
    except Exception:
        return 0.5


def make_quality_decision(mtf_data, opts_intel=None, ml_prob=None, vix=18.0):
    """
    Quality decision with all filters
    Min score: 80 (was 70)
    """
    # Time filter
    no_trade, nt_reason = is_no_trade_time()
    if no_trade:
        return None

    # ADX filter
    adx_val = mtf_data.get("adx", 0) if mtf_data else 0
    sideways, sw_reason = is_market_sideways(adx_val, vix)
    if sideways:
        return None

    master = mtf_data.get("master_trend","SIDEWAYS") if mtf_data else "SIDEWAYS"
    if master == "SIDEWAYS":
        return None

    best = None; best_score = 0

    for opt_type in ["CE","PE"]:
        if opt_type=="CE" and master=="TRENDING_DOWN": continue
        if opt_type=="PE" and master=="TRENDING_UP":   continue

        score, reasons = enhanced_score(mtf_data, opts_intel, opt_type, vix)

        # ML boost
        if ml_prob:
            prob = ml_prob.get("bullish" if opt_type=="CE" else "bearish", 0.5)
            if prob > 0.65:
                score = min(100, score+5)
                reasons.append(f"ML {prob:.2f} +5")
            elif prob < 0.35:
                score = max(0, score-10)

        if score > best_score:
            best_score = score
            best = {
                "opt_type":     opt_type,
                "score":        score,
                "score_pct":    f"{score}%",
                "confluence":   "HIGH" if score>=85 else "MEDIUM" if score>=80 else "LOW",
                "action":       "TRADE"  if score>=MIN_SCORE else
                                "MONITOR" if score>=70 else "SKIP",
                "reasons":      reasons,
                "master_trend": master,
                "rsi":          mtf_data.get("rsi_1m",50) if mtf_data else 50,
                "vwap":         mtf_data.get("vwap",0) if mtf_data else 0,
                "adx":          adx_val,
            }

    if best and best["action"] == "TRADE":
        logger.info(f"QUALITY SIGNAL: {best['opt_type']} score={best_score}")
        return best
    return None
