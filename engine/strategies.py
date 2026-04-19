"""
Chanakya v3 — Multi-Strategy Engine
8 Strategies + Adaptive ATR-based TP/SL
ML auto-selects best strategy per market condition
"""
import logging, math
import numpy as np
from datetime import datetime
import pytz

logger = logging.getLogger(__name__)
IST = pytz.timezone("Asia/Kolkata")

# ── INDICATORS ─────────────────────────────────────────

def _ema(prices, n):
    if len(prices) < n: return prices[-1] if prices else 0
    k = 2/(n+1); e = sum(prices[:n])/n
    for p in prices[n:]: e = p*k + e*(1-k)
    return e

def _rsi(prices, n=14):
    if len(prices) < n+1: return 50.0
    d = [prices[i]-prices[i-1] for i in range(1,len(prices))]
    g = [max(x,0) for x in d[-n:]]
    l = [max(-x,0) for x in d[-n:]]
    ag,al = sum(g)/n, sum(l)/n
    return round(100-100/(1+ag/al),2) if al>0 else 100.0

def _atr(candles, n=14):
    if len(candles) < 2: return 0
    trs = [max(c["high"]-c["low"],
               abs(c["high"]-candles[i-1]["close"]),
               abs(c["low"] -candles[i-1]["close"]))
           for i,c in enumerate(candles) if i>0]
    return sum(trs[-n:])/min(n,len(trs)) if trs else 0

def _vwap(candles):
    tv = tp = 0
    for c in candles:
        v = c.get("volume",1)
        tp_c = (c["high"]+c["low"]+c["close"])/3
        tv += v; tp += tp_c*v
    return tp/tv if tv>0 else 0

def _bb(closes, n=20, k=2):
    if len(closes)<n: return closes[-1],closes[-1],0
    sl=closes[-n:]; m=np.mean(sl); s=np.std(sl)
    return m+k*s, m-k*s, 2*k*s/m if m>0 else 0

def _stoch(highs, lows, closes, k=14):
    if len(closes)<k: return 50,50
    h14=max(highs[-k:]); l14=min(lows[-k:])
    if h14==l14: return 50,50
    kv = 100*(closes[-1]-l14)/(h14-l14)
    return round(kv,1), round(kv,1)

def _supertrend(highs, lows, closes, n=7, mult=3.0):
    if len(closes)<n+1: return 1, closes[-1]
    from engine.strategies import _atr as _a
    atr_v = sum([max(highs[i]-lows[i],
                     abs(highs[i]-(closes[i-1] if i>0 else closes[i])),
                     abs(lows[i]-(closes[i-1] if i>0 else closes[i])))
                 for i in range(max(0,len(closes)-n),len(closes))]) / n
    mid = (highs[-1]+lows[-1])/2
    upper = mid+mult*atr_v
    lower = mid-mult*atr_v
    trend = 1 if closes[-1]>lower else -1
    level = lower if trend==1 else upper
    return trend, level

# ── ADAPTIVE TP/SL ─────────────────────────────────────

def adaptive_tpsl(entry, opt_type, atr_val, vix=18, rr_min=1.5, trend_strength=0):
    """
    ATR-based adaptive TP/SL
    VIX high → wider stops
    Strong trend → better R:R
    """
    # Base multipliers
    sl_mult  = 1.5
    tgt_mult = 2.5

    # VIX adjustment
    if vix > 20:   sl_mult += 0.5; tgt_mult += 0.5
    if vix > 25:   sl_mult += 0.5; tgt_mult += 1.0
    if vix < 14:   sl_mult -= 0.3; tgt_mult -= 0.3

    # Trend strength adjustment
    if trend_strength > 0.7:   tgt_mult += 0.5  # Strong trend → higher target
    if trend_strength < 0.3:   tgt_mult -= 0.3  # Weak → conservative

    # Ensure minimum R:R
    while tgt_mult/sl_mult < rr_min:
        tgt_mult += 0.1

    sl_pts  = round(atr_val * sl_mult, 2)
    tgt_pts = round(atr_val * tgt_mult, 2)

    if opt_type == "CE":
        sl  = round(entry - sl_pts,  2)
        tgt = round(entry + tgt_pts, 2)
    else:
        sl  = round(entry + sl_pts,  2)
        tgt = round(entry - tgt_pts, 2)

    rr = round(tgt_pts/sl_pts, 2) if sl_pts>0 else 1.5

    return {
        "entry":  entry,
        "sl":     max(0.05, sl),
        "target": max(0.05, tgt),
        "rr":     rr,
        "sl_pts": sl_pts,
        "tgt_pts":tgt_pts,
        "sl_mult":sl_mult,
        "tgt_mult":tgt_mult,
    }

# ── STRATEGIES ─────────────────────────────────────────

class Strategy:
    name = "BASE"
    min_candles = 30

    def analyze(self, candles, opt_type, vix=18, pcr=1.0) -> dict:
        """Returns signal dict or None"""
        raise NotImplementedError

    def _result(self, candles, opt_type, vix, score, reason, trend_strength=0.5):
        if not candles: return None
        entry = candles[-1]["close"]
        atr_v = _atr(candles)
        if atr_v == 0: atr_v = entry * 0.02
        levels = adaptive_tpsl(entry, opt_type, atr_v, vix, trend_strength=trend_strength)
        return {
            "strategy":   self.name,
            "score":      round(score, 3),
            "reason":     reason,
            "entry":      entry,
            "target":     levels["target"],
            "sl":         levels["sl"],
            "rr":         levels["rr"],
            "opt_type":   opt_type,
            "atr":        round(atr_v, 2),
            "vix":        vix,
        }


class EMACrossStrategy(Strategy):
    """EMA 9/21/50 crossover — trend following"""
    name = "EMA_CROSS"
    min_candles = 55

    def analyze(self, candles, opt_type, vix=18, pcr=1.0):
        closes = [c["close"] for c in candles]
        e9  = _ema(closes, 9)
        e21 = _ema(closes, 21)
        e50 = _ema(closes, 50)
        last = closes[-1]
        rsi14 = _rsi(closes)

        # Bullish CE
        if opt_type == "CE":
            if e9 > e21 > e50 and last > e9:
                rsi_ok = 40 < rsi14 < 75
                score = 0.65
                if rsi_ok: score += 0.10
                if pcr > 1.1: score += 0.05
                ts = min(1.0, (e9-e50)/e50*100) if e50>0 else 0.5
                return self._result(candles, "CE", vix, score,
                    f"EMA Bull: 9>{e9:.1f}>21>{e21:.1f}>50>{e50:.1f} RSI:{rsi14}", ts)
        # Bearish PE
        else:
            if e9 < e21 < e50 and last < e9:
                score = 0.65
                if rsi14 > 55: score += 0.10
                ts = min(1.0, (e50-e9)/e50*100) if e50>0 else 0.5
                return self._result(candles, "PE", vix, score,
                    f"EMA Bear: 9<{e9:.1f}<21<{e21:.1f}<50<{e50:.1f} RSI:{rsi14}", ts)
        return None


class RSIReversalStrategy(Strategy):
    """RSI oversold/overbought reversal"""
    name = "RSI_REVERSAL"
    min_candles = 20

    def analyze(self, candles, opt_type, vix=18, pcr=1.0):
        closes = [c["close"] for c in candles]
        rsi14 = _rsi(closes)
        rsi9  = _rsi(closes, 9)
        e21   = _ema(closes, 21)
        last  = closes[-1]

        if opt_type == "CE" and rsi14 < 35:
            # Oversold + RSI turning up
            if rsi9 > rsi14:  # RSI momentum up
                score = 0.60 + (35-rsi14)/100
                ts = 0.4
                if last > e21*0.98: score += 0.05; ts = 0.6
                return self._result(candles, "CE", vix, score,
                    f"RSI Oversold: {rsi14} turning up, RSI9:{rsi9}", ts)

        elif opt_type == "PE" and rsi14 > 65:
            if rsi9 < rsi14:
                score = 0.60 + (rsi14-65)/100
                ts = 0.4
                if last < e21*1.02: score += 0.05; ts = 0.6
                return self._result(candles, "PE", vix, score,
                    f"RSI Overbought: {rsi14} turning down", ts)
        return None


class MACDMomentumStrategy(Strategy):
    """MACD histogram momentum"""
    name = "MACD_MOMENTUM"
    min_candles = 40

    def analyze(self, candles, opt_type, vix=18, pcr=1.0):
        closes = [c["close"] for c in candles]
        if len(closes) < 35: return None
        e12 = [_ema(closes[:i], 12) for i in range(12, len(closes)+1)]
        e26 = [_ema(closes[:i], 26) for i in range(26, len(closes)+1)]
        if len(e12) < 9 or len(e26) < 9: return None
        macd_line = [e12[i]-e26[i] for i in range(min(len(e12),len(e26)))]
        if len(macd_line) < 9: return None
        sig = _ema(macd_line, 9)
        hist = macd_line[-1] - sig
        prev_hist = macd_line[-2] - sig if len(macd_line)>1 else 0

        if opt_type == "CE" and hist > 0 and hist > prev_hist:
            score = 0.60
            ts = min(1.0, hist/closes[-1]*1000) if closes[-1]>0 else 0.5
            if macd_line[-1] > 0: score += 0.10
            return self._result(candles, "CE", vix, score,
                f"MACD Bull hist:{hist:.2f} rising", ts)

        elif opt_type == "PE" and hist < 0 and hist < prev_hist:
            score = 0.60
            ts = min(1.0, abs(hist)/closes[-1]*1000) if closes[-1]>0 else 0.5
            if macd_line[-1] < 0: score += 0.10
            return self._result(candles, "PE", vix, score,
                f"MACD Bear hist:{hist:.2f} falling", ts)
        return None


class BBSqueezeStrategy(Strategy):
    """Bollinger Band squeeze breakout"""
    name = "BB_SQUEEZE"
    min_candles = 25

    def analyze(self, candles, opt_type, vix=18, pcr=1.0):
        closes = [c["close"] for c in candles]
        highs  = [c["high"]  for c in candles]
        lows   = [c["low"]   for c in candles]
        bb_up, bb_lo, bb_w = _bb(closes)
        last = closes[-1]
        # Previous BB width
        if len(closes) > 5:
            prev_up, prev_lo, prev_w = _bb(closes[:-3])
        else:
            prev_w = bb_w

        # Squeeze — width < 3% AND expanding
        is_squeeze = bb_w < 0.04
        is_expanding = bb_w > prev_w * 1.1

        if opt_type == "CE" and is_expanding and last > bb_up * 0.99:
            score = 0.65 if is_squeeze else 0.55
            ts = min(1.0, bb_w * 10)
            return self._result(candles, "CE", vix, score,
                f"BB Breakout UP bb_w:{bb_w:.3f} last:{last:.1f}>upper:{bb_up:.1f}", ts)

        elif opt_type == "PE" and is_expanding and last < bb_lo * 1.01:
            score = 0.65 if is_squeeze else 0.55
            ts = min(1.0, bb_w * 10)
            return self._result(candles, "PE", vix, score,
                f"BB Breakdown bb_w:{bb_w:.3f} last:{last:.1f}<lower:{bb_lo:.1f}", ts)
        return None


class VWAPBounceStrategy(Strategy):
    """VWAP support/resistance bounce"""
    name = "VWAP_BOUNCE"
    min_candles = 15

    def analyze(self, candles, opt_type, vix=18, pcr=1.0):
        vwap_val = _vwap(candles)
        last = candles[-1]["close"]
        atr_v = _atr(candles)
        if vwap_val == 0 or atr_v == 0: return None

        dist = abs(last - vwap_val) / atr_v

        if opt_type == "CE" and last > vwap_val and dist < 0.5:
            # Price just crossed above VWAP
            score = 0.60
            ts = 0.5
            if dist < 0.2: score += 0.10  # Very close to VWAP = stronger
            return self._result(candles, "CE", vix, score,
                f"VWAP Bounce: last:{last:.1f} > VWAP:{vwap_val:.1f}", ts)

        elif opt_type == "PE" and last < vwap_val and dist < 0.5:
            score = 0.60
            ts = 0.5
            if dist < 0.2: score += 0.10
            return self._result(candles, "PE", vix, score,
                f"VWAP Rejection: last:{last:.1f} < VWAP:{vwap_val:.1f}", ts)
        return None


class SupertrendStrategy(Strategy):
    """Supertrend trend following"""
    name = "SUPERTREND"
    min_candles = 20

    def analyze(self, candles, opt_type, vix=18, pcr=1.0):
        closes = [c["close"] for c in candles]
        highs  = [c["high"]  for c in candles]
        lows   = [c["low"]   for c in candles]
        trend, level = _supertrend(highs, lows, closes)
        last = closes[-1]
        rsi14 = _rsi(closes)
        dist = abs(last - level) / last if last > 0 else 0

        if opt_type == "CE" and trend == 1:
            score = 0.65
            ts = min(1.0, dist * 10)
            if rsi14 > 50: score += 0.05
            return self._result(candles, "CE", vix, score,
                f"Supertrend BULL: level:{level:.1f} dist:{dist:.2%}", ts)

        elif opt_type == "PE" and trend == -1:
            score = 0.65
            ts = min(1.0, dist * 10)
            if rsi14 < 50: score += 0.05
            return self._result(candles, "PE", vix, score,
                f"Supertrend BEAR: level:{level:.1f} dist:{dist:.2%}", ts)
        return None


class MCXAutoStrategy(Strategy):
    """MCX Commodity specific strategy"""
    name = "MCX_AUTO"
    min_candles = 20

    def analyze(self, candles, opt_type, vix=18, pcr=1.0):
        closes = [c["close"] for c in candles]
        highs  = [c["high"]  for c in candles]
        lows   = [c["low"]   for c in candles]
        e9  = _ema(closes, 9)
        e21 = _ema(closes, 21)
        rsi14 = _rsi(closes)
        atr_v = _atr(candles)
        last = closes[-1]

        # MCX: wider ATR multiplier (commodities more volatile)
        if opt_type == "CE":
            if e9 > e21 and rsi14 > 50 and last > e9:
                score = 0.62
                ts = 0.55
                levels = adaptive_tpsl(last, "CE", atr_v*1.5, vix,
                                       rr_min=1.8, trend_strength=ts)
                return {
                    "strategy": self.name,
                    "score": score,
                    "reason": f"MCX Bull: E9:{e9:.1f}>E21:{e21:.1f} RSI:{rsi14}",
                    "entry": last, "target": levels["target"],
                    "sl": levels["sl"], "rr": levels["rr"],
                    "opt_type": "CE", "atr": round(atr_v,2), "vix": vix,
                }
        else:
            if e9 < e21 and rsi14 < 50 and last < e9:
                score = 0.62
                ts = 0.55
                levels = adaptive_tpsl(last, "PE", atr_v*1.5, vix,
                                       rr_min=1.8, trend_strength=ts)
                return {
                    "strategy": self.name,
                    "score": score,
                    "reason": f"MCX Bear: E9:{e9:.1f}<E21:{e21:.1f} RSI:{rsi14}",
                    "entry": last, "target": levels["target"],
                    "sl": levels["sl"], "rr": levels["rr"],
                    "opt_type": "PE", "atr": round(atr_v,2), "vix": vix,
                }
        return None


class SMCScalpStrategy(Strategy):
    """Smart Money Concepts scalp"""
    name = "SMC_SCALP"
    min_candles = 25

    def analyze(self, candles, opt_type, vix=18, pcr=1.0):
        closes = [c["close"] for c in candles]
        highs  = [c["high"]  for c in candles]
        lows   = [c["low"]   for c in candles]
        last = closes[-1]

        # Order block detection
        lookback = min(20, len(candles)-3)
        ob_bull = ob_bear = 0
        for i in range(-lookback, -2):
            if (closes[i] < closes[i-1] and  # Down candle
                closes[i+1] > closes[i] and closes[i+1] > closes[i-1]):
                ob_bull = closes[i]  # Bullish OB
            if (closes[i] > closes[i-1] and  # Up candle
                closes[i+1] < closes[i] and closes[i+1] < closes[i-1]):
                ob_bear = closes[i]  # Bearish OB

        atr_v = _atr(candles)
        rsi14 = _rsi(closes)

        if opt_type == "CE" and ob_bull > 0:
            dist = abs(last - ob_bull) / atr_v if atr_v > 0 else 99
            if dist < 1.5:
                score = 0.68
                ts = 0.6
                if rsi14 > 45: score += 0.05
                return self._result(candles, "CE", vix, score,
                    f"SMC OB Bull at {ob_bull:.1f} dist:{dist:.1f}ATR", ts)

        elif opt_type == "PE" and ob_bear > 0:
            dist = abs(last - ob_bear) / atr_v if atr_v > 0 else 99
            if dist < 1.5:
                score = 0.68
                ts = 0.6
                if rsi14 < 55: score += 0.05
                return self._result(candles, "PE", vix, score,
                    f"SMC OB Bear at {ob_bear:.1f} dist:{dist:.1f}ATR", ts)
        return None


# ── STRATEGY REGISTRY ──────────────────────────────────

ALL_STRATEGIES = [
    SMCScalpStrategy(),
    EMACrossStrategy(),
    RSIReversalStrategy(),
    MACDMomentumStrategy(),
    BBSqueezeStrategy(),
    VWAPBounceStrategy(),
    SupertrendStrategy(),
    MCXAutoStrategy(),
]

STRATEGY_MAP = {s.name: s for s in ALL_STRATEGIES}

def get_all_signals(candles, opt_type, vix=18, pcr=1.0, symbol=""):
    """Run all strategies — return all signals sorted by score"""
    signals = []
    for strat in ALL_STRATEGIES:
        # Skip MCX for NSE symbols
        if strat.name == "MCX_AUTO" and symbol in ("NIFTY","BANKNIFTY","FINNIFTY"):
            continue
        if len(candles) < strat.min_candles:
            continue
        try:
            sig = strat.analyze(candles, opt_type, vix, pcr)
            if sig and sig.get("score", 0) >= 0.55:
                sig["symbol"] = symbol
                signals.append(sig)
        except Exception as e:
            logger.debug(f"{strat.name} error: {e}")
    signals.sort(key=lambda x: x.get("score",0), reverse=True)
    return signals

def get_best_signal(candles, opt_type, vix=18, pcr=1.0, symbol="", ml_boost=0):
    """Get highest scoring signal with ML boost"""
    signals = get_all_signals(candles, opt_type, vix, pcr, symbol)
    if not signals: return None
    best = signals[0]
    # ML confidence boost
    if ml_boost > 0:
        best["score"] = min(0.99, best["score"] + ml_boost * 0.1)
        best["ml_boost"] = round(ml_boost, 3)
    best["all_strategies"] = [s["strategy"] for s in signals]
    best["strategy_count"] = len(signals)
    return best

def confluence_score(candles, opt_type, vix=18, pcr=1.0, symbol=""):
    """How many strategies agree? (confluence = stronger signal)"""
    signals = get_all_signals(candles, opt_type, vix, pcr, symbol)
    if not signals: return 0, []
    avg_score = sum(s["score"] for s in signals) / len(signals)
    # Confluence bonus
    if len(signals) >= 4: avg_score = min(0.95, avg_score + 0.10)
    elif len(signals) >= 3: avg_score = min(0.95, avg_score + 0.05)
    return round(avg_score, 3), [s["strategy"] for s in signals]
