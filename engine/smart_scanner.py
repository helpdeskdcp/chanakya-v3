"""
Chanakya AI v4.0 — Smart Scanner
MTF + Options Intel + Decision Engine integrated
"""
import logging, time
logger = logging.getLogger(__name__)

SYMBOLS = [
    {"symbol":"NIFTY",      "token":"99926000","exchange":"NSE","lot":75},
    {"symbol":"BANKNIFTY",  "token":"99926009","exchange":"NSE","lot":30},
    {"symbol":"FINNIFTY",   "token":"99926037","exchange":"NSE","lot":65},
    {"symbol":"CRUDEOIL",   "token":"488290",  "exchange":"MCX","lot":100},
    {"symbol":"NATURALGAS", "token":"487465",  "exchange":"MCX","lot":1250},
]

def smart_scan(broker):
    """Full MTF + Decision scan"""
    from engine.mtf_engine import analyze_mtf
    from engine.decision_engine import make_decision
    from engine.option_chain import get_best_option
    from engine.signal_store import update

    signals = []

    for sym_info in SYMBOLS:
        sym   = sym_info["symbol"]
        token = sym_info["token"]
        exch  = sym_info["exchange"]
        lot   = sym_info["lot"]

        try:
            # MTF Analysis
            mtf = analyze_mtf(broker, sym, token, exch)
            if not mtf:
                logger.debug(f"{sym}: MTF failed")
                continue

            # Quality decision (stricter)
            try:
                from engine.signal_quality import make_quality_decision
                from data.market import get_vix
                vix = get_vix() or 18.0
                decision = make_quality_decision(mtf, vix=vix)
            except Exception:
                from engine.decision_engine import make_decision
                decision = make_decision(mtf)
            if not decision:
                logger.debug(f"{sym}: No signal (score too low)")
                continue

            opt_type = decision["opt_type"]
            ltp      = mtf["ltp"]

            # Get option LTP
            opt_info = get_best_option(
                broker.api, sym, ltp, opt_type,
                mtf["master_trend"]
            )
            if not opt_info or opt_info.get("option_ltp", 0) <= 0:
                logger.debug(f"{sym}: No option LTP")
                continue

            oltp = opt_info["option_ltp"]

            signals.append({
                "symbol":        sym,
                "exchange":      exch,
                "opt_type":      opt_type,
                "strategy":      "MTF_SMART",
                "score":         round(decision["score"] / 100, 3),
                "score_pct":     decision["score"],
                "confluence":    "HIGH" if decision["score"] >= 80 else "MEDIUM" if decision["score"] >= 65 else "LOW",
                "regime":        mtf["master_trend"],
                "ltp":           ltp,
                "underlying_ltp": ltp,
                "entry":         oltp,
                "target":        round(oltp * 1.25, 2),
                "sl":            round(oltp * 0.85, 2),
                "rr":            round(0.25/0.15, 2),
                "option_symbol": opt_info["symbol"],
                "option_token":  opt_info["token"],
                "strike":        opt_info["strike"],
                "strike_type":   opt_info["strike_type"],
                "atm_strike":    opt_info["atm_strike"],
                "lot_size":      lot,
                "rsi":           mtf["rsi_1m"],
                "vwap":          mtf["vwap"],
                "adx":           mtf["adx"],
                "vol_ratio":     mtf["vol_ratio"],
                "reason":        " | ".join(decision["reasons"][:3]),
            })

            logger.info(f"✅ {sym} {opt_type}: score={decision['score']} {mtf['master_trend']}")
            # Telegram alert
            try:
                from engine.telegram import telegram
                if telegram.enabled and opt_info:
                    oltp = opt_info.get("option_ltp",0)
                    msg = (
                        f"⚡ CHANAKYA SIGNAL\n"
                        f"{'━'*25}\n"
                        f"📊 {sym} {opt_type} | {mtf['master_trend']}\n"
                        f"📋 {opt_info.get('symbol','')}\n"
                        f"🎯 Score: {decision['score']}% | {decision.get('confluence','') if hasattr(decision,'get') else ''}\n"
                        f"💰 Entry:  ₹{oltp}\n"
                        f"✅ Target: ₹{round(oltp*1.25,2)} (+25%)\n"
                        f"🛑 SL:     ₹{round(oltp*0.85,2)} (-15%)\n"
                        f"📈 R:R: 1.67\n"
                        f"{'━'*25}\n"
                        f"💡 {decision.get('reasons',[''])[0] if decision.get('reasons') else ''}"
                    )
                    telegram.signal_alert(signals[-1])
            except Exception as _te:
                logger.debug(f"Telegram: {_te}")
            # Telegram alert
            try:
                from engine.telegram import telegram
                if telegram.enabled and opt_info:
                    oltp = opt_info.get("option_ltp",0)
                    msg = (
                        f"⚡ CHANAKYA SIGNAL\n"
                        f"{'━'*25}\n"
                        f"📊 {sym} {opt_type} | {mtf['master_trend']}\n"
                        f"📋 {opt_info.get('symbol','')}\n"
                        f"🎯 Score: {decision['score']}% | {decision.get('confluence','') if hasattr(decision,'get') else ''}\n"
                        f"💰 Entry:  ₹{oltp}\n"
                        f"✅ Target: ₹{round(oltp*1.25,2)} (+25%)\n"
                        f"🛑 SL:     ₹{round(oltp*0.85,2)} (-15%)\n"
                        f"📈 R:R: 1.67\n"
                        f"{'━'*25}\n"
                        f"💡 {decision.get('reasons',[''])[0] if decision.get('reasons') else ''}"
                    )
                    telegram.signal_alert(signals[-1])
            except Exception as _te:
                logger.debug(f"Telegram: {_te}")

        except Exception as e:
            logger.error(f"SmartScan {sym}: {e}")
            continue

        time.sleep(0.5)  # Rate limit

    signals.sort(key=lambda x: x["score"], reverse=True)
    # Store signals for ALL connected users
    from engine.broker_pool import _pool
    import sqlite3 as _sq
    # Get all active premium/admin users
    try:
        _conn = _sq.connect("data/users.db")
        _users = _conn.execute(
            "SELECT username FROM users WHERE active=1 AND role IN ('admin','premium','viewer')"
        ).fetchall()
        _conn.close()
        for _u in _users:
            update(_u[0], signals)
    except Exception:
        pass
    # Always store for avinash
    update("avinash", signals)
    logger.info(f"SmartScan complete: {len(signals)} signals")
    return signals
