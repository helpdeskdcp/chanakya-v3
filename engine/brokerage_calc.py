"""Angel One Brokerage Calculator"""

def calc_equity_intraday(buy_price, sell_price, qty):
    turnover   = (buy_price + sell_price) * qty
    brokerage  = min(0.0003 * turnover, 40)
    stt        = 0.00025 * sell_price * qty
    exch_txn   = 0.0000345 * turnover
    sebi       = 0.000001 * turnover
    stamp      = 0.00003 * buy_price * qty
    gst        = 0.18 * (brokerage + exch_txn + sebi)
    total      = brokerage + stt + exch_txn + sebi + stamp + gst
    gross_pnl  = (sell_price - buy_price) * qty
    net_pnl    = gross_pnl - total
    breakeven  = buy_price + (total / qty)
    return {"gross_pnl":round(gross_pnl,2),"net_pnl":round(net_pnl,2),
            "total_charges":round(total,2),"brokerage":round(brokerage,2),
            "stt":round(stt,2),"gst":round(gst,2),
            "breakeven":round(breakeven,2),"breakeven_pct":round((breakeven-buy_price)/buy_price*100,4)}

def calc_equity_delivery(buy_price, sell_price, qty):
    turnover   = (buy_price + sell_price) * qty
    brokerage  = 0
    stt        = 0.001 * buy_price * qty + 0.001 * sell_price * qty
    exch_txn   = 0.0000345 * turnover
    sebi       = 0.000001 * turnover
    stamp      = 0.00015 * buy_price * qty
    gst        = 0.18 * (brokerage + exch_txn + sebi)
    total      = brokerage + stt + exch_txn + sebi + stamp + gst
    gross_pnl  = (sell_price - buy_price) * qty
    net_pnl    = gross_pnl - total
    breakeven  = buy_price + (total / qty)
    return {"gross_pnl":round(gross_pnl,2),"net_pnl":round(net_pnl,2),
            "total_charges":round(total,2),"brokerage":round(brokerage,2),
            "stt":round(stt,2),"gst":round(gst,2),
            "breakeven":round(breakeven,2),"breakeven_pct":round((breakeven-buy_price)/buy_price*100,4)}

def calc_options(buy_price, sell_price, qty):
    turnover   = (buy_price + sell_price) * qty
    brokerage  = min(20, 0.0003*buy_price*qty) + min(20, 0.0003*sell_price*qty)
    stt        = 0.000625 * sell_price * qty
    exch_txn   = 0.000053 * turnover
    sebi       = 0.000001 * turnover
    stamp      = 0.00003 * buy_price * qty
    gst        = 0.18 * (brokerage + exch_txn + sebi)
    total      = brokerage + stt + exch_txn + sebi + stamp + gst
    gross_pnl  = (sell_price - buy_price) * qty
    net_pnl    = gross_pnl - total
    breakeven  = buy_price + (total / qty)
    return {"gross_pnl":round(gross_pnl,2),"net_pnl":round(net_pnl,2),
            "total_charges":round(total,2),"brokerage":round(brokerage,2),
            "stt":round(stt,2),"breakeven":round(breakeven,2),
            "breakeven_pct":round((breakeven-buy_price)/buy_price*100,4)}

def position_size_equity(capital, risk_pct, entry, sl):
    risk_amt = capital * (risk_pct / 100)
    risk_per = entry - sl
    if risk_per <= 0: return 1
    qty = int(risk_amt / risk_per)
    max_qty = int(capital * 0.20 / entry)
    return max(1, min(qty, max_qty))
