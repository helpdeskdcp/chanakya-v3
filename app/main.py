"""
Chanakya AI v3.0 — Main Flask Application
"""
import logging, os, sys
sys.path.insert(0, '/root/chanakya_v3')
from dotenv import load_dotenv
load_dotenv("/root/chanakya_v3/.env")

from flask import Flask, jsonify, request, session, render_template, redirect, url_for
from flask_cors import CORS
from datetime import datetime
import pytz

from config import config
from data.database import init_db, get_today_stats
from engine.broker import broker
from engine.signals import signal_engine
from ai.ml_engine import ensemble

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('logs/app.log')
    ]
)
logger = logging.getLogger(__name__)
IST = pytz.timezone("Asia/Kolkata")

app = Flask(__name__, template_folder='../templates', static_folder='../static')
# ProxyFix — nginx behind proxy fix
from werkzeug.middleware.proxy_fix import ProxyFix
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
app.secret_key = os.getenv("SECRET_KEY", "chanakya_v3_secret_2026")
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"]   = False  # nginx handles HTTPS
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_PATH"]     = "/"
app.config["PERMANENT_SESSION_LIFETIME"] = 86400  # 1 day
CORS(app, origins=["https://bramha.cloud", "http://localhost:3001"], supports_credentials=True)

# ── Simple Token Store (bypass cookie issues) ─────────
import json as _json, os as _os
_TOKEN_FILE = "/tmp/chanakya_tokens.json"

def _load_tokens():
    try:
        if _os.path.exists(_TOKEN_FILE):
            return _json.load(open(_TOKEN_FILE))
    except: pass
    return {}

def _save_tokens(t):
    try: _json.dump(t, open(_TOKEN_FILE,"w"))
    except: pass

_tokens = _load_tokens()

# ── Auth Helper ────────────────────────────────────────
def get_session():
    return session.get("user") or {}

INTERNAL_TOKEN = "chanakya_internal_2026"

def require_auth(f):
    from functools import wraps
    @wraps(f)
    def wrapper(*args, **kwargs):
        # Check session
        if session.get("user"):
            return f(*args, **kwargs)
        # Check token in header or query
        token = (request.headers.get("X-Auth-Token") or
                 request.args.get("t") or
                 request.cookies.get("chanakya_token",""))
        if token and token in _tokens:
            session["user"] = _tokens[token]
            return f(*args, **kwargs)
        return jsonify({"success": False, "error": "Unauthorized"}), 401
    return wrapper

# ── Auth Routes ────────────────────────────────────────
@app.route("/api/v3/login", methods=["POST", "GET"])
def login():
    if request.method == "GET":
        return redirect("/v3")

    # Get credentials from JSON or Form
    if request.is_json:
        data = request.get_json() or {}
        user = data.get("username", "").strip()
        pwd  = data.get("password", "").strip()
    else:
        user = (request.form.get("username") or "").strip()
        pwd  = (request.form.get("password") or "").strip()

    # Hardcoded + env fallback
    valid = {
        "avinash": "chanakya2026",
        "ravi":    "ravi2026",
    }
    # Also check env
    env_user = os.getenv("ADMIN_USER", "avinash")
    env_pass = os.getenv("ADMIN_PASS", "chanakya2026")
    valid[env_user] = env_pass

    logger.info(f"Login attempt: user={user!r} match={valid.get(user)==pwd}")

    if user in valid and valid[user] == pwd:
        import secrets
        token = secrets.token_hex(16)
        _tokens[token] = {"username": user, "role": "admin" if user == env_user else "user"}
        _save_tokens(_tokens)
        session.clear()
        session["user"] = _tokens[token]
        session.permanent = True
        logger.info(f"Login OK: {user} token={token[:8]}...")
        # Background madhe broker connect karo
        import threading
        def _bg_connect(u):
            try:
                from engine.broker_pool import get_broker
                get_broker(u)
            except Exception:
                pass
        threading.Thread(target=_bg_connect, args=(user,), daemon=True).start()
        if request.is_json:
            return jsonify({"success": True, "username": user, "token": token})
        # Form POST — render directly with logged_in=True
        return render_template("index_v3.html", logged_in=True,
                               user={"username": user},
                               auth_token=token, login_error="")

    logger.warning(f"Login failed: user={user!r}")
    if request.is_json:
        return jsonify({"success": False, "error": "Invalid credentials"}), 401
    return redirect("/v3?login_error=1")

@app.route("/api/v3/logout", methods=["POST"])
def logout():
    user = get_current_user()
    username = user.get("username","")
    if username:
        try:
            from engine.broker_pool import clear_broker
            clear_broker(username)
        except Exception:
            pass
    session.clear()
    _tokens.pop(request.headers.get("X-Auth-Token",""), None)
    return jsonify({"success": True})

# ── Status API ─────────────────────────────────────────
@app.route("/api/v3/status")
def status():
    # Per-user broker info
    curr_user = get_current_user()
    curr_username = curr_user.get("username","")
    # Per-user broker pool — cache only
    from engine.broker_pool import _pool
    _ub = _pool.get(curr_username) if curr_username else None
    if _ub and _ub.connected:
        broker_user_name = _ub.user_name
        broker_connected = True
        broker_capital   = _ub.capital
    elif curr_username == "avinash" or not curr_username:
        # Admin — use global broker
        broker_user_name = broker.user_name
        broker_connected = broker.connected
        broker_capital   = 0
    else:
        # Non-admin — show own broker name from DB
        try:
            from data.users import get_broker_credentials
            _creds = get_broker_credentials(curr_username)
            broker_connected = bool(_creds and _creds.get("connected"))
            broker_user_name = _creds.get("client_id","") if broker_connected else ""
        except Exception:
            broker_connected = False
            broker_user_name = ""
        broker_capital = 0

    stats = get_today_stats()
    vix = _get_vix()
    now = datetime.now(IST)
    return jsonify({
        "success":       True,
        "version":       config.VERSION,
        "connected":     broker_connected,
        "user":          broker_user_name,
        "login_user":    curr_username,
        "mode":          _get_user_mode(curr_username) if curr_username else "PAPER",
        "capital":       broker_capital,
        "market_open":   signal_engine.is_market_open(),
        "mcx_open":      signal_engine.is_market_open("MCX"),
        "time":          now.strftime("%H:%M:%S"),
        "date":          now.strftime("%d %b %Y"),
        "vix":           vix,
        "today":         stats,
        "ml_ready":      __import__("ai.ml_engine",fromlist=["get_brain"]).get_brain().is_trained,
        "ml_accuracy":   round(__import__("ai.ml_engine",fromlist=["get_brain"]).get_brain().accuracy*100,1),
        "ml_samples":    __import__("ai.ml_engine",fromlist=["get_brain"]).get_brain().n_samples,
    })

# ── Dashboard API ──────────────────────────────────────


def _get_user_mode(username):
    """Get per-user trading mode"""
    try:
        import sqlite3 as _sq
        conn = _sq.connect("data/users.db")
        try:
            conn.execute("ALTER TABLE users ADD COLUMN pref_mode TEXT DEFAULT 'PAPER'")
            conn.commit()
        except Exception:
            pass
        r = conn.execute("SELECT pref_mode FROM users WHERE username=?", (username,)).fetchone()
        conn.close()
        return (r[0] if r and r[0] else "PAPER")
    except Exception:
        return "PAPER"

def _set_user_mode(username, mode):
    """Set per-user trading mode"""
    try:
        import sqlite3 as _sq
        conn = _sq.connect("data/users.db")
        try:
            conn.execute("ALTER TABLE users ADD COLUMN pref_mode TEXT DEFAULT 'PAPER'")
            conn.commit()
        except Exception:
            pass
        conn.execute("UPDATE users SET pref_mode=? WHERE username=?", (mode, username))
        conn.commit()
        conn.close()
    except Exception:
        pass

# ── Per-User Capital Helpers ───────────────────────────
def _get_user_broker_info(username):
    try:
        from engine.broker_pool import get_broker_info
        return get_broker_info(username) or {}
    except Exception:
        return {}

def _get_user_capital(username):
    info = _get_user_broker_info(username)
    if info.get("connected"):
        return float(info.get("capital") or 0)
    return 0.0

def _get_user_broker_status(username):
    info = _get_user_broker_info(username)
    return "connected" if info.get("connected") else "not_connected"

def _get_user_broker_name(username):
    info = _get_user_broker_info(username)
    return info.get("user_name","")

@app.route("/api/v3/dashboard")
@require_auth
def dashboard():
    import sqlite3
    curr_username = get_current_user().get('username','')
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # Today stats
    cur.execute("""SELECT COUNT(*), COALESCE(SUM(pnl),0),
        SUM(CASE WHEN pnl>0 THEN 1 ELSE 0 END)
        FROM trades WHERE date(created_at)=date('now','localtime')
        AND status='CLOSED'
        AND (username=? OR (? = 'avinash' AND username IS NOT NULL))
    """, (curr_username, curr_username))
    r = cur.fetchone()
    today_trades = r[0] or 0
    today_pnl    = round(r[1] or 0, 2)
    today_wins   = r[2] or 0

    # All time
    cur.execute("""SELECT COUNT(*), COALESCE(SUM(pnl),0),
        SUM(CASE WHEN pnl>0 THEN 1 ELSE 0 END)
        FROM trades WHERE status='CLOSED'
        AND ABS(pnl)<100000
        AND (username=? OR (? = 'avinash' AND username IS NOT NULL))
    """, (curr_username, curr_username))
    r2 = cur.fetchone()
    all_trades = r2[0] or 0
    all_pnl    = round(r2[1] or 0, 2)
    all_wins   = r2[2] or 0

    # Open positions
    cur.execute("SELECT COUNT(*) FROM trades WHERE status='OPEN'")
    open_count = cur.fetchone()[0] or 0

    # Best strategy
    cur.execute("""SELECT strategy, SUM(pnl) as total FROM trades
        WHERE status='CLOSED' AND strategy IS NOT NULL
        GROUP BY strategy ORDER BY total DESC LIMIT 1""")
    bs = cur.fetchone()
    conn.close()

    win_rate = round(today_wins / today_trades * 100, 1) if today_trades > 0 else 0
    all_wr   = round(all_wins  / all_trades  * 100, 1) if all_trades  > 0 else 0

    return jsonify({
        "success":       True,
        "capital":       round(_get_user_capital(curr_username), 2),
        "broker_status": _get_user_broker_status(curr_username),
        "broker_name":   _get_user_broker_name(curr_username) or broker.user_name,
        "today_pnl":     today_pnl,
        "today_trades":  today_trades,
        "today_wins":    today_wins,
        "win_rate":      win_rate,
        "total_trades":  all_trades,
        "total_pnl":     all_pnl,
        "all_win_rate":  all_wr,
        "open_trades":   open_count,
        "best_strategy": {"name": bs[0], "pnl": round(bs[1],2)} if bs else None,
        "mode":          _get_user_mode(curr_username) if curr_username else "PAPER",
        "vix":           _get_vix(),
        "pcr":           1.0,
        "connected":     broker.connected,
    })

# ── Chain Signal API ───────────────────────────────────
@app.route("/api/v3/chain-signal", methods=["POST"])
@require_auth
def chain_signal_v3():
    data      = request.get_json() or {}
    symbol    = data.get("symbol", "NIFTY").upper()
    strike    = int(data.get("strike", 0))
    opt_type  = data.get("opt_type", "CE").upper()
    timeframe = data.get("timeframe", "5min")

    try:
        # Get chain data
        from engine.chain import get_chain
        chain_data = get_chain(broker, symbol)
        if not chain_data:
            return jsonify({"error": "Chain data not available"})

        spot = chain_data["spot"]
        atm  = chain_data["atm"]
        use_strike = strike if strike > 0 else atm

        # Find strike row
        selected = next((r for r in chain_data["chain"] if r["strike"] == use_strike), None)
        if not selected:
            return jsonify({"error": f"Strike {use_strike} not found"})

        opt_data = selected.get(opt_type.lower(), {})
        ltp      = opt_data.get("ltp", 0)
        if not ltp:
            return jsonify({"error": "LTP not available"})

        vix = _get_vix()
        pcr = chain_data.get("pcr", 1.0)

        # Fetch candles for ML + ATR
        candles, atr_val, ml_signal, ml_conf = [], 0, "NEUTRAL", 0
        token = opt_data.get("token", "")
        if token:
            try:
                from engine.candles import get_candles
                candles = get_candles(broker, token,
                    "MCX" if symbol in ("CRUDEOIL","NATURALGAS") else "NFO")
                if candles and len(candles) >= 14:
                    from engine.signals import atr as calc_atr
                    atr_val = calc_atr(candles)
                if candles and len(candles) >= 60:
                    from ai.ml_engine import build_features
                    feats = build_features(candles, vix=vix, pcr=pcr,
                                          iv=opt_data.get("iv",0)/100,
                                          delta=opt_data.get("delta",0.5))
                    if feats is not None:
                        ml_signal, ml_conf = ensemble.predict(feats)
            except Exception as e:
                logger.debug(f"Candle/ML: {e}")

        # Smart entry
        bid   = opt_data.get("bid", ltp)
        ask   = opt_data.get("ask", ltp)
        entry = round(round(((bid+ask)/2 if ask > bid else ltp) / 0.05) * 0.05, 2)

        # CE/PE bias score
        fii_bias = "NEUTRAL"
        fii_net  = 0
        try:
            from data.fii import get_fii_data
            fd = get_fii_data()
            fii_bias = fd.get("bias", "NEUTRAL")
            fii_net  = fd.get("fii_net", 0)
        except Exception:
            pass

        bias = 0
        if "BULL" in fii_bias:  bias += 20
        elif "BEAR" in fii_bias: bias -= 20
        if pcr < 0.7:   bias += 20
        elif pcr < 0.9: bias += 10
        elif pcr > 1.3: bias -= 20
        elif pcr > 1.1: bias -= 10
        if vix < 14:  bias += 10
        elif vix > 22: bias -= 15
        if ml_signal == "BUY":  bias += 15
        elif ml_signal == "SELL": bias -= 15

        bias     = max(-100, min(100, bias))
        ce_score = min(95, max(5, int(50 + bias/2)))
        pe_score = min(95, max(5, int(50 - bias/2)))

        # Recommendation
        if ce_score > pe_score + 15:
            recommendation = "🟢 BUY CE"
            rec_reason = f"CE favored (CE:{ce_score} vs PE:{pe_score})"
        elif pe_score > ce_score + 15:
            recommendation = "🔴 BUY PE"
            rec_reason = f"PE favored (PE:{pe_score} vs CE:{ce_score})"
        else:
            recommendation = "⚠️ NEUTRAL"
            rec_reason = f"No clear direction (CE:{ce_score} PE:{pe_score})"

        # Signal for selected opt_type
        score = ce_score if opt_type == "CE" else pe_score
        if score >= 70:  sm_signal = f"✅ BUY {opt_type}"
        elif score >= 55: sm_signal = f"⚠️ WEAK {opt_type}"
        else:            sm_signal = f"❌ AVOID {opt_type}"

        # ATR-based signals for all timeframes
        tf_map = config.TIMEFRAMES
        signals = {}
        for tf, params in tf_map.items():
            sl_pts  = round(atr_val * params["atr_sl"],  2) if atr_val else round(entry*0.08, 2)
            tgt_pts = round(atr_val * params["atr_tgt"], 2) if atr_val else round(entry*0.15, 2)
            sl      = round(round((entry - sl_pts)  / 0.05) * 0.05, 2)
            tgt     = round(round((entry + tgt_pts) / 0.05) * 0.05, 2)
            sl      = max(sl, round(entry * 0.5, 2))
            rr      = round(tgt_pts / sl_pts, 1) if sl_pts > 0 else 0
            signals[tf] = {
                "label":    params["label"],
                "max_hold": params["hold"],
                "entry":    entry,
                "target":   tgt,
                "sl":       sl,
                "target_pts": tgt_pts,
                "sl_pts":   sl_pts,
                "rr":       rr,
                "profitable": rr >= 1.5,
            }

        # Greeks
        greeks = {
            "iv":         opt_data.get("iv", 0),
            "delta":      opt_data.get("delta", 0),
            "gamma":      opt_data.get("gamma", 0),
            "theta":      opt_data.get("theta", 0),
            "vega":       opt_data.get("vega", 0),
            "theo_price": opt_data.get("theo_price", 0),
            "moneyness":  opt_data.get("moneyness", "ATM"),
        }

        return jsonify({
            "success":        True,
            "symbol":         symbol,
            "strike":         use_strike,
            "opt_type":       opt_type,
            "spot":           spot,
            "atm":            atm,
            "ltp":            ltp,
            "smart_entry":    entry,
            "atr":            atr_val,
            "expiry":         chain_data.get("expiry"),
            "recommendation": recommendation,
            "rec_reason":     rec_reason,
            "ce_score":       ce_score,
            "pe_score":       pe_score,
            "smart_money": {
                "signal":   sm_signal,
                "score":    score,
                "fii_net":  fii_net,
                "fii_bias": fii_bias,
                "pcr":      pcr,
                "vix":      vix,
                "reasons":  [],
            },
            "ml": {"signal": ml_signal, "confidence": ml_conf},
            "signals":        signals,
            "greeks":         greeks,
            "max_pain":       chain_data.get("max_pain", 0),
            "pcr":            pcr,
        })

    except Exception as e:
        import traceback
        logger.error(f"chain_signal: {e}\n{traceback.format_exc()}")
        return jsonify({"error": str(e)})

# ── Health API ─────────────────────────────────────────
@app.route("/api/v3/health")
def health():
    import psutil
    return jsonify({
        "success":    True,
        "cpu":        psutil.cpu_percent(interval=0.1),
        "memory":     psutil.virtual_memory().percent,
        "disk_free":  round(psutil.disk_usage('/').free / 1e9, 1),
        "uptime":     "running",
    })

# ── Index Page ─────────────────────────────────────────
@app.route("/")
@app.route("/v3")
@app.route("/v3/")
def index():
    # Reload tokens from file (persist across restarts)
    global _tokens
    _tokens = _load_tokens()
    # Token from URL
    token = request.args.get("t","")
    if token and token in _tokens:
        session.clear()
        session["user"] = _tokens[token]
        session.permanent = True
    logged_in = bool(session.get("user"))
    return render_template("index_v3.html", logged_in=logged_in,
                           user=session.get("user",{}),
                           login_error=request.args.get("login_error",""),
                           auth_token=token if logged_in else "")

# ── Helpers ────────────────────────────────────────────
_vix_cache = {"val": 18.0, "ts": 0}
def _get_vix():
    import time
    if time.time() - _vix_cache["ts"] < 300:  # 5 min cache
        return _vix_cache["val"]
    try:
        import requests
        r = requests.get("https://www.nseindia.com/api/allIndices", headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json",
        }, timeout=5)
        for idx in r.json().get("data", []):
            if idx.get("index") == "India VIX":
                _vix_cache.update({"val": float(idx["last"]), "ts": time.time()})
                return _vix_cache["val"]
    except Exception:
        pass
    return _vix_cache["val"]

if __name__ == "__main__":
    init_db()
    logger.info(f"🚀 Chanakya v3 starting on port {config.PORT}")
    app.run(host=config.HOST, port=config.PORT, debug=False)

# ── Market Summary API ─────────────────────────────────
@app.route("/api/v3/market")
@require_auth
def market_summary():
    from data.market import get_market_summary
    data = get_market_summary(broker if broker.connected else None)
    return jsonify({"success": True, **data})

# ── Signals API ────────────────────────────────────────
@app.route("/api/v3/signals")
@require_auth
def get_signals():
    import sqlite3
    limit = int(request.args.get("limit", 20))
    conn  = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    rows  = conn.execute("""
        SELECT * FROM signals
        ORDER BY created_at DESC LIMIT ?
    """, (limit,)).fetchall()
    conn.close()
    return jsonify({"success": True, "signals": [dict(r) for r in rows]})

# ── Trades API ─────────────────────────────────────────
@app.route("/api/v3/trades")
@require_auth
def get_trades():
    import sqlite3
    status = request.args.get("status", "ALL")
    limit  = int(request.args.get("limit", 50))
    conn   = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    if status == "TODAY":
        rows = conn.execute("""SELECT * FROM trades
            WHERE date(created_at)=date('now','localtime')
            ORDER BY created_at DESC LIMIT ?""", (limit,)).fetchall()
    elif status == "OPEN":
        rows = conn.execute("""SELECT * FROM trades
            WHERE status='OPEN' ORDER BY created_at DESC""").fetchall()
    else:
        rows = conn.execute("""SELECT * FROM trades
            ORDER BY created_at DESC LIMIT ?""", (limit,)).fetchall()
    conn.close()
    trades = [dict(r) for r in rows]
    return jsonify({"success": True, "trades": trades, "count": len(trades)})

# ── Positions API ──────────────────────────────────────
@app.route("/api/v3/positions")
@require_auth
def get_positions():
    import sqlite3
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT * FROM trades WHERE status='OPEN' ORDER BY created_at DESC"
    ).fetchall()
    conn.close()
    return jsonify({"success": True, "positions": [dict(r) for r in rows]})

# ── Force Scan API ─────────────────────────────────────
@app.route("/api/v3/scan", methods=["POST"])
@require_auth
def force_scan():
    try:
        from engine.scanner import SignalScanner
        scanner = SignalScanner(broker)
        signals = scanner.scan_all()
        return jsonify({
            "success": True,
            "signals": len(signals),
            "data":    signals
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

# ── Analytics API ──────────────────────────────────────
@app.route("/api/v3/analytics")
@require_auth
def analytics():
    import sqlite3
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row

    # Overall stats
    r = conn.execute("""
        SELECT COUNT(*) t, COALESCE(SUM(pnl),0) pnl,
               SUM(CASE WHEN pnl>0 THEN 1 ELSE 0 END) wins,
               AVG(CASE WHEN pnl>0 THEN pnl END) avg_win,
               AVG(CASE WHEN pnl<0 THEN pnl END) avg_loss,
               MAX(pnl) best, MIN(pnl) worst
        FROM trades WHERE status='CLOSED'
    """).fetchone()

    # Strategy breakdown
    strats = conn.execute("""
        SELECT strategy, COUNT(*) t, SUM(pnl) pnl,
               SUM(CASE WHEN pnl>0 THEN 1 ELSE 0 END) wins
        FROM trades WHERE status='CLOSED' AND strategy IS NOT NULL
        GROUP BY strategy ORDER BY pnl DESC
    """).fetchall()

    # Daily P&L (30 days)
    daily = conn.execute("""
        SELECT date(created_at) dt, SUM(pnl) pnl, COUNT(*) trades
        FROM trades WHERE status='CLOSED'
        AND created_at >= date('now','-30 days')
        GROUP BY date(created_at) ORDER BY dt
    """).fetchall()

    conn.close()
    t = r["t"] or 1
    return jsonify({
        "success":      True,
        "total_trades": r["t"],
        "total_pnl":    round(r["pnl"] or 0, 2),
        "wins":         r["wins"] or 0,
        "losses":       (r["t"] or 0) - (r["wins"] or 0),
        "win_rate":     round((r["wins"] or 0) / t * 100, 1),
        "avg_win":      round(r["avg_win"] or 0, 2),
        "avg_loss":     round(r["avg_loss"] or 0, 2),
        "best_trade":   round(r["best"] or 0, 2),
        "worst_trade":  round(r["worst"] or 0, 2),
        "profit_factor": round(abs((r["avg_win"] or 0) / (r["avg_loss"] or -1)), 2),
        "strategies":   [dict(s) for s in strats],
        "daily_pnl":    [dict(d) for d in daily],
    })

# ── Switch Mode API ────────────────────────────────────
@app.route("/api/v3/switch-mode", methods=["POST"])
@require_auth
def switch_mode():
    data = request.get_json() or {}
    mode = data.get("mode", "PAPER").upper()
    confirmed = data.get("confirmed", False)

    if mode not in ("PAPER", "LIVE"):
        return jsonify({"success": False, "error": "Invalid mode"})

    # Check role — only premium/admin can go LIVE
    curr_user = get_current_user()
    username  = curr_user.get("username","")
    from data.users import get_user_role, get_broker_credentials
    role = get_user_role(username)

    if mode == "LIVE":
        if role not in ("admin","premium"):
            return jsonify({
                "success": False,
                "error": "🔒 Upgrade to Premium to enable Live trading"
            })
        # Check broker connected
        creds = get_broker_credentials(username)
        if not creds or not creds.get("connected") or not creds.get("api_key"):
            return jsonify({
                "success": False,
                "error": "⚠️ Connect your broker first in Settings → Broker Connect"
            })
        # Confirmation required
        if not confirmed:
            return jsonify({
                "success": False,
                "confirm": True,
                "message": "Switch to LIVE trading? User: " + username + " Broker: Angel One (" + creds.get("client_id","") + ") Real money will be used! Confirm to proceed."
            })

    # Per-user mode save
    _set_user_mode(username, mode)
    # Admin switches global
    if username == "avinash":
        config.PAPER_MODE = (mode == "PAPER")
    logger.info(f"🔄 Mode: {username} -> {mode}")


    # Telegram alert
    try:
        from engine.telegram import telegram
        mode_txt = "LIVE TRADING ACTIVE" if mode=="LIVE" else "Paper mode"
        telegram.system_alert(
            "Mode Switch! User: " + username + " Mode: " + mode + " " + mode_txt,
            "WARNING" if mode=="LIVE" else "SUCCESS"
        )
    except Exception:
        pass


    return jsonify({"success": True, "mode": mode, "username": username})

# ── WebSocket Real-time ────────────────────────────────
from flask_socketio import SocketIO, emit

socketio = SocketIO(app,
    cors_allowed_origins=["https://bramha.cloud","http://localhost:3001"],
    async_mode="threading"
)

@socketio.on("connect")
def on_connect():
    if not session.get("user"):
        return False  # Reject unauthenticated
    logger.info(f"WS connected: {session.get('user',{}).get('username')}")
    emit("status", {"connected": True, "version": config.VERSION})

@socketio.on("disconnect")
def on_disconnect():
    logger.debug("WS disconnected")

@socketio.on("subscribe")
def on_subscribe(data):
    """Client subscribes to live updates"""
    symbols = data.get("symbols", [])
    emit("subscribed", {"symbols": symbols})

def emit_trade_update(trade_data):
    """Emit trade update to all connected clients"""
    try:
        socketio.emit("trade_update", trade_data)
    except Exception:
        pass

def emit_signal(signal_data):
    """Emit new signal to all clients"""
    try:
        socketio.emit("new_signal", signal_data)
    except Exception:
        pass

def emit_pnl_update(pnl, trades, wins):
    """Emit live P&L update"""
    try:
        socketio.emit("pnl_update", {
            "pnl": pnl, "trades": trades, "wins": wins,
            "win_rate": round(wins/trades*100,1) if trades > 0 else 0
        })
    except Exception:
        pass

# ── Square-off API ─────────────────────────────────────
@app.route("/api/v3/squareoff", methods=["POST"])
@require_auth
def squareoff():
    data     = request.get_json() or {}
    trade_id = data.get("trade_id")
    sq_all   = data.get("all", False)
    try:
        from engine.order import OrderEngine
        oe = OrderEngine(broker)
        if sq_all:
            from engine.squareoff import SquareOffEngine
            sq = SquareOffEngine(broker, oe)
            count = sq.manual_squareoff_all()
            return jsonify({"success": True, "closed": count})
        elif trade_id:
            # Get current LTP
            import sqlite3
            conn = sqlite3.connect(config.DB_PATH)
            conn.row_factory = sqlite3.Row
            trade = conn.execute(
                "SELECT * FROM trades WHERE id=?", (trade_id,)
            ).fetchone()
            conn.close()
            if not trade:
                return jsonify({"success": False, "error": "Trade not found"})
            ltp = broker.get_ltp(
                trade["exchange"] or "NFO",
                trade["trading_symbol"] or trade["symbol"],
                trade["token"] or ""
            ) or trade["entry_price"]
            ok, result = oe.place_exit(trade_id, ltp, "MANUAL_EXIT")
            return jsonify({"success": ok, "result": result})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

# ── ML Retrain API ─────────────────────────────────────
@app.route("/api/v3/ml/retrain", methods=["POST"])
@require_auth
def ml_retrain_v3():
    try:
        import sqlite3, numpy as np
        conn = sqlite3.connect(config.DB_PATH)
        conn.row_factory = sqlite3.Row
        trades = conn.execute("""
            SELECT * FROM trades WHERE status='CLOSED'
            AND pnl IS NOT NULL AND entry_price > 0
        """).fetchall()
        conn.close()

        X, y = [], []
        for t in trades:
            try:
                entry  = float(t["entry_price"] or 1)
                sl     = float(t["sl_price"] or 0)
                tgt    = float(t["target_price"] or 0)
                sl_d   = (entry-sl)/entry   if sl  > 0 else 0.05
                tgt_d  = (tgt-entry)/entry  if tgt > 0 else 0.10
                rr     = tgt_d/sl_d         if sl_d > 0 else 1.5
                opt_ce = 1 if (t["opt_type"] or "CE")=="CE" else 0
                nse    = 1 if (t["exchange"] or "NFO") in ("NFO","NSE") else 0
                strat  = (t["strategy"] or "").upper()
                sym    = (t["symbol"] or "").upper()
                from datetime import datetime
                dt   = datetime.strptime(t["created_at"][:19],"%Y-%m-%d %H:%M:%S")
                feat = [sl_d, tgt_d, min(rr,5), opt_ce, nse,
                        1 if "SCALP" in strat else 0,
                        1 if "MCX" in strat else 0,
                        1 if "NIFTY" in sym and "BANK" not in sym else 0,
                        1 if "BANK" in sym else 0,
                        1 if "CRUDE" in sym else 0,
                        1 if "NATURAL" in sym else 0,
                        (dt.hour-9)/7, dt.weekday()/4,
                        float(t["lots"] or 1)/10,
                        entry/1000]
                X.append(feat); y.append(1 if (t["pnl"] or 0)>0 else 0)
            except Exception:
                pass

        if len(X) < 50:
            return jsonify({"success": False, "error": f"Too few samples: {len(X)}"})

        from ai.ml_engine import ChanakayaBrain
        model = ChanakayaBrain()
        # Use new train_from_db with full 42 features
        acc = model.train_from_db(config.DB_PATH)
        if acc > 0:
            from ai import ml_engine
            ml_engine.ensemble = model
            ml_engine._brain   = model
            return jsonify({
                "success":  True,
                "accuracy": round(acc*100, 1),
                "samples":  model.n_samples,
            })
        # Fallback — old 15-feature training
        if len(X) >= 30:
            ok = model.train(np.array(X), np.array(y))
            if ok:
                from ai import ml_engine
                ml_engine.ensemble = model
                ml_engine._brain   = model
                return jsonify({
                    "success":  True,
                    "accuracy": round(model.accuracy*100, 1),
                    "samples":  model.n_samples,
                })
        return jsonify({"success": False, "error": "Training failed — need more data"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

# ── Squareoff Times API ────────────────────────────────
@app.route("/api/v3/squareoff/times")
@require_auth
def squareoff_times():
    from engine.squareoff import SquareOffEngine
    from engine.order import OrderEngine
    sq = SquareOffEngine(broker, OrderEngine(broker))
    return jsonify({"success": True, "times": sq.get_squareoff_times()})

# ── Backup APIs ────────────────────────────────────────
@app.route("/api/v3/backup", methods=["POST"])
@require_auth
def manual_backup():
    from data.backup import backup_now
    result = backup_now()
    return jsonify(result)

@app.route("/api/v3/backup/list")
@require_auth
def list_backups():
    from data.backup import list_backups
    return jsonify({"success": True, "backups": list_backups()})

@app.route("/api/v3/backup/restore", methods=["POST"])
@require_auth
def restore_backup():
    data = request.get_json() or {}
    path = data.get("path", "")
    if not path:
        return jsonify({"success": False, "error": "path required"})
    from data.backup import restore_backup
    ok, msg = restore_backup(path)
    return jsonify({"success": ok, "message": msg})

# ── Backtest APIs ──────────────────────────────────────
@app.route("/api/v3/backtest/db", methods=["POST"])
@require_auth
def backtest_db():
    """Type 1: DB Trade Analysis — instant results"""
    data     = request.get_json() or {}
    days     = int(data.get("days", 90))
    symbol   = data.get("symbol")
    strategy = data.get("strategy")
    try:
        from engine.backtest import DBAnalyzer
        analyzer = DBAnalyzer()
        result   = analyzer.run(days=days, symbol=symbol, strategy=strategy)
        return jsonify({"success": True, **result})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

@app.route("/api/v3/backtest/replay", methods=["POST"])
@require_auth
def backtest_replay():
    """Type 2: Signal Replay on Historical Candles"""
    data      = request.get_json() or {}
    symbol    = data.get("symbol", "NIFTY")
    opt_type  = data.get("opt_type", "CE")
    days_back = int(data.get("days", 30))
    timeframe = data.get("timeframe", "FIVE_MINUTE")
    try:
        from engine.backtest import SignalReplay
        replay = SignalReplay(broker)
        result = replay.run(
            symbol=symbol, opt_type=opt_type,
            days_back=days_back, timeframe=timeframe
        )
        return jsonify({"success": True, **result})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

# ── Tickers API ────────────────────────────────────────
@app.route("/api/v3/tickers")
def tickers_v3():
    """Live ticker prices — no auth required for topbar"""
    try:
        from config import config
        result = {}
        symbols = {
            "NIFTY":     {"token": "99926000", "exch": "NSE"},
            "BANKNIFTY": {"token": "99926009", "exch": "NSE"},
            "FINNIFTY":  {"token": "99926037", "exch": "NSE"},
        }
        for sym, info in symbols.items():
            try:
                ltp = broker.get_ltp(info["exch"], sym, info["token"])
                result[sym] = {"ltp": ltp, "change_pct": 0}
            except Exception:
                result[sym] = {"ltp": 0, "change_pct": 0}
        # MCX spot prices
        try:
            from angel_live_chain_v3 import load_instruments
            instr = load_instruments()
            mcx_map = {
                "CRUDEOIL":   "CRUDEOIL",
                "NATURALGAS": "NATURALGAS",
            }
            for sym, name in mcx_map.items():
                fut = next((i for i in instr
                    if i.get("name","").upper()==name and
                    i.get("exch_seg")=="MCX" and
                    i.get("instrumenttype")=="FUTCOM"), None)
                if fut:
                    ltp = broker.get_ltp("MCX", fut["symbol"], fut["token"])
                    result[sym] = {"ltp": ltp or 0, "change_pct": 0}
        except Exception as _me:
            pass
        # VIX
        from data.market import get_vix
        result["VIX"] = {"ltp": get_vix(), "change_pct": 0}
        return jsonify({"success": True, **result})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

# ── User Management APIs ───────────────────────────────

# Initialize users DB on startup
from data.users import init_users_db
init_users_db()

def get_current_user():
    """Get current logged in user details"""
    token = (request.headers.get("X-Auth-Token") or
             request.args.get("t",""))
    if token and token in _tokens:
        return _tokens[token]
    return session.get("user", {})

def check_subscription(f):
    """Decorator — check trial/subscription status"""
    from functools import wraps
    @wraps(f)
    def wrapper(*args, **kwargs):
        user = get_current_user()
        if not user:
            return jsonify({"success": False, "error": "Unauthorized"}), 401
        username = user.get("username","")
        from data.users import get_user_role, get_trial_status
        role = get_user_role(username)
        if role == "expired":
            return jsonify({
                "success":  False,
                "error":    "trial_expired",
                "message":  "🔴 Your 15-day free trial has expired!",
                "upgrade":  "Pay ₹3,000/month to continue",
                "upi_id":   "chanakya@upi",
                "contact":  "Contact admin to upgrade"
            }), 403
        return f(*args, **kwargs)
    return wrapper

@app.route("/api/v3/user/status")
@require_auth
def user_status():
    user = get_current_user()
    username = user.get("username","")
    from data.users import get_user, get_user_role, get_trial_status, get_trade_limit, check_trade_allowed
    u = get_user(username)
    if not u:
        return jsonify({"success": False, "error": "User not found"})
    role = get_user_role(username)
    trial_days = get_trial_status(username)
    limit = get_trade_limit(role)
    can_trade, trade_msg = check_trade_allowed(username)

    # Subscription message
    sub_msg = None
    if role == "viewer" and trial_days is not None:
        if trial_days <= 3:
            sub_msg = f"⚠️ Only {trial_days} days left! Upgrade to Premium ₹3,000/month"
        elif trial_days <= 7:
            sub_msg = f"📅 {trial_days} days remaining in trial"
    elif role == "expired":
        sub_msg = "🔴 Trial expired! Pay ₹3,000 to continue"

    return jsonify({
        "success":      True,
        "username":     username,
        "role":         role,
        "trial_days":   trial_days,
        "trade_limit":  limit,
        "can_trade":    can_trade,
        "trade_msg":    trade_msg,
        "sub_message":  sub_msg,
        "premium_expiry": u.get("premium_expiry"),
        "upi_id":       "chanakya@upi",
        "price":        3000,
    })

@app.route("/api/v3/user/register", methods=["POST"])
@require_auth
def register_user():
    """Admin only — register new user"""
    user = get_current_user()
    if user.get("role") != "admin":
        return jsonify({"success": False, "error": "Admin only"}), 403
    data = request.get_json() or {}
    username = data.get("username","").strip()
    password = data.get("password","").strip()
    role     = data.get("role","viewer")
    if not username or not password:
        return jsonify({"success": False, "error": "Username/password required"})
    from data.users import register_user as reg
    ok, msg = reg(username, password, role)
    # Send Telegram welcome
    if ok:
        from engine.telegram import telegram
        telegram.system_alert(
            f"🆕 New user registered!\n"
            f"👤 Username: {username}\n"
            f"🎭 Role: {role}\n"
            f"🎁 15-day free trial started!",
            "SUCCESS"
        )
    return jsonify({"success": ok, "message": msg})

@app.route("/api/v3/user/payment", methods=["POST"])
@require_auth
def submit_payment():
    """User submits UTR for payment verification"""
    user = get_current_user()
    username = user.get("username","")
    data = request.get_json() or {}
    utr = data.get("utr","").strip()
    if not utr or len(utr) < 10:
        return jsonify({"success": False, "error": "Valid UTR required (min 10 digits)"})
    from data.users import create_payment_request, get_user
    u = get_user(username)
    payment_id = create_payment_request(username, utr)

    # Alert admin on Telegram
    from engine.telegram import telegram
    telegram.system_alert(
        f"💰 NEW PAYMENT REQUEST!\n"
        f"━━━━━━━━━━━━━━━\n"
        f"👤 User: {username}\n"
        f"🔢 UTR: {utr}\n"
        f"💵 Amount: ₹3,000\n"
        f"🆔 Payment ID: {payment_id}\n\n"
        f"To verify, run:\n"
        f"/verify {payment_id}",
        "INFO"
    )
    return jsonify({
        "success":    True,
        "message":    "Payment submitted! Admin will verify within 2 hours.",
        "payment_id": payment_id,
    })

@app.route("/api/v3/admin/verify-payment", methods=["POST"])
@require_auth
def verify_payment():
    """Admin verifies payment → upgrade user"""
    user = get_current_user()
    if user.get("role") != "admin":
        return jsonify({"success": False, "error": "Admin only"}), 403
    data = request.get_json() or {}
    payment_id = data.get("payment_id")
    if not payment_id:
        return jsonify({"success": False, "error": "payment_id required"})
    from data.users import verify_payment as vp
    ok, msg = vp(payment_id, verified_by=user.get("username","admin"))
    if ok:
        from engine.telegram import telegram
        telegram.system_alert(f"✅ Payment #{payment_id} verified!\n{msg}", "SUCCESS")
    return jsonify({"success": ok, "message": msg})

@app.route("/api/v3/admin/users")
@require_auth
def list_users():
    """Admin — list all users"""
    user = get_current_user()
    if user.get("role") != "admin":
        return jsonify({"success": False, "error": "Admin only"}), 403
    from data.users import get_all_users, get_user_role, get_trial_status
    users = get_all_users()
    for u in users:
        u["effective_role"] = get_user_role(u["username"])
        u["trial_days_left"] = get_trial_status(u["username"])
        # Hide sensitive data
        u.pop("password_hash", None)
        u.pop("angel_password", None)
        u.pop("angel_totp_key", None)
    return jsonify({"success": True, "users": users})

@app.route("/api/v3/admin/payments")
@require_auth
def list_payments():
    """Admin — pending payments"""
    user = get_current_user()
    if user.get("role") != "admin":
        return jsonify({"success": False, "error": "Admin only"}), 403
    from data.users import get_pending_payments
    return jsonify({"success": True, "payments": get_pending_payments()})

# ── Registration + OTP APIs ────────────────────────────

@app.route("/api/v3/register/send-otp", methods=["POST"])
def register_send_otp():
    """Step 1 — Send OTP to email or telegram"""
    data       = request.get_json() or {}
    username   = data.get("username","").strip()
    contact    = data.get("contact","").strip()  # email or telegram_id
    password   = data.get("password","").strip()

    if not username or not contact or not password:
        return jsonify({"success":False,"error":"All fields required"})
    if len(password) < 6:
        return jsonify({"success":False,"error":"Password min 6 characters"})

    # Check username taken
    from data.users import get_user
    if get_user(username):
        return jsonify({"success":False,"error":"Username already taken"})

    # Send OTP
    from data.otp import send_otp
    ok, msg, channel = send_otp(contact, purpose="verify")

    if ok:
        # Store temp registration data in session
        session["reg_pending"] = {
            "username": username,
            "password": password,
            "contact":  contact,
            "channel":  channel,
        }
        return jsonify({
            "success": True,
            "channel": channel,
            "message": msg,
            "hint":    f"OTP sent via {channel}"
        })
    return jsonify({"success":False,"error":msg})

@app.route("/api/v3/register/verify-otp", methods=["POST"])
def register_verify_otp():
    """Step 2 — Verify OTP and complete registration"""
    data      = request.get_json() or {}
    otp_input = data.get("otp","").strip()
    eula_accepted = data.get("eula_accepted", False)

    if not eula_accepted:
        return jsonify({"success":False,"error":"Please accept the User Agreement"})

    reg = session.get("reg_pending")
    if not reg:
        return jsonify({"success":False,"error":"Session expired — start registration again"})

    from data.otp import verify_otp
    ok, msg = verify_otp(reg["contact"], otp_input, purpose="verify")

    if not ok:
        return jsonify({"success":False,"error":msg})

    # Create user
    from data.users import register_user
    ok2, msg2 = register_user(reg["username"], reg["password"], role="viewer")
    if not ok2:
        return jsonify({"success":False,"error":msg2})

    # Update contact info
    import sqlite3
    conn = sqlite3.connect("data/users.db")
    if "@" in reg["contact"]:
        conn.execute("UPDATE users SET upi_name=? WHERE username=?",
                     (reg["contact"], reg["username"]))
    else:
        conn.execute("UPDATE users SET telegram_id=? WHERE username=?",
                     (reg["contact"], reg["username"]))
    conn.commit()
    conn.close()

    session.pop("reg_pending", None)

    # Welcome telegram + email
    from engine.telegram import telegram
    telegram.system_alert(
        f"🎉 New user registered!\n"
        f"👤 {reg['username']}\n"
        f"📱 {reg['contact']}\n"
        f"🎁 15-day free trial started!",
        "SUCCESS"
    )

    return jsonify({
        "success": True,
        "message": "Registration complete! 15-day free trial started.",
        "username": reg["username"],
    })

@app.route("/api/v3/password/send-otp", methods=["POST"])
def password_reset_otp():
    """Send OTP for password reset"""
    data    = request.get_json() or {}
    contact = data.get("contact","").strip()
    if not contact:
        return jsonify({"success":False,"error":"Email or Telegram ID required"})
    from data.otp import send_otp
    ok, msg, channel = send_otp(contact, purpose="reset")
    return jsonify({"success":ok,"message":msg,"channel":channel})

@app.route("/api/v3/password/reset", methods=["POST"])
def password_reset():
    """Reset password with OTP"""
    data        = request.get_json() or {}
    contact     = data.get("contact","").strip()
    otp_input   = data.get("otp","").strip()
    new_password = data.get("new_password","").strip()

    if len(new_password) < 6:
        return jsonify({"success":False,"error":"Password min 6 characters"})

    from data.otp import verify_otp
    ok, msg = verify_otp(contact, otp_input, purpose="reset")
    if not ok:
        return jsonify({"success":False,"error":msg})

    # Update password
    import sqlite3
    from data.users import hash_password
    conn = sqlite3.connect("data/users.db")
    field = "upi_name" if "@" in contact else "telegram_id"
    conn.execute(
        f"UPDATE users SET password_hash=? WHERE {field}=?",
        (hash_password(new_password), contact)
    )
    conn.commit()
    conn.close()
    return jsonify({"success":True,"message":"Password updated successfully"})

@app.route("/api/v3/plans")
def get_plans():
    """Get subscription plans — no auth needed"""
    from data.eula import get_all_plans
    return jsonify({"success":True,"plans":get_all_plans()})

@app.route("/api/v3/eula")
def get_eula():
    """Get EULA text — no auth needed"""
    from data.eula import EULA_TEXT
    return jsonify({"success":True,"eula":EULA_TEXT})

@app.route("/api/v3/user/payment/plan", methods=["POST"])
@require_auth
def submit_payment_with_plan():
    """Submit payment with plan selection"""
    user = get_current_user()
    username = user.get("username","")
    data     = request.get_json() or {}
    utr      = data.get("utr","").strip()
    plan_key = data.get("plan","monthly")

    if not utr or len(utr) < 10:
        return jsonify({"success":False,"error":"Valid UTR required"})

    from data.eula import get_plan
    plan = get_plan(plan_key)
    if not plan:
        return jsonify({"success":False,"error":"Invalid plan"})

    from data.users import create_payment_request
    payment_id = create_payment_request(username, utr)

    # Alert admin
    from engine.telegram import telegram
    telegram.system_alert(
        f"💰 PAYMENT REQUEST\n"
        f"━━━━━━━━━━━━━━━\n"
        f"👤 User: {username}\n"
        f"📦 Plan: {plan['label']}\n"
        f"💵 Amount: ₹{plan['price']:,}\n"
        f"📅 Duration: {plan['days']} days\n"
        f"🔢 UTR: {utr}\n"
        f"🆔 Payment ID: #{payment_id}\n\n"
        f"Verify: /api/v3/admin/verify-payment\n"
        f"Body: {{\"payment_id\":{payment_id},\"plan\":\"{plan_key}\"}}",
        "INFO"
    )
    return jsonify({
        "success":    True,
        "payment_id": payment_id,
        "plan":       plan["label"],
        "amount":     plan["price"],
        "message":    f"Payment submitted! Admin will verify within 2 hours.",
    })

# ── Broker Management APIs ─────────────────────────────

SUPPORTED_BROKERS = {
    "angelone": {
        "name":    "Angel One (SmartAPI)",
        "fields":  ["api_key","client_id","password","totp_key"],
        "labels":  ["API Key","Client ID","Password","TOTP Secret"],
        "help_url": "https://smartapi.angelbroking.com",
        "help": [
            "1. Login to angelbroking.com",
            "2. Go to My Profile → API Key",
            "3. Generate new API key",
            "4. Client ID = your Angel One login ID",
            "5. Password = your Angel One login password",
            "6. TOTP = scan QR in app settings → get secret key",
        ],
        "available": True,
    },
    "zerodha": {
        "name":    "Zerodha (KiteConnect)",
        "fields":  ["api_key","api_secret","client_id"],
        "labels":  ["API Key","API Secret","Client ID (UserID)"],
        "help_url": "https://kite.trade",
        "help": [
            "1. Login to kite.trade/connect",
            "2. Create new app",
            "3. Get API key and API secret",
            "4. Client ID = your Zerodha UserID",
        ],
        "available": False,  # Coming soon
    },
    "upstox": {
        "name":    "Upstox (APIv2)",
        "fields":  ["api_key","api_secret","redirect_uri"],
        "labels":  ["API Key","API Secret","Redirect URI"],
        "help_url": "https://developer.upstox.com",
        "help": [
            "1. Login to developer.upstox.com",
            "2. Create new app",
            "3. Get API key and secret",
        ],
        "available": False,  # Coming soon
    },
    "fyers": {
        "name":    "Fyers API",
        "fields":  ["app_id","secret_key","client_id"],
        "labels":  ["App ID","Secret Key","Client ID"],
        "help_url": "https://myapi.fyers.in",
        "help": ["1. Login to myapi.fyers.in", "2. Create new app"],
        "available": False,
    },
    "paper": {
        "name":    "Paper Trading (No Broker)",
        "fields":  [],
        "labels":  [],
        "help": ["No real money — simulated trading only"],
        "available": True,
    },
}

@app.route("/api/v3/brokers")
def get_brokers():
    """List supported brokers — no auth needed"""
    return jsonify({"success": True, "brokers": SUPPORTED_BROKERS})

@app.route("/api/v3/user/broker", methods=["GET"])
@require_auth
def get_user_broker():
    """Get current user's broker details"""
    user = get_current_user()
    username = user.get("username","")
    import sqlite3 as sq
    conn = sq.connect("data/users.db")
    conn.row_factory = sq.Row
    u = conn.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
    conn.close()
    if not u:
        return jsonify({"success":False,"error":"User not found"})
    broker = u["broker_name"] or "angelone"
    has_creds = bool(u["angel_api_key"])
    return jsonify({
        "success":        True,
        "broker":         broker,
        "connected":      bool(u["broker_connected"]),
        "has_credentials": has_creds,
        "last_sync":      u["broker_last_sync"],
        "broker_info":    SUPPORTED_BROKERS.get(broker,{}),
    })

@app.route("/api/v3/user/broker/save", methods=["POST"])
@require_auth
def save_broker_credentials():
    """Save user's broker API credentials"""
    user     = get_current_user()
    username = user.get("username","")
    data     = request.get_json() or {}
    broker   = data.get("broker","angelone")
    role     = get_session().get("role") or "viewer"

    # Only admin + premium can connect broker
    from data.users import get_user_role
    eff_role = get_user_role(username)
    if eff_role not in ("admin","premium"):
        return jsonify({"success":False,"error":"Upgrade to Premium to connect broker"})

    import sqlite3 as sq
    conn = sq.connect("data/users.db")
    now  = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S")

    if broker == "angelone":
        api_key   = data.get("api_key","").strip()
        client_id = data.get("client_id","").strip()
        password  = data.get("password","").strip()
        totp_key  = data.get("totp_key","").strip()

        if not all([api_key, client_id, password, totp_key]):
            conn.close()
            return jsonify({"success":False,"error":"All Angel One fields required"})

        # Test connection
        try:
            import pyotp
            from SmartApi import SmartConnect
            api = SmartConnect(api_key=api_key)
            totp = pyotp.TOTP(totp_key).now()
            resp = api.generateSession(client_id, password, totp)
            if not resp.get("status"):
                conn.close()
                return jsonify({"success":False,"error":"Invalid credentials: "+resp.get("message","")})
            user_name = resp.get("data",{}).get("name","")

            # Save encrypted (basic)
            conn.execute("""
                UPDATE users SET
                    angel_api_key=?, angel_client_id=?,
                    angel_password=?, angel_totp_key=?,
                    broker_name='angelone', broker_connected=1,
                    broker_last_sync=?
                WHERE username=?
            """, (api_key, client_id, password, totp_key, now, username))
            conn.commit()
            conn.close()

            logger.info(f"✅ Broker connected: {username} → {user_name}")
            return jsonify({
                "success":   True,
                "message":   f"✅ Connected as {user_name}",
                "broker":    "angelone",
                "user_name": user_name,
            })
        except Exception as e:
            conn.close()
            return jsonify({"success":False,"error":f"Connection failed: {str(e)}"})

    elif broker == "paper":
        conn.execute("""
            UPDATE users SET broker_name='paper', broker_connected=1,
            broker_last_sync=? WHERE username=?
        """, (now, username))
        conn.commit()
        conn.close()
        return jsonify({"success":True,"message":"Paper trading mode enabled"})
    else:
        conn.close()
        return jsonify({"success":False,"error":f"{broker} coming soon!"})

@app.route("/api/v3/user/broker/disconnect", methods=["POST"])
@require_auth
def disconnect_broker():
    user = get_current_user()
    import sqlite3 as sq
    conn = sq.connect("data/users.db")
    conn.execute("""
        UPDATE users SET broker_connected=0,
        angel_api_key=NULL, angel_client_id=NULL,
        angel_password=NULL, angel_totp_key=NULL
        WHERE username=?
    """, (user.get("username",""),))
    conn.commit()
    conn.close()
    return jsonify({"success":True,"message":"Broker disconnected"})

# ── CPU Cache (non-blocking) ───────────────────────────
import psutil as _psutil
_cpu_cache = {"val": 0.0}
def _cpu_updater():
    import time
    while True:
        try: _cpu_cache["val"] = _psutil.cpu_percent(interval=2)
        except: pass
        time.sleep(3)
import threading as _thr
_thr.Thread(target=_cpu_updater, daemon=True).start()

@app.route("/api/v3/strategies")
def get_strategies():
    """List all strategies + their performance"""
    try:
        from engine.strategies import ALL_STRATEGIES
        from engine.backtest import strategy_performance_summary
        perf = {p["strategy"]:p for p in strategy_performance_summary()}
        result = []
        for s in ALL_STRATEGIES:
            p = perf.get(s.name, {})
            result.append({
                "name":       s.name,
                "min_candles":s.min_candles,
                "trades":     p.get("trades",0),
                "win_rate":   p.get("win_rate",0),
                "total_pnl":  p.get("total_pnl",0),
                "avg_pnl":    p.get("avg_pnl",0),
            })
        return jsonify({"success":True, "strategies":result,
                       "total": len(result)})
    except Exception as e:
        return jsonify({"success":False,"error":str(e)})

# ── Admin System Monitor ────────────────────────────────
@app.route("/v3/admin")
def admin_panel():
    # Auth handled by JS in admin_v3.html
    return render_template("admin_v3.html")



@app.route("/api/v3/admin/create-user", methods=["POST"])
@require_auth
def admin_create_user():
    user = get_current_user()
    if user.get("role") != "admin":
        return jsonify({"success": False, "error": "Admin only"}), 403
    data = request.get_json() or {}
    username = data.get("username","").strip().lower()
    password = data.get("password","").strip()
    role     = data.get("role","viewer")
    if not username or not password:
        return jsonify({"success": False, "error": "Username and password required"})
    if len(password) < 4:
        return jsonify({"success": False, "error": "Password min 4 chars"})
    try:
        import sqlite3 as sq2, hashlib as hs
        pw_hash = hs.sha256(password.encode()).hexdigest()
        conn2 = sq2.connect("data/users.db")
        ex = conn2.execute("SELECT username FROM users WHERE username=?", (username,)).fetchone()
        if ex:
            conn2.close()
            return jsonify({"success": False, "error": "User already exists"})
        conn2.execute(
            "INSERT INTO users (username,password_hash,role,broker_name,broker_connected,active) VALUES (?,?,?,'paper',0,1)",
            (username, pw_hash, role)
        )
        conn2.commit()
        conn2.close()
        logger.info(f"Admin created user: {username} role={role}")
        return jsonify({"success": True, "message": f"User {username} created"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

@app.route("/api/v3/admin/delete-user", methods=["POST"])
@require_auth
def admin_delete_user():
    user = get_current_user()
    if user.get("role") != "admin":
        return jsonify({"success": False, "error": "Admin only"}), 403
    data = request.get_json() or {}
    username = data.get("username","").strip()
    if not username:
        return jsonify({"success": False, "error": "username required"})
    if username == "avinash":
        return jsonify({"success": False, "error": "Cannot delete admin"})
    try:
        import sqlite3 as sq
        conn = sq.connect("data/users.db")
        conn.execute("DELETE FROM users WHERE username=?", (username,))
        conn.commit()
        conn.close()
        logger.info(f"Admin deleted user: {username}")
        return jsonify({"success": True, "message": f"User {username} deleted"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

@app.route("/api/v3/admin/reset-pnl", methods=["POST"])
@require_auth
def reset_user_pnl():
    user = get_current_user()
    if user.get("role") != "admin":
        return jsonify({"success": False, "error": "Admin only"}), 403
    data = request.get_json() or {}
    username = data.get("username","")
    if not username:
        return jsonify({"success": False, "error": "username required"})
    try:
        import sqlite3 as sq
        conn = sq.connect("data/users.db")
        from datetime import datetime
        import pytz
        IST = pytz.timezone("Asia/Kolkata")
        now = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S")
        # Add pnl_reset_date column if not exists
        try:
            conn.execute("ALTER TABLE users ADD COLUMN pnl_reset_date TEXT")
        except Exception:
            pass
        conn.execute("UPDATE users SET pnl_reset_date=? WHERE username=?", (now, username))
        conn.commit()
        conn.close()
        logger.info(f"P&L reset for {username} by {user.get('username')}")
        return jsonify({"success": True, "message": f"P&L reset for {username}"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

@app.route("/api/v3/admin/system")
@require_auth
def system_monitor():
    user = get_current_user()
    if user.get("role") != "admin":
        return jsonify({"success": False, "error": "Admin only"}), 403
    import psutil, os
    cpu    = _cpu_cache['val']
    mem    = psutil.virtual_memory()
    disk   = psutil.disk_usage('/')
    proc   = []
    for p in psutil.process_iter(['pid','name','cpu_percent','memory_percent','cmdline']):
        try:
            cmd = " ".join(p.info['cmdline'] or [])
            if 'python' in cmd:
                proc.append({
                    "pid":   p.info['pid'],
                    "cpu":   round(p.info['cpu_percent'],1),
                    "ram":   round(p.info['memory_percent'],1),
                    "cmd":   cmd[:60],
                })
        except Exception:
            pass
    proc.sort(key=lambda x: x['cpu'], reverse=True)
    # Online users
    online = len(set(v.get('username','') for v in _tokens.values() if isinstance(v,dict) and v.get('username')))
    return jsonify({
        "success":   True,
        "cpu":       round(cpu, 1),
        "ram_used":  round(mem.used/1024**3, 2),
        "ram_total": round(mem.total/1024**3, 2),
        "ram_pct":   round(mem.percent, 1),
        "disk_used": round(disk.used/1024**3, 2),
        "disk_total":round(disk.total/1024**3, 2),
        "disk_pct":  round(disk.percent, 1),
        "processes": proc[:8],
        "online_users": online,
        "uptime":    os.popen("uptime -p").read().strip(),
    })

# ── Per-User P&L (starts from 0 for each user) ─────────
@app.route("/api/v3/user/pnl")
@require_auth
def user_pnl():
    user     = get_current_user()
    username = user.get("username","")
    import sqlite3 as sq
    conn = sq.connect(config.DB_PATH)
    conn.row_factory = sq.Row
    today = datetime.now(IST).strftime("%Y-%m-%d")
    # Today P&L for this user
    t = conn.execute("""
        SELECT COUNT(*) tc,
               SUM(CASE WHEN pnl>0 THEN 1 ELSE 0 END) wins,
               SUM(pnl) pnl
        FROM trades
        WHERE DATE(created_at)=? AND status='CLOSED'
        AND (username=? OR username IS NULL)
    """, (today, username)).fetchone()
    # All time P&L for this user
    a = conn.execute("""
        SELECT COUNT(*) tc, SUM(pnl) pnl,
               SUM(CASE WHEN pnl>0 THEN 1 ELSE 0 END) wins
        FROM trades WHERE status='CLOSED'
        AND (username=? OR username IS NULL)
        AND ABS(pnl) < 100000
        AND (created_at >= (SELECT COALESCE(pnl_reset_date,'2000-01-01')
             FROM users WHERE username=?) OR username IS NULL)
    """, (username, username)).fetchone()
    conn.close()
    today_pnl   = round(t["pnl"] or 0, 2)
    today_tc    = t["tc"] or 0
    today_wins  = t["wins"] or 0
    all_pnl     = round(a["pnl"] or 0, 2)
    all_tc      = a["tc"] or 0
    all_wins    = a["wins"] or 0
    win_rate    = round(today_wins/today_tc*100,1) if today_tc>0 else 0
    all_wr      = round(all_wins/all_tc*100,1) if all_tc>0 else 0
    return jsonify({
        "success":      True,
        "username":     username,
        "today_pnl":    today_pnl,
        "today_trades": today_tc,
        "today_wins":   today_wins,
        "win_rate":     win_rate,
        "total_pnl":    all_pnl,
        "total_trades": all_tc,
        "all_win_rate": all_wr,
    })
