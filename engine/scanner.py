"""
Chanakya v3 — Auto Signal Scanner
7-Layer validated signals for NSE + MCX
"""
import logging, time, sqlite3
from datetime import datetime
import pytz
from config import config

logger = logging.getLogger(__name__)
IST = pytz.timezone("Asia/Kolkata")


class SignalScanner:
    def __init__(self, broker):
        self.broker    = broker
        self.last_scan = {}  # {symbol: timestamp}
        self.scan_interval = 60  # seconds between scans

    def scan_symbol(self, symbol):
        """
        Full scan for one symbol.
        Returns signal dict or None.
        """
        try:
            # Rate limit
            now = time.time()
            if now - self.last_scan.get(symbol, 0) < self.scan_interval:
                return None
            self.last_scan[symbol] = now

            # Step 1: Get chain data
            from engine.chain import get_chain
            chain = get_chain(self.broker, symbol)
            if not chain:
                logger.debug(f"No chain data: {symbol}")
                return None

            spot    = chain["spot"]
            atm     = chain["atm"]
            pcr     = chain.get("pcr", 1.0)
            expiry  = chain.get("expiry", "")

            # Step 2: Get market context
            vix = self._get_vix()
            fii_data = self._get_fii()
            fii_net  = fii_data.get("fii_net", 0)
            fii_bias = fii_data.get("bias", "NEUTRAL")

            # Step 3: Determine best opt_type
            # Based on bias score
            bias = 0
            if "BULL" in fii_bias: bias += 20
            elif "BEAR" in fii_bias: bias -= 20
            if pcr < 0.8:  bias += 15
            elif pcr > 1.3: bias -= 15
            if vix < 15:   bias += 10
            elif vix > 22:  bias -= 10

            opt_type = "CE" if bias >= 0 else "PE"

            # Step 4: Find best strike
            step = config.STRIKE_STEPS.get(symbol, 50)
            # Slightly OTM for scalping
            if opt_type == "CE":
                strike = atm  # ATM CE
            else:
                strike = atm  # ATM PE

            # Find strike in chain
            selected = next(
                (r for r in chain["chain"] if r["strike"] == strike), None
            )
            if not selected:
                return None

            opt_data = selected.get(opt_type.lower(), {})
            ltp = opt_data.get("ltp", 0)
            if not ltp or ltp < 5:
                logger.debug(f"LTP too low: {symbol} {strike} {opt_type} = {ltp}")
                return None

            # Step 5: Get candles + signals
            token = opt_data.get("token", "")
            candles = []
            if token:
                from engine.candles import get_candles
                exchange = "MCX" if symbol in ("CRUDEOIL","NATURALGAS") else "NFO"
                candles = get_candles(self.broker, token, exchange)

            if len(candles) < 20:
                logger.debug(f"Insufficient candles: {symbol} ({len(candles)})")
                return None

            # Signal analysis
            from engine.signals import signal_engine
            sig_result = signal_engine.analyze(
                candles, symbol, opt_type,
                spot=spot, vix=vix, pcr=pcr, fii_bias=fii_bias
            )

            signal_score = sig_result.get("score", 0)
            if signal_score < 65:
                logger.debug(f"Signal score too low: {symbol} {signal_score}")
                return None

            # Step 6: ATR-based levels
            from engine.signals import atr as calc_atr
            atr_val  = calc_atr(candles)
            tf       = "5min"
            tf_params = config.TIMEFRAMES.get(tf, {})
            sl_pts   = atr_val * tf_params.get("atr_sl", 0.8)  if atr_val else ltp * 0.08
            tgt_pts  = atr_val * tf_params.get("atr_tgt", 1.2) if atr_val else ltp * 0.15
            entry    = round(ltp / 0.05) * 0.05
            sl       = round((entry - sl_pts) / 0.05) * 0.05
            target   = round((entry + tgt_pts) / 0.05) * 0.05
            sl       = max(sl, entry * 0.5)
            rr       = round(tgt_pts / sl_pts, 1) if sl_pts > 0 else 0

            if rr < config.MIN_RR:
                logger.debug(f"R:R too low: {symbol} {rr}")
                return None

            # Step 7: ML prediction
            ml_signal, ml_conf = "NEUTRAL", 0
            try:
                from ai.ml_engine import ensemble, build_features
                from engine.signals import rsi, atr as calc_atr
                closes = [c[4] for c in candles]
                rsi_v  = rsi(closes)
                feats  = build_features(
                    candles, vix=vix, pcr=pcr, fii_net=fii_net,
                    iv=opt_data.get("iv",0)/100,
                    delta=opt_data.get("delta", 0.5)
                )
                if feats is not None and ensemble.is_trained:
                    ml_signal, ml_conf = ensemble.predict(feats)
            except Exception as e:
                logger.debug(f"ML error: {e}")

            # Step 8: CE/PE scores
            ce_score = min(95, max(5, int(50 + bias/2)))
            pe_score = min(95, max(5, int(50 - bias/2)))

            # Step 9: 7-Layer risk check
            lot_size = config.LOT_SIZES.get(symbol, 1)
            capital  = self.broker.get_funds() if self.broker.connected else config.PAPER_CAPITAL
            lots     = 1  # Start with 1 lot

            from engine.risk import risk_engine
            approved, risk_results, risk_score = risk_engine.check_all({
                "vix":           vix,
                "signal_result": sig_result,
                "fii_net":       fii_net,
                "pcr":           pcr,
                "opt_type":      opt_type,
                "iv":            opt_data.get("iv", 0),
                "days_left":     opt_data.get("t", 10),
                "ce_score":      ce_score,
                "pe_score":      pe_score,
                "ml_signal":     ml_signal,
                "ml_confidence": ml_conf,
                "entry":         entry,
                "sl":            sl,
                "target":        target,
                "capital":       capital,
                "lots":          lots,
                "lot_size":      lot_size,
            })

            if not approved:
                failed = [k for k,v in risk_results.items() if not v["ok"]]
                logger.info(f"🚫 {symbol} blocked: {failed}")
                return None

            # Kelly position sizing
            wr = 0.55  # Default win rate
            try:
                conn = sqlite3.connect(config.DB_PATH)
                r = conn.execute("""
                    SELECT COUNT(*), SUM(CASE WHEN pnl>0 THEN 1 ELSE 0 END)
                    FROM trades WHERE status='CLOSED'
                    AND symbol=? ORDER BY created_at DESC LIMIT 20
                """, (symbol,)).fetchone()
                conn.close()
                if r and r[0] > 5:
                    wr = r[1] / r[0]
            except Exception:
                pass

            risk_amt = risk_engine.kelly_position_size(capital, wr, rr)
            lots     = risk_engine.calculate_lots(risk_amt, entry, sl, lot_size)
            quantity = lots * lot_size

            # Build signal
            signal = {
                "symbol":         symbol,
                "trading_symbol": opt_data.get("trading_symbol", ""),
                "token":          token,
                "exchange":       "MCX" if symbol in ("CRUDEOIL","NATURALGAS") else "NFO",
                "opt_type":       opt_type,
                "strike":         strike,
                "expiry":         expiry,
                "spot":           spot,
                "ltp":            ltp,
                "entry_price":    entry,
                "sl_price":       sl,
                "target_price":   target,
                "quantity":       quantity,
                "lots":           lots,
                "lot_size":       lot_size,
                "atr":            atr_val,
                "rr":             rr,
                "vix":            vix,
                "pcr":            pcr,
                "fii_net":        fii_net,
                "iv":             opt_data.get("iv", 0),
                "delta":          opt_data.get("delta", 0),
                "signal_score":   signal_score,
                "ml_signal":      ml_signal,
                "ml_confidence":  ml_conf,
                "ce_score":       ce_score,
                "pe_score":       pe_score,
                "risk_score":     risk_score,
                "strategy":       f"CHANAKYA_V3_{tf.upper()}",
                "timeframe":      tf,
                "approved":       approved,
                "scan_time":      datetime.now(IST).isoformat(),
            }

            logger.info(
                f"✅ SIGNAL: {symbol} {strike} {opt_type} "
                f"Entry:₹{entry} SL:₹{sl} T:₹{target} "
                f"R:R:{rr} ML:{ml_conf}% Score:{signal_score}"
            )

            # Save to DB
            self._save_signal(signal)
            return signal

        except Exception as e:
            logger.error(f"Scan error {symbol}: {e}")
            import traceback; logger.debug(traceback.format_exc())
            return None

    def scan_all(self):
        """Scan all symbols using new AI selector + correct tokens"""
        from engine.token_manager import get_all_tokens
        from engine.candles import get_candles
        from engine.ai_selector import ai_select_strategy, detect_market_regime
        from engine.strike_selector import get_atm_strike, STRIKE_INTERVALS
        import time as _t

        signals = []
        try:
            tokens = get_all_tokens(self.broker)
            for sym, info in tokens.items():
                if sym in ("VIX",): continue
                try:
                    cr = get_candles(self.broker, info["token"],
                                    exchange=info["exchange"],
                                    interval="FIVE_MINUTE", days=5)
                    if len(cr) < 25: continue
                    candles = [{"open":x[1],"high":x[2],"low":x[3],
                               "close":x[4],"volume":x[5]} for x in cr]
                    regime  = detect_market_regime(candles)
                    ltp_val = info.get("ltp", candles[-1]["close"])
                    atm     = get_atm_strike(ltp_val, sym)
                    interval_sz = STRIKE_INTERVALS.get(sym.upper(), 50)
                    lot_size = config.LOT_SIZES.get(sym, 1)

                    for opt in ["CE","PE"]:
                        sig = ai_select_strategy(candles, opt, symbol=sym, vix=18)
                        if sig and sig.get("score",0) >= 0.60:
                            if regime in ("TRENDING_UP","TRENDING_DOWN"):
                                strike = atm-interval_sz if opt=="CE" else atm+interval_sz
                                stype = "ITM"
                            elif regime == "VOLATILE":
                                strike = atm+interval_sz if opt=="CE" else atm-interval_sz
                                stype = "OTM"
                            else:
                                strike = atm; stype = "ATM"

                            signals.append({
                                "symbol":      sym,
                                "exchange":    info["exchange"],
                                "opt_type":    opt,
                                "strategy":    sig["strategy"],
                                "score":       round(sig["score"],3),
                                "confluence":  sig.get("confluence",""),
                                "regime":      regime,
                                "entry":       sig["entry"],
                                "target":      sig["target"],
                                "sl":          sig["sl"],
                                "rr":          sig["rr"],
                                "ltp":         ltp_val,
                                "strike":      strike,
                                "strike_type": stype,
                                "atm_strike":  atm,
                                "lot_size":    lot_size,
                                "reason":      sig.get("reason",""),
                            })
                except Exception as _e:
                    logger.debug(f"Scan {sym}: {_e}")
                    continue
        except Exception as e:
            logger.error(f"scan_all: {e}")

        signals.sort(key=lambda x: x["score"], reverse=True)
        logger.info(f"🔍 Scan complete: {len(signals)} signals from {len(tokens) if 'tokens' in dir() else 0} symbols")
        return signals

    def _get_vix(self):
        try:
            import requests
            r = requests.get(
                "https://www.nseindia.com/api/allIndices",
                headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"},
                timeout=5
            )
            for idx in r.json().get("data", []):
                if idx.get("index") == "India VIX":
                    return float(idx["last"])
        except Exception:
            pass
        return 18.0

    def _get_fii(self):
        try:
            from data.fii import get_fii_data
            return get_fii_data()
        except Exception:
            return {"fii_net": 0, "dii_net": 0, "bias": "NEUTRAL"}

    def _save_signal(self, sig):
        try:
            conn = sqlite3.connect(config.DB_PATH)
            conn.execute("""
                INSERT INTO signals (
                    symbol, opt_type, strike, direction,
                    confidence, ml_conf, ce_score, pe_score,
                    entry_price, sl_price, target_price,
                    atr, strategy, timeframe, status
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,'PENDING')
            """, (
                sig["symbol"], sig["opt_type"], sig["strike"],
                sig["opt_type"],
                sig["signal_score"], sig["ml_confidence"],
                sig["ce_score"], sig["pe_score"],
                sig["entry_price"], sig["sl_price"], sig["target_price"],
                sig["atr"], sig["strategy"], sig["timeframe"],
            ))
            conn.commit()
            conn.close()
        except Exception as e:
            logger.debug(f"Signal save: {e}")
