
RESISTANCE = 2.45
SUPPORT = 2.20

def check_breakout(df):

    last = df.iloc[-1]

    cond1 = last.close > RESISTANCE
    cond2 = last.ema9 > last.ema21
    cond3 = last.rsi > 55
    cond4 = last.volume > last.vol_avg

    if cond1 and cond2 and cond3 and cond4:

        return {
            "signal": "BUY",
            "sl": SUPPORT,
            "target": last.close + 0.40
        }

    return {"signal": "WAIT"}

