import sqlite3, logging, threading
from datetime import datetime
import pytz
logger = logging.getLogger(__name__)
IST = pytz.timezone("Asia/Kolkata")

# CONFIG
MAX_DAILY_LOSS_PCT  = 3.0   # Stop if daily loss > 3% of capital
MAX_TRADES_PER_DAY  = 10    # Max trades per day
MAX_CONSEC_LOSSES   = 3     # Pause after 3 consecutive losses
PAUSE_MINUTES       = 30    # Pause duration after consec losses

_lock = threading.Lock()
_state = {
    "kill_switch": False,
    "safe_mode":   False,
    "paused_until": None,
    "consec_losses": 0,
    "daily_trades": 0,
    "daily_pnl":   0.0,
    "last_reset":  None,
}

def _reset_if_new_day():
    today = datetime.now(IST).strftime("%Y-%m-%d")
    if _state["last_reset"] != today:
        _state["daily_trades"] = 0
        _state["daily_pnl"]    = 0.0
        _state["consec_losses"] = 0
        _state["safe_mode"]    = False
        _state["paused_until"] = None
        _state["last_reset"]   = today
        logger.info("Risk Manager: daily reset")

def can_trade(capital, db_path="data/chanakya_v3.db"):
    with _lock:
        _reset_if_new_day()
        if _state["kill_switch"]:
            return False, "KILL SWITCH active"
        if _state["safe_mode"]:
            return False, "SAFE MODE active"
        now = datetime.now(IST)
        if _state["paused_until"] and now < _state["paused_until"]:
            mins = (_state["paused_until"]-now).seconds//60
            return False, f"Paused — {mins}min remaining"
        if _state["daily_trades"] >= MAX_TRADES_PER_DAY:
            return False, f"Max trades/day reached ({MAX_TRADES_PER_DAY})"
        max_loss = capital * MAX_DAILY_LOSS_PCT / 100
        if _state["daily_pnl"] <= -max_loss:
            _state["safe_mode"] = True
            loss_amt = abs(_state["daily_pnl"]); return False, f"Daily loss limit Rs{loss_amt:.0f}"
        return True, "OK"

def record_trade_result(pnl, db_path="data/chanakya_v3.db"):
    with _lock:
        _state["daily_pnl"] += pnl
        _state["daily_trades"] += 1
        if pnl < 0:
            _state["consec_losses"] += 1
            if _state["consec_losses"] >= MAX_CONSEC_LOSSES:
                from datetime import timedelta
                _state["paused_until"] = datetime.now(IST) + timedelta(minutes=PAUSE_MINUTES)
                logger.warning(f"PAUSE: {MAX_CONSEC_LOSSES} consecutive losses — paused {PAUSE_MINUTES}min")
        else:
            _state["consec_losses"] = 0
        logger.info(f"Trade result: PnL=Rs{pnl:.0f} daily=Rs{_state['daily_pnl']:.0f} trades={_state['daily_trades']}")

def kill_switch(activate=True):
    with _lock:
        _state["kill_switch"] = activate
        logger.critical(f"KILL SWITCH: {'ACTIVATED' if activate else 'DEACTIVATED'}")

def get_status():
    with _lock:
        _reset_if_new_day()
        return dict(_state)
