"""
Chanakya AI — Equity Scanner
Scans NSE equities for profitable momentum signals
Uses: RSI, EMA, MACD, Volume, Supertrend
"""
import logging, sqlite3, time
from datetime import datetime
import pytz

logger = logging.getLogger(__name__)
IST = pytz.timezone("Asia/Kolkata")

# Top NSE equity watchlist — liquid stocks
EQUITY_WATCHLIST = [
    {"symbol": "RELIANCE",   "token": "2885",  "exchange": "NSE"},
    {"symbol": "TCS",        "token": "11536", "exchange": "NSE"},
    {"symbol": "INFY",       "token": "1594",  "exchange": "NSE"},
    {"symbol": "HDFCBANK",   "token": "1333",  "exchange": "NSE"},
    {"symbol": "ICICIBANK",  "token": "4963",  "exchange": "NSE"},
    {"symbol": "SBIN",       "token": "3045",  "exchange": "NSE"},
    {"symbol": "AXISBANK",   "token": "5900",  "exchange": "NSE"},
    {"symbol": "WIPRO",      "token": "3787",  "exchange": "NSE"},
    {"symbol": "TATAMOTORS", "token": "3456",  "exchange": "NSE"},
    {"symbol": "BAJFINANCE", "token": "317",   "exchange": "NSE"},
    {"symbol": "HCLTECH",    "token": "1232",  "exchange": "NSE"},
    {"symbol": "MARUTI",     "token": "10999", "exchange": "NSE"},
    {"symbol": "ITC",        "token": "1660",  "exchange": "NSE"},
    {"symbol": "KOTAKBANK",  "token": "1922",  "exchange": "NSE"},
    {"symbol": "LTIM",       "token": "17818", "exchange": "NSE"},
    {"symbol": "SUNPHARMA",  "token": "3351",  "exchange": "NSE"},
    {"symbol": "TITAN",      "token": "3506",  "exchange": "NSE"},
    {"symbol": "ASIANPAINT", "token": "236",   "exchange": "NSE"},
    {"symbol": "NESTLEIND",  "token": "17963", "exchange": "NSE"},
    {"symbol": "BHARTIARTL", "token": "10604", "exchange": "NSE"},
]


def _ema(data, period):
    if len(data) < period:
        return data[-1] if data else 0
    k = 2/(period+1)
    e = sum(data[:period])/period
    for d in data[period:]:
        e = d*k + e*(1-k)
    return e


def _rsi(closes, period=14):
    if len(closes) < period+1:
        return 50
    gains = [max(closes[i]-closes[i-1],0) for i in range(1,len(closes))]
    losses = [max(closes[i-1]-closes[i],0) for i in range(1,len(closes))]
    ag = sum(gains[-period:])/period
    al = sum(losses[-period:])/period
    if al == 0:
        return 100
    return round(100 - 100/(1+ag/al), 1)


def _macd(closes):
    if len(closes) < 26:
        return 0, 0
    e12 = _ema(closes, 12)
    e26 = _ema(closes, 26)
    macd = e12 - e26
    signal = _ema(closes[-9:], 9)
    return round(macd, 2), round(macd - signal, 2)


def _supertrend(candles, period=7, mult=3):
    """Supertrend indicator"""
    if len(candles) < period:
        return "NEUTRAL"
    highs  = [c["high"] for c in candles[-period:]]
    lows   = [c["low"]  for c in candles[-period:]]
    closes = [c["close"] for c in candles]
    tr_list = []
    for i in range(1, len(highs)):
        tr = max(highs[i]-lows[i],
                 abs(highs[i]-closes[-period+i-1]),
                 abs(lows[i]-closes[-period+i-1]))
        tr_list.append(tr)
    atr = sum(tr_list)/len(tr_list) if tr_list else 0
    upper = (sum(highs)/len(highs)+sum(lows)/len(lows))/2 + mult*atr
    lower = (sum(highs)/len(highs)+sum(lows)/len(lows))/2 - mult*atr
    ltp   = closes[-1]
    if ltp > lower:
        return "BULLISH"
    elif ltp < upper:
        return "BEARISH"
    return "NEUTRAL"


def scan_equity(broker, capital=10000):
    """
    Scan equity watchlist for profitable signals
    Returns signals with position size + brokerage-adjusted targets
    """
    from engine.brokerage_calc import calc_equity_intraday, position_size_equity
    from engine.rate_limiter import get_rate_limiter
    rl = get_rate_limiter()

    signals = []
    logger.info(f"📊 Equity scan started — {len(EQUITY_WATCHLIST)} stocks")

    for stock in EQUITY_WATCHLIST:
        try:
            # Rate limited candle fetch
            rl.wait_if_needed("candleData")
            now = datetime.now(IST)
            from_dt = now.strftime("%Y-%m-%d") + " 09:15"
            to_dt   = now.strftime("%Y-%m-%d %H:%M")

            r = broker.api.getCandleData({
                "exchange":    stock["exchange"],
                "symboltoken": stock["token"],
                "interval":    "FIVE_MINUTE",
                "fromdate":    from_dt,
                "todate":      to_dt,
            })

            if not r or not r.get("data") or len(r["data"]) < 20:
                continue

            candles = r["data"]
            closes  = [float(c[4]) for c in candles]
            volumes = [float(c[5]) for c in candles]
            highs   = [float(c[2]) for c in candles]
            lows    = [float(c[3]) for c in candles]

            ltp    = closes[-1]
            rsi    = _rsi(closes)
            ema9   = _ema(closes, 9)
            ema21  = _ema(closes, 21)
            ema50  = _ema(closes[-50:] if len(closes)>=50 else closes, 50)
            macd, macd_hist = _macd(closes)
            vol_avg = sum(volumes[-20:])/20
            vol_now = volumes[-1]
            vol_ratio = vol_now/vol_avg if vol_avg > 0 else 1

            candle_dicts = [{"high":float(c[2]),"low":float(c[3]),"close":float(c[4])} for c in candles]
            trend = _supertrend(candle_dicts)

            # Scoring
            score = 0
            direction = None

            # BULLISH signals
            bull_score = 0
            if ema9 > ema21 > ema50:         bull_score += 30
            elif ema9 > ema21:               bull_score += 15
            if rsi > 50 and rsi < 70:        bull_score += 20
            if macd_hist > 0:                bull_score += 20
            if vol_ratio > 1.5:              bull_score += 15
            if trend == "BULLISH":           bull_score += 15

            # BEARISH signals
            bear_score = 0
            if ema9 < ema21 < ema50:         bear_score += 30
            elif ema9 < ema21:               bear_score += 15
            if rsi < 50 and rsi > 30:        bear_score += 20
            if macd_hist < 0:                bear_score += 20
            if vol_ratio > 1.5:              bear_score += 15
            if trend == "BEARISH":           bear_score += 15

            if bull_score > bear_score and bull_score >= 60:
                score = bull_score
                direction = "BUY"
            elif bear_score > bull_score and bear_score >= 60:
                score = bear_score
                direction = "SELL"
            else:
                continue

            # Calculate SL/Target
            atr = sum([highs[i]-lows[i] for i in range(-10,0)])/10
            if direction == "BUY":
                sl     = round(ltp - 1.5*atr, 2)
                target = round(ltp + 3.0*atr, 2)
            else:
                sl     = round(ltp + 1.5*atr, 2)
                target = round(ltp - 3.0*atr, 2)

            # Position sizing
            qty = position_size_equity(capital, 1.5, ltp, sl)
            if qty <= 0:
                continue

            # Brokerage calculation
            brok = calc_equity_intraday(ltp, target, qty)

            # Skip if net profit too low
            if brok["net_pnl"] < 50:
                continue

            signals.append({
                "symbol":       stock["symbol"],
                "token":        stock["token"],
                "exchange":     "NSE",
                "trading_symbol": stock["symbol"] + "-EQ",
                "direction":    direction,
                "ltp":          ltp,
                "entry":        ltp,
                "sl":           sl,
                "target":       target,
                "qty":          qty,
                "score":        round(score/100, 3),
                "rsi":          rsi,
                "trend":        trend,
                "vol_ratio":    round(vol_ratio, 2),
                "macd_hist":    macd_hist,
                "net_profit":   brok["net_pnl"],
                "charges":      brok["total_charges"],
                "breakeven":    brok["breakeven"],
                "rr":           round(abs(target-ltp)/abs(ltp-sl), 2),
                "type":         "EQUITY",
            })

            logger.info(f"✅ {stock['symbol']}: {direction} score={score}% "
                       f"entry={ltp} sl={sl} T={target} qty={qty} "
                       f"net=Rs{brok['net_pnl']}")

        except Exception as e:
            logger.debug(f"Equity scan {stock['symbol']}: {e}")
            continue

    signals.sort(key=lambda x: x["score"], reverse=True)
    logger.info(f"📊 Equity scan: {len(signals)} signals")
    return signals
