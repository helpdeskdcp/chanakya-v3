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
    session.clear()
    return jsonify({"success": True})

# ── Status API ─────────────────────────────────────────
@app.route("/api/v3/status")
def status():
    now = datetime.now(IST)
    stats = get_today_stats()
    vix = _get_vix()
    return jsonify({
        "success":       True,
        "version":       config.VERSION,
        "connected":     broker.connected,
        "user":          broker.user_name,
        "mode":          "PAPER" if config.PAPER_MODE else "LIVE",
        "market_open":   signal_engine.is_market_open(),
        "mcx_open":      signal_engine.is_market_open("MCX"),
        "time":          now.strftime("%H:%M:%S"),
        "date":          now.strftime("%d %b %Y"),
        "vix":           vix,
        "today":         stats,
        "ml_ready":      ensemble.is_trained,
        "ml_accuracy":   round(ensemble.accuracy * 100, 1),
        "ml_samples":    ensemble.n_samples,
    })

# ── Dashboard API ──────────────────────────────────────
@app.route("/api/v3/dashboard")
@require_auth
def dashboard():
    import sqlite3
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # Today stats
    cur.execute("""SELECT COUNT(*), COALESCE(SUM(pnl),0),
        SUM(CASE WHEN pnl>0 THEN 1 ELSE 0 END)
        FROM trades WHERE date(created_at)=date('now','localtime')
        AND status='CLOSED'""")
    r = cur.fetchone()
    today_trades = r[0] or 0
    today_pnl    = round(r[1] or 0, 2)
    today_wins   = r[2] or 0

    # All time
    cur.execute("""SELECT COUNT(*), COALESCE(SUM(pnl),0),
        SUM(CASE WHEN pnl>0 THEN 1 ELSE 0 END)
        FROM trades WHERE status='CLOSED'""")
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
        "capital":       round(broker.get_funds() if broker.connected else config.PAPER_CAPITAL, 2),
        "today_pnl":     today_pnl,
        "today_trades":  today_trades,
        "today_wins":    today_wins,
        "win_rate":      win_rate,
        "total_trades":  all_trades,
        "total_pnl":     all_pnl,
        "all_win_rate":  all_wr,
        "open_trades":   open_count,
        "best_strategy": {"name": bs[0], "pnl": round(bs[1],2)} if bs else None,
        "mode":          "PAPER" if config.PAPER_MODE else "LIVE",
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
    if mode not in ("PAPER", "LIVE"):
        return jsonify({"success": False, "error": "Invalid mode"})
    config.PAPER_MODE = (mode == "PAPER")
    logger.info(f"Mode switched to {mode}")
    return jsonify({"success": True, "mode": mode})

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

        from ai.ml_engine import EnsembleModel
        model = EnsembleModel()
        ok = model.train(np.array(X), np.array(y))
        if ok:
            # Update global ensemble
            from ai import ml_engine
            ml_engine.ensemble = model
            return jsonify({
                "success":  True,
                "accuracy": round(model.accuracy*100, 1),
                "samples":  model.n_samples,
            })
        return jsonify({"success": False, "error": "Training failed"})
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
