"""
Angel One Brokerage Calculator — Equity + F&O
Calculates exact profit after all charges
"""

def calc_equity_intraday(buy_price, sell_price, qty):
    """NSE Equity Intraday brokerage calculation"""
    turnover = (buy_price + sell_price) * qty

    brokerage  = min(0.0003 * turnover, 40)  # 0.03% or Rs20 per order max
    stt        = 0.00025 * sell_price * qty   # 0.025% on sell side
    exch_txn   = 0.0000345 * turnover        # NSE exchange fee
    sebi       = 0.000001 * turnover         # SEBI charges
    stamp      = 0.00003 * buy_price * qty   # Stamp duty on buy
    gst        = 0.18 * (brokerage + exch_txn + sebi)

    total_charges = brokerage + stt + exch_txn + sebi + stamp + gst
    gross_pnl     = (sell_price - buy_price) * qty
    net_pnl       = gross_pnl - total_charges
    breakeven     = buy_price + (total_charges / qty)

    return {
        "gross_pnl":      round(gross_pnl, 2),
        "net_pnl":        round(net_pnl, 2),
        "total_charges":  round(total_charges, 2),
        "brokerage":      round(brokerage, 2),
        "stt":            round(stt, 2),
        "gst":            round(gst, 2),
        "breakeven":      round(breakeven, 2),
        "breakeven_pct":  round((breakeven - buy_price) / buy_price * 100, 4),
    }


def calc_equity_delivery(buy_price, sell_price, qty):
    """NSE Equity Delivery brokerage calculation"""
    turnover = (buy_price + sell_price) * qty

    brokerage  = 0  # Zero brokerage on delivery (Angel One)
    stt        = 0.001 * buy_price * qty + 0.001 * sell_price * qty  # 0.1% both sides
    exch_txn   = 0.0000345 * turnover
    sebi       = 0.000001 * turnover
    stamp      = 0.00015 * buy_price * qty
    gst        = 0.18 * (brokerage + exch_txn + sebi)

    total_charges = brokerage + stt + exch_txn + sebi + stamp + gst
    gross_pnl     = (sell_price - buy_price) * qty
    net_pnl       = gross_pnl - total_charges
    breakeven     = buy_price + (total_charges / qty)

    return {
        "gross_pnl":      round(gross_pnl, 2),
        "net_pnl":        round(net_pnl, 2),
        "total_charges":  round(total_charges, 2),
        "brokerage":      round(brokerage, 2),
        "stt":            round(stt, 2),
        "gst":            round(gst, 2),
        "breakeven":      round(breakeven, 2),
        "breakeven_pct":  round((breakeven - buy_price) / buy_price * 100, 4),
    }


def calc_options(buy_price, sell_price, qty, opt_type="CE"):
    """F&O Options brokerage calculation"""
    turnover = (buy_price + sell_price) * qty

    brokerage  = min(20, 0.0003 * buy_price * qty) + min(20, 0.0003 * sell_price * qty)
    stt        = 0.000625 * sell_price * qty  # 0.0625% on sell
    exch_txn   = 0.000053 * turnover          # NFO exchange
    sebi       = 0.000001 * turnover
    stamp      = 0.00003 * buy_price * qty
    gst        = 0.18 * (brokerage + exch_txn + sebi)

    total_charges = brokerage + stt + exch_txn + sebi + stamp + gst
    gross_pnl     = (sell_price - buy_price) * qty
    net_pnl       = gross_pnl - total_charges
    breakeven     = buy_price + (total_charges / qty)

    return {
        "gross_pnl":      round(gross_pnl, 2),
        "net_pnl":        round(net_pnl, 2),
        "total_charges":  round(total_charges, 2),
        "brokerage":      round(brokerage, 2),
        "stt":            round(stt, 2),
        "breakeven":      round(breakeven, 2),
        "breakeven_pct":  round((breakeven - buy_price) / buy_price * 100, 4),
    }


def position_size_equity(capital, risk_pct, entry, sl, max_qty=None):
    """
    Capital-aware position sizing for equity
    Risk: % of capital to risk per trade
    """
    risk_amt  = capital * (risk_pct / 100)
    risk_per_share = entry - sl
    if risk_per_share <= 0:
        return 0
    qty = int(risk_amt / risk_per_share)
    # Max 20% capital in one trade
    max_by_capital = int(capital * 0.20 / entry)
    qty = min(qty, max_by_capital)
    if max_qty:
        qty = min(qty, max_qty)
    return max(1, qty)
