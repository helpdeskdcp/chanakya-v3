import logging, requests
from datetime import datetime
import pytz
logger = logging.getLogger(__name__)
IST = pytz.timezone("Asia/Kolkata")

def get_nse_session():
    """Get proper NSE session with cookies"""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120",
        "Accept": "text/html,application/json,*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Referer": "https://www.nseindia.com/",
    }
    s = requests.Session()
    try:
        s.get("https://www.nseindia.com", headers=headers, timeout=8)
        s.get("https://www.nseindia.com/option-chain", headers=headers, timeout=8)
    except: pass
    s.headers.update(headers)
    return s

def get_pcr_oi(broker, symbol="NIFTY"):
    """Get PCR and OI data safely"""
    try:
        from engine.rate_limiter import get_rate_limiter
        rl = get_rate_limiter()
        rl.wait_if_needed("ltpData")
        # Get expiry
        now = datetime.now(IST)
        r = broker.api.allTradeBook()
        # Use NSE option chain API
        headers = {"User-Agent":"Mozilla/5.0"}
        url = f"https://www.nseindia.com/api/option-chain-indices?symbol={symbol}"
        s = get_nse_session()
        resp = s.get(url, timeout=8)
        if resp.status_code == 200:
            data = resp.json()
            records = data.get("records", {})
            filtered = data.get("filtered",{})
            ce_oi = filtered.get("CE",{}).get("totOI",0) or sum(r.get("CE",{}).get("openInterest",0) for r in records.get("data",[]) if r.get("CE"))
            pe_oi = filtered.get("PE",{}).get("totOI",0) or sum(r.get("PE",{}).get("openInterest",0) for r in records.get("data",[]) if r.get("PE"))
            pcr = round(pe_oi/ce_oi, 2) if ce_oi > 0 else 1.0
            # Max pain
            strikes = {}
            for r in records.get("data",[]):
                strike = r.get("strikePrice",0)
                ce_pain = r.get("CE",{}).get("openInterest",0)
                pe_pain = r.get("PE",{}).get("openInterest",0)
                strikes[strike] = ce_pain + pe_pain
            max_pain = min(strikes, key=strikes.get) if strikes else 0
            # ATM strike
            atm = records.get("underlyingValue", 0)
            # Support/Resistance from OI
            sorted_pe = sorted([(r.get("strikePrice",0), r.get("PE",{}).get("openInterest",0)) for r in records.get("data",[]) if r.get("PE")], key=lambda x:-x[1])
            sorted_ce = sorted([(r.get("strikePrice",0), r.get("CE",{}).get("openInterest",0)) for r in records.get("data",[]) if r.get("CE")], key=lambda x:-x[1])
            support = sorted_pe[0][0] if sorted_pe else 0
            resistance = sorted_ce[0][0] if sorted_ce else 0
            return {
                "pcr": pcr,
                "max_pain": max_pain,
                "atm": atm,
                "ce_oi": ce_oi,
                "pe_oi": pe_oi,
                "support_oi": support,
                "resistance_oi": resistance,
                "bias": "BULLISH" if pcr > 1.2 else "BEARISH" if pcr < 0.8 else "NEUTRAL",
            }
    except Exception as e:
        logger.debug("PCR error: %s", e)
    return {"pcr": 1.0, "bias": "NEUTRAL", "max_pain": 0, "support_oi": 0, "resistance_oi": 0}

def get_news_sentiment(symbol="NIFTY"):
    """Get market news and sentiment"""
    try:
        headers = {"User-Agent":"Mozilla/5.0"}
        # NSE news
        url = "https://www.nseindia.com/api/marketStatus"
        r = requests.get(url, headers=headers, timeout=5)
        news = []
        if r.status_code == 200:
            data = r.json()
            news.append(f"Market: {data.get('marketState',[{}])[0].get('marketStatus','')}")
        return news
    except:
        return []

def get_fii_dii(broker=None):
    """Get FII/DII data"""
    try:
        headers = {"User-Agent":"Mozilla/5.0"}
        s = get_nse_session()
        r = s.get("https://www.nseindia.com/api/fiidiiTradeReact", timeout=8)
        if r.status_code == 200:
            data = r.json()
            if data:
                latest = data[0]
                fii_net = float(latest.get("fiiNetDii","0").replace(",","")) if latest.get("fiiNetDii") else 0
                dii_net = float(latest.get("diiNetDii","0").replace(",","")) if latest.get("diiNetDii") else 0
                return {"fii_net": fii_net, "dii_net": dii_net,
                        "fii_bias": "BUYING" if fii_net > 0 else "SELLING",
                        "dii_bias": "BUYING" if dii_net > 0 else "SELLING"}
    except Exception as e:
        logger.debug("FII: %s", e)
    return {"fii_net": 0, "dii_net": 0, "fii_bias": "UNKNOWN", "dii_bias": "UNKNOWN"}

def detect_pattern(candles):
    """Detect chart patterns"""
    try:
        if len(candles) < 20:
            return []
        closes = [float(c[4]) for c in candles]
        highs  = [float(c[2]) for c in candles]
        lows   = [float(c[3]) for c in candles]
        patterns = []
        # Breakout detection
        recent_high = max(highs[-20:-1])
        recent_low  = min(lows[-20:-1])
        ltp = closes[-1]
        if ltp > recent_high * 1.002:
            patterns.append("BREAKOUT_UP")
        elif ltp < recent_low * 0.998:
            patterns.append("BREAKOUT_DOWN")
        # Double top
        if len(highs) >= 20:
            h1 = max(highs[-20:-10])
            h2 = max(highs[-10:])
            if abs(h1-h2)/h1 < 0.01:
                patterns.append("DOUBLE_TOP")
        # Double bottom
        if len(lows) >= 20:
            l1 = min(lows[-20:-10])
            l2 = min(lows[-10:])
            if abs(l1-l2)/l1 < 0.01:
                patterns.append("DOUBLE_BOTTOM")
        # Bollinger squeeze
        import statistics
        if len(closes) >= 20:
            mean = sum(closes[-20:])/20
            std  = statistics.stdev(closes[-20:])
            bb_upper = mean + 2*std
            bb_lower = mean - 2*std
            bb_width = (bb_upper-bb_lower)/mean
            if bb_width < 0.02:
                patterns.append("BB_SQUEEZE")
        return patterns
    except:
        return []

def get_telegram_config():
    """Get telegram config if exists"""
    try:
        bot_token = os.getenv("TELEGRAM_BOT_TOKEN","")
        chat_id   = os.getenv("TELEGRAM_CHAT_ID","")
        return bot_token, chat_id
    except:
        return "",""

def send_telegram(message):
    """Send telegram alert safely"""
    try:
        import os
        bot_token = os.getenv("TELEGRAM_BOT_TOKEN","")
        chat_id   = os.getenv("TELEGRAM_CHAT_ID","")
        if not bot_token or not chat_id:
            return False
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        requests.post(url, json={"chat_id":chat_id,"text":message,"parse_mode":"HTML"}, timeout=5)
        return True
    except:
        return False

def send_signal_alert(signal):
    """Format and send signal to telegram"""
    try:
        msg = (f"🚀 <b>CHANAKYA AI SIGNAL</b>\n"
               f"Symbol: {signal.get('symbol','')}\n"
               f"Direction: {signal.get('direction','BUY')}\n"
               f"Entry: Rs{signal.get('entry',0)}\n"
               f"Target: Rs{signal.get('target',0)}\n"
               f"SL: Rs{signal.get('sl',0)}\n"
               f"Score: {signal.get('score',0):.0%}\n"
               f"Confidence: {signal.get('confidence','Medium')}")
        return send_telegram(msg)
    except:
        return False
