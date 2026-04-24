"""
Chanakya AI v4.0 — Decision Engine
Score 0-100 + ML Ensemble Voting
"Data + Discipline = Profit"
"""
import logging
from datetime import datetime
import pytz

logger = logging.getLogger(__name__)
IST = pytz.timezone("Asia/Kolkata")

# No-trade time zones
NO_TRADE_TIMES = [
    ("09:15", "09:21"),  # Opening volatility
    ("11:30", "12:01"),  # Lunch lull
    ("15:15", "15:31"),  # Closing
]


def is_no_trade_time():
    now = datetime.now(IST).strftime("%H:%M")
    for start, end in NO_TRADE_TIMES:
        if start <= now <= end:
            return True, f"No-trade zone {start}-{end}"
    return False, ""


def calculate_score(mtf_data, opts_intel=None, opt_type="CE"):
    """
    Score 0-100 based on all signals
    Score >= 70 → TRADE
    Score 50-69 → MONITOR
    Score < 50  → SKIP
    """
    score = 0
    reasons = []

    if not mtf_data:
        return 0, ["No MTF data"]

    master  = mtf_data.get("master_trend", "SIDEWAYS")
    rsi_val = mtf_data.get("rsi_1m", 50)
    above_vwap = mtf_data.get("above_vwap", False)
    vol_spike  = mtf_data.get("vol_spike", False)
    vol_ratio  = mtf_data.get("vol_ratio", 1.0)
    adx_val    = mtf_data.get("adx", 0)

    # 1. MTF Trend Match (+30)
    if opt_type == "CE" and master == "TRENDING_UP":
        score += 30
        reasons.append("MTF UP +30")
    elif opt_type == "PE" and master == "TRENDING_DOWN":
        score += 30
        reasons.append("MTF DOWN +30")
    elif master == "SIDEWAYS":
        score -= 15
        reasons.append("SIDEWAYS -15")

    # 2. RSI Signal (+25)
    if opt_type == "CE" and rsi_val < 35:
        score += 25
        reasons.append(f"RSI oversold {rsi_val} +25")
    elif opt_type == "PE" and rsi_val > 65:
        score += 25
        reasons.append(f"RSI overbought {rsi_val} +25")
    elif opt_type == "CE" and 35 <= rsi_val <= 50:
        score += 10
        reasons.append(f"RSI neutral-low {rsi_val} +10")
    elif opt_type == "PE" and 50 <= rsi_val <= 65:
        score += 10
        reasons.append(f"RSI neutral-high {rsi_val} +10")

    # 3. VWAP Position (+20)
    if opt_type == "CE" and above_vwap:
        score += 20
        reasons.append("Above VWAP +20")
    elif opt_type == "PE" and not above_vwap:
        score += 20
        reasons.append("Below VWAP +20")
    else:
        score -= 5
        reasons.append("VWAP opposing -5")

    # 4. Volume Spike (+20)
    if vol_spike and vol_ratio >= 2.0:
        score += 20
        reasons.append(f"Vol spike {vol_ratio}x +20")
    elif vol_spike and vol_ratio >= 1.5:
        score += 12
        reasons.append(f"Vol spike {vol_ratio}x +12")

    # 5. ADX Strength (+10/-15)
    if adx_val >= 25:
        score += 10
        reasons.append(f"ADX strong {adx_val} +10")
    elif adx_val < 20:
        score -= 15
        reasons.append(f"ADX weak {adx_val} -15")

    # 6. Options Intelligence (+15)
    if opts_intel:
        pcr_bias  = opts_intel.get("pcr_bias", "NEUTRAL")
        iv_signal = opts_intel.get("iv_signal", "NORMAL_IV")
        spot      = opts_intel.get("spot", 0)
        support   = opts_intel.get("support", 0)
        resistance= opts_intel.get("resistance", 0)

        if opt_type == "CE" and pcr_bias == "BULLISH":
            score += 10
            reasons.append("PCR bullish +10")
        elif opt_type == "PE" and pcr_bias == "BEARISH":
            score += 10
            reasons.append("PCR bearish +10")

        if iv_signal == "HIGH_IV_AVOID":
            score -= 20
            reasons.append("High IV expensive -20")
        elif iv_signal == "LOW_IV_BUY":
            score += 5
            reasons.append("Low IV cheap +5")

        if opt_type == "CE" and support > 0 and spot > support:
            score += 5
            reasons.append("Above OI support +5")
        elif opt_type == "PE" and resistance > 0 and spot < resistance:
            score += 5
            reasons.append("Below OI resistance +5")

    score = max(0, min(100, score))
    return score, reasons


def make_decision(mtf_data, opts_intel=None, ml_prob=None):
    """
    Final trading decision
    Returns: signal dict or None
    """
    # No-trade zone check
    no_trade, reason = is_no_trade_time()
    if no_trade:
        logger.debug(f"Skip: {reason}")
        return None

    # ADX filter
    adx_val = mtf_data.get("adx", 0) if mtf_data else 0
    if adx_val < 15:
        logger.debug("Skip: ADX too weak")
        return None

    master = mtf_data.get("master_trend", "SIDEWAYS") if mtf_data else "SIDEWAYS"

    best_signal = None
    best_score  = 0

    for opt_type in ["CE", "PE"]:
        # Skip opposing direction
        if opt_type == "CE" and master == "TRENDING_DOWN":
            continue
        if opt_type == "PE" and master == "TRENDING_UP":
            continue

        score, reasons = calculate_score(mtf_data, opts_intel, opt_type)

        # ML boost
        if ml_prob:
            prob = ml_prob.get("bullish" if opt_type=="CE" else "bearish", 0.5)
            if prob > 0.65:
                score += 10
                reasons.append(f"ML {prob:.2f} +10")
            elif prob < 0.35:
                score -= 10

        if score > best_score:
            best_score  = score
            best_signal = {
                "opt_type":  opt_type,
                "score":     score,
                "score_pct": f"{score}%",
                "reasons":   reasons,
                "action":    "TRADE" if score >= 70 else "MONITOR" if score >= 50 else "SKIP",
                "master_trend": master,
                "rsi":       mtf_data.get("rsi_1m", 50) if mtf_data else 50,
                "vwap":      mtf_data.get("vwap", 0) if mtf_data else 0,
                "adx":       adx_val,
            }

    if best_signal and best_signal["action"] == "TRADE":
        logger.info(f"SIGNAL: {best_signal['opt_type']} score={best_score} {best_signal['reasons'][:2]}")
        return best_signal

    return None
