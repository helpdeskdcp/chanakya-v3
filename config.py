"""
Chanakya AI v3.0 — Configuration
"""
import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    # ── App ────────────────────────────────
    APP_NAME    = "Chanakya AI v3.0"
    VERSION     = "3.0.0"
    SECRET_KEY  = os.getenv("SECRET_KEY", "change-me-in-production")
    DEBUG       = False
    PORT        = 5001  # Different from v1 (5000)
    HOST        = "127.0.0.1"

    # ── AngelOne ───────────────────────────
    ANGEL_API_KEY    = os.getenv("ANGEL_API_KEY", "")
    ANGEL_CLIENT_ID  = os.getenv("ANGEL_CLIENT_ID", "")
    ANGEL_PASSWORD   = os.getenv("ANGEL_PASSWORD", "")
    ANGEL_TOTP_KEY   = os.getenv("ANGEL_TOTP_KEY", "")

    # ── Database ───────────────────────────
    DB_PATH      = "data/chanakya_v3.db"
    REDIS_URL    = "redis://localhost:6379/1"  # DB 1 (separate from v1)

    # ── Trading ────────────────────────────
    PAPER_MODE       = True   # Start in paper mode
    PAPER_CAPITAL    = 100000
    MAX_TRADES_DAY   = 8
    MAX_OPEN_POS     = 3
    MAX_CAPITAL_PCT  = 0.20   # 20% per trade
    DAILY_LOSS_LIMIT = -3000

    # ── Risk ───────────────────────────────
    MIN_CONFIDENCE   = 70     # Min ML confidence
    MIN_RR           = 1.5    # Min Risk:Reward
    MAX_VIX          = 25     # Trade only below this

    # ── Symbols ────────────────────────────
    NSE_SYMBOLS  = ["NIFTY", "BANKNIFTY", "FINNIFTY"]
    MCX_SYMBOLS  = ["CRUDEOIL", "NATURALGAS"]

    # ── Strike Steps ───────────────────────
    STRIKE_STEPS = {
        "NIFTY": 50, "BANKNIFTY": 100, "FINNIFTY": 50,
        "CRUDEOIL": 50, "NATURALGAS": 10,
    }

    # ── Lot Sizes ──────────────────────────
    LOT_SIZES = {
        # NSE Index Options — AngelOne API verified
        "NIFTY":       65,
        "BANKNIFTY":   30,
        "FINNIFTY":    60,
        "MIDCPNIFTY":  120,
        "SENSEX":      20,
        # MCX Options — AngelOne API verified
        "CRUDEOIL":    100,
        "CRUDEOILM":   10,
        "NATURALGAS":  1250,
        "NATGASMINI":  250,
        "GOLD":        1,
        "GOLDM":       100,
        "SILVER":      30,
        "SILVERM":     5,
    }

    # ── Index Tokens (NSE) ─────────────────
    INDEX_TOKENS = {
        "NIFTY":     "99926000",
        "BANKNIFTY": "99926009",
        "FINNIFTY":  "99926037",
    }

    # ── Market Hours (IST) ─────────────────
    NSE_OPEN   = "09:15"
    NSE_CLOSE  = "15:30"
    NSE_SQUAREOFF = "15:20"
    MCX_OPEN   = "09:00"
    MCX_CLOSE  = "23:30"
    MCX_SQUAREOFF = "23:25"

    # ── Timeframes ─────────────────────────
    TIMEFRAMES = {
        "1min":  {"atr_sl": 0.5, "atr_tgt": 0.8,  "label": "1 Min",  "hold": "3-5 min"},
        "5min":  {"atr_sl": 0.8, "atr_tgt": 1.2,  "label": "5 Min",  "hold": "10-15 min"},
        "15min": {"atr_sl": 1.0, "atr_tgt": 1.8,  "label": "15 Min", "hold": "30-45 min"},
        "1hour": {"atr_sl": 1.5, "atr_tgt": 2.5,  "label": "1 Hour", "hold": "2-4 hrs"},
    }

config = Config()
