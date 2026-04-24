"""
Chanakya AI v4.0 — Multi-Timeframe Engine
"जो शत्रूची चाल आधी ओळखतो — तोच जिंकतो"

MTF Logic:
  15m → Master Trend
  5m  → Confirmation  
  1m  → Entry Timing
"""
import logging
import numpy as np
from datetime import datetime, timedelta
import pytz

logger = logging.getLogger(__name__)
IST = pytz.timezone("Asia/Kolkata")


def ema(values, period):
    """Exponential Moving Average"""
    if len(values) < period:
        return []
    result = []
    k = 2.0 / (period + 1)
    e = sum(values[:period]) / period
    result.append(e)
    for v in values[period:]:
        e = v * k + e * (1 - k)
        result.append(e)
    return result


def rsi(values, period=14):
    """RSI calculation"""
    if len(values) < period + 1:
        return 50.0
    deltas = [values[i+1] - values[i] for i in range(len(values)-1)]
    gains  = [d if d > 0 else 0 for d in deltas]
    losses = [-d if d < 0 else 0 for d in deltas]
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period-1) + gains[i]) / period
        avg_loss = (avg_loss * (period-1) + losses[i]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100 - (100 / (1 + rs)), 2)


def adx(highs, lows, closes, period=14):
    """Average Directional Index"""
    if len(closes) < period + 1:
        return 0.0
    trs, pdms, mdms = [], [], []
    for i in range(1, len(closes)):
        h, l, pc = highs[i], lows[i], closes[i-1]
        tr  = max(h-l, abs(h-pc), abs(l-pc))
        pdm = max(h - highs[i-1], 0)
        mdm = max(lows[i-1] - l, 0)
        if pdm > mdm: mdm = 0
        elif mdm > pdm: pdm = 0
        trs.append(tr); pdms.append(pdm); mdms.append(mdm)

    def smooth(vals, p):
        s = sum(vals[:p])
        result = [s]
        for v in vals[p:]:
            s = s - s/p + v
            result.append(s)
        return result

    atr  = smooth(trs,  period)
    spdi = smooth(pdms, period)
    smdi = smooth(mdms, period)

    dxs = []
    for i in range(len(atr)):
        if atr[i] == 0: continue
        pdi = 100 * spdi[i] / atr[i]
        mdi = 100 * smdi[i] / atr[i]
        dx  = 100 * abs(pdi - mdi) / (pdi + mdi) if (pdi + mdi) > 0 else 0
        dxs.append(dx)

    return round(sum(dxs[-period:]) / period, 2) if len(dxs) >= period else 0.0


def vwap(candles):
    """Volume Weighted Average Price"""
    total_vol = sum(c.get("volume", 0) for c in candles)
    if total_vol == 0:
        return candles[-1]["close"] if candles else 0
    vwap_val = sum(
        ((c["high"] + c["low"] + c["close"]) / 3) * c.get("volume", 1)
        for c in candles
    ) / total_vol
    return round(vwap_val, 2)


def volume_spike(candles, window=20, threshold=1.5):
    """Detect volume spike — current vs average"""
    if len(candles) < window:
        return False, 1.0
    vols = [c.get("volume", 0) for c in candles]
    avg  = sum(vols[-window-1:-1]) / window
    curr = vols[-1]
    ratio = (curr / avg) if avg > 0 else 1.0
    return ratio >= threshold, round(ratio, 2)


def get_trend(candles, label=""):
    """
    Detect trend using EMA20/50 + ADX
    Returns: TRENDING_UP / TRENDING_DOWN / SIDEWAYS
    """
    if len(candles) < 51:
        return "SIDEWAYS", {}

    closes = [c["close"] for c in candles]
    highs  = [c["high"]  for c in candles]
    lows   = [c["low"]   for c in candles]

    ema20_vals = ema(closes, 20)
    ema50_vals = ema(closes, 50)

    if not ema20_vals or not ema50_vals:
        return "SIDEWAYS", {}

    e20 = ema20_vals[-1]
    e50 = ema50_vals[-1]
    adx_val = adx(highs, lows, closes, 14)

    if e20 > e50 and adx_val > 20:
        trend = "TRENDING_UP"
    elif e20 < e50 and adx_val > 20:
        trend = "TRENDING_DOWN"
    else:
        trend = "SIDEWAYS"

    logger.debug(f"[{label}] EMA20={e20:.1f} EMA50={e50:.1f} ADX={adx_val:.1f} → {trend}")

    return trend, {
        "ema20":   round(e20, 2),
        "ema50":   round(e50, 2),
        "adx":     adx_val,
        "trend":   trend,
    }


def analyze_mtf(broker, symbol, token, exchange):
    """
    Full MTF analysis — 15m + 5m + 1m
    Returns comprehensive signal dict
    """
    try:
        from engine.candles import get_candles

        # Fetch 3 timeframes
        c15 = get_candles(broker, token, exchange=exchange, interval="FIFTEEN_MINUTE", days=10)
        c5  = get_candles(broker, token, exchange=exchange, interval="FIVE_MINUTE",    days=5)
        c1  = get_candles(broker, token, exchange=exchange, interval="ONE_MINUTE",     days=2)

        def to_dict(raw):
            return [{"open":c[1],"high":c[2],"low":c[3],"close":c[4],"volume":c[5]}
                    for c in raw] if raw else []

        c15d = to_dict(c15)
        c5d  = to_dict(c5)
        c1d  = to_dict(c1)

        if len(c15d) < 51 or len(c5d) < 25:
            return None

        # Trend per timeframe
        trend_15m, info_15m = get_trend(c15d, "15m")
        trend_5m,  info_5m  = get_trend(c5d,  "5m")

        # 1m indicators
        rsi_1m   = rsi([c["close"] for c in c1d]) if len(c1d) > 14 else 50.0
        vwap_val = vwap(c5d)
        ltp      = c5d[-1]["close"] if c5d else 0
        vol_spike, vol_ratio = volume_spike(c5d)

        # Master trend decision
        if trend_15m == trend_5m == "TRENDING_UP":
            master = "TRENDING_UP"
            opt_bias = "CE"
        elif trend_15m == trend_5m == "TRENDING_DOWN":
            master = "TRENDING_DOWN"
            opt_bias = "PE"
        else:
            master = "SIDEWAYS"
            opt_bias = "NONE"

        # ADX strength
        adx_val = info_15m.get("adx", 0)

        result = {
            "symbol":      symbol,
            "ltp":         ltp,
            "master_trend": master,
            "opt_bias":    opt_bias,
            "trend_15m":   trend_15m,
            "trend_5m":    trend_5m,
            "rsi_1m":      rsi_1m,
            "vwap":        vwap_val,
            "above_vwap":  ltp > vwap_val,
            "vol_spike":   vol_spike,
            "vol_ratio":   vol_ratio,
            "adx":         adx_val,
            "ema20_15m":   info_15m.get("ema20", 0),
            "ema50_15m":   info_15m.get("ema50", 0),
            "ema20_5m":    info_5m.get("ema20", 0),
            "ema50_5m":    info_5m.get("ema50", 0),
        }

        logger.info(f"MTF {symbol}: {master} | RSI={rsi_1m} | VWAP={vwap_val} | ADX={adx_val}")
        return result

    except Exception as e:
        logger.error(f"MTF {symbol}: {e}")
        return None
