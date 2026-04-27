"""
Chanakya AI — Role Based Access Policy
admin > premium > viewer(demo) > expired
"""
from datetime import datetime, timedelta
import sqlite3

FEATURES = {
    "admin":   {"signals":True,"paper_trade":True,"live_trade":True,"own_broker":True,"analytics":True,"option_chain":True,"backtest":True,"chart":True,"admin_panel":True,"system_monitor":True,"user_mgmt":True,"ml_retrain":True},
    "premium": {"signals":True,"paper_trade":True,"live_trade":True,"own_broker":True,"analytics":True,"option_chain":True,"backtest":True,"chart":True,"admin_panel":False,"system_monitor":False,"user_mgmt":False,"ml_retrain":False},
    "viewer":  {"signals":True,"paper_trade":True,"live_trade":False,"own_broker":False,"analytics":False,"option_chain":False,"backtest":True,"chart":True,"admin_panel":False,"system_monitor":False,"user_mgmt":False,"ml_retrain":False},
    "expired": {"signals":False,"paper_trade":False,"live_trade":False,"own_broker":False,"analytics":False,"option_chain":False,"backtest":False,"chart":False,"admin_panel":False,"system_monitor":False,"user_mgmt":False,"ml_retrain":False},
}

PLANS = {
    "monthly":   {"days":30,  "price":999},
    "quarterly": {"days":90,  "price":2499},
    "halfyear":  {"days":180, "price":4499},
    "yearly":    {"days":365, "price":7999},
}

UPI_ID   = "helpdeskdcp-2@okicici"
UPI_NAME = "Chanakya AI"


def _parse_dt(s):
    """Parse datetime string — handle both ISO and datetime formats"""
    if not s:
        return None
    s = str(s).replace('T',' ').split('.')[0].strip()
    for fmt in ["%Y-%m-%d %H:%M:%S", "%Y-%m-%d"]:
        try:
            return datetime.strptime(s, fmt)
        except Exception:
            pass
    return None


def get_effective_role(username, db_path="data/users.db"):
    """Get effective role considering expiry"""
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        u = conn.execute(
            "SELECT role,trial_start,trial_days,premium_expiry,active FROM users WHERE username=?",
            (username,)
        ).fetchone()
        conn.close()

        if not u or not u["active"]:
            return "expired"

        role = u["role"]
        if role == "admin":
            return "admin"
        if role == "premium":
            if u["premium_expiry"]:
                exp = _parse_dt(u["premium_expiry"])
                if exp and datetime.utcnow() > exp:
                    return "expired"
            return "premium"
        if role == "viewer":
            if u["trial_start"] and u["trial_days"]:
                start = _parse_dt(u["trial_start"])
                if start:
                    expiry = start + timedelta(days=int(u["trial_days"]))
                    if datetime.utcnow() > expiry:
                        return "expired"
            return "viewer"
        return "expired"
    except Exception:
        return "viewer"


def can_access(username, feature, db_path="data/users.db"):
    role = get_effective_role(username, db_path)
    return FEATURES.get(role, {}).get(feature, False)


def get_trial_days_left(username, db_path="data/users.db"):
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        u = conn.execute(
            "SELECT trial_start,trial_days FROM users WHERE username=?",
            (username,)
        ).fetchone()
        conn.close()
        if u and u["trial_start"] and u["trial_days"]:
            start = _parse_dt(u["trial_start"])
            if start:
                expiry = start + timedelta(days=int(u["trial_days"]))
                left = (expiry - datetime.utcnow()).days
                return max(0, left)
    except Exception:
        pass
    return 0


def get_user_policy(username, db_path="data/users.db"):
    role = get_effective_role(username, db_path)
    features = FEATURES.get(role, {})
    trial_left = get_trial_days_left(username, db_path) if role == "viewer" else None
    return {
        "role":       role,
        "features":   features,
        "trial_left": trial_left,
        "can_trade":  features.get("paper_trade", False),
        "can_live":   features.get("live_trade", False),
        "is_admin":   role == "admin",
        "is_premium": role in ("admin","premium"),
        "is_expired": role == "expired",
        "upi_id":     UPI_ID,
        "plans":      PLANS,
    }
