import time, logging, threading, sqlite3
from datetime import datetime
import pytz
logger = logging.getLogger(__name__)
IST = pytz.timezone("Asia/Kolkata")

class ChanakeyaOrchestrator:
    def __init__(self, broker, db_path="data/chanakya_v3.db"):
        self.broker   = broker
        self.db_path  = db_path
        self.running  = False
        self._thread  = None
        from engine.self_healer import SelfHealingBroker
        self.safe_broker = SelfHealingBroker(broker)

    def start(self):
        if self.running: return
        self.running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        logger.info("Chanakya Orchestrator started")

    def stop(self):
        self.running = False
        logger.info("Orchestrator stopped")

    def _loop(self):
        cycle = 0
        while self.running:
            try:
                cycle += 1
                now = datetime.now(IST)
                h, mn = now.hour, now.minute
                # Health check every 10 cycles
                if cycle % 10 == 0:
                    from engine.self_healer import health_check
                    ok, issues = health_check(self.broker, self.db_path)
                    if not ok:
                        logger.warning(f"Health issues: {issues}")
                        if "broker_disconnected" in issues:
                            self.safe_broker._try_reconnect()
                # Risk check
                from engine.risk_manager import can_trade, get_status
                capital = self._get_capital()
                tradeable, reason = can_trade(capital, self.db_path)
                # Monitor positions (always)
                self._monitor_positions()
                # Signal scan (only during market hours)
                if tradeable and self._is_market_hours(h, mn):
                    self._scan_and_signal(capital)
                elif not tradeable:
                    logger.debug(f"Trading paused: {reason}")
                time.sleep(30)
            except Exception as e:
                logger.error(f"Orchestrator loop error: {e}")
                time.sleep(10)

    def _is_market_hours(self, h, mn):
        nse = (9,30)<=(h,mn)<=(15,25)
        mcx = (9,0)<=(h,mn)<=(23,25)
        return nse or mcx

    def _get_capital(self):
        try:
            r = self.broker.api.rmsLimit()
            if r and r.get("data"):
                return float(r["data"].get("net",0))
        except: pass
        return 0.0

    def _monitor_positions(self):
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            pos = conn.execute(
                "SELECT id,username FROM trades WHERE status=?",
                ("OPEN",)
            ).fetchall()
            conn.close()
            for p in pos:
                try:
                    from engine.adaptive_exit import adaptive_check
                    adaptive_check(self.broker, p["id"], p["username"], self.db_path)
                except Exception as e:
                    pid=p["id"]; logger.debug(f"Monitor #{pid}: {e}")
        except Exception as e:
            logger.error(f"Position monitor error: {e}")

    def _scan_and_signal(self, capital):
        try:
            from engine.smart_scanner import smart_scan
            from data.market import get_vix
            vix = get_vix() or 18
            signals = smart_scan(self.broker)
            if signals:
                logger.info(f"Orchestrator: {len(signals)} signals found")
                # Store to signal cache
                from engine.signal_store import update as sig_update
                sig_update("avinash", signals)
        except Exception as e:
            logger.debug(f"Scan error: {e}")

    def emergency_stop(self):
        from engine.risk_manager import kill_switch
        kill_switch(True)
        self.stop()
        logger.critical("EMERGENCY STOP activated")

# Singleton
_orchestrator = None

def get_orchestrator(broker=None, db_path="data/chanakya_v3.db"):
    global _orchestrator
    if _orchestrator is None and broker:
        _orchestrator = ChanakeyaOrchestrator(broker, db_path)
    return _orchestrator
