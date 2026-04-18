"""
Chanakya v3 — Risk Management Engine
7-Layer Filter + Kelly Criterion + Dynamic SL
"""
import logging, sqlite3
from datetime import datetime
import pytz
from config import config

logger = logging.getLogger(__name__)
IST = pytz.timezone("Asia/Kolkata")

# ── Layer 1: Market Regime ─────────────────────────────
def check_vix(vix):
    if vix <= 0:
        return True, "VIX unavailable — allow"
    if vix > 25:
        return False, f"VIX {vix:.1f} EXTREME — NO TRADE"
    if vix > 20:
        return True, f"VIX {vix:.1f} HIGH — reduce size 50%"
    if vix < 14:
        return True, f"VIX {vix:.1f} LOW — bullish calm"
    return True, f"VIX {vix:.1f} NORMAL"

# ── Layer 2: Trend Alignment ───────────────────────────
def check_trend(signal_result):
    trend  = signal_result.get("trend", "NEUTRAL")
    struct = signal_result.get("structure", "UNKNOWN")
    score  = signal_result.get("score", 50)
    if score < 50:
        return False, f"Score too low: {score}"
    if trend == "NEUTRAL" and struct == "CONSOLIDATION":
        return False, "No clear trend"
    return True, f"Trend: {trend} | Structure: {struct}"

# ── Layer 3: Smart Money ───────────────────────────────
def check_smart_money(fii_net, pcr, opt_type):
    reasons = []
    score   = 50
    if opt_type == "CE":
        if fii_net > 500:  score += 20; reasons.append(f"FII buying ₹{fii_net:.0f}Cr")
        if pcr < 0.8:      score += 15; reasons.append(f"PCR bullish {pcr:.2f}")
        if pcr > 1.5:      score -= 20; reasons.append(f"PCR bearish {pcr:.2f}")
    else:
        if fii_net < -500: score += 20; reasons.append(f"FII selling ₹{fii_net:.0f}Cr")
        if pcr > 1.3:      score += 15; reasons.append(f"PCR bearish {pcr:.2f}")
        if pcr < 0.6:      score -= 20; reasons.append(f"PCR bullish {pcr:.2f}")
    ok = score >= 45
    return ok, f"SM Score:{score} | " + " | ".join(reasons) if reasons else f"SM Score:{score}"

# ── Layer 4: Options Intelligence ─────────────────────
def check_options(iv, days_left, ce_score, pe_score, opt_type):
    reasons = []
    # IV check
    if iv > 0:
        if iv > 60:
            reasons.append(f"IV very high {iv}% — premium expensive")
        elif iv < 8:
            reasons.append(f"IV very low {iv}% — caution")
    # Days to expiry
    if days_left is not None:
        if days_left <= 1:
            return False, "Expiry day — NO TRADE"
        if days_left <= 3:
            reasons.append(f"Near expiry: {days_left} days")
    # Score check
    score = ce_score if opt_type == "CE" else pe_score
    if score < 40:
        return False, f"{opt_type} score too low: {score}%"
    return True, f"{opt_type} score: {score}% | " + " | ".join(reasons)

# ── Layer 5: ML Confidence ─────────────────────────────
def check_ml(ml_signal, ml_confidence, opt_type, min_conf=None):
    min_conf = min_conf or config.MIN_CONFIDENCE
    if ml_confidence < min_conf:
        return False, f"ML conf {ml_confidence}% < min {min_conf}%"
    # Signal direction check
    if opt_type == "CE" and ml_signal == "SELL":
        return False, f"ML says SELL but trading CE"
    if opt_type == "PE" and ml_signal == "BUY":
        return False, f"ML says BUY but trading PE"
    return True, f"ML: {ml_signal} {ml_confidence}%"

# ── Layer 6: Risk/Reward ───────────────────────────────
def check_rr(entry, sl, target, capital, lots, lot_size):
    if sl <= 0 or target <= 0:
        return False, "Missing SL or Target"
    risk   = (entry - sl) * lots * lot_size
    reward = (target - entry) * lots * lot_size
    rr     = reward / risk if risk > 0 else 0
    if rr < config.MIN_RR:
        return False, f"R:R {rr:.1f} < min {config.MIN_RR}"
    # Capital exposure
    exposure = risk / capital if capital > 0 else 1
    if exposure > config.MAX_CAPITAL_PCT:
        return False, f"Risk ₹{risk:.0f} = {exposure:.1%} > {config.MAX_CAPITAL_PCT:.0%} capital"
    return True, f"R:R {rr:.1f}:1 | Risk ₹{risk:.0f} ({exposure:.1%})"

# ── Layer 7: Time Filter ───────────────────────────────
def check_time():
    now = datetime.now(IST)
    if now.weekday() >= 5:
        return False, "Weekend — markets closed"
    h, m = now.hour, now.minute
    t = h * 60 + m
    if t < 555:    return False, "Pre-market — wait for 9:15 AM"
    if t < 570:    return False, "Opening volatility — wait till 9:30 AM"
    if t >= 915:   return False, "Post 3:15 PM — EXIT ONLY"
    if 750 <= t <= 780: return True, "⚠️ Lunch zone 12:30-1:00 — low liquidity"
    return True, f"Market hours OK — {h:02d}:{m:02d}"

# ── Daily Loss Check ───────────────────────────────────
def check_daily_loss():
    try:
        conn = sqlite3.connect(config.DB_PATH)
        row = conn.execute("""
            SELECT COALESCE(SUM(pnl), 0) FROM trades
            WHERE date(created_at) = date('now', 'localtime')
            AND status = 'CLOSED'
        """).fetchone()
        conn.close()
        daily_pnl = row[0] or 0
        if daily_pnl <= config.DAILY_LOSS_LIMIT:
            return False, f"Daily loss limit hit: ₹{daily_pnl:.0f}"
        return True, f"Daily P&L: ₹{daily_pnl:.0f}"
    except Exception as e:
        return True, f"DB check error: {e}"

# ── Open Positions Check ───────────────────────────────
def check_open_positions():
    try:
        conn = sqlite3.connect(config.DB_PATH)
        open_count = conn.execute(
            "SELECT COUNT(*) FROM trades WHERE status='OPEN'"
        ).fetchone()[0]
        conn.close()
        if open_count >= config.MAX_OPEN_POS:
            return False, f"Max positions reached: {open_count}/{config.MAX_OPEN_POS}"
        return True, f"Open: {open_count}/{config.MAX_OPEN_POS}"
    except Exception as e:
        return True, f"Position check error: {e}"

# ── Loss Streak Check ──────────────────────────────────
def check_loss_streak(max_streak=3):
    try:
        conn = sqlite3.connect(config.DB_PATH)
        recent = conn.execute("""
            SELECT pnl FROM trades WHERE status='CLOSED'
            ORDER BY closed_at DESC LIMIT ?
        """, (max_streak,)).fetchall()
        conn.close()
        streak = sum(1 for r in recent if (r[0] or 0) < 0)
        if streak >= max_streak:
            return False, f"Loss streak: {streak} — cooling off"
        return True, f"Streak OK ({streak} recent losses)"
    except Exception:
        return True, "Streak check skipped"

# ── MAIN 7-LAYER FILTER ────────────────────────────────
class RiskEngine:
    def check_all(self, params):
        """
        Run all 7 layers.
        params: dict with all required fields
        Returns: (approved, reasons_dict)
        """
        results = {}
        passed  = 0
        failed  = 0

        checks = [
            # (layer_name, function, args)
            ("L1_VIX",      check_vix,
             [params.get("vix", 18)]),

            ("L2_TREND",    check_trend,
             [params.get("signal_result", {})]),

            ("L3_SM",       check_smart_money,
             [params.get("fii_net", 0), params.get("pcr", 1.0), params.get("opt_type", "CE")]),

            ("L4_OPTIONS",  check_options,
             [params.get("iv", 0), params.get("days_left", 10),
              params.get("ce_score", 50), params.get("pe_score", 50),
              params.get("opt_type", "CE")]),

            ("L5_ML",       check_ml,
             [params.get("ml_signal", "NEUTRAL"), params.get("ml_confidence", 0),
              params.get("opt_type", "CE")]),

            ("L6_RR",       check_rr,
             [params.get("entry", 0), params.get("sl", 0), params.get("target", 0),
              params.get("capital", config.PAPER_CAPITAL),
              params.get("lots", 1), params.get("lot_size", 1)]),

            ("L7_TIME",     check_time, []),
        ]

        # Extra checks
        extra = [
            ("DAILY_LOSS",  check_daily_loss, []),
            ("OPEN_POS",    check_open_positions, []),
            ("LOSS_STREAK", check_loss_streak, []),
        ]

        all_checks = checks + extra

        for name, fn, args in all_checks:
            ok, msg = fn(*args)
            results[name] = {"ok": ok, "msg": msg}
            if ok:
                passed += 1
            else:
                failed += 1
                logger.info(f"🚫 {name}: {msg}")

        # Must pass all 7 layers + extra
        approved = failed == 0
        score = int(passed / len(all_checks) * 100)

        if approved:
            logger.info(f"✅ ALL CHECKS PASSED ({passed}/{len(all_checks)})")
        else:
            logger.info(f"❌ BLOCKED: {failed} checks failed")

        return approved, results, score

    def kelly_position_size(self, capital, win_rate, rr, max_risk_pct=0.02):
        """
        Modified Kelly Criterion for position sizing.
        Returns max risk amount in ₹
        """
        if win_rate <= 0 or rr <= 0:
            return capital * 0.01
        kelly_f = win_rate - (1 - win_rate) / rr
        kelly_f = max(0, kelly_f)
        # Use 25% of Kelly (conservative)
        safe_f = kelly_f * 0.25
        # Cap at max_risk_pct
        risk_fraction = min(safe_f, max_risk_pct)
        return round(capital * risk_fraction, 0)

    def calculate_lots(self, risk_amount, entry, sl, lot_size):
        """How many lots can we trade given risk amount?"""
        risk_per_lot = (entry - sl) * lot_size
        if risk_per_lot <= 0:
            return 1
        lots = int(risk_amount / risk_per_lot)
        return max(1, lots)

risk_engine = RiskEngine()
