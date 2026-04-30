"""
Chanakya AI — Equity Scanner v2.0
5-Layer filter: Trend + Momentum + Volume + RR + Capital
Min score 75% → Signal
"""
import logging
logger = logging.getLogger(__name__)

WATCHLIST = [
    {"symbol":"RELIANCE","token":"2885"},{"symbol":"TCS","token":"11536"},
    {"symbol":"INFY","token":"1594"},{"symbol":"HDFCBANK","token":"1333"},
    {"symbol":"ICICIBANK","token":"4963"},{"symbol":"SBIN","token":"3045"},
    {"symbol":"WIPRO","token":"3787"},{"symbol":"TATAMOTORS","token":"3456"},
    {"symbol":"ITC","token":"1660"},{"symbol":"AXISBANK","token":"5900"},
    {"symbol":"BAJFINANCE","token":"317"},{"symbol":"HCLTECH","token":"1232"},
    {"symbol":"MARUTI","token":"10999"},{"symbol":"KOTAKBANK","token":"1922"},
    {"symbol":"SUNPHARMA","token":"3351"},{"symbol":"TITAN","token":"3506"},
    {"symbol":"ASIANPAINT","token":"236"},{"symbol":"BHARTIARTL","token":"10604"},
    {"symbol":"LTIM","token":"17818"},{"symbol":"NESTLEIND","token":"17963"},
]

def _ema(data, p):
    if len(data) < p: return data[-1] if data else 0
    k = 2/(p+1); e = sum(data[:p])/p
    for d in data[p:]: e = d*k + e*(1-k)
    return e

def _rsi(closes, p=14):
    if len(closes) < p+1: return 50
    g = [max(closes[i]-closes[i-1], 0) for i in range(1, len(closes))]
    l = [max(closes[i-1]-closes[i], 0) for i in range(1, len(closes))]
    ag = sum(g[-p:])/p; al = sum(l[-p:])/p
    return round(100 - 100/(1+ag/al), 1) if al > 0 else 100

def _macd(closes):
    if len(closes) < 26: return 0, 0
    e12 = _ema(closes[-12:], 12)
    e26 = _ema(closes[-26:], 26)
    macd = e12 - e26
    signal = _ema(closes[-9:], 9)
    return round(macd, 3), round(macd - signal, 3)

def _vwap(candles):
    """VWAP calculation"""
    tp_vol = sum(((c[2]+c[3]+c[4])/3) * c[5] for c in candles)
    vol    = sum(c[5] for c in candles)
    return round(tp_vol/vol, 2) if vol > 0 else 0

def _supertrend(highs, lows, closes, period=7, mult=3):
    if len(closes) < period+1: return "NEUTRAL"
    atr_list = []
    for i in range(1, len(closes)):
        tr = max(highs[i]-lows[i],
                 abs(highs[i]-closes[i-1]),
                 abs(lows[i]-closes[i-1]))
        atr_list.append(tr)
    atr = sum(atr_list[-period:])/period if atr_list else 0
    hl2 = (highs[-1]+lows[-1])/2
    upper = hl2 + mult*atr
    lower = hl2 - mult*atr
    ltp = closes[-1]
    if ltp > lower: return "BULLISH"
    if ltp < upper: return "BEARISH"
    return "NEUTRAL"

def _higher_highs(closes, n=5):
    """Check if price making higher highs"""
    if len(closes) < n+1: return False
    recent = closes[-n:]
    return all(recent[i] >= recent[i-1] for i in range(1, len(recent)))

def scan_equity(broker, capital=10000):
    from engine.brokerage_calc import calc_equity_intraday, position_size_equity
    from engine.rate_limiter import get_rate_limiter
    from datetime import datetime
    import pytz

    rl  = get_rate_limiter()
    IST = pytz.timezone("Asia/Kolkata")
    signals = []

    logger.info(f"📊 Equity scan v2.0 — {len(WATCHLIST)} stocks capital=Rs{capital}")

    for stock in WATCHLIST:
        try:
            rl.wait_if_needed("candleData")
            now = datetime.now(IST)
            r = broker.api.getCandleData({
                "exchange":    "NSE",
                "symboltoken": stock["token"],
                "interval":    "FIVE_MINUTE",
                "fromdate":    now.strftime("%Y-%m-%d") + " 09:15",
                "todate":      now.strftime("%Y-%m-%d %H:%M"),
            })
            if not r or not r.get("data") or len(r["data"]) < 26:
                continue

            raw    = r["data"]
            closes = [float(c[4]) for c in raw]
            opens  = [float(c[1]) for c in raw]
            highs  = [float(c[2]) for c in raw]
            lows   = [float(c[3]) for c in raw]
            vols   = [float(c[5]) for c in raw]
            ltp    = closes[-1]

            # Skip if stock too expensive for capital
            if ltp > capital * 0.5:
                continue

            # ── INDICATORS ─────────────────────────────
            ema9  = _ema(closes, 9)
            ema21 = _ema(closes, 21)
            ema50 = _ema(closes[-50:] if len(closes) >= 50 else closes, 50)
            rsi   = _rsi(closes)
            macd_val, macd_hist = _macd(closes)
            vwap  = _vwap([(0, o, h, l, c, v) for o,h,l,c,v in zip(opens,highs,lows,closes,vols)])
            st    = _supertrend(highs, lows, closes)
            vol_avg = sum(vols[-20:])/20
            vol_now = vols[-1]
            vol_ratio = round(vol_now/vol_avg, 2) if vol_avg > 0 else 1
            hh = _higher_highs(closes)

            # ATR for SL/Target
            atr_list = [highs[i]-lows[i] for i in range(-10, 0)]
            atr = sum(atr_list)/len(atr_list) if atr_list else ltp*0.01

            # ── 5 LAYER SCORING ─────────────────────────
            score = 0
            reasons = []

            # LAYER 1: TREND (25pts)
            if ema9 > ema21 > ema50:
                score += 25; reasons.append("EMA9>21>50 +25")
            elif ema9 > ema21:
                score += 12; reasons.append("EMA9>21 +12")

            # LAYER 2: MOMENTUM (20pts)
            if 50 <= rsi <= 65:
                score += 20; reasons.append(f"RSI {rsi} +20")
            elif 45 <= rsi < 50:
                score += 10; reasons.append(f"RSI {rsi} +10")
            elif rsi > 70:
                score -= 15; reasons.append(f"RSI overbought {rsi} -15")

            # LAYER 3: MACD (15pts)
            if macd_hist > 0 and macd_val > 0:
                score += 15; reasons.append(f"MACD bull +15")
            elif macd_hist > 0:
                score += 8; reasons.append(f"MACD hist+ +8")

            # LAYER 4: VOLUME (20pts)
            if vol_ratio >= 2.0:
                score += 20; reasons.append(f"Vol {vol_ratio}x +20")
            elif vol_ratio >= 1.5:
                score += 12; reasons.append(f"Vol {vol_ratio}x +12")
            elif vol_ratio < 0.8:
                score -= 10; reasons.append(f"Low vol -10")

            # LAYER 5: VWAP + Supertrend (20pts)
            if ltp > vwap:
                score += 10; reasons.append("Above VWAP +10")
            if st == "BULLISH":
                score += 10; reasons.append("Supertrend bull +10")

            # BONUS: Higher highs
            if hh:
                score += 5; reasons.append("Higher highs +5")

            # MIN SCORE CHECK: 65%
            if score < 65:
                logger.debug(f"{stock['symbol']}: score={score} < 65 — skip")
                continue

            # ── ENTRY/SL/TARGET ─────────────────────────
            sl     = round(ltp - 1.5*atr, 2)
            target = round(ltp + 3.0*atr, 2)
            rr     = round(abs(target-ltp)/abs(ltp-sl), 2) if ltp > sl else 0

            # MIN RR: 2:1
            if rr < 2.0:
                logger.debug(f"{stock['symbol']}: RR={rr} < 2 — skip")
                continue

            # CAPITAL CHECK
            qty = position_size_equity(capital, 1.5, ltp, sl)
            if qty <= 0:
                continue

            # BROKERAGE DEDUCT
            brok = calc_equity_intraday(ltp, target, qty)

            # MIN NET PROFIT: Rs100
            if brok["net_pnl"] < 100:
                logger.debug(f"{stock['symbol']}: net={brok['net_pnl']} < 100 — skip")
                continue

            signals.append({
                "symbol":    stock["symbol"],
                "token":     stock["token"],
                "exchange":  "NSE",
                "direction": "BUY",
                "ltp":       ltp,
                "entry":     ltp,
                "sl":        sl,
                "target":    target,
                "qty":       qty,
                "score":     round(score/100, 3),
                "score_pct": score,
                "rsi":       rsi,
                "macd_hist": macd_hist,
                "vol_ratio": vol_ratio,
                "vwap":      vwap,
                "supertrend":st,
                "atr":       round(atr, 2),
                "rr":        rr,
                "net_profit":brok["net_pnl"],
                "charges":   brok["total_charges"],
                "breakeven": brok["breakeven"],
                "reasons":   reasons,
                "type":      "EQUITY",
            })

            logger.info(f"✅ {stock['symbol']}: score={score}% "
                       f"E={ltp} SL={sl} T={target} RR={rr} "
                       f"qty={qty} net=Rs{brok['net_pnl']}")

        except Exception as e:
            logger.debug(f"Equity {stock['symbol']}: {e}")
            continue

    signals.sort(key=lambda x: x["score"], reverse=True)
    logger.info(f"📊 Equity scan done: {len(signals)} signals")
    return signals
