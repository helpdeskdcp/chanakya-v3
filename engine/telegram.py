"""
Chanakya v3 — Telegram Alert Engine
Trade alerts, signals, daily summary
"""
import logging, requests, os
from datetime import datetime
import pytz

logger = logging.getLogger(__name__)
IST = pytz.timezone("Asia/Kolkata")

class TelegramAlert:
    def __init__(self):
        self.token   = os.getenv("TELEGRAM_BOT_TOKEN", "")
        self.chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
        self.enabled = bool(self.token and self.chat_id)
        if self.enabled:
            logger.info("✅ Telegram alerts enabled")
        else:
            logger.info("📴 Telegram not configured")

    def send(self, message, parse_mode="HTML"):
        if not self.enabled:
            logger.debug(f"Telegram (disabled): {message[:50]}")
            return False
        try:
            r = requests.post(
                f"https://api.telegram.org/bot{self.token}/sendMessage",
                json={
                    "chat_id":    self.chat_id,
                    "text":       message,
                    "parse_mode": parse_mode,
                },
                timeout=5
            )
            return r.status_code == 200
        except Exception as e:
            logger.debug(f"Telegram error: {e}")
            return False

    # ── Trade Alerts ──────────────────────────────────
    def trade_entry(self, trade):
        """Alert on new trade entry"""
        now = datetime.now(IST).strftime("%H:%M")
        sym = trade.get("symbol", "")
        opt = trade.get("opt_type", "")
        stk = trade.get("strike", "")
        ent = trade.get("entry_price", 0)
        sl  = trade.get("sl_price", 0)
        tgt = trade.get("target_price", 0)
        rr  = trade.get("rr", 0)
        ml  = trade.get("ml_confidence", 0)
        lots = trade.get("lots", 1)
        mode = trade.get("mode", "PAPER")

        icon = "📝" if mode == "PAPER" else "🔴"
        msg = (
            f"{icon} <b>NEW TRADE — {mode}</b>\n"
            f"━━━━━━━━━━━━━━━\n"
            f"📌 <b>{sym} {stk} {opt}</b>\n"
            f"💰 Entry: <b>₹{ent}</b> | Lots: {lots}\n"
            f"🎯 Target: ₹{tgt} (+{round((tgt-ent)/ent*100,1)}%)\n"
            f"🛑 SL: ₹{sl} (-{round((ent-sl)/ent*100,1)}%)\n"
            f"⚡ R:R: {rr}:1\n"
            f"🤖 ML Confidence: {ml}%\n"
            f"🕐 Time: {now}"
        )
        return self.send(msg)

    def trade_exit(self, trade, pnl, reason):
        """Alert on trade exit"""
        now  = datetime.now(IST).strftime("%H:%M")
        sym  = trade.get("symbol", "")
        opt  = trade.get("opt_type", "")
        stk  = trade.get("strike", "")
        ent  = trade.get("entry_price", 0)
        exit_p = trade.get("exit_price", 0)
        mode = trade.get("mode", "PAPER")

        icon   = "✅" if pnl > 0 else "❌"
        result = "WIN" if pnl > 0 else "LOSS"
        pct    = round((exit_p - ent) / ent * 100, 1) if ent > 0 else 0

        msg = (
            f"{icon} <b>TRADE CLOSED — {result}</b>\n"
            f"━━━━━━━━━━━━━━━\n"
            f"📌 <b>{sym} {stk} {opt}</b>\n"
            f"💰 Entry: ₹{ent} → Exit: ₹{exit_p}\n"
            f"{'🟢' if pnl>0 else '🔴'} P&L: <b>₹{pnl:.0f}</b> ({pct:+.1f}%)\n"
            f"📋 Reason: {reason}\n"
            f"🕐 Time: {now}"
        )
        return self.send(msg)

    def signal_alert(self, signal):
        """Alert on new signal"""
        sym  = signal.get("symbol", "")
        opt  = signal.get("opt_type", "")
        stk  = signal.get("strike", "")
        ent  = signal.get("entry_price", 0)
        sl   = signal.get("sl_price", 0)
        tgt  = signal.get("target_price", 0)
        rr   = signal.get("rr", 0)
        ml   = signal.get("ml_confidence", 0)
        score = signal.get("signal_score", 0)
        rec  = "🟢 BUY CE" if opt=="CE" else "🔴 BUY PE"

        msg = (
            f"⚡ <b>AI SIGNAL</b>\n"
            f"━━━━━━━━━━━━━━━\n"
            f"🎯 {rec} — <b>{sym} {stk}</b>\n"
            f"💰 Entry: ₹{ent}\n"
            f"🎯 Target: ₹{tgt} | SL: ₹{sl}\n"
            f"⚡ R:R: {rr}:1\n"
            f"🤖 ML: {ml}% | Score: {score}%"
        )
        return self.send(msg)

    def daily_summary(self, stats):
        """Daily P&L summary"""
        date  = datetime.now(IST).strftime("%d %b %Y")
        pnl   = stats.get("pnl", 0)
        total = stats.get("total", 0)
        wins  = stats.get("wins", 0)
        wr    = round(wins/total*100, 1) if total > 0 else 0
        icon  = "🟢" if pnl >= 0 else "🔴"

        msg = (
            f"📊 <b>DAILY SUMMARY — {date}</b>\n"
            f"━━━━━━━━━━━━━━━\n"
            f"{icon} P&L: <b>₹{pnl:,.0f}</b>\n"
            f"📈 Trades: {total} | Wins: {wins} | WR: {wr}%\n"
            f"🤖 Chanakya AI v3.0"
        )
        return self.send(msg)

    def system_alert(self, message, level="INFO"):
        """System alerts (errors, reconnects, etc.)"""
        icons = {"INFO": "ℹ️", "WARNING": "⚠️", "ERROR": "🚨", "SUCCESS": "✅"}
        icon  = icons.get(level, "ℹ️")
        now   = datetime.now(IST).strftime("%H:%M:%S")
        msg   = f"{icon} <b>SYSTEM [{level}]</b>\n{message}\n🕐 {now}"
        return self.send(msg)

telegram = TelegramAlert()
