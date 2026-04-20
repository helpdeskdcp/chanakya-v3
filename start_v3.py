"""
Chanakya AI v3.0 — Startup
"""
import os, sys, logging
sys.path.insert(0, '/root/chanakya_v3')

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('logs/trading.log')
    ]
)
logger = logging.getLogger(__name__)

def main():
    os.makedirs("logs", exist_ok=True)
    os.makedirs("data", exist_ok=True)
    os.makedirs("ai/models", exist_ok=True)

    logger.info("=" * 50)
    logger.info("⚡ CHANAKYA AI v3.0 STARTING")
    logger.info("=" * 50)

    # Init DB
    from data.database import init_db
    init_db()

    # Connect broker
    from engine.broker import broker
    from config import config
    from dotenv import load_dotenv
    load_dotenv()

    # Update config from env
    config.ANGEL_API_KEY   = os.getenv("ANGEL_API_KEY", "")
    config.ANGEL_CLIENT_ID = os.getenv("ANGEL_CLIENT_ID", "")
    config.ANGEL_PASSWORD  = os.getenv("ANGEL_PASSWORD", "")
    config.ANGEL_TOTP_KEY  = os.getenv("ANGEL_TOTP_KEY") or os.getenv("ANGEL_TOTP_SECRET", "")

    if config.ANGEL_API_KEY:
        logger.info("Connecting to Angel One...")
        try:
            if broker.connect():
                logger.info(f"✅ Connected: {broker.user_name}")
                broker.start_session_refresh()  # Daily 8:15 AM refresh
    # Refresh MCX tokens daily
    try:
        from engine.token_manager import refresh_mcx_tokens
        refresh_mcx_tokens()
        logger.info("✅ MCX tokens refreshed")
    except Exception as _te:
        logger.warning(f"Token refresh: {_te}")
                funds = broker.get_funds()
                logger.info(f"💰 Funds: ₹{funds:,.2f}")
            else:
                logger.warning("⚠️ Broker failed — continuing in PAPER mode")
        except Exception as _be:
            logger.warning(f"⚠️ Broker error: {_be} — continuing in PAPER mode")
    else:
        logger.info("📝 No API key — PAPER mode")

    # Load ML model
    from ai.ml_engine import ensemble
    if ensemble.is_trained:
        logger.info(f"🤖 ML ready: {ensemble.n_samples} samples, {ensemble.accuracy:.1%} accuracy")
    else:
        logger.info("🤖 ML model not trained yet — training needed")

    # Init Square-off engine
    from engine.order import OrderEngine
    from engine.squareoff import SquareOffEngine
    import engine.squareoff as sq_module
    oe = OrderEngine(broker)
    sq_engine = SquareOffEngine(broker, oe)
    sq_engine.start()
    sq_module.squareoff_engine = sq_engine
    logger.info("✅ Square-off engine started")

    # Init Auto Backup Scheduler
    from data.backup import scheduler as backup_scheduler, backup_now
    backup_scheduler.start()
    # Startup backup
    backup_now()
    logger.info("✅ Backup scheduler started")

    # Init Telegram
    from engine.telegram import telegram
    if telegram.enabled:
        telegram.system_alert("Chanakya AI v3.0 started ✅", "SUCCESS")
    logger.info("✅ Telegram alerts ready")

    # Auto Scanner — background thread
    import threading, time as _time
    def _auto_scan_loop():
        from engine.scanner import SignalScanner
        from engine.signals import signal_engine as se
        scanner = SignalScanner(broker)
        logger.info("✅ Auto scanner started")
        _time.sleep(30)  # Wait for market data
        while True:
            try:
                if se.is_market_open("NSE") or se.is_market_open("MCX"):
                    sigs = scanner.scan_all()
                    if sigs:
                        logger.info(f"⚡ {len(sigs)} new signals generated")
                else:
                    logger.debug("Market closed — scanner idle")
            except Exception as _se:
                logger.error(f"Scanner loop: {_se}")
            _time.sleep(120)  # Scan every 2 minutes

    scan_thread = threading.Thread(
        target=_auto_scan_loop,
        daemon=True, name="AutoScanner"
    )
    scan_thread.start()
    logger.info("✅ Auto scanner thread started")

    # Start Flask
    logger.info(f"🌐 Starting web server on port {config.PORT}...")
    from app.main import app
    from app.main import socketio
    socketio.run(app, host=config.HOST, port=config.PORT,
                 debug=False, use_reloader=False, allow_unsafe_werkzeug=True)

if __name__ == "__main__":
    main()
