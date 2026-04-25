"""
Chanakya AI — Backtest Engine
Historical signal validation using candle DB
"""
import logging, json, sqlite3
from datetime import datetime, timedelta
import pytz

logger = logging.getLogger(__name__)
IST = pytz.timezone("Asia/Kolkata")


def get_candles_for_backtest(symbol, interval, days=30):
    """Get candles from DB for backtesting"""
    from engine.candle_db import get_candles_db
    return get_candles_db(symbol, interval, days=days)


def calc_ema(values, period):
    if len(values) < period:
        return []
    k = 2.0 / (period + 1)
    e = sum(values[:period]) / period
    result = [e]
    for v in values[period:]:
        e = v * k + e * (1 - k)
        result.append(e)
    return result


def calc_rsi(values, period=14):
    if len(values) < period + 1:
        return 50.0
    deltas = [values[i+1] - values[i] for i in range(len(values)-1)]
    gains  = [d if d > 0 else 0 for d in deltas]
    losses = [-d if d < 0 else 0 for d in deltas]
    ag = sum(gains[:period]) / period
    al = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        ag = (ag * (period-1) + gains[i]) / period
        al = (al * (period-1) + losses[i]) / period
    return round(100 - (100 / (1 + ag/al)), 2) if al > 0 else 100.0


def calc_adx(highs, lows, closes, period=14):
    if len(closes) < period + 2:
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

    def smooth(v, p):
        s = sum(v[:p])
        r = [s]
        for x in v[p:]:
            s = s - s/p + x
            r.append(s)
        return r

    atr  = smooth(trs,  period)
    spdi = smooth(pdms, period)
    smdi = smooth(mdms, period)
    dxs  = []
    for i in range(len(atr)):
        if atr[i] == 0: continue
        pdi = 100 * spdi[i] / atr[i]
        mdi = 100 * smdi[i] / atr[i]
        dx  = 100 * abs(pdi-mdi) / (pdi+mdi) if (pdi+mdi) > 0 else 0
        dxs.append(dx)
    return round(sum(dxs[-period:]) / period, 2) if len(dxs) >= period else 0.0


def calc_vwap(candles):
    ct = cv = 0
    result = []
    for c in candles:
        tp = (c['high'] + c['low'] + c['close']) / 3
        ct += tp * (c['volume'] or 1)
        cv += (c['volume'] or 1)
        result.append(ct / cv)
    return result


def generate_signals(candles, symbol="NIFTY", opt_type="CE"):
    """
    Generate signals from historical candles
    Returns list of signal dicts with entry points
    """
    signals = []
    if len(candles) < 60:
        return signals

    closes = [c['close'] for c in candles]
    highs  = [c['high']  for c in candles]
    lows   = [c['low']   for c in candles]
    vwaps  = calc_vwap(candles)

    ema20 = calc_ema(closes, 20)
    ema50 = calc_ema(closes, 50)

    # Scan each candle (start from 60 for enough history)
    for i in range(60, len(candles)):
        c    = candles[i]
        ts   = c['ts']
        ltp  = c['close']

        # Get indicators at this point
        e20 = ema20[i - (len(closes) - len(ema20))] if i >= len(closes)-len(ema20) else 0
        e50 = ema50[i - (len(closes) - len(ema50))] if i >= len(closes)-len(ema50) else 0
        if e20 == 0 or e50 == 0:
            continue

        adx_val = calc_adx(highs[:i+1], lows[:i+1], closes[:i+1], 14)
        rsi_val = calc_rsi(closes[max(0,i-30):i+1], 14)
        vwap_val = vwaps[i]

        # Score
        score = 0
        if opt_type == "CE":
            if e20 > e50 and adx_val > 20: score += 30
            if rsi_val < 40: score += 25
            if ltp > vwap_val: score += 20
        else:
            if e20 < e50 and adx_val > 20: score += 30
            if rsi_val > 60: score += 25
            if ltp < vwap_val: score += 20

        # Volume spike
        vols = [candles[j].get('volume',0) for j in range(max(0,i-20),i)]
        avg_vol = sum(vols)/len(vols) if vols else 0
        curr_vol = c.get('volume', 0)
        if avg_vol > 0 and curr_vol > avg_vol * 1.5:
            score += 25

        if score >= 70:
            signals.append({
                "ts":       ts,
                "symbol":   symbol,
                "opt_type": opt_type,
                "score":    score,
                "entry":    ltp,
                "ema20":    round(e20, 2),
                "ema50":    round(e50, 2),
                "adx":      adx_val,
                "rsi":      rsi_val,
                "vwap":     round(vwap_val, 2),
                "candle_i": i,
            })

    return signals


def simulate_trade(signal, candles, sl_pct=0.15, t1_pct=0.15, t2_pct=0.25, t3_pct=0.40):
    """
    Simulate trade from signal entry
    Uses delta-based option premium simulation
    """
    # Simulate option premium from index price
    # ATM option premium ~ 0.5-1% of spot
    spot   = signal['entry']
    delta  = 0.5  # ATM delta
    # Estimate premium from ATR
    i = signal['candle_i']
    closes = [candles[j]['close'] for j in range(max(0,i-14),i+1)]
    highs  = [candles[j]['high']  for j in range(max(0,i-14),i+1)]
    lows   = [candles[j]['low']   for j in range(max(0,i-14),i+1)]
    # ATR-based premium estimate
    trs = [max(highs[k]-lows[k], abs(highs[k]-closes[k-1]) if k>0 else 0)
           for k in range(len(closes))]
    atr = sum(trs)/len(trs) if trs else spot*0.005
    # Premium = ATR * delta * multiplier
    entry = round(atr * delta * 2, 1)
    entry = max(entry, 50)  # Min ₹50 premium

    sl = entry * (1 - sl_pct)
    t1 = entry * (1 + t1_pct)
    t2 = entry * (1 + t2_pct)
    t3 = entry * (1 + t3_pct)
    i_start = signal['candle_i'] + 1

    result = {
        "entry":    entry,
        "sl":       round(sl, 2),
        "t1":       round(t1, 2),
        "t2":       round(t2, 2),
        "t3":       round(t3, 2),
        "exit":     entry,
        "exit_reason": "TIMEOUT",
        "pnl_pct":  0,
        "pnl":      0,
        "t1_hit":   False,
        "t2_hit":   False,
        "t3_hit":   False,
        "bars_held": 0,
        "ts":       signal['ts'],
    }

    trail_sl = sl
    entry_spot = candles[i_start-1]['close'] if i_start > 0 else signal['entry']

    for i in range(i_start, min(i_start + 20, len(candles))):
        c    = candles[i]
        result['bars_held'] = i - i_start + 1

        # Simulate option premium using spot % change * delta * 2
        spot_now   = c['close']
        spot_chg   = (spot_now - entry_spot) / entry_spot
        opt_type   = signal.get('opt_type','CE')
        # CE gains when spot up, PE gains when spot down
        if opt_type == 'PE':
            spot_chg = -spot_chg
        curr_prem  = entry * (1 + spot_chg * 2)
        curr_prem  = max(curr_prem, entry * 0.1)  # Min 10% of entry

        # Simulated high/low
        sim_high = entry * (1 + (c['high']-entry_spot)/entry_spot * 2)
        sim_low  = entry * (1 + (c['low']-entry_spot)/entry_spot * 2)
        if opt_type == 'PE':
            sim_high = entry * (1 - (c['low']-entry_spot)/entry_spot * 2)
            sim_low  = entry * (1 - (c['high']-entry_spot)/entry_spot * 2)

        # Check T1
        if not result['t1_hit'] and sim_high >= t1:
            result['t1_hit'] = True
            trail_sl = entry

        # Check T2
        if result['t1_hit'] and not result['t2_hit'] and sim_high >= t2:
            result['t2_hit'] = True
            trail_sl = entry * (1 + t1_pct * 0.5)

        # Check T3
        if result['t2_hit'] and not result['t3_hit'] and sim_high >= t3:
            result['t3_hit'] = True
            result['exit']       = round(t3, 2)
            result['exit_reason'] = "T3_HIT"
            break

        # Check SL
        if sim_low <= trail_sl:
            result['exit']       = round(trail_sl, 2)
            result['exit_reason'] = "TRAIL_SL" if result['t1_hit'] else "SL_HIT"
            break

        # Timeout
        if i - i_start >= 19:
            result['exit']       = round(curr_prem, 2)
            result['exit_reason'] = "TIMEOUT"
            break

    pnl_pct = (result['exit'] - entry) / entry * 100
    result['pnl_pct'] = round(pnl_pct, 2)
    result['pnl']     = round(pnl_pct, 2)  # % based
    return result


def run_backtest(symbol="NIFTY", interval="FIVE_MINUTE", days=30, opt_type="CE"):
    """
    Full backtest run
    Returns comprehensive results
    """
    logger.info(f"Backtest: {symbol} {opt_type} {interval} {days}d")

    candles = get_candles_for_backtest(symbol, interval, days=days)
    if len(candles) < 60:
        return {"error": f"Not enough candles: {len(candles)}"}

    # Generate signals
    signals = generate_signals(candles, symbol, opt_type)
    if not signals:
        return {"error": "No signals generated", "candles": len(candles)}

    # Simulate each trade
    trades = []
    last_exit_i = 0
    for sig in signals:
        # Skip if too close to last trade
        if sig['candle_i'] < last_exit_i + 5:
            continue
        trade = simulate_trade(sig, candles)
        trade['signal_score'] = sig['score']
        trade['rsi']   = sig['rsi']
        trade['adx']   = sig['adx']
        trades.append(trade)
        last_exit_i = sig['candle_i'] + trade['bars_held']

    if not trades:
        return {"error": "No trades simulated"}

    # Statistics
    wins  = [t for t in trades if t['pnl'] > 0]
    loss  = [t for t in trades if t['pnl'] <= 0]
    total_pnl = sum(t['pnl'] for t in trades)

    t1_hits = sum(1 for t in trades if t['t1_hit'])
    t2_hits = sum(1 for t in trades if t['t2_hit'])
    t3_hits = sum(1 for t in trades if t['t3_hit'])

    exit_reasons = {}
    for t in trades:
        r = t['exit_reason']
        exit_reasons[r] = exit_reasons.get(r, 0) + 1

    avg_win  = sum(t['pnl'] for t in wins)  / len(wins)  if wins else 0
    avg_loss = sum(t['pnl'] for t in loss) / len(loss) if loss else 0
    rr_ratio = abs(avg_win/avg_loss) if avg_loss != 0 else 0

    # Drawdown
    cum_pnl = 0
    peak    = 0
    max_dd  = 0
    for t in trades:
        cum_pnl += t['pnl']
        if cum_pnl > peak: peak = cum_pnl
        dd = peak - cum_pnl
        if dd > max_dd: max_dd = dd

    # Consecutive wins/losses
    max_consec_win = max_consec_loss = curr_w = curr_l = 0
    for t in trades:
        if t['pnl'] > 0:
            curr_w += 1; curr_l = 0
            max_consec_win = max(max_consec_win, curr_w)
        else:
            curr_l += 1; curr_w = 0
            max_consec_loss = max(max_consec_loss, curr_l)

    return {
        "symbol":       symbol,
        "opt_type":     opt_type,
        "interval":     interval,
        "days":         days,
        "candles":      len(candles),
        "signals":      len(signals),
        "trades":       len(trades),
        "wins":         len(wins),
        "losses":       len(loss),
        "win_rate":     round(len(wins)/len(trades)*100, 1),
        "total_pnl":    round(total_pnl, 2),
        "avg_win":      round(avg_win, 2),
        "avg_loss":     round(avg_loss, 2),
        "rr_ratio":     round(rr_ratio, 2),
        "max_drawdown": round(max_dd, 2),
        "t1_rate":      round(t1_hits/len(trades)*100, 1),
        "t2_rate":      round(t2_hits/len(trades)*100, 1),
        "t3_rate":      round(t3_hits/len(trades)*100, 1),
        "exit_reasons": exit_reasons,
        "max_consec_win":  max_consec_win,
        "max_consec_loss": max_consec_loss,
        "trade_list":   trades[:50],  # First 50 trades
    }
