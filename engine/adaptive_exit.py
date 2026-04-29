"""
Chanakya AI — Adaptive Target/SL Engine
Uses regime + ML + candles to dynamically adjust target/SL
"""
import sqlite3, logging
from datetime import datetime
import pytz

logger = logging.getLogger(__name__)
from engine.rate_limiter import get_rate_limiter as _rl
IST = pytz.timezone("Asia/Kolkata")

# Decision thresholds
CONFIG = {
    "ml_exit_threshold":    0.35,  # Exit if ML confidence < 35%
    "trail_start_pct":      0.15,  # Start trailing at 15% profit
    "trail_buffer_pct":     0.08,  # Trail 8% below peak LTP
    "regime_tighten_pct":   0.05,  # Tighten SL by 5% on regime change
    "momentum_boost_pct":   0.10,  # Raise target 10% on strong momentum
    "max_loss_pct":         0.30,  # Hard max loss 30%
    "quick_exit_rsi_ce":    75,    # Exit CE if RSI overbought
    "quick_exit_rsi_pe":    25,    # Exit PE if RSI oversold
}

def adaptive_check(broker, pos_id, username, db_path="data/chanakya_v3.db"):
    """
    Full adaptive analysis for one position.
    Returns: action = "HOLD" / "RAISE_TARGET" / "TIGHTEN_SL" / "EXIT"
    """
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        pos = conn.execute(
            "SELECT * FROM trades WHERE id=? AND status='OPEN'", (pos_id,)
        ).fetchone()
        conn.close()

        if not pos:
            return "HOLD", "Position not found"

        entry   = float(pos["entry_price"] or 0)
        sl      = float(pos["sl_price"] or 0)
        target  = float(pos["target_price"] or 0)
        opt     = pos["opt_type"] or "CE"
        symbol  = pos["symbol"] or "NIFTY"

        if entry <= 0:
            return "HOLD", "Invalid entry"

        # 1. Get live LTP
        _rl().wait_if_needed("ltpData")
    r = broker.api.ltpData(
            pos["exchange"] or "NFO",
            pos["trading_symbol"],
            str(pos["token"] or "")
        )
        if not r or not r.get("data"):
            return "HOLD", "LTP fetch failed"

        ltp     = float(r["data"]["ltp"])
        pnl_pct = (ltp - entry) / entry * 100

        # 2. Get candles for regime + RSI
        try:
            from engine.candles import get_candles
            from engine.ai_selector import detect_market_regime
            from engine.token_manager import get_all_tokens
            tokens = get_all_tokens(broker)
            info   = tokens.get(symbol, {})
            if info.get("token"):
                candles_raw = get_candles(broker, info["token"],
                    exchange=info.get("exchange","NSE"),
                    interval="FIVE_MINUTE", days=2)
                candles = [{"open":x[1],"high":x[2],"low":x[3],
                           "close":x[4],"volume":x[5]} for x in candles_raw[-30:]]
                regime  = detect_market_regime(candles)
                rsi     = _calc_rsi(candles)
                macd_sig = _calc_macd_signal(candles)
            else:
                candles, regime, rsi, macd_sig = [], "SIDEWAYS", 50, 0
        except Exception:
            candles, regime, rsi, macd_sig = [], "SIDEWAYS", 50, 0

        # 3. ML confidence
        ml_conf = 0.5
        try:
            from ai.ml_engine import get_brain
            brain = get_brain()
            if brain.is_trained:
                feats = [
                    entry/1000, target/entry, sl/entry,
                    (target-entry)/(entry-sl) if (entry-sl)>0 else 1.5,
                    1.0 if opt=="CE" else 0.0,
                    rsi/100, pnl_pct/100, 0.5, 18/50, 1/3,
                    0,0,0,0
                ] + [0]*28
                ml_conf = float(brain.predict_proba([feats[:42]])[0][1])
        except Exception:
            pass

        # 4. Decision engine
        action, reason = _decide(
            ltp=ltp, entry=entry, sl=sl, target=target,
            pnl_pct=pnl_pct, regime=regime, rsi=rsi,
            macd_sig=macd_sig, ml_conf=ml_conf, opt=opt
        )

        # 5. Apply decision
        if action != "HOLD":
            _apply_decision(pos_id, action, ltp, entry, sl, target,
                           pnl_pct, reason, broker, pos, username, db_path)

        logger.info(f"🧠 #{pos_id} {symbol} {opt} LTP=₹{ltp} "
                   f"PnL={pnl_pct:.1f}% ML={ml_conf:.2f} "
                   f"RSI={rsi:.0f} Regime={regime} → {action}")

        return action, reason

    except Exception as e:
        logger.error(f"adaptive_check #{pos_id}: {e}")
        return "HOLD", str(e)


def _decide(ltp, entry, sl, target, pnl_pct, regime, rsi,
            macd_sig, ml_conf, opt):
    """Core decision logic"""

    # ── HARD EXIT CONDITIONS ──
    # 1. Hard SL hit
    if ltp <= sl:
        return "EXIT", f"SL hit ₹{ltp} <= ₹{sl}"

    # 2. Target hit
    if ltp >= target:
        return "EXIT", f"Target hit ₹{ltp} >= ₹{target}"

    # 3. ML very low confidence → exit early
    if ml_conf < CONFIG["ml_exit_threshold"] and pnl_pct > 0:
        return "EXIT", f"ML confidence low ({ml_conf:.2f}) — exit in profit"

    # 4. RSI extreme — momentum reversal
    if opt == "CE" and rsi > CONFIG["quick_exit_rsi_ce"] and pnl_pct > 10:
        return "EXIT", f"RSI overbought ({rsi:.0f}) — CE exit"
    if opt == "PE" and rsi < CONFIG["quick_exit_rsi_pe"] and pnl_pct > 10:
        return "EXIT", f"RSI oversold ({rsi:.0f}) — PE exit"

    # 5. Regime changed against position
    if opt == "CE" and regime in ("TRENDING_DOWN", "BEARISH"):
        if pnl_pct > 5:
            return "EXIT", f"Regime bearish ({regime}) — CE exit in profit"
        else:
            return "TIGHTEN_SL", f"Regime bearish — tighten SL"
    if opt == "PE" and regime in ("TRENDING_UP", "BULLISH"):
        if pnl_pct > 5:
            return "EXIT", f"Regime bullish ({regime}) — PE exit in profit"
        else:
            return "TIGHTEN_SL", f"Regime bullish — tighten SL"

    # ── ADAPTIVE ADJUSTMENTS ──
    # 6. Strong momentum → raise target
    if opt == "CE" and regime == "TRENDING_UP" and macd_sig > 0 and pnl_pct > 20:
        return "RAISE_TARGET", f"Strong uptrend (MACD+RSI={rsi:.0f}) — raise target"
    if opt == "PE" and regime == "TRENDING_DOWN" and macd_sig < 0 and pnl_pct > 20:
        return "RAISE_TARGET", f"Strong downtrend — raise PE target"

    # 7. Profitable — trail SL
    if pnl_pct >= CONFIG["trail_start_pct"] * 100:
        return "TRAIL_SL", f"Profit {pnl_pct:.1f}% — trail SL"

    return "HOLD", f"Holding — LTP=₹{ltp} PnL={pnl_pct:.1f}%"


def _apply_decision(pos_id, action, ltp, entry, sl, target,
                   pnl_pct, reason, broker, pos, username, db_path):
    """Apply the decision to DB + broker"""
    conn = sqlite3.connect(db_path)
    now  = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S")
    qty  = int(pos["quantity"] or 0)

    if action == "EXIT":
        pnl = round((ltp - entry) * qty, 2)
        pnl_p = round(pnl_pct, 2)
        conn.execute("""
            UPDATE trades SET status='CLOSED', exit_price=?,
            pnl=?, pnl_pct=?, exit_reason=?, closed_at=?, updated_at=?
            WHERE id=?
        """, (ltp, pnl, pnl_p, reason, now, now, pos_id))
        logger.info(f"{'✅' if pnl>0 else '❌'} EXIT #{pos_id} ₹{pnl:.0f} | {reason}")

        # Live order
        if pos.get("mode") == "LIVE":
            _place_exit_order(broker, pos, qty)

    elif action == "RAISE_TARGET":
        # Raise target by 10%
        new_target = round(target * (1 + CONFIG["momentum_boost_pct"]), 2)
        conn.execute("UPDATE trades SET target_price=?,updated_at=? WHERE id=?",
                    (new_target, now, pos_id))
        logger.info(f"🎯 RAISE TARGET #{pos_id}: ₹{target}→₹{new_target} | {reason}")

    elif action == "TIGHTEN_SL":
        # Tighten SL closer to entry
        new_sl = round(ltp * (1 - CONFIG["regime_tighten_pct"]), 2)
        if new_sl > sl:
            conn.execute("UPDATE trades SET sl_price=?,updated_at=? WHERE id=?",
                        (new_sl, now, pos_id))
            logger.info(f"🔒 TIGHTEN SL #{pos_id}: ₹{sl}→₹{new_sl} | {reason}")

    elif action == "TRAIL_SL":
        # Trail SL 8% below current LTP
        new_sl = round(ltp * (1 - CONFIG["trail_buffer_pct"]), 2)
        if new_sl > sl:
            conn.execute("UPDATE trades SET sl_price=?,updated_at=? WHERE id=?",
                        (new_sl, now, pos_id))
            logger.info(f"📈 TRAIL SL #{pos_id}: ₹{sl}→₹{new_sl} (LTP=₹{ltp})")

    conn.commit()
    conn.close()


def _place_exit_order(broker, pos, qty):
    """Place actual SELL order on Angel One"""
    try:
        r = broker.api.placeOrder({
            "variety":         "NORMAL",
            "tradingsymbol":   pos["trading_symbol"],
            "symboltoken":     str(pos["token"]),
            "transactiontype": "SELL",
            "exchange":        pos["exchange"] or "NFO",
            "ordertype":       "MARKET",
            "producttype":     "INTRADAY",
            "duration":        "DAY",
            "quantity":        str(qty),
            "price":           "0",
            "triggerprice":    "0",
        })
        logger.info(f"🔴 SELL ORDER placed: {pos['trading_symbol']} qty={qty} → {r}")
    except Exception as e:
        logger.error(f"Exit order failed: {e}")


def _calc_rsi(candles, period=14):
    """RSI calculation"""
    if len(candles) < period + 1:
        return 50
    closes = [c["close"] for c in candles]
    gains, losses = [], []
    for i in range(1, len(closes)):
        d = closes[i] - closes[i-1]
        gains.append(max(d,0))
        losses.append(max(-d,0))
    ag = sum(gains[-period:]) / period
    al = sum(losses[-period:]) / period
    if al == 0:
        return 100
    rs = ag / al
    return round(100 - 100/(1+rs), 1)


def _calc_macd_signal(candles):
    """MACD histogram signal (+ve=bullish, -ve=bearish)"""
    if len(candles) < 26:
        return 0
    closes = [c["close"] for c in candles]
    def ema(data, p):
        k = 2/(p+1)
        e = data[0]
        for d in data[1:]: e = d*k + e*(1-k)
        return e
    e12 = ema(closes[-12:], 12)
    e26 = ema(closes[-26:], 26)
    macd = e12 - e26
    signal = ema(closes[-9:], 9)
    return round(macd - signal, 4)
