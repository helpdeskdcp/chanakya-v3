import logging, json, os
from datetime import datetime
import pytz
logger = logging.getLogger(__name__)
IST = pytz.timezone("Asia/Kolkata")

# Stocks to scan for Chanakya Prediction
PREDICTION_WATCHLIST = [
    # Indices
    {"symbol":"NIFTY",      "token":"99926000","exch":"NSE","type":"index"},
    {"symbol":"BANKNIFTY",  "token":"99926009","exch":"NSE","type":"index"},
    {"symbol":"FINNIFTY",   "token":"99926037","exch":"NSE","type":"index"},
    # MCX
    {"symbol":"CRUDEOIL",   "token":"488290",  "exch":"MCX","type":"commodity"},
    {"symbol":"NATURALGAS", "token":"488505",  "exch":"MCX","type":"commodity"},
    {"symbol":"GOLD",       "token":"67694",   "exch":"MCX","type":"commodity"},
    # Top NSE Equity
    {"symbol":"RELIANCE",   "token":"2885",    "exch":"NSE","type":"equity"},
    {"symbol":"TCS",        "token":"11536",   "exch":"NSE","type":"equity"},
    {"symbol":"HDFCBANK",   "token":"1333",    "exch":"NSE","type":"equity"},
    {"symbol":"ICICIBANK",  "token":"4963",    "exch":"NSE","type":"equity"},
    {"symbol":"WIPRO",      "token":"3787",    "exch":"NSE","type":"equity"},
    {"symbol":"INFY",       "token":"1594",    "exch":"NSE","type":"equity"},
    {"symbol":"SBIN",       "token":"3045",    "exch":"NSE","type":"equity"},
    {"symbol":"TATAMOTORS", "token":"3456",    "exch":"NSE","type":"equity"},
    {"symbol":"TATASTEEL",  "token":"3499",    "exch":"NSE","type":"equity"},
    {"symbol":"SUZLON",     "token":"12018",   "exch":"NSE","type":"equity"},
]

_cache = {"signals":[], "last_scan": None}

def run_prediction_scan(broker):
    """Main prediction scan — MTF + Groq AI confirmation"""
    try:
        now = datetime.now(IST)
        h, mn = now.hour, now.minute
        nse_open = (9,15)<=(h,mn)<=(15,30) and now.weekday()<5
        mcx_open = ((9,0)<=(h,mn) or (h,mn)<=(23,30)) and now.weekday()<5
        if not nse_open and not mcx_open:
            logger.info("Market closed — using prev data")
        signals = []
        from engine.groq_ai import get_mtf_analysis
        from engine.rate_limiter import get_rate_limiter
        rl = get_rate_limiter()
        for stock in PREDICTION_WATCHLIST:
            try:
                # Check market open for this exchange
                if stock["exch"]=="NSE" and not nse_open:
                    continue
                if stock["exch"]=="MCX" and not mcx_open:
                    continue
                # MTF Analysis
                mtf = get_mtf_analysis(broker, stock["symbol"], stock["token"], stock["exch"])
                if not mtf or "confluence" not in mtf:
                    continue
                conf = mtf["confluence"]
                score = conf.get("score", 0)
                overall = conf.get("overall","SIDEWAYS")
                bull_tf = conf.get("bull_tf", 0)
                bear_tf = conf.get("bear_tf", 0)
                # Only HIGH confidence
                if score < 50 and overall == "SIDEWAYS":
                    continue
                if bull_tf < 3 and bear_tf < 3:
                    continue
                # Get price data from 5m TF
                tf_data = mtf.get("5m") or mtf.get("15m") or {}
                ltp = tf_data.get("ltp", 0)
                atr = tf_data.get("atr", 0)
                rsi = tf_data.get("rsi", 50)
                vwap_bias = tf_data.get("vwap_bias","")
                macd_sig = tf_data.get("macd_signal","")
                trend = tf_data.get("trend","")
                fake = tf_data.get("fake",[])
                if ltp <= 0: continue
                # Direction
                direction = "BUY" if overall=="BULLISH" else "SELL"
                if direction=="BUY":
                    sl = round(ltp - 1.5*atr, 1)
                    target = round(ltp + 3*atr, 1)
                else:
                    sl = round(ltp + 1.5*atr, 1)
                    target = round(ltp - 3*atr, 1)
                rr = round(abs(target-ltp)/abs(ltp-sl),1) if ltp!=sl else 0
                # Confidence %
                confidence = min(95, int(score + bull_tf*5 + bear_tf*5))
                if fake: confidence -= len(fake)*10
                confidence = max(30, confidence)
                # Groq AI confirmation
                ai_verdict = ""
                try:
                    from engine.groq_ai import get_client, build_context
                    client = get_client()
                    if client:
                        ctx = build_context(broker)
                        tf_summary = " | ".join([f"{k}:{v['trend']}" for k,v in mtf.items() if k!="confluence" and isinstance(v,dict)])
                        prompt = (f"Market:{ctx}\n"
                                  f"Stock:{stock['symbol']} LTP={ltp} Direction={direction}\n"
                                  f"MTF:{tf_summary}\n"
                                  f"Confluence:{overall} score={score} {bull_tf if direction=='BUY' else bear_tf}/5 TF agree\n"
                                  f"RSI={rsi} VWAP={vwap_bias} MACD={macd_sig}\n"
                                  f"Entry={ltp} SL={sl} Target={target} RR={rr}\n"
                                  f"Give 1-line verdict: STRONG/MODERATE/WEAK signal + reason")
                        r = client.chat.completions.create(
                            model="llama-3.3-70b-versatile",
                            messages=[{"role":"user","content":prompt}],
                            max_tokens=60, temperature=0.1)
                        ai_verdict = r.choices[0].message.content.strip()
                except Exception as e:
                    logger.debug("Groq verdict: %s", e)
                # Skip weak signals
                if "WEAK" in ai_verdict.upper():
                    continue
                sig = {
                    "symbol":    stock["symbol"],
                    "type":      stock["type"],
                    "exchange":  stock["exch"],
                    "direction": direction,
                    "ltp":       ltp,
                    "entry":     ltp,
                    "sl":        sl,
                    "target":    target,
                    "rr":        rr,
                    "rsi":       rsi,
                    "confidence":confidence,
                    "overall":   overall,
                    "bull_tf":   bull_tf,
                    "bear_tf":   bear_tf,
                    "vwap_bias": vwap_bias,
                    "macd":      macd_sig,
                    "trend":     trend,
                    "fake":      fake,
                    "ai_verdict":ai_verdict,
                    "score":     score,
                    "scanned_at":now.strftime("%H:%M IST"),
                }
                signals.append(sig)
                logger.info("Prediction: %s %s conf=%d%% %s", stock["symbol"], direction, confidence, ai_verdict[:30])
            except Exception as e:
                logger.debug("Scan %s: %s", stock["symbol"], e)
        # Sort by confidence
        signals.sort(key=lambda x: -x["confidence"])
        _cache["signals"] = signals
        _cache["last_scan"] = now.strftime("%H:%M IST")
        # Save to file
        try:
            json.dump({"signals":signals,"scanned_at":_cache["last_scan"]},
                      open("data/chanakya_predictions.json","w"))
        except: pass
        logger.info("Prediction scan done: %d signals", len(signals))
        return signals
    except Exception as e:
        logger.error("Prediction scan: %s", e)
        return []

def get_cached_predictions():
    """Get cached predictions"""
    try:
        if os.path.exists("data/chanakya_predictions.json"):
            data = json.load(open("data/chanakya_predictions.json"))
            return data.get("signals",[]), data.get("scanned_at","")
    except: pass
    return _cache.get("signals",[]), _cache.get("last_scan","")
