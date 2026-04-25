"""
Chanakya AI — Real Option Backtest Engine
Uses actual option premium candles (not simulation)
"""
import logging, sqlite3
from datetime import datetime
import pytz

logger = logging.getLogger(__name__)
IST = pytz.timezone("Asia/Kolkata")

OPTION_SYMBOLS = {
    "NIFTY": {
        "spot_token": "99926000",
        "spot_exch":  "NSE",
        "interval":   50,
        "options": [
            {"symbol":"NIFTY28APR2623700CE","token":"72251","strike":23700,"type":"CE"},
            {"symbol":"NIFTY28APR2623700PE","token":"72252","strike":23700,"type":"PE"},
            {"symbol":"NIFTY28APR2623800CE","token":"72255","strike":23800,"type":"CE"},
            {"symbol":"NIFTY28APR2623800PE","token":"72256","strike":23800,"type":"PE"},
            {"symbol":"NIFTY28APR2623900CE","token":"72259","strike":23900,"type":"CE"},
            {"symbol":"NIFTY28APR2623900PE","token":"72260","strike":23900,"type":"PE"},
            {"symbol":"NIFTY28APR2624000CE","token":"72263","strike":24000,"type":"CE"},
            {"symbol":"NIFTY28APR2624000PE","token":"72264","strike":24000,"type":"PE"},
            {"symbol":"NIFTY28APR2624100CE","token":"72267","strike":24100,"type":"CE"},
            {"symbol":"NIFTY28APR2624100PE","token":"72268","strike":24100,"type":"PE"},
        ]
    }
}


def get_option_candles(opt_symbol, interval="FIVE_MINUTE", days=30):
    """Get real option candles from DB"""
    from engine.candle_db import get_candles_db
    return get_candles_db(opt_symbol, interval, days=days)


def get_spot_candles(symbol, interval="FIVE_MINUTE", days=30):
    """Get spot index candles from DB"""
    from engine.candle_db import get_candles_db
    return get_candles_db(symbol, interval, days=days)


def calc_ema(values, period):
    if len(values) < period: return [None]*len(values)
    k = 2.0/(period+1)
    e = sum(values[:period])/period
    result = [None]*(period-1) + [e]
    for v in values[period:]:
        e = v*k + e*(1-k)
        result.append(e)
    return result


def calc_rsi(values, period=14):
    if len(values) < period+1: return 50.0
    deltas = [values[i+1]-values[i] for i in range(len(values)-1)]
    gains  = [d if d>0 else 0 for d in deltas]
    losses = [-d if d<0 else 0 for d in deltas]
    ag = sum(gains[:period])/period
    al = sum(losses[:period])/period
    for i in range(period, len(gains)):
        ag = (ag*(period-1)+gains[i])/period
        al = (al*(period-1)+losses[i])/period
    return round(100-(100/(1+ag/al)),2) if al>0 else 100.0


def calc_vwap(candles):
    ct=cv=0; result=[]
    for c in candles:
        tp=(c['high']+c['low']+c['close'])/3
        ct+=tp*(c['volume'] or 1); cv+=(c['volume'] or 1)
        result.append(ct/cv)
    return result


def calc_atr(candles, period=14):
    if len(candles)<2: return 0
    trs=[max(candles[i]['high']-candles[i]['low'],
             abs(candles[i]['high']-candles[i-1]['close']),
             abs(candles[i]['low']-candles[i-1]['close']))
         for i in range(1,len(candles))]
    return sum(trs[-period:])/min(period,len(trs)) if trs else 0


def generate_spot_signals(spot_candles, opt_type="CE"):
    """Generate signals from spot data"""
    signals = []
    if len(spot_candles) < 55: return signals

    closes = [c['close'] for c in spot_candles]
    highs  = [c['high']  for c in spot_candles]
    lows   = [c['low']   for c in spot_candles]
    vwaps  = calc_vwap(spot_candles)
    ema9   = calc_ema(closes, 9)
    ema21  = calc_ema(closes, 21)
    ema50  = calc_ema(closes, 50)

    prev_i = -15

    for i in range(55, len(spot_candles)-5):
        if i - prev_i < 12: continue

        c  = spot_candles[i]
        ts = c['ts']
        dt = datetime.fromtimestamp(ts, IST)
        h,m = dt.hour, dt.minute

        # No-trade zones
        if (9,15)<=(h,m)<=(9,30): continue
        if (15,0)<=(h,m)<=(15,30): continue
        if dt.weekday() >= 5: continue

        e9  = ema9[i]
        e21 = ema21[i]
        e50 = ema50[i]
        if e9 is None or e21 is None or e50 is None: continue

        vwap_v = vwaps[i]
        rsi_v  = calc_rsi(closes[max(0,i-30):i+1])
        atr_v  = calc_atr(spot_candles[:i+1])
        ltp    = c['close']

        score = 0

        if opt_type == "CE":
            # Bullish conditions
            if e9 > e21 > e50: score += 30
            elif e9 > e21: score += 15
            if ltp > vwap_v: score += 20
            if rsi_v < 45: score += 20
            elif rsi_v < 55: score += 10
            # Breakout of prev candle high
            if i > 0 and c['high'] > spot_candles[i-1]['high']: score += 15
            # Volume
            vols = [spot_candles[j].get('volume',0) for j in range(max(0,i-20),i)]
            avg_v = sum(vols)/len(vols) if vols else 1
            if avg_v > 0 and c.get('volume',0) > avg_v*1.5: score += 15
        else:
            # Bearish conditions
            if e9 < e21 < e50: score += 30
            elif e9 < e21: score += 15
            if ltp < vwap_v: score += 20
            if rsi_v > 55: score += 20
            elif rsi_v > 45: score += 10
            # Breakdown of prev candle low
            if i > 0 and c['low'] < spot_candles[i-1]['low']: score += 15
            # Volume
            vols = [spot_candles[j].get('volume',0) for j in range(max(0,i-20),i)]
            avg_v = sum(vols)/len(vols) if vols else 1
            if avg_v > 0 and c.get('volume',0) > avg_v*1.5: score += 15

        # Skip low volatility
        if atr_v < 3:
            continue

        if score >= 75:
            signals.append({
                "ts":       ts,
                "score":    score,
                "opt_type": opt_type,
                "spot":     ltp,
                "vwap":     round(vwap_v,2),
                "rsi":      rsi_v,
                "atr":      round(atr_v,2),
                "candle_i": i,
                "e9":       round(e9,2),
                "e21":      round(e21,2),
            })
            prev_i = i

    return signals


def find_atm_option(spot, options, opt_type):
    """Find slightly ITM option for faster premium move"""
    atm = round(spot/50)*50
    candidates = [o for o in options if o['type']==opt_type]
    if not candidates: return None
    # CE: slightly ITM = strike below spot | PE: slightly ITM = strike above spot
    if opt_type == "CE":
        target_strike = atm - 50  # 1 strike ITM for CE
    else:
        target_strike = atm + 50  # 1 strike ITM for PE
    candidates.sort(key=lambda x: abs(x['strike']-target_strike))
    return candidates[0]


def simulate_real_trade(signal, opt_candles, sl_pct=0.12, t1_pct=0.08, t2_pct=0.15, t3_pct=0.25):
    """
    Simulate trade using REAL option candles
    Find matching timestamp in option candles
    """
    # Find entry candle in option data
    sig_ts = signal['ts']

    # Find closest candle at or after signal
    entry_idx = None
    for i, c in enumerate(opt_candles):
        if c['ts'] >= sig_ts:
            entry_idx = i
            break

    if entry_idx is None or entry_idx >= len(opt_candles)-2:
        return None

    entry_candle = opt_candles[entry_idx]
    entry_price  = entry_candle['close']

    if entry_price <= 0:
        return None

    # Slippage: buy at high of entry candle (realistic)
    entry_price = entry_candle['high'] * 0.998  # 0.2% slippage
    entry_price = round(entry_price, 1)

    sl     = round(entry_price * (1 - sl_pct), 1)
    t1     = round(entry_price * (1 + t1_pct), 1)
    t2     = round(entry_price * (1 + t2_pct), 1)
    t3     = round(entry_price * (1 + t3_pct), 1)

    result = {
        "ts":          sig_ts,
        "entry":       entry_price,
        "sl":          sl,
        "t1":          t1,
        "t2":          t2,
        "t3":          t3,
        "exit":        entry_price,
        "exit_reason": "TIMEOUT",
        "pnl_pct":     0.0,
        "t1_hit":      False,
        "t2_hit":      False,
        "t3_hit":      False,
        "bars_held":   0,
        "signal_score": signal['score'],
        "spot_entry":  signal['spot'],
    }

    trail_sl  = sl
    max_bars  = 6   # Max 30 min scalping
    brokerage = 0.001  # 0.1% per side

    for i in range(entry_idx+1, min(entry_idx+max_bars+1, len(opt_candles))):
        c = opt_candles[i]
        result['bars_held'] = i - entry_idx
        h = c['high']; l = c['low']; cl = c['close']

        # T3
        if result['t2_hit'] and h >= t3:
            result['t3_hit']     = True
            result['exit']       = round(t3 * (1-brokerage), 1)
            result['exit_reason']= "T3_HIT"
            break

        # T2
        if result['t1_hit'] and h >= t2:
            result['t2_hit'] = True
            trail_sl = round(entry_price * 1.10, 1)  # Trail to +10%

        # T1
        if not result['t1_hit'] and h >= t1:
            result['t1_hit'] = True
            trail_sl = round(entry_price * 1.02, 1)  # Lock 2% profit

        # SL
        if l <= trail_sl:
            result['exit']       = round(trail_sl * (1-brokerage), 1)
            result['exit_reason']= "TRAIL_SL" if result['t1_hit'] else "SL_HIT"
            break

        # No momentum exit (stuck trade)
        if i - entry_idx >= 3 and cl < entry_price * 1.005:
            if not result['t1_hit']:
                result['exit']       = round(cl * (1-brokerage), 1)
                result['exit_reason']= "NO_MOMENTUM"
                break

        # Final timeout
        if i == min(entry_idx+max_bars, len(opt_candles)-1):
            result['exit']       = round(cl * (1-brokerage), 1)
            result['exit_reason']= "TIMEOUT"

    pnl = (result['exit'] - entry_price) / entry_price * 100
    pnl = max(pnl, -sl_pct*100)
    result['pnl_pct'] = round(pnl, 2)
    result['pnl']     = round(pnl, 2)
    return result


def run_real_backtest(symbol="NIFTY", interval="FIVE_MINUTE", days=30, opt_type="CE"):
    """Full backtest with real option candles"""
    config = OPTION_SYMBOLS.get(symbol)
    if not config:
        return {"error": f"Symbol {symbol} not configured"}

    # Get spot candles
    spot_candles = get_spot_candles(symbol, interval, days=days)
    if len(spot_candles) < 60:
        return {"error": f"Not enough spot candles: {len(spot_candles)}"}

    # Generate signals from spot
    signals = generate_spot_signals(spot_candles, opt_type)
    if not signals:
        return {"error": "No signals generated", "candles": len(spot_candles)}

    trades = []; last_exit_i = 0

    for sig in signals:
        if sig['candle_i'] < last_exit_i+5: continue

        # Find best ATM option at signal time
        spot = sig['spot']
        opt_info = find_atm_option(spot, config['options'], opt_type)
        if not opt_info: continue

        # Get option candles
        opt_sym = opt_info['symbol']
        opt_candles = get_option_candles(opt_sym, interval, days=days)
        if not opt_candles: continue

        # Simulate trade
        trade = simulate_real_trade(sig, opt_candles)
        if not trade: continue

        trade['option_symbol'] = opt_sym
        trade['strike']        = opt_info['strike']
        trades.append(trade)
        last_exit_i = sig['candle_i'] + trade['bars_held']

    if not trades:
        return {"error": "No trades executed", "signals": len(signals)}

    # Statistics
    wins   = [t for t in trades if t['pnl']>0]
    losses = [t for t in trades if t['pnl']<=0]
    t_pnl  = sum(t['pnl'] for t in trades)
    t1_hit = sum(1 for t in trades if t['t1_hit'])
    t2_hit = sum(1 for t in trades if t['t2_hit'])
    t3_hit = sum(1 for t in trades if t['t3_hit'])

    exit_reasons = {}
    for t in trades:
        r = t['exit_reason']
        exit_reasons[r] = exit_reasons.get(r,0)+1

    avg_win  = sum(t['pnl'] for t in wins)/len(wins)   if wins else 0
    avg_loss = sum(t['pnl'] for t in losses)/len(losses) if losses else 0
    rr       = abs(avg_win/avg_loss) if avg_loss<0 else 0

    # Drawdown
    cum=pk=dd=0
    for t in trades:
        cum+=t['pnl']
        if cum>pk: pk=cum
        if pk-cum>dd: dd=pk-cum

    mw=ml=cw=cl=0
    for t in trades:
        if t['pnl']>0: cw+=1;cl=0;mw=max(mw,cw)
        else: cl+=1;cw=0;ml=max(ml,cl)

    return {
        "symbol":       symbol,
        "opt_type":     opt_type,
        "interval":     interval,
        "days":         days,
        "data_type":    "REAL_OPTION_CANDLES",
        "spot_candles": len(spot_candles),
        "signals":      len(signals),
        "trades":       len(trades),
        "wins":         len(wins),
        "losses":       len(losses),
        "win_rate":     round(len(wins)/len(trades)*100,1),
        "total_pnl":    round(t_pnl,2),
        "avg_win":      round(avg_win,2),
        "avg_loss":     round(avg_loss,2),
        "rr_ratio":     round(rr,2),
        "max_drawdown": round(dd,2),
        "t1_rate":      round(t1_hit/len(trades)*100,1),
        "t2_rate":      round(t2_hit/len(trades)*100,1),
        "t3_rate":      round(t3_hit/len(trades)*100,1),
        "exit_reasons": exit_reasons,
        "max_consec_win":  mw,
        "max_consec_loss": ml,
        "profit_factor": round(abs(sum(t['pnl'] for t in wins)/sum(t['pnl'] for t in losses)),2) if losses and sum(t['pnl'] for t in losses)!=0 else 0,
        "trade_list":   trades,
    }
