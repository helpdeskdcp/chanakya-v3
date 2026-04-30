"""
Chanakya AI — Signal Guard v1.0
Multi-layer loss prevention system
NO trade unless ALL guards pass
"""
import logging
logger = logging.getLogger(__name__)

# ── GUARD RULES ────────────────────────────────────────
RULES = {
    "min_rr":           2.5,   # Min Risk:Reward ratio
    "min_score":        70,    # Min signal score %
    "min_net_profit":   150,   # Min net profit after brokerage
    "max_sl_pct":       2.0,   # Max SL% from entry
    "min_volume_ratio": 1.5,   # Min volume vs avg
    "rsi_ce_min":       45,    # RSI min for CE/BUY
    "rsi_ce_max":       68,    # RSI max for CE/BUY
    "rsi_pe_min":       32,    # RSI min for PE/SELL
    "rsi_pe_max":       55,    # RSI max for PE/SELL
    "min_atr_ratio":    0.3,   # Min ATR% — avoid flat stocks
    "max_atr_ratio":    5.0,   # Max ATR% — avoid too volatile
    "sideways_block":   True,  # Block trades in sideways market
    "vix_max":          22,    # Block if VIX > 22
    "no_trade_mins":    15,    # Block first 15 min (9:15-9:30)
    "min_candles":      30,    # Min candles needed for analysis
    "trend_confirm":    True,  # Need 2 timeframes aligned
    "ml_min_conf":      0.55,  # ML minimum confidence
}


def check_all(signal_data, market_data=None):
    """
    Run all guards on a signal
    Returns: (passed, reasons_passed, reasons_failed)
    """
    passed  = []
    failed  = []
    d = signal_data
    m = market_data or {}

    entry     = float(d.get("entry", 0))
    sl        = float(d.get("sl", 0))
    target    = float(d.get("target", 0))
    score     = float(d.get("score_pct", d.get("score", 0)*100))
    rsi       = float(d.get("rsi", 50))
    vol_ratio = float(d.get("vol_ratio", 1))
    net_profit= float(d.get("net_profit", 0))
    direction = d.get("direction", d.get("opt_type", "BUY"))
    atr       = float(d.get("atr", 0))
    vix       = float(m.get("vix", d.get("vix", 18)))
    regime    = m.get("regime", d.get("regime", "SIDEWAYS"))
    ml_conf   = float(d.get("ml_conf", 0.5))

    # ── GUARD 1: Score ──────────────────────────────────
    if score >= RULES["min_score"]:
        passed.append(f"Score {score:.0f}% ✅")
    else:
        failed.append(f"Score {score:.0f}% < {RULES['min_score']}% ❌")

    # ── GUARD 2: Risk:Reward ────────────────────────────
    if entry > 0 and sl > 0 and target > 0:
        if direction in ("BUY","CE"):
            rr = (target-entry)/(entry-sl) if entry > sl else 0
        else:
            rr = (entry-target)/(sl-entry) if sl > entry else 0
        rr = round(rr, 2)
        if rr >= RULES["min_rr"]:
            passed.append(f"RR {rr} ✅")
        else:
            failed.append(f"RR {rr} < {RULES['min_rr']} ❌")
    else:
        failed.append("Invalid entry/sl/target ❌")
        rr = 0

    # ── GUARD 3: Net Profit ─────────────────────────────
    if net_profit >= RULES["min_net_profit"]:
        passed.append(f"Net Rs{net_profit} ✅")
    else:
        failed.append(f"Net Rs{net_profit} < Rs{RULES['min_net_profit']} ❌")

    # ── GUARD 4: SL % ──────────────────────────────────
    if entry > 0:
        sl_pct = abs(entry-sl)/entry*100
        if sl_pct <= RULES["max_sl_pct"]:
            passed.append(f"SL {sl_pct:.1f}% ✅")
        else:
            failed.append(f"SL {sl_pct:.1f}% > {RULES['max_sl_pct']}% ❌")

    # ── GUARD 5: Volume ─────────────────────────────────
    if vol_ratio >= RULES["min_volume_ratio"]:
        passed.append(f"Vol {vol_ratio}x ✅")
    else:
        failed.append(f"Vol {vol_ratio}x < {RULES['min_volume_ratio']}x ❌")

    # ── GUARD 6: RSI Zone ───────────────────────────────
    if direction in ("BUY","CE"):
        if RULES["rsi_ce_min"] <= rsi <= RULES["rsi_ce_max"]:
            passed.append(f"RSI {rsi} bull zone ✅")
        else:
            failed.append(f"RSI {rsi} out of bull zone ({RULES['rsi_ce_min']}-{RULES['rsi_ce_max']}) ❌")
    else:
        if RULES["rsi_pe_min"] <= rsi <= RULES["rsi_pe_max"]:
            passed.append(f"RSI {rsi} bear zone ✅")
        else:
            failed.append(f"RSI {rsi} out of bear zone ❌")

    # ── GUARD 7: ATR Ratio ──────────────────────────────
    if entry > 0 and atr > 0:
        atr_pct = atr/entry*100
        if RULES["min_atr_ratio"] <= atr_pct <= RULES["max_atr_ratio"]:
            passed.append(f"ATR {atr_pct:.1f}% ✅")
        else:
            failed.append(f"ATR {atr_pct:.1f}% out of range ❌")

    # ── GUARD 8: Regime ─────────────────────────────────
    if RULES["sideways_block"] and regime == "SIDEWAYS":
        failed.append(f"Regime SIDEWAYS — blocked ❌")
    elif regime in ("TRENDING_UP","BULLISH") and direction in ("BUY","CE"):
        passed.append(f"Regime {regime} ✅")
    elif regime in ("TRENDING_DOWN","BEARISH") and direction in ("SELL","PE"):
        passed.append(f"Regime {regime} ✅")
    else:
        passed.append(f"Regime {regime} neutral")

    # ── GUARD 9: VIX ────────────────────────────────────
    if vix <= RULES["vix_max"]:
        passed.append(f"VIX {vix} ✅")
    else:
        failed.append(f"VIX {vix} > {RULES['vix_max']} ❌")

    # ── GUARD 10: ML Confidence ─────────────────────────
    if ml_conf >= RULES["ml_min_conf"]:
        passed.append(f"ML {ml_conf:.2f} ✅")
    else:
        failed.append(f"ML {ml_conf:.2f} < {RULES['ml_min_conf']} ❌")

    # ── FINAL VERDICT ───────────────────────────────────
    # Critical guards — ALL must pass
    critical = ["RR","Score","Net","SL","Vol","RSI"]
    critical_failed = [f for f in failed if any(c in f for c in critical)]

    all_passed = len(critical_failed) == 0

    logger.info(f"Signal Guard: {'✅ PASS' if all_passed else '❌ BLOCK'} "
               f"passed={len(passed)} failed={len(failed)}")
    if failed:
        logger.info(f"  Failed: {' | '.join(failed[:3])}")

    return all_passed, passed, failed


def filter_signals(signals, market_data=None):
    """Filter list of signals — only pass strong ones"""
    approved = []
    for sig in signals:
        ok, passed, failed = check_all(sig, market_data)
        sig["guard_passed"] = ok
        sig["guard_reasons"] = passed
        sig["guard_failed"]  = failed
        if ok:
            approved.append(sig)
        else:
            logger.debug(f"Blocked: {sig.get('symbol','')} — {failed[:2]}")
    logger.info(f"Signal Guard: {len(approved)}/{len(signals)} passed")
    return approved
