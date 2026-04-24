"""
Chanakya AI — Signal Tracker
Live tracking: T1/T2/T3 achieved + SL hit messages
Reply to original signal message
"""
import os, requests, logging, threading, time, json
from datetime import datetime
import pytz

logger = logging.getLogger(__name__)
IST = pytz.timezone("Asia/Kolkata")

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN","")
CHANNEL = os.getenv("TELEGRAM_CHANNEL_ID","")

# Active tracked signals
_tracked = {}  # {signal_id: tracker_data}
_lock = threading.Lock()

def _send_reply(text, reply_to_msg_id):
    """Reply to original signal message"""
    if not TOKEN or not CHANNEL: return None
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{TOKEN}/sendMessage",
            json={
                "chat_id": CHANNEL,
                "text": text,
                "parse_mode": "HTML",
                "reply_to_message_id": reply_to_msg_id,
            },
            timeout=10
        )
        return r.json().get("result",{}).get("message_id")
    except Exception as e:
        logger.debug(f"Reply: {e}")
    return None

def track_signal(signal, telegram_msg_id):
    """Start tracking a signal"""
    entry  = signal.get("entry",0)
    t1     = round(entry * 1.15, 2)   # +15%
    t2     = round(entry * 1.25, 2)   # +25%
    t3     = round(entry * 1.40, 2)   # +40%
    sl     = signal.get("sl", round(entry * 0.85, 2))

    sig_id = f"{signal.get('option_symbol','')}_{int(time.time())}"

    with _lock:
        _tracked[sig_id] = {
            "signal":      signal,
            "msg_id":      telegram_msg_id,
            "entry":       entry,
            "t1":          t1,
            "t2":          t2,
            "t3":          t3,
            "sl":          sl,
            "trail_sl":    sl,
            "t1_hit":      False,
            "t2_hit":      False,
            "t3_hit":      False,
            "sl_hit":      False,
            "profitable":  False,
            "start_time":  datetime.now(IST),
        }

    logger.info(f"Tracking: {sig_id} E={entry} T1={t1} T2={t2} T3={t3} SL={sl}")
    return sig_id

def update_ltp(sig_id, ltp):
    """Update LTP and check levels"""
    with _lock:
        t = _tracked.get(sig_id)
        if not t or t["sl_hit"]:
            return

    entry   = t["entry"]
    msg_id  = t["msg_id"]
    osym    = t["signal"].get("option_symbol","")
    sym     = t["signal"].get("symbol","")
    opt     = t["signal"].get("opt_type","")

    # Trail SL — move up when profit > 15%
    if ltp > entry * 1.15:
        new_trail = round(entry * 1.05, 2)  # Trail to +5%
        if new_trail > t["trail_sl"]:
            t["trail_sl"] = new_trail

    if ltp > entry * 1.25:
        new_trail = round(entry * 1.15, 2)  # Trail to +15%
        if new_trail > t["trail_sl"]:
            t["trail_sl"] = new_trail

    # T1 Check (+15%)
    if not t["t1_hit"] and ltp >= t["t1"]:
        t["t1_hit"] = True
        t["profitable"] = True
        pct = round((ltp-entry)/entry*100, 1)
        msg = (
            f"🎯 <b>TARGET 1 ACHIEVED!</b>\n"
            f"{'━'*20}\n"
            f"📊 {sym} {opt} | <code>{osym}</code>\n"
            f"✅ Entry:  ₹{entry}\n"
            f"🚀 LTP:    <b>₹{ltp}</b> (+{pct}%)\n"
            f"🎯 T1:     ₹{t['t1']} ✅ HIT!\n"
            f"🎯 T2:     ₹{t['t2']} ⏳\n"
            f"🎯 T3:     ₹{t['t3']} ⏳\n"
            f"{'━'*20}\n"
            f"💡 SL moved to cost ₹{entry} (Risk FREE!)\n"
            f"🔥 Holding for T2..."
        )
        _send_reply(msg, msg_id)

    # T2 Check (+25%)
    elif t["t1_hit"] and not t["t2_hit"] and ltp >= t["t2"]:
        t["t2_hit"] = True
        pct = round((ltp-entry)/entry*100, 1)
        msg = (
            f"🔥 <b>TARGET 2 ACHIEVED!</b>\n"
            f"{'━'*20}\n"
            f"📊 {sym} {opt} | <code>{osym}</code>\n"
            f"✅ Entry:  ₹{entry}\n"
            f"🚀 LTP:    <b>₹{ltp}</b> (+{pct}%)\n"
            f"🎯 T1:     ₹{t['t1']} ✅\n"
            f"🎯 T2:     ₹{t['t2']} ✅ HIT!\n"
            f"🎯 T3:     ₹{t['t3']} ⏳\n"
            f"{'━'*20}\n"
            f"💡 Trail SL: ₹{t['trail_sl']} (+15%)\n"
            f"💎 Holding for T3 — BONUS ZONE!"
        )
        _send_reply(msg, msg_id)

    # T3 Check (+40%)
    elif t["t2_hit"] and not t["t3_hit"] and ltp >= t["t3"]:
        t["t3_hit"] = True
        pct = round((ltp-entry)/entry*100, 1)
        profit_per_lot = round((ltp-entry) * t["signal"].get("lot_size",1), 0)
        msg = (
            f"💥 <b>TARGET 3 — JACKPOT!</b>\n"
            f"{'━'*20}\n"
            f"📊 {sym} {opt} | <code>{osym}</code>\n"
            f"✅ Entry:  ₹{entry}\n"
            f"🚀 LTP:    <b>₹{ltp}</b> (+{pct}%)\n"
            f"🎯 T1:     ₹{t['t1']} ✅\n"
            f"🎯 T2:     ₹{t['t2']} ✅\n"
            f"🎯 T3:     ₹{t['t3']} ✅ JACKPOT!\n"
            f"{'━'*20}\n"
            f"💰 Profit: ~₹{profit_per_lot:,.0f} per lot!\n"
            f"🏆 Chanakya ne sahi kaha tha!\n"
            f"📤 <b>EXIT recommended at T3</b>"
        )
        _send_reply(msg, msg_id)

    # Trail SL Hit (Profitable)
    elif t["profitable"] and ltp <= t["trail_sl"] and not t["sl_hit"]:
        t["sl_hit"] = True
        profit_pct = round((t["trail_sl"]-entry)/entry*100, 1)
        msg = (
            f"🛡️ <b>PROFITABLE EXIT!</b>\n"
            f"{'━'*20}\n"
            f"📊 {sym} {opt} | <code>{osym}</code>\n"
            f"✅ Entry:  ₹{entry}\n"
            f"💰 Exit:   <b>₹{t['trail_sl']}</b>\n"
            f"📈 Profit: <b>+{profit_pct}%</b>\n"
            f"{'━'*20}\n"
            f"✅ Trail SL hit — Capital protected!\n"
            f"🎯 T1 {'✅' if t['t1_hit'] else '❌'} "
            f"T2 {'✅' if t['t2_hit'] else '❌'} "
            f"T3 {'✅' if t['t3_hit'] else '❌'}\n"
            f"💡 <b>Smart exit — Profit booked!</b>"
        )
        _send_reply(msg, msg_id)

    # SL Hit (Loss)
    elif not t["profitable"] and ltp <= t["sl"] and not t["sl_hit"]:
        t["sl_hit"] = True
        loss_pct = round((entry-ltp)/entry*100, 1)
        msg = (
            f"🛑 <b>STOP LOSS HIT</b>\n"
            f"{'━'*20}\n"
            f"📊 {sym} {opt} | <code>{osym}</code>\n"
            f"✅ Entry:  ₹{entry}\n"
            f"🔴 Exit:   <b>₹{ltp}</b>\n"
            f"📉 Loss:   -{loss_pct}%\n"
            f"{'━'*20}\n"
            f"🛡️ Capital protected at -15%\n"
            f"💡 <b>Small loss — next signal better!</b>\n"
            f"📊 Review: Market condition changed"
        )
        _send_reply(msg, msg_id)


class SignalTracker:
    def __init__(self):
        self.tracked = {}
        self._thread = None

    def add(self, signal, msg_id):
        """Add signal to track"""
        sig_id = track_signal(signal, msg_id)
        self.tracked[sig_id] = signal
        return sig_id

    def update_prices(self, broker):
        """Update all tracked signal prices"""
        from engine.token_manager import get_all_tokens
        try:
            tokens = get_all_tokens(broker)
            with _lock:
                active = {k:v for k,v in _tracked.items() if not v["sl_hit"]}

            for sig_id, t in active.items():
                sym    = t["signal"].get("symbol","")
                osym   = t["signal"].get("option_symbol","")
                exch   = t["signal"].get("exchange","NSE")

                # Get option LTP
                try:
                    from engine.option_chain import _get_instruments
                    instr = _get_instruments()
                    opt_token = None
                    for i in instr:
                        if i.get("symbol","") == osym:
                            opt_token = i["token"]
                            exch = i["exch_seg"]
                            break
                    if opt_token:
                        r = broker.api.ltpData(exch, osym, opt_token)
                        if r and r.get("data"):
                            ltp = float(r["data"]["ltp"])
                            update_ltp(sig_id, ltp)
                except Exception:
                    pass
                time.sleep(0.3)
        except Exception as e:
            logger.debug(f"Price update: {e}")

    def start_monitoring(self, broker, interval=30):
        """Start background monitoring"""
        def _loop():
            while True:
                if _tracked:
                    self.update_prices(broker)
                time.sleep(interval)

        self._thread = threading.Thread(target=_loop, daemon=True, name="SignalTracker")
        self._thread.start()
        logger.info("✅ Signal tracker started")


# Global instance
signal_tracker = SignalTracker()
