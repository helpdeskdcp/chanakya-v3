"""
Chanakya v3 — SQLite Database Manager
"""
import sqlite3, os, logging
from datetime import datetime
from config import config

logger = logging.getLogger(__name__)

def get_conn():
    os.makedirs("data", exist_ok=True)
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_conn()
    cur = conn.cursor()

    cur.executescript("""
    CREATE TABLE IF NOT EXISTS trades (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        symbol        TEXT NOT NULL,
        opt_type      TEXT NOT NULL,
        strike        REAL NOT NULL,
        expiry        TEXT,
        entry_price   REAL NOT NULL,
        exit_price    REAL,
        sl_price      REAL,
        target_price  REAL,
        quantity      INTEGER NOT NULL,
        lots          INTEGER NOT NULL DEFAULT 1,
        pnl           REAL DEFAULT 0,
        status        TEXT DEFAULT 'OPEN',
        strategy      TEXT,
        signal_conf   REAL DEFAULT 0,
        ml_confidence REAL DEFAULT 0,
        ce_score      INTEGER DEFAULT 0,
        pe_score      INTEGER DEFAULT 0,
        atr           REAL DEFAULT 0,
        vix           REAL DEFAULT 0,
        pcr           REAL DEFAULT 0,
        exit_reason   TEXT,
        order_id      TEXT,
        mode          TEXT DEFAULT 'PAPER',
        created_at    DATETIME DEFAULT CURRENT_TIMESTAMP,
        closed_at     DATETIME,
        updated_at    DATETIME DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS signals (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        symbol        TEXT NOT NULL,
        opt_type      TEXT NOT NULL,
        strike        REAL,
        direction     TEXT,
        confidence    REAL DEFAULT 0,
        ml_conf       REAL DEFAULT 0,
        ce_score      INTEGER DEFAULT 0,
        pe_score      INTEGER DEFAULT 0,
        entry_price   REAL,
        sl_price      REAL,
        target_price  REAL,
        atr           REAL,
        strategy      TEXT,
        timeframe     TEXT,
        status        TEXT DEFAULT 'PENDING',
        executed      INTEGER DEFAULT 0,
        created_at    DATETIME DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS market_data (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        symbol     TEXT NOT NULL,
        vix        REAL,
        pcr        REAL,
        fii_net    REAL,
        dii_net    REAL,
        max_pain   REAL,
        spot       REAL,
        atm        REAL,
        date       DATE DEFAULT (date('now')),
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS model_performance (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        model_name TEXT,
        accuracy   REAL,
        win_rate   REAL,
        samples    INTEGER,
        trained_at DATETIME DEFAULT CURRENT_TIMESTAMP
    );

    CREATE INDEX IF NOT EXISTS idx_trades_status ON trades(status);
    CREATE INDEX IF NOT EXISTS idx_trades_date   ON trades(created_at);
    CREATE INDEX IF NOT EXISTS idx_signals_date  ON signals(created_at);
    """)

    conn.commit()
    conn.close()
    logger.info("✅ Database initialized")

def get_today_stats():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT
            COUNT(*) as total,
            COALESCE(SUM(pnl), 0) as pnl,
            SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) as wins,
            SUM(CASE WHEN status='OPEN' THEN 1 ELSE 0 END) as open
        FROM trades
        WHERE date(created_at) = date('now', 'localtime')
    """)
    r = dict(cur.fetchone())
    r['win_rate'] = round(r['wins'] / r['total'] * 100, 1) if r['total'] > 0 else 0
    conn.close()
    return r

if __name__ == "__main__":
    init_db()
    print("✅ DB created:", config.DB_PATH)
