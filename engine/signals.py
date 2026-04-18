"""
Chanakya v3 — Signal Generation Engine
ATR + Smart Money + Multi-TF Confluence
"""
import logging, math
from datetime import datetime
import pytz
from config import config

logger = logging.getLogger(__name__)
IST = pytz.timezone("Asia/Kolkata")

# ── Technical Indicators ───────────────────────────────
def ema(prices, period):
    if len(prices) < period:
        return []
    result, k = [], 2 / (period + 1)
    result.append(sum(prices[:period]) / period)
    for p in prices[period:]:
        result.append(p * k + result[-1] * (1 - k))
    return result

def rsi(prices, period=14):
    if len(prices) < period + 1:
        return 50.0
    gains, losses = [], []
    for i in range(1, len(prices)):
        d = prices[i] - prices[i-1]
        gains.append(max(d, 0))
        losses.append(max(-d, 0))
    avg_g = sum(gains[:period]) / period
    avg_l = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        avg_g = (avg_g * (period-1) + gains[i]) / period
        avg_l = (avg_l * (period-1) + losses[i]) / period
    if avg_l == 0:
        return 100.0
    return round(100 - 100 / (1 + avg_g / avg_l), 2)

def atr(candles, period=14):
    """Average True Range"""
    if len(candles) < period + 1:
        return 0.0
    trs = []
    for i in range(1, len(candles)):
        h, l, pc = candles[i][2], candles[i][3], candles[i-1][4]
        trs.append(max(h-l, abs(h-pc), abs(l-pc)))
    if len(trs) < period:
        return sum(trs) / len(trs) if trs else 0.0
    avg = sum(trs[:period]) / period
    for tr in trs[period:]:
        avg = (avg * (period-1) + tr) / period
    return round(avg, 2)

def vwap(candles):
    """Volume Weighted Average Price"""
    if not candles:
        return 0.0
    tp_vol = sum(((c[2]+c[3]+c[4])/3) * c[5] for c in candles)
    vol    = sum(c[5] for c in candles)
    return round(tp_vol / vol, 2) if vol > 0 else 0.0

def macd(prices, fast=12, slow=26, signal=9):
    if len(prices) < slow + signal:
        return 0, 0, 0
    ema_fast = ema(prices, fast)
    ema_slow = ema(prices, slow)
    min_len  = min(len(ema_fast), len(ema_slow))
    macd_line = [ema_fast[-min_len+i] - ema_slow[-min_len+i]
                 for i in range(min_len)]
    signal_line = ema(macd_line, signal)
    if not signal_line:
        return 0, 0, 0
    hist = macd_line[-1] - signal_line[-1]
    return round(macd_line[-1], 4), round(signal_line[-1], 4), round(hist, 4)

# ── Smart Money Concepts ───────────────────────────────
class SmartMoneySMC:
    def detect_order_blocks(self, candles, lookback=20):
        """
        Bullish OB: Last bearish candle before strong bullish move
        Bearish OB: Last bullish candle before strong bearish move
        """
        obs = []
        if len(candles) < lookback:
            return obs
        for i in range(2, min(lookback, len(candles)-2)):
            c = candles[-i]
            next_c = candles[-i+1]
            o, h, l, close = c[1], c[2], c[3], c[4]
            # Bullish OB: bearish candle followed by strong bull move
            if close < o:  # bearish candle
                move = next_c[4] - next_c[1]
                if move > (h - l) * 1.5:  # Strong follow-through
                    obs.append({"type": "BULLISH_OB", "high": h, "low": l,
                               "index": i, "strength": move / (h-l)})
            # Bearish OB: bullish candle followed by strong bear move
            elif close > o:
                move = next_c[1] - next_c[4]
                if move > (h - l) * 1.5:
                    obs.append({"type": "BEARISH_OB", "high": h, "low": l,
                               "index": i, "strength": move / (h-l)})
        return obs[:3]  # Top 3 most recent

    def detect_fvg(self, candles):
        """Fair Value Gap: 3-candle imbalance"""
        fvgs = []
        if len(candles) < 3:
            return fvgs
        for i in range(len(candles)-3):
            c1, c2, c3 = candles[i], candles[i+1], candles[i+2]
            # Bullish FVG: C1 high < C3 low (gap up)
            if c1[2] < c3[3]:
                fvgs.append({"type": "BULLISH_FVG",
                            "top": c3[3], "bottom": c1[2],
                            "size": c3[3] - c1[2]})
            # Bearish FVG: C1 low > C3 high (gap down)
            elif c1[3] > c3[2]:
                fvgs.append({"type": "BEARISH_FVG",
                            "top": c1[3], "bottom": c3[2],
                            "size": c1[3] - c3[2]})
        return fvgs[-3:] if fvgs else []

    def detect_liquidity_sweep(self, candles, lookback=20):
        """Stop hunt: price breaks key level then reverses"""
        if len(candles) < lookback + 2:
            return None
        recent = candles[-lookback:]
        prev_high = max(c[2] for c in recent[:-2])
        prev_low  = min(c[3] for c in recent[:-2])
        last = candles[-1]
        # Bullish sweep: price breaks below prev_low then closes above
        if last[3] < prev_low and last[4] > prev_low:
            return {"type": "BULLISH_SWEEP", "level": prev_low,
                   "signal": "BUY_CE"}
        # Bearish sweep: price breaks above prev_high then closes below
        if last[2] > prev_high and last[4] < prev_high:
            return {"type": "BEARISH_SWEEP", "level": prev_high,
                   "signal": "BUY_PE"}
        return None

    def market_structure(self, candles, lookback=20):
        """HH+HL=Uptrend | LH+LL=Downtrend | MSS=Reversal"""
        if len(candles) < lookback:
            return "UNKNOWN"
        highs = [c[2] for c in candles[-lookback:]]
        lows  = [c[3] for c in candles[-lookback:]]
        mid   = lookback // 2
        h1, h2 = max(highs[:mid]), max(highs[mid:])
        l1, l2 = min(lows[:mid]),  min(lows[mid:])
        if h2 > h1 and l2 > l1:   return "UPTREND"
        if h2 < h1 and l2 < l1:   return "DOWNTREND"
        if h2 < h1 and l2 > l1:   return "CONSOLIDATION"
        return "REVERSAL"

# ── Main Signal Generator ──────────────────────────────
class SignalEngine:
    def __init__(self):
        self.smc = SmartMoneySMC()

    def is_market_open(self, exchange="NSE"):
        now = datetime.now(IST)
        if now.weekday() >= 5:   # Weekend
            return False
        h, m = now.hour, now.minute
        t = h * 60 + m
        if exchange == "NSE":
            return 555 <= t <= 930    # 9:15 - 15:30
        else:  # MCX
            return 540 <= t <= 1410   # 9:00 - 23:30

    def analyze(self, candles, symbol, opt_type, spot=0, vix=18, pcr=1.0, fii_bias="NEUTRAL"):
        """
        Full signal analysis.
        Returns signal dict with all indicators.
        """
        if len(candles) < 20:
            return {"signal": "INSUFFICIENT_DATA", "confidence": 0}

        closes  = [c[4] for c in candles]
        highs   = [c[2] for c in candles]
        lows    = [c[3] for c in candles]
        volumes = [c[5] for c in candles] if len(candles[0]) > 5 else []

        # ── Indicators ────────────────────
        rsi_val     = rsi(closes)
        atr_val     = atr(candles)
        ema9        = ema(closes, 9)
        ema21       = ema(closes, 21)
        ema50       = ema(closes, 50)
        macd_val, macd_sig, macd_hist = macd(closes)
        vwap_val    = vwap(candles) if volumes else 0

        last_close  = closes[-1]
        ema9_last   = ema9[-1]  if ema9  else 0
        ema21_last  = ema21[-1] if ema21 else 0
        ema50_last  = ema50[-1] if ema50 else 0

        # ── Trend Detection ───────────────
        trend = "NEUTRAL"
        if ema9_last > ema21_last > ema50_last and last_close > ema9_last:
            trend = "UPTREND"
        elif ema9_last < ema21_last < ema50_last and last_close < ema9_last:
            trend = "DOWNTREND"

        # ── SMC Analysis ──────────────────
        structure   = self.smc.market_structure(candles)
        obs         = self.smc.detect_order_blocks(candles)
        fvgs        = self.smc.detect_fvg(candles)
        sweep       = self.smc.detect_liquidity_sweep(candles)

        # ── Scoring ───────────────────────
        score = 50  # Neutral start

        if opt_type == "CE":  # Bullish signals
            if trend == "UPTREND":           score += 15
            if rsi_val < 40:                 score += 10  # Oversold
            if rsi_val > 50:                 score += 5
            if macd_hist > 0:                score += 8
            if last_close > vwap_val > 0:    score += 7
            if structure in ("UPTREND",):    score += 10
            if sweep and "BULLISH" in sweep.get("type",""):  score += 15
            if any(o["type"]=="BULLISH_OB" for o in obs):   score += 12
            if "BULL" in fii_bias:           score += 10
            if pcr < 0.7:                    score += 10
            if pcr < 0.85:                   score += 5
            if vix < 15:                     score += 8
        else:  # PE — Bearish signals
            if trend == "DOWNTREND":         score += 15
            if rsi_val > 60:                 score += 10  # Overbought
            if rsi_val < 50:                 score += 5
            if macd_hist < 0:                score += 8
            if last_close < vwap_val > 0:    score += 7
            if structure in ("DOWNTREND",):  score += 10
            if sweep and "BEARISH" in sweep.get("type",""):  score += 15
            if any(o["type"]=="BEARISH_OB" for o in obs):   score += 12
            if "BEAR" in fii_bias:           score += 10
            if pcr > 1.3:                    score += 10
            if pcr > 1.1:                    score += 5
            if vix > 22:                     score += 8

        # Penalty for VIX extremes
        if vix > 25: score -= 20
        if vix > 20: score -= 10

        score = min(95, max(5, score))

        # ── Signal Decision ───────────────
        if score >= 75:
            signal, strength = f"STRONG_BUY_{opt_type}", "STRONG"
        elif score >= 65:
            signal, strength = f"BUY_{opt_type}", "MODERATE"
        elif score >= 55:
            signal, strength = f"WEAK_{opt_type}", "WEAK"
        else:
            signal, strength = "AVOID", "AVOID"

        return {
            "signal":    signal,
            "strength":  strength,
            "score":     score,
            "rsi":       rsi_val,
            "atr":       atr_val,
            "trend":     trend,
            "structure": structure,
            "macd_hist": macd_hist,
            "ema_aligned": trend in ("UPTREND", "DOWNTREND"),
            "smc": {
                "order_blocks": obs,
                "fvg":          fvgs,
                "sweep":        sweep,
            },
            "indicators": {
                "ema9":  round(ema9_last, 2),
                "ema21": round(ema21_last, 2),
                "ema50": round(ema50_last, 2),
                "rsi":   rsi_val,
                "macd":  macd_hist,
                "vwap":  vwap_val,
            }
        }

smc_engine  = SmartMoneySMC()
signal_engine = SignalEngine()
