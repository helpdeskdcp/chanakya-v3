"""
Chanakya AI — Backtest Engine v2
Realistic option premium simulation
"""
import logging
from datetime import datetime
import pytz

logger = logging.getLogger(__name__)
IST = pytz.timezone("Asia/Kolkata")


def get_candles_for_backtest(symbol, interval, days=30):
    from engine.candle_db import get_candles_db
    return get_candles_db(symbol, interval, days=days)


def calc_ema(values, period):
    if len(values) < period:
        return [None]*len(values)
    k = 2.0/(period+1)
    e = sum(values[:period])/period
    result = [None]*(len(values)-len(values[period-1:]))
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
    return round(100-(100/(1+ag/al)), 2) if al>0 else 100.0


def calc_adx(highs, lows, closes, period=14):
    if len(closes) < period+2: return 0.0
    trs,pdms,mdms = [],[],[]
    for i in range(1, len(closes)):
        h,l,pc = highs[i],lows[i],closes[i-1]
        tr  = max(h-l, abs(h-pc), abs(l-pc))
        pdm = max(h-highs[i-1], 0)
        mdm = max(lows[i-1]-l, 0)
        if pdm > mdm: mdm=0
        elif mdm > pdm: pdm=0
        trs.append(tr); pdms.append(pdm); mdms.append(mdm)
    def sm(v,p):
        s=sum(v[:p]); r=[s]
        for x in v[p:]: s=s-s/p+x; r.append(s)
        return r
    atr=sm(trs,period); spdi=sm(pdms,period); smdi=sm(mdms,period)
    dxs=[]
    for i in range(len(atr)):
        if atr[i]==0: continue
        pdi=100*spdi[i]/atr[i]; mdi=100*smdi[i]/atr[i]
        dx=100*abs(pdi-mdi)/(pdi+mdi) if (pdi+mdi)>0 else 0
        dxs.append(dx)
    return round(sum(dxs[-period:])/period,2) if len(dxs)>=period else 0.0


def calc_atr(highs, lows, closes, period=14):
    if len(closes) < 2: return 0
    trs = [max(highs[i]-lows[i], abs(highs[i]-closes[i-1]), abs(lows[i]-closes[i-1]))
           for i in range(1, len(closes))]
    return sum(trs[-period:])/min(period, len(trs)) if trs else 0


def calc_vwap(candles):
    ct=cv=0; result=[]
    for c in candles:
        tp=(c['high']+c['low']+c['close'])/3
        ct+=tp*(c['volume'] or 1); cv+=(c['volume'] or 1)
        result.append(ct/cv)
    return result


def estimate_option_premium(spot, atr, opt_type="CE", trend="UP"):
    """
    Realistic ATM option premium estimate
    Based on ATR and market conditions
    """
    # ATM premium ≈ 0.4-0.8% of spot
    base_pct = 0.006  # 0.6% of spot
    premium  = spot * base_pct

    # Adjust for ATR volatility
    atr_pct = atr / spot
    if atr_pct > 0.01:   # High volatility
        premium *= 1.3
    elif atr_pct < 0.003: # Low volatility
        premium *= 0.7

    # Round to nearest 0.5
    premium = round(premium * 2) / 2
    return max(premium, 30.0)  # Min ₹30


def generate_signals(candles, symbol="NIFTY", opt_type="CE"):
    """Generate trading signals from historical data"""
    signals = []
    if len(candles) < 60: return signals

    closes = [c['close'] for c in candles]
    highs  = [c['high']  for c in candles]
    lows   = [c['low']   for c in candles]
    vwaps  = calc_vwap(candles)
    ema20  = calc_ema(closes, 20)
    ema50  = calc_ema(closes, 50)

    prev_signal_i = -10

    for i in range(60, len(candles)-5):
        # Skip if too close to last signal
        if i - prev_signal_i < 10: continue

        c   = candles[i]
        ltp = c['close']
        e20 = ema20[i]
        e50 = ema50[i]
        if e20 is None or e50 is None: continue

        adx_val  = calc_adx(highs[:i+1], lows[:i+1], closes[:i+1], 14)
        rsi_val  = calc_rsi(closes[max(0,i-30):i+1], 14)
        vwap_val = vwaps[i]
        atr_val  = calc_atr(highs[:i+1], lows[:i+1], closes[:i+1], 14)

        score = 0
        trend = "SIDEWAYS"

        if opt_type == "CE":
            if e20 > e50 and adx_val > 20:
                score += 30; trend = "UP"
            if rsi_val < 40: score += 25
            elif rsi_val < 50: score += 10
            if ltp > vwap_val: score += 20
        else:  # PE
            if e20 < e50 and adx_val > 20:
                score += 30; trend = "DOWN"
            if rsi_val > 60: score += 25
            elif rsi_val > 50: score += 10
            if ltp < vwap_val: score += 20

        # Volume spike
        vols = [candles[j].get('volume',0) for j in range(max(0,i-20),i)]
        avg_vol = sum(vols)/len(vols) if vols else 1
        if avg_vol > 0 and c.get('volume',0) > avg_vol*1.5:
            score += 25

        if score >= 70:
            # Estimate realistic premium
            premium = estimate_option_premium(ltp, atr_val, opt_type, trend)

            signals.append({
                "ts":        c['ts'],
                "symbol":    symbol,
                "opt_type":  opt_type,
                "score":     score,
                "spot":      ltp,
                "premium":   premium,
                "entry":     premium,
                "ema20":     round(e20,2),
                "ema50":     round(e50,2),
                "adx":       adx_val,
                "rsi":       rsi_val,
                "vwap":      round(vwap_val,2),
                "atr":       round(atr_val,2),
                "candle_i":  i,
                "trend":     trend,
            })
            prev_signal_i = i

    return signals


def simulate_trade(signal, candles, sl_pct=0.15, t1_pct=0.15, t2_pct=0.25, t3_pct=0.40):
    """
    Simulate option trade using spot price movement
    """
    entry      = signal['premium']
    spot_entry = signal['spot']
    opt_type   = signal.get('opt_type','CE')
    i_start    = signal['candle_i'] + 1

    sl     = entry * (1 - sl_pct)
    t1     = entry * (1 + t1_pct)
    t2     = entry * (1 + t2_pct)
    t3     = entry * (1 + t3_pct)

    result = {
        "ts":          signal['ts'],
        "entry":       round(entry,1),
        "spot_entry":  round(spot_entry,1),
        "sl":          round(sl,1),
        "t1":          round(t1,1),
        "t2":          round(t2,1),
        "t3":          round(t3,1),
        "exit":        round(entry,1),
        "exit_reason": "TIMEOUT",
        "pnl_pct":     0.0,
        "pnl":         0.0,
        "t1_hit":      False,
        "t2_hit":      False,
        "t3_hit":      False,
        "bars_held":   0,
        "signal_score": signal['score'],
        "rsi":         signal['rsi'],
        "adx":         signal['adx'],
    }

    trail_sl = sl
    max_bars = 20

    for i in range(i_start, min(i_start+max_bars, len(candles))):
        c = candles[i]
        result['bars_held'] = i - i_start + 1

        # Simulate option price from spot movement
        spot_now  = c['close']
        spot_high = c['high']
        spot_low  = c['low']

        # % change from entry
        if opt_type == "CE":
            chg_high = (spot_high - spot_entry) / spot_entry
            chg_low  = (spot_low  - spot_entry) / spot_entry
        else:
            chg_high = (spot_entry - spot_low)  / spot_entry
            chg_low  = (spot_entry - spot_high) / spot_entry

        # Option moves faster than spot (2x delta approximation)
        sim_high = entry * (1 + chg_high * 2.0)
        sim_low  = entry * (1 + chg_low  * 2.0)
        sim_high = max(sim_high, entry * 0.05)
        sim_low  = max(sim_low,  entry * 0.05)

        # T3 check
        if result['t2_hit'] and sim_high >= t3:
            result['t3_hit']     = True
            result['exit']       = round(t3, 1)
            result['exit_reason']= "T3_HIT"
            break

        # T2 check
        if result['t1_hit'] and sim_high >= t2:
            result['t2_hit'] = True
            trail_sl = entry * (1 + t1_pct*0.5)

        # T1 check
        if not result['t1_hit'] and sim_high >= t1:
            result['t1_hit'] = True
            trail_sl = entry  # Move to cost

        # SL check
        if sim_low <= trail_sl:
            result['exit']       = round(trail_sl, 1)
            result['exit_reason']= "TRAIL_SL" if result['t1_hit'] else "SL_HIT"
            break

        # Final bar timeout
        if i == min(i_start+max_bars, len(candles))-1:
            spot_now_chg = (spot_now-spot_entry)/spot_entry if opt_type=="CE" else (spot_entry-spot_now)/spot_entry
            curr_prem    = max(entry*(1+spot_now_chg*2), entry*0.1)
            result['exit']       = round(curr_prem, 1)
            result['exit_reason']= "TIMEOUT"

    pnl_pct = (result['exit'] - entry) / entry * 100
    result['pnl_pct'] = round(pnl_pct, 2)
    result['pnl']     = round(pnl_pct, 2)
    return result


def run_backtest(symbol="NIFTY", interval="FIVE_MINUTE", days=30, opt_type="CE"):
    """Full backtest with statistics"""
    candles = get_candles_for_backtest(symbol, interval, days=days)
    if len(candles) < 60:
        return {"error": f"Not enough candles: {len(candles)}"}

    signals = generate_signals(candles, symbol, opt_type)
    if not signals:
        return {"error": "No signals generated", "candles": len(candles)}

    trades = []; last_exit_i = 0
    for sig in signals:
        if sig['candle_i'] < last_exit_i+5: continue
        t = simulate_trade(sig, candles)
        trades.append(t)
        last_exit_i = sig['candle_i'] + t['bars_held']

    if not trades:
        return {"error": "No trades simulated"}

    wins  = [t for t in trades if t['pnl'] > 0]
    loss  = [t for t in trades if t['pnl'] <= 0]
    total = sum(t['pnl'] for t in trades)

    t1_hits = sum(1 for t in trades if t['t1_hit'])
    t2_hits = sum(1 for t in trades if t['t2_hit'])
    t3_hits = sum(1 for t in trades if t['t3_hit'])

    exit_reasons = {}
    for t in trades:
        r = t['exit_reason']
        exit_reasons[r] = exit_reasons.get(r,0)+1

    avg_win  = sum(t['pnl'] for t in wins)/len(wins)   if wins else 0
    avg_loss = sum(t['pnl'] for t in loss)/len(loss) if loss else 0
    rr       = abs(avg_win/avg_loss) if avg_loss<0 else 0

    # Drawdown
    cum=pk=dd_max=0
    for t in trades:
        cum+=t['pnl']
        if cum>pk: pk=cum
        dd=pk-cum
        if dd>dd_max: dd_max=dd

    # Consecutive
    mw=ml=cw=cl=0
    for t in trades:
        if t['pnl']>0: cw+=1;cl=0;mw=max(mw,cw)
        else: cl+=1;cw=0;ml=max(ml,cl)

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
        "win_rate":     round(len(wins)/len(trades)*100,1) if trades else 0,
        "total_pnl":    round(total,2),
        "avg_win":      round(avg_win,2),
        "avg_loss":     round(avg_loss,2),
        "rr_ratio":     round(rr,2),
        "max_drawdown": round(dd_max,2),
        "t1_rate":      round(t1_hits/len(trades)*100,1),
        "t2_rate":      round(t2_hits/len(trades)*100,1),
        "t3_rate":      round(t3_hits/len(trades)*100,1),
        "exit_reasons": exit_reasons,
        "max_consec_win":  mw,
        "max_consec_loss": ml,
        "trade_list":   trades,
    }
