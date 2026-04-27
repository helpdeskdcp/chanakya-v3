"""
Background thread — monitors all user positions every 30s
"""
import threading, time, logging, sqlite3
logger = logging.getLogger(__name__)

_monitor_thread = None
_running = False


def start_monitor(broker_getter_fn, db_path="data/chanakya_v3.db"):
    """Start background position monitor"""
    global _monitor_thread, _running
    if _running:
        return
    _running = True
    _monitor_thread = threading.Thread(
        target=_monitor_loop,
        args=(broker_getter_fn, db_path),
        daemon=True
    )
    _monitor_thread.start()
    logger.info("🔍 Position monitor started")


def _monitor_loop(broker_getter_fn, db_path):
    global _running
    while _running:
        try:
            _run_sync(broker_getter_fn, db_path)
        except Exception as e:
            logger.debug(f"Monitor loop: {e}")
        time.sleep(30)  # Every 30 seconds


def _run_sync(broker_getter_fn, db_path):
    """Sync + monitor all active users"""
    from engine.position_sync import sync_broker_positions, monitor_and_trail
    import sqlite3

    conn = sqlite3.connect("data/users.db")
    conn.row_factory = sqlite3.Row
    users = conn.execute(
        "SELECT username,role FROM users WHERE active=1 AND role IN ('admin','premium')"
    ).fetchall()
    conn.close()

    for u in users:
        try:
            uname  = u["username"]
            broker = broker_getter_fn(uname)
            if not broker or not broker.connected:
                continue

            # Sync broker positions
            synced = sync_broker_positions(broker, uname, db_path)
            if synced > 0:
                logger.info(f"Synced {synced} new positions for {uname}")

            # Adaptive check — AI driven exit/trail
            try:
                import sqlite3 as _sq
                _conn = _sq.connect(db_path)
                _conn.row_factory = _sq.Row
                _pos = _conn.execute(
                    "SELECT id FROM trades WHERE status='OPEN' AND username=?",
                    (uname,)
                ).fetchall()
                _conn.close()
                from engine.adaptive_exit import adaptive_check
                for _p in _pos:
                    adaptive_check(broker, _p["id"], uname, db_path)
            except Exception as _ae:
                logger.debug(f"Adaptive check: {_ae}")
                # Fallback to basic monitor
                monitor_and_trail(broker, uname, db_path)

        except Exception as e:
            logger.debug(f"Monitor {u['username']}: {e}")


def stop_monitor():
    global _running
    _running = False
