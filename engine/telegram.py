"""
Chanakya AI — Telegram Alerts
Admin: private alerts (health, errors, trades)
Channel: public signals only (score 70%+)
"""
import os, requests, logging
logger = logging.getLogger(__name__)

class TelegramAlert:
    def __init__(self):
        self.token      = os.getenv("TELEGRAM_BOT_TOKEN","")
        self.chat_id    = os.getenv("TELEGRAM_CHAT_ID","")     # Admin private
        self.channel_id = os.getenv("TELEGRAM_CHANNEL_ID","") # Public channel
        self.enabled    = bool(self.token and self.chat_id)
        if self.enabled:
            logger.info("✅ Telegram alerts enabled")

    def send(self, message, chat_id=None):
        """Send to specific chat"""
        if not self.token: return False
        target = chat_id or self.chat_id
        if not target: return False
        try:
            r = requests.post(
                f"https://api.telegram.org/bot{self.token}/sendMessage",
                json={"chat_id": target, "text": message,
                      "parse_mode": "HTML"},
                timeout=10
            )
            return r.json().get("ok", False)
        except Exception as e:
            logger.debug(f"Telegram: {e}")
            return False

    def admin_alert(self, message):
        """Admin only — system health, errors, trades"""
        return self.send(message, self.chat_id)

    def signal_alert(self, signal):
        """Public channel — signals only"""
        if not self.channel_id: return False
        try:
            sym    = signal.get("symbol","")
            opt    = signal.get("opt_type","")
            osym   = signal.get("option_symbol","")
            entry  = signal.get("entry",0)
            target = signal.get("target",0)
            sl     = signal.get("sl",0)
            rr     = signal.get("rr",0)
            score  = signal.get("score_pct") or round(signal.get("score",0)*100,1)
            regime = signal.get("regime","")
            reason = signal.get("reason","")
            conf   = signal.get("confluence","")

            clr = "🟢" if opt == "CE" else "🔴"

            msg = (
                f"⚡ <b>CHANAKYA AI SIGNAL</b>\n"
                f"{'━'*20}\n"
                f"{clr} <b>{sym} {opt}</b> | {regime}\n"
                f"📋 <code>{osym}</code>\n"
                f"{'━'*20}\n"
                f"💰 Entry:  <b>₹{entry}</b>\n"
                f"✅ Target: <b>₹{target}</b>\n"
                f"🛑 SL:     <b>₹{sl}</b>\n"
                f"📊 R:R:    <b>{rr}</b>\n"
                f"{'━'*20}\n"
                f"🎯 Score: <b>{score}%</b> | {conf}\n"
                f"💡 {reason}\n"
                f"{'━'*20}\n"
                f"⚠️ <i>Educational only. Not financial advice.</i>"
            )
            result = self.send_get_id(msg, self.channel_id)
            return result
        except Exception as e:
            logger.debug(f"Signal alert: {e}")
            return None

    def send_get_id(self, message, chat_id):
        """Send and return message_id"""
        if not self.token or not chat_id: return None
        try:
            r = requests.post(
                f"https://api.telegram.org/bot{self.token}/sendMessage",
                json={"chat_id":chat_id,"text":message,"parse_mode":"HTML"},
                timeout=10
            )
            data = r.json()
            if data.get("ok"):
                return data["result"]["message_id"]
        except Exception as e:
            logger.debug(f"Send: {e}")
        return None

    def system_alert(self, message, level="INFO"):
        """System health — admin only"""
        icons = {"INFO":"ℹ️","SUCCESS":"✅","WARNING":"⚠️","ERROR":"❌"}
        icon  = icons.get(level, "📢")
        return self.admin_alert(f"{icon} <b>Chanakya System</b>\n{message}")

    def trade_alert(self, trade, action="PLACED"):
        """Trade notification — admin only"""
        icons = {"PLACED":"📈","CLOSED":"💰","SL_HIT":"🛑","TARGET":"🎯"}
        icon  = icons.get(action,"📢")
        msg   = (
            f"{icon} <b>Trade {action}</b>\n"
            f"Symbol: {trade.get('symbol','')}\n"
            f"Mode:   {trade.get('mode','PAPER')}\n"
            f"Entry:  ₹{trade.get('entry_price',0)}\n"
            f"P&L:    ₹{trade.get('pnl',0)}"
        )
        return self.admin_alert(msg)

telegram = TelegramAlert()
