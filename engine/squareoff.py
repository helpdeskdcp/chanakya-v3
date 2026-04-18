"""
Chanakya v3 — Auto Square-off Engine
NSE: 3:20 PM | MCX: 11:25 PM IST
"""
import logging, sqlite3, threading, time
from datetime import datetime
import pytz
from config import config

logger = logging.getLogger(__name__)
IST = pytz.timezone("Asia/Kolkata")

# ── Square-off Times ───────────────────────────────────
SQUAREOFF_TIMES = {
    "NSE": (15, 20),   # 3:20 PM
    "NFO": (15, 20),
    "MCX": (23, 25),   # 11:25 PM
}

class SquareOffEngine:
    def __init__(self, broker, order_engine):
        self.broker       = broker
        self.order_engine = order_engine
        self.running      = False
        self._thread      = None
        self._sq_done     = set()  # Track already squared-off sessions

    def start(self):
        """Start background square-off monitor"""
        self.running = True
        self._thread = threading.Thread(
            target=self._monitor_loop,
            daemon=True, name="SquareoffMonitor"
        )
        self._thread.start()
        logger.info("✅ Square-off monitor started")

    def stop(self):
        self.running = False
        logger.info("⏹️ Square-off monitor stopped")

    def _monitor_loop(self):
        while self.running:
            try:
                self._check_squareoff()
                self.order_engine.monitor_positions(self.broker)
            except Exception as e:
                logger.error(f"Monitor loop error: {e}")
            time.sleep(30)  # Check every 30 seconds

    def _check_squareoff(self):
        now = datetime.now(IST)
        if now.weekday() >= 5:  # Weekend
            return

        h, m = now.hour, now.minute

        for exchange, (sq_h, sq_m) in SQUAREOFF_TIMES.items():
            session_key = f"{exchange}_{now.date()}"
            if session_key in self._sq_done:
                continue

            # Time to square off?
            if h == sq_h and m >= sq_m:
                count = self._squareoff_exchange(exchange)
                if count >= 0:
                    self._sq_done.add(session_key)
                    logger.info(f"✅ {exchange} square-off done: {count} positions closed")

    def _squareoff_exchange(self, exchange):
        """Square off all open positions for exchange"""
        try:
            conn = sqlite3.connect(config.DB_PATH)
            conn.row_factory = sqlite3.Row
            trades = conn.execute("""
                SELECT * FROM trades
                WHERE status='OPEN' AND exchange=?
            """, (exchange,)).fetchall()
            conn.close()

            if not trades:
                return 0

            count = 0
            for trade in trades:
                token  = trade["token"] or ""
                symbol = trade["trading_symbol"] or trade["symbol"]
                ltp    = self.broker.get_ltp(exchange, symbol, token) if token else 0
                # Use entry price if LTP unavailable
                exit_p = ltp if ltp > 0 else trade["entry_price"]
                ok, result = self.order_engine.place_exit(
                    trade["id"], exit_p, f"AUTO_SQUAREOFF_{exchange}"
                )
                if ok:
                    count += 1
                    pnl = result.get("pnl", 0)
                    logger.info(
                        f"🔴 SQUARED OFF: {symbol} @ ₹{exit_p} | "
                        f"P&L: ₹{pnl:.0f}"
                    )
            return count
        except Exception as e:
            logger.error(f"Square-off error {exchange}: {e}")
            return -1

    def manual_squareoff_all(self):
        """Manually square off ALL open positions"""
        try:
            conn = sqlite3.connect(config.DB_PATH)
            conn.row_factory = sqlite3.Row
            trades = conn.execute(
                "SELECT * FROM trades WHERE status='OPEN'"
            ).fetchall()
            conn.close()

            count = 0
            for trade in trades:
                token    = trade["token"] or ""
                exchange = trade["exchange"] or "NFO"
                symbol   = trade["trading_symbol"] or trade["symbol"]
                ltp      = self.broker.get_ltp(exchange, symbol, token) if token else 0
                exit_p   = ltp if ltp > 0 else trade["entry_price"]
                ok, _    = self.order_engine.place_exit(
                    trade["id"], exit_p, "MANUAL_SQUAREOFF"
                )
                if ok:
                    count += 1
            logger.info(f"✅ Manual square-off: {count} positions closed")
            return count
        except Exception as e:
            logger.error(f"Manual square-off error: {e}")
            return 0

    def get_squareoff_times(self):
        """Return next square-off times"""
        now = datetime.now(IST)
        times = {}
        for exchange, (h, m) in SQUAREOFF_TIMES.items():
            sq_time = now.replace(hour=h, minute=m, second=0)
            remaining = (sq_time - now).total_seconds()
            times[exchange] = {
                "time":      f"{h:02d}:{m:02d}",
                "remaining": max(0, int(remaining)),
                "passed":    remaining < 0,
            }
        return times

squareoff_engine = None  # Initialized in start_v3.py
