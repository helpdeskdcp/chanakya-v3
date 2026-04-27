"""
Chanakya AI — Role Based Access Policy
admin > premium > viewer(demo)
"""
from datetime import datetime, timedelta
import pytz, sqlite3
IST = pytz.timezone("Asia/Kolkata")

# Feature access matrix
FEATURES = {
    "admin": {
        "signals":True,"paper_trade":True,"live_trade":True,
        "own_broker":True,"analytics":True,"option_chain":True,
        "backtest":True,"chart":True,"admin_panel":True,
        "system_monitor":True,"user_mgmt":True,"ml_retrain":True,
    },
    "premium": {
        "signals":True,"paper_trade":True,"live_trade":True,
        "own_broker":True,"analytics":True,"option_chain":True,
        "backtest":True,"chart":True,"admin_panel":False,
        "system_monitor":False,"user_mgmt":False,"ml_retrain":False,
    },
    "viewer": {
        "signals":True,"paper_trade":True,"live_trade":False,
        "own_broker":False,"analytics":False,"option_chain":False,
        "backtest":True,"chart":True,"admin_panel":False,
        "system_monitor":False,"user_mgmt":False,"ml_retrain":False,
    },
    "expired": {
        "signals":False,"paper_trade":False,"live_trade":False,
        "own_broker":False,"analytics":False,"option_chain":False,
        "backtest":False,"chart":False,"admin_panel":False,
        "system_monitor":False,"user_mgmt":False,"ml_retrain":False,
    }
}

PLANS = {
    "monthly":   {"days":30,  "price":999},
    "quarterly": {"days":90,  "price":2499},
    "halfyear":  {"days":180, "price":4499},
    "yearly":    {"days":365, "price":7999},
}

UPI_ID   = "helpdeskdcp-2@okicici"
UPI_NAME = "Chanakya AI"

def get_effective_role(username, db_path="data/users.db"):
    """Get effective role considering trial expiry"""
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
            # Check premium expiry
            if u["premium_expiry"]:
                try:
                    exp = datetime.fromisoformat(u["premium_expiry"])
                    if datetime.utcnow() > exp:
                        return "expired"
                except Exception:
                    pass
            return "premium"
        if role == "viewer":
            # Check trial expiry
            if u["trial_start"] and u["trial_days"]:
                try:
                    start = datetime.fromisoformat(u["trial_start"])
                    expiry = start + timedelta(days=int(u["trial_days"]))
                    if datetime.utcnow() > expiry:
                        return "expired"
                    return "viewer"
                except Exception:
                    pass
            return "viewer"
        return "expired"
    except Exception:
        return "viewer"

def can_access(username, feature, db_path="data/users.db"):
    """Check if user can access a feature"""
    role = get_effective_role(username, db_path)
    return FEATURES.get(role, {}).get(feature, False)

def get_trial_days_left(username, db_path="data/users.db"):
    """Days left in trial"""
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        u = conn.execute(
            "SELECT trial_start,trial_days FROM users WHERE username=?",
            (username,)
        ).fetchone()
        conn.close()
        if u and u["trial_start"] and u["trial_days"]:
            start = datetime.fromisoformat(u["trial_start"])
            expiry = start + timedelta(days=int(u["trial_days"]))
            left = (expiry - datetime.utcnow()).days
            return max(0, left)
    except Exception:
        pass
    return 0

def get_user_policy(username, db_path="data/users.db"):
    """Full policy info for a user"""
    role = get_effective_role(username, db_path)
    features = FEATURES.get(role, {})
    trial_left = get_trial_days_left(username, db_path) if role=="viewer" else None
    return {
        "role":        role,
        "features":    features,
        "trial_left":  trial_left,
        "can_trade":   features.get("paper_trade", False),
        "can_live":    features.get("live_trade", False),
        "is_admin":    role=="admin",
        "is_premium":  role in ("admin","premium"),
        "is_expired":  role=="expired",
        "upi_id":      UPI_ID,
        "plans":       PLANS,
    }
