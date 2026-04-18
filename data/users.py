"""
Chanakya v3 — User Management
Roles: admin, premium, viewer
"""
import sqlite3, hashlib, os, secrets
from datetime import datetime, timedelta
import pytz

IST = pytz.timezone("Asia/Kolkata")
DB_PATH = "data/users.db"


import base64 as _b64
_ENC_KEY = "chanakya_v3_2026"

def _enc(text):
    """Encrypt sensitive data"""
    if not text: return ""
    import hashlib
    kb = hashlib.sha256(_ENC_KEY.encode()).digest()
    tb = text.encode()
    return _b64.b64encode(bytes([tb[i]^kb[i%len(kb)] for i in range(len(tb))])).decode()

def _dec(text):
    """Decrypt sensitive data"""
    if not text: return ""
    import hashlib
    kb = hashlib.sha256(_ENC_KEY.encode()).digest()
    eb = _b64.b64decode(text.encode())
    return bytes([eb[i]^kb[i%len(kb)] for i in range(len(eb))]).decode()

def get_broker_credentials(username):
    """Get decrypted broker credentials for a user"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    u = conn.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
    conn.close()
    if not u:
        return None
    return {
        "broker":     u["broker_name"] or "angelone",
        "connected":  bool(u["broker_connected"]),
        "api_key":    _dec(u["angel_api_key"] or ""),
        "client_id":  _dec(u["angel_client_id"] or ""),
        "password":   _dec(u["angel_password"] or ""),
        "totp_key":   _dec(u["angel_totp_key"] or ""),
    }

def init_users_db():
    conn = sqlite3.connect(DB_PATH)
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS users (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        username        TEXT UNIQUE NOT NULL,
        password_hash   TEXT NOT NULL,
        role            TEXT DEFAULT 'viewer',
        active          INTEGER DEFAULT 1,
        -- Angel One credentials
        angel_api_key   TEXT,
        angel_client_id TEXT,
        angel_password  TEXT,
        angel_totp_key  TEXT,
        -- Subscription
        trial_start     DATETIME DEFAULT CURRENT_TIMESTAMP,
        trial_days      INTEGER DEFAULT 15,
        premium_start   DATETIME,
        premium_expiry  DATETIME,
        -- Limits
        trades_today    INTEGER DEFAULT 0,
        last_trade_date TEXT,
        -- Payment
        upi_name        TEXT,
        -- Meta
        telegram_id     TEXT,
        created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
        last_login      DATETIME
    );

    CREATE TABLE IF NOT EXISTS payments (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id     INTEGER NOT NULL,
        amount      REAL DEFAULT 3000,
        utr_number  TEXT,
        status      TEXT DEFAULT 'PENDING',
        verified_by TEXT,
        created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
        verified_at DATETIME,
        FOREIGN KEY(user_id) REFERENCES users(id)
    );

    CREATE TABLE IF NOT EXISTS audit_log (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id     INTEGER,
        action      TEXT,
        details     TEXT,
        ip_address  TEXT,
        created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # Default admin user
    admin_hash = hash_password("chanakya2026")
    ravi_hash  = hash_password("ravi2026")

    conn.execute("""
        INSERT OR IGNORE INTO users
        (username, password_hash, role, trial_days)
        VALUES (?,?,'admin',9999)
    """, ("avinash", admin_hash))

    conn.execute("""
        INSERT OR IGNORE INTO users
        (username, password_hash, role, trial_days)
        VALUES (?,?,'premium',9999)
    """, ("ravi", ravi_hash))

    conn.commit()
    conn.close()
    print("✅ Users DB initialized")

def hash_password(pwd):
    return hashlib.sha256(pwd.encode()).hexdigest()

def verify_user(username, password):
    """Returns user dict or None"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    user = conn.execute(
        "SELECT * FROM users WHERE username=? AND active=1",
        (username,)
    ).fetchone()
    conn.close()
    if not user:
        return None
    if user["password_hash"] != hash_password(password):
        return None
    return dict(user)

def get_user(username):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    u = conn.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
    conn.close()
    return dict(u) if u else None

def get_user_role(username):
    """Returns effective role considering expiry"""
    u = get_user(username)
    if not u:
        return None

    role = u["role"]

    # Admin — always admin
    if role == "admin":
        return "admin"

    # Check trial expiry
    if role == "viewer":
        trial_start = datetime.strptime(
            u["trial_start"][:19], "%Y-%m-%d %H:%M:%S"
        ).replace(tzinfo=IST)
        trial_end = trial_start + timedelta(days=u["trial_days"] or 15)
        if datetime.now(IST) > trial_end:
            return "expired"
        return "viewer"

    # Check premium expiry
    if role == "premium":
        if u["premium_expiry"]:
            expiry = datetime.strptime(
                u["premium_expiry"][:19], "%Y-%m-%d %H:%M:%S"
            ).replace(tzinfo=IST)
            if datetime.now(IST) > expiry:
                # Auto downgrade
                conn = sqlite3.connect(DB_PATH)
                conn.execute(
                    "UPDATE users SET role='viewer', trial_start=? WHERE username=?",
                    (datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S"), username)
                )
                conn.commit()
                conn.close()
                return "viewer"
        return "premium"

    return role

def get_trade_limit(role):
    """Max trades per day by role"""
    return {"admin": 999, "premium": 10, "viewer": 1}.get(role, 0)

def check_trade_allowed(username):
    """Can user place another trade today?"""
    u = get_user(username)
    if not u:
        return False, "User not found"

    role = get_user_role(username)
    if role == "expired":
        return False, "Trial expired — upgrade to premium"

    limit = get_trade_limit(role)
    today = datetime.now(IST).strftime("%Y-%m-%d")

    # Reset daily counter
    trades_today = u["trades_today"] or 0
    if u["last_trade_date"] != today:
        trades_today = 0

    if trades_today >= limit:
        return False, f"Daily limit reached ({limit} trades for {role})"

    return True, f"{limit - trades_today} trades remaining"

def increment_trade_count(username):
    today = datetime.now(IST).strftime("%Y-%m-%d")
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        UPDATE users SET
            trades_today = CASE WHEN last_trade_date=? THEN trades_today+1 ELSE 1 END,
            last_trade_date = ?
        WHERE username=?
    """, (today, today, username))
    conn.commit()
    conn.close()

def get_trial_status(username):
    """Days remaining in trial"""
    u = get_user(username)
    if not u or u["role"] != "viewer":
        return None
    trial_start = datetime.strptime(
        u["trial_start"][:19], "%Y-%m-%d %H:%M:%S"
    )
    days_used = (datetime.now() - trial_start).days
    days_left = max(0, (u["trial_days"] or 15) - days_used)
    return days_left

def create_payment_request(username, utr_number):
    """User submits payment UTR"""
    u = get_user(username)
    if not u:
        return None

    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        INSERT INTO payments (user_id, utr_number, status)
        VALUES (?,?,'PENDING')
    """, (u["id"], utr_number))
    payment_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.commit()
    conn.close()
    return payment_id

def verify_payment(payment_id, verified_by="admin", plan_key="monthly"):
    """Admin verifies payment → upgrade user based on plan"""
    from data.eula import get_plan
    plan = get_plan(plan_key) or get_plan("monthly")
    days = plan["days"]
    """Admin verifies payment → upgrade user"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    payment = conn.execute(
        "SELECT * FROM payments WHERE id=?", (payment_id,)
    ).fetchone()

    if not payment:
        conn.close()
        return False, "Payment not found"

    now = datetime.now(IST)
    expiry = now + timedelta(days=days)

    # Upgrade user
    conn.execute("""
        UPDATE users SET
            role='premium',
            premium_start=?,
            premium_expiry=?
        WHERE id=?
    """, (now.strftime("%Y-%m-%d %H:%M:%S"),
          expiry.strftime("%Y-%m-%d %H:%M:%S"),
          payment["user_id"]))

    # Mark payment verified
    conn.execute("""
        UPDATE payments SET
            status='VERIFIED',
            verified_by=?,
            verified_at=?
        WHERE id=?
    """, (verified_by, now.strftime("%Y-%m-%d %H:%M:%S"), payment_id))

    conn.commit()
    conn.close()
    return True, f"User upgraded to premium until {expiry.strftime('%d %b %Y')}"

def get_all_users():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    users = conn.execute("""
        SELECT u.*, 
               (SELECT COUNT(*) FROM payments WHERE user_id=u.id AND status='VERIFIED') paid_count
        FROM users u ORDER BY created_at DESC
    """).fetchall()
    conn.close()
    return [dict(u) for u in users]

def get_pending_payments():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    payments = conn.execute("""
        SELECT p.*, u.username FROM payments p
        JOIN users u ON p.user_id = u.id
        WHERE p.status='PENDING'
        ORDER BY p.created_at DESC
    """).fetchall()
    conn.close()
    return [dict(p) for p in payments]

def register_user(username, password, role="viewer"):
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.execute("""
            INSERT INTO users (username, password_hash, role)
            VALUES (?,?,?)
        """, (username, hash_password(password), role))
        conn.commit()
        conn.close()
        return True, "User created"
    except Exception as e:
        return False, str(e)

def log_action(user_id, action, details="", ip=""):
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.execute("""
            INSERT INTO audit_log (user_id, action, details, ip_address)
            VALUES (?,?,?,?)
        """, (user_id, action, details, ip))
        conn.commit()
        conn.close()
    except Exception:
        pass
