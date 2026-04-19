"""
Chanakya v3 — Backtest Engine
Type 1: DB Trade Analysis
Type 2: Signal Replay on Historical Data
"""
import logging, sqlite3
from datetime import datetime, timedelta
import pytz
from config import config

logger = logging.getLogger(__name__)
IST = pytz.timezone("Asia/Kolkata")


# ══════════════════════════════════════════════════════
# TYPE 1: DB Trade Analysis (Instant — no API needed)
# ══════════════════════════════════════════════════════
class DBAnalyzer:
    """Analyze existing trades from DB"""

    def __init__(self):
        self.conn = sqlite3.connect(config.DB_PATH)
        self.conn.row_factory = sqlite3.Row

    def run(self, days=90, symbol=None, strategy=None):
        """Full analysis of past trades"""
        # Build query
        where = ["status='CLOSED'", "pnl IS NOT NULL"]
        params = []
        if days:
            where.append("created_at >= date('now', ?, 'localtime')")
            params.append(f"-{days} days")
        if symbol:
            where.append("symbol=?"); params.append(symbol)
        if strategy:
            where.append("strategy LIKE ?"); params.append(f"%{strategy}%")

        trades = self.conn.execute(
            f"SELECT * FROM trades WHERE {' AND '.join(where)} ORDER BY created_at",
            params
        ).fetchall()

        if not trades:
            return {"error": "No trades found for given filters"}

        trades = [dict(t) for t in trades]
        return {
            "summary":       self._summary(trades),
            "by_symbol":     self._by_field(trades, "symbol"),
            "by_strategy":   self._by_field(trades, "strategy"),
            "by_opt_type":   self._by_field(trades, "opt_type"),
            "by_hour":       self._by_hour(trades),
            "by_day":        self._by_weekday(trades),
            "daily_pnl":     self._daily_pnl(trades),
            "equity_curve":  self._equity_curve(trades),
            "drawdown":      self._drawdown(trades),
            "streaks":       self._streaks(trades),
            "best_trades":   self._best_worst(trades, best=True),
            "worst_trades":  self._best_worst(trades, best=False),
        }

    def _summary(self, trades):
        pnls    = [t["pnl"] for t in trades]
        wins    = [p for p in pnls if p > 0]
        losses  = [p for p in pnls if p < 0]
        total   = len(pnls)
        win_n   = len(wins)

        avg_win  = sum(wins)/len(wins)   if wins   else 0
        avg_loss = sum(losses)/len(losses) if losses else 0
        pf = abs(avg_win / avg_loss) if avg_loss else 0

        # Sharpe (daily returns)
        daily = {}
        for t in trades:
            d = t["created_at"][:10]
            daily[d] = daily.get(d, 0) + t["pnl"]
        rets = list(daily.values())
        import statistics
        sharpe = 0
        if len(rets) > 1:
            avg_r = statistics.mean(rets)
            std_r = statistics.stdev(rets)
            sharpe = round(avg_r / std_r * (252**0.5), 2) if std_r > 0 else 0

        return {
            "total_trades":  total,
            "wins":          win_n,
            "losses":        total - win_n,
            "win_rate":      round(win_n / total * 100, 1) if total else 0,
            "total_pnl":     round(sum(pnls), 2),
            "avg_win":       round(avg_win, 2),
            "avg_loss":      round(avg_loss, 2),
            "best_trade":    round(max(pnls), 2),
            "worst_trade":   round(min(pnls), 2),
            "profit_factor": round(pf, 2),
            "sharpe_ratio":  sharpe,
            "expectancy":    round(
                (win_n/total * avg_win) + ((total-win_n)/total * avg_loss), 2
            ) if total else 0,
        }

    def _by_field(self, trades, field):
        groups = {}
        for t in trades:
            k = t.get(field) or "Unknown"
            if k not in groups: groups[k] = []
            groups[k].append(t["pnl"])
        result = []
        for k, pnls in sorted(groups.items()):
            wins = len([p for p in pnls if p > 0])
            result.append({
                "name":      k,
                "trades":    len(pnls),
                "wins":      wins,
                "win_rate":  round(wins/len(pnls)*100, 1),
                "total_pnl": round(sum(pnls), 2),
                "avg_pnl":   round(sum(pnls)/len(pnls), 2),
            })
        return sorted(result, key=lambda x: x["total_pnl"], reverse=True)

    def _by_hour(self, trades):
        hours = {}
        for t in trades:
            try:
                h = int(t["created_at"][11:13])
                if h not in hours: hours[h] = []
                hours[h].append(t["pnl"])
            except Exception:
                pass
        result = []
        for h in sorted(hours):
            pnls = hours[h]
            wins = len([p for p in pnls if p > 0])
            result.append({
                "hour":      f"{h:02d}:00",
                "trades":    len(pnls),
                "wins":      wins,
                "win_rate":  round(wins/len(pnls)*100, 1),
                "total_pnl": round(sum(pnls), 2),
            })
        return result

    def _by_weekday(self, trades):
        days = {0:"Mon",1:"Tue",2:"Wed",3:"Thu",4:"Fri"}
        groups = {d: [] for d in days.values()}
        for t in trades:
            try:
                dt = datetime.strptime(t["created_at"][:10], "%Y-%m-%d")
                d  = days.get(dt.weekday(), "Other")
                groups[d].append(t["pnl"])
            except Exception:
                pass
        result = []
        for d in ["Mon","Tue","Wed","Thu","Fri"]:
            pnls = groups[d]
            if not pnls: continue
            wins = len([p for p in pnls if p > 0])
            result.append({
                "day":       d,
                "trades":    len(pnls),
                "wins":      wins,
                "win_rate":  round(wins/len(pnls)*100, 1),
                "total_pnl": round(sum(pnls), 2),
            })
        return result

    def _daily_pnl(self, trades):
        daily = {}
        for t in trades:
            d = t["created_at"][:10]
            if d not in daily: daily[d] = {"pnl":0,"trades":0,"wins":0}
            daily[d]["pnl"]    += t["pnl"]
            daily[d]["trades"] += 1
            if t["pnl"] > 0: daily[d]["wins"] += 1
        return [{"date": d, **v, "pnl": round(v["pnl"], 2)}
                for d, v in sorted(daily.items())]

    def _equity_curve(self, trades):
        curve, running = [], 0
        for t in sorted(trades, key=lambda x: x["created_at"]):
            running += t["pnl"]
            curve.append({
                "date":     t["created_at"][:10],
                "pnl":      round(t["pnl"], 2),
                "cumulative": round(running, 2),
            })
        return curve

    def _drawdown(self, trades):
        curve   = self._equity_curve(trades)
        peak    = 0
        max_dd  = 0
        dd_list = []
        for c in curve:
            peak = max(peak, c["cumulative"])
            dd   = c["cumulative"] - peak
            max_dd = min(max_dd, dd)
            dd_list.append({"date": c["date"], "drawdown": round(dd, 2)})
        return {"max_drawdown": round(max_dd, 2), "curve": dd_list}

    def _streaks(self, trades):
        sorted_t = sorted(trades, key=lambda x: x["created_at"])
        cur_w = cur_l = max_w = max_l = 0
        for t in sorted_t:
            if t["pnl"] > 0:
                cur_w += 1; cur_l = 0
                max_w = max(max_w, cur_w)
            else:
                cur_l += 1; cur_w = 0
                max_l = max(max_l, cur_l)
        return {
            "max_win_streak":  max_w,
            "max_loss_streak": max_l,
            "current_win":     cur_w,
            "current_loss":    cur_l,
        }

    def _best_worst(self, trades, best=True):
        sorted_t = sorted(trades, key=lambda x: x["pnl"], reverse=best)
        return [{
            "id":       t["id"],
            "symbol":   t["symbol"],
            "opt_type": t["opt_type"],
            "pnl":      round(t["pnl"], 2),
            "strategy": t["strategy"],
            "date":     t["created_at"][:10],
        } for t in sorted_t[:5]]


# ══════════════════════════════════════════════════════
# TYPE 2: Signal Replay on Historical Candles
# ══════════════════════════════════════════════════════
class SignalReplay:
    """Replay signals on historical candle data"""

    def __init__(self, broker):
        self.broker = broker

    def run(self, symbol="NIFTY", opt_type="CE",
            days_back=30, timeframe="FIVE_MINUTE"):
        """
        Fetch historical candles + replay signal engine
        Returns simulated trade results
        """
        logger.info(f"🔄 Backtest: {symbol} {opt_type} | {days_back} days | {timeframe}")

        # Step 1: Get option chain for token
        from engine.chain import get_chain
        chain = get_chain(self.broker, symbol)
        if not chain:
            return {"error": "No chain data"}

        atm      = chain["atm"]
        expiry   = chain["expiry"]
        spot     = chain["spot"]

        # Find ATM option token
        selected = next((r for r in chain["chain"] if r["strike"]==atm), None)
        if not selected:
            return {"error": "ATM strike not found"}

        opt_data = selected.get(opt_type.lower(), {})
        token    = opt_data.get("token", "")
        if not token:
            return {"error": "Token not found"}

        # Step 2: Fetch historical candles
        from engine.candles import get_candles
        exch    = "MCX" if symbol in ("CRUDEOIL","NATURALGAS") else "NFO"
        candles = get_candles(
            self.broker, token, exch,
            interval=timeframe, days=days_back
        )
        if len(candles) < 60:
            return {"error": f"Insufficient candles: {len(candles)}"}

        logger.info(f"📊 Got {len(candles)} candles for replay")

        # Step 3: Replay signal engine on each bar
        from engine.signals import signal_engine, atr as calc_atr
        from engine.risk import check_vix, check_rr

        trades       = []
        in_trade     = False
        trade_entry  = 0
        trade_sl     = 0
        trade_target = 0
        trade_start  = 0

        window = 60  # Minimum candles for signal

        for i in range(window, len(candles)):
            bar     = candles[i]
            ts      = bar[0]
            close   = bar[4]
            hist    = candles[max(0, i-window):i]

            if in_trade:
                # Check SL / Target
                if close <= trade_sl:
                    pnl = trade_sl - trade_entry
                    trades.append({
                        "entry":  trade_entry,
                        "exit":   trade_sl,
                        "pnl":    round(pnl, 2),
                        "result": "SL_HIT",
                        "bars":   i - trade_start,
                        "ts":     ts,
                    })
                    in_trade = False
                elif close >= trade_target:
                    pnl = trade_target - trade_entry
                    trades.append({
                        "entry":  trade_entry,
                        "exit":   trade_target,
                        "pnl":    round(pnl, 2),
                        "result": "TARGET_HIT",
                        "bars":   i - trade_start,
                        "ts":     ts,
                    })
                    in_trade = False
                continue

            # Generate signal
            sig = signal_engine.analyze(
                hist, symbol, opt_type,
                spot=spot, vix=18, pcr=1.0
            )
            if sig.get("score", 0) < 65:
                continue

            # ATR levels
            atr_val = calc_atr(hist)
            if atr_val <= 0:
                continue

            entry  = close
            sl     = round(entry - atr_val * 0.8, 2)
            target = round(entry + atr_val * 1.2, 2)
            rr     = (target - entry) / (entry - sl) if (entry - sl) > 0 else 0

            if rr < 1.5:
                continue

            # Enter trade
            in_trade    = True
            trade_entry = entry
            trade_sl    = sl
            trade_target = target
            trade_start = i

        # Force close any open trade at last bar
        if in_trade:
            last_close = candles[-1][4]
            pnl = last_close - trade_entry
            trades.append({
                "entry":  trade_entry,
                "exit":   last_close,
                "pnl":    round(pnl, 2),
                "result": "FORCE_CLOSED",
                "bars":   len(candles) - trade_start,
                "ts":     candles[-1][0],
            })

        return self._summarize(trades, symbol, opt_type, days_back)

    def _summarize(self, trades, symbol, opt_type, days):
        if not trades:
            return {"error": "No trades generated"}

        pnls  = [t["pnl"] for t in trades]
        wins  = [p for p in pnls if p > 0]
        total = len(pnls)
        win_n = len(wins)

        avg_w = sum(wins)/len(wins)       if wins else 0
        avg_l = sum(p for p in pnls if p < 0) / max(1, total-win_n)
        pf    = abs(avg_w/avg_l)          if avg_l else 0

        # Equity curve
        equity = []
        running = 0
        for t in trades:
            running += t["pnl"]
            equity.append(running)

        # Max drawdown
        peak   = 0
        max_dd = 0
        for e in equity:
            peak   = max(peak, e)
            max_dd = min(max_dd, e - peak)

        return {
            "symbol":        symbol,
            "opt_type":      opt_type,
            "days_tested":   days,
            "total_candles": len(trades),
            "summary": {
                "total_trades":  total,
                "wins":          win_n,
                "losses":        total - win_n,
                "win_rate":      round(win_n/total*100, 1) if total else 0,
                "total_pnl":     round(sum(pnls), 2),
                "avg_win":       round(avg_w, 2),
                "avg_loss":      round(avg_l, 2),
                "profit_factor": round(pf, 2),
                "max_drawdown":  round(max_dd, 2),
                "best_trade":    round(max(pnls), 2),
                "worst_trade":   round(min(pnls), 2),
            },
            "trades":        trades,
            "equity_curve":  equity,
        }

def strategy_performance_summary(db_path="data/chanakya_v3.db"):
    """Per-strategy win rate, avg P&L"""
    import sqlite3
    from collections import defaultdict
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    trades = conn.execute("""
        SELECT strategy, pnl FROM trades
        WHERE status='CLOSED' AND ABS(pnl)<50000
    """).fetchall()
    conn.close()
    stats = defaultdict(lambda: {"wins":0,"losses":0,"pnl":0})
    for t in trades:
        s = t["strategy"] or "UNKNOWN"
        p = t["pnl"] or 0
        stats[s]["pnl"] += p
        if p>0: stats[s]["wins"] += 1
        else:   stats[s]["losses"] += 1
    result = []
    for name, d in stats.items():
        total = d["wins"]+d["losses"]
        if total < 2: continue
        result.append({
            "strategy": name, "trades": total,
            "wins": d["wins"],
            "win_rate": round(d["wins"]/total*100,1),
            "total_pnl": round(d["pnl"],2),
            "avg_pnl": round(d["pnl"]/total,2),
        })
    return sorted(result, key=lambda x: x["win_rate"], reverse=True)
