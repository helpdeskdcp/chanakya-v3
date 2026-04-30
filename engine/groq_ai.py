
def find_stock_token(broker, symbol):
    """Dynamically find stock token using Angel One searchScrip"""
    if not (broker and broker.connected):
        return None
    try:
        # Try NSE first
        for exch in ["NSE","BSE","MCX"]:
            r = broker.api.searchScrip(exch, symbol.upper())
            if r and r.get("data"):
                for s in r["data"]:
                    if s.get("tradingsymbol","").upper() == symbol.upper()+"-EQ" or                        s.get("tradingsymbol","").upper() == symbol.upper():
                        return {
                            "token": s.get("symboltoken",""),
                            "exch":  exch,
                            "name":  s.get("tradingsymbol",""),
                        }
    except: pass
    return None

def get_any_ltp(broker, symbol):
    """Get LTP for any stock — live or prev close"""
    if not (broker and broker.connected):
        return None, None
    # Check known symbols first
    for name,token,exch,typ in SYMBOLS:
        if name.upper() == symbol.upper():
            try:
                from engine.rate_limiter import get_rate_limiter
                get_rate_limiter().wait_if_needed("ltpData")
                r = broker.api.ltpData(exch, name, token)
                if r and r.get("data"):
                    return float(r["data"]["ltp"]), exch
            except: pass
    # Dynamic search
    info = find_stock_token(broker, symbol)
    if info:
        try:
            from engine.rate_limiter import get_rate_limiter
            get_rate_limiter().wait_if_needed("ltpData")
            r = broker.api.ltpData(info["exch"], info["name"], info["token"])
            if r and r.get("data"):
                return float(r["data"]["ltp"]), info["exch"]
        except: pass
    return None, None

import os,logging,sqlite3
from datetime import datetime
import pytz
logger=logging.getLogger(__name__)
GROQ_KEY=os.getenv("GROQ_API_KEY","")
MODEL="llama-3.3-70b-versatile"
_client=None
SYMBOLS=[
    ("NIFTY","99926000","NSE","index"),
    ("BANKNIFTY","99926009","NSE","index"),
    ("FINNIFTY","99926037","NSE","index"),
    ("CRUDEOIL","488290","MCX","commodity"),
    ("NATURALGAS","488505","MCX","commodity"),
    ("GOLD","67694","MCX","commodity"),
]

_scrip_master = None

def load_scrip_master():
    global _scrip_master
    if _scrip_master is None:
        try:
            import json
            data = json.load(open("data/scrip_master.json"))
            # Index by symbol for fast lookup
            _scrip_master = {}
            for s in data:
                sym = s.get("symbol","").upper().replace("-EQ","")
                exch = s.get("exch_seg","NSE")
                if sym not in _scrip_master:
                    _scrip_master[sym] = {"token":s.get("token",""),"exch":exch,"name":s.get("symbol","")}
        except Exception as e:
            logger.error("Scrip master: %s",e)
            _scrip_master = {}
    return _scrip_master

def find_stock_token(broker, symbol):
    """Find token from scrip master — no API call needed"""
    master = load_scrip_master()
    sym = symbol.upper().replace("-EQ","")
    if sym in master:
        return master[sym]
    return None


_scrip_master = None

def load_scrip_master():
    global _scrip_master
    if _scrip_master is None:
        try:
            import json
            data = json.load(open("data/scrip_master.json"))
            # Index by symbol for fast lookup
            _scrip_master = {}
            for s in data:
                sym = s.get("symbol","").upper().replace("-EQ","")
                exch = s.get("exch_seg","NSE")
                if sym not in _scrip_master:
                    _scrip_master[sym] = {"token":s.get("token",""),"exch":exch,"name":s.get("symbol","")}
        except Exception as e:
            logger.error("Scrip master: %s",e)
            _scrip_master = {}
    return _scrip_master

def find_stock_token(broker, symbol):
    """Find token from scrip master — no API call needed"""
    master = load_scrip_master()
    sym = symbol.upper().replace("-EQ","")
    if sym in master:
        return master[sym]
    return None

def get_client():
    global _client
    if not _client:
        try:
            from groq import Groq
            _client=Groq(api_key=GROQ_KEY)
        except Exception as e:
            logger.error("Groq: %s",e)
    return _client

def get_technical_analysis(broker, symbol, token, exch="NSE"):
    """Get VWAP, MACD, EMA, RSI for any stock"""
    try:
        from engine.rate_limiter import get_rate_limiter
        from engine.equity_scanner import _ema, _rsi, _macd, _vwap
        from datetime import datetime, timedelta
        import pytz
        rl = get_rate_limiter()
        IST = pytz.timezone("Asia/Kolkata")
        now = datetime.now(IST)
        rl.wait_if_needed("candleData")
        r = broker.api.getCandleData({
            "exchange": exch,
            "symboltoken": token,
            "interval": "FIVE_MINUTE",
            "fromdate": (now-timedelta(days=2)).strftime("%Y-%m-%d")+" 09:15",
            "todate": now.strftime("%Y-%m-%d %H:%M"),
        })
        if not r or not r.get("data") or len(r["data"]) < 10:
            return {}
        candles = r["data"]
        closes = [float(c[4]) for c in candles]
        highs  = [float(c[2]) for c in candles]
        lows   = [float(c[3]) for c in candles]
        vols   = [float(c[5]) for c in candles]
        ltp    = closes[-1]
        rsi    = _rsi(closes)
        ema9   = _ema(closes, 9)
        ema21  = _ema(closes, 21)
        ema50  = _ema(closes[-50:] if len(closes)>=50 else closes, 50)
        macd_v, macd_h = _macd(closes)
        # VWAP
        vwap = _vwap(candles) if len(candles)>=5 else ltp
        # ATR
        atr = sum([highs[i]-lows[i] for i in range(-10,0)])/10
        # Volume ratio
        vol_avg = sum(vols)/len(vols)
        vol_ratio = round(vols[-1]/vol_avg,2) if vol_avg>0 else 1
        # Signals
        ema_cross = "BULLISH" if ema9>ema21 else "BEARISH"
        vwap_bias = "ABOVE VWAP (Bullish)" if ltp>vwap else "BELOW VWAP (Bearish)"
        macd_signal = "BULLISH CROSS" if macd_h>0 else "BEARISH CROSS"
        # Fake signal filter
        fake = []
        if vol_ratio < 0.7: fake.append("Low Volume")
        if abs(macd_h) < 0.1: fake.append("Weak MACD")
        if 45<rsi<55: fake.append("RSI Neutral")
        return {
            "ltp": ltp, "rsi": round(rsi,1),
            "ema9": round(ema9,1), "ema21": round(ema21,1), "ema50": round(ema50,1),
            "macd_hist": round(macd_h,2), "macd_signal": macd_signal,
            "vwap": round(vwap,1), "vwap_bias": vwap_bias,
            "ema_cross": ema_cross, "vol_ratio": vol_ratio,
            "atr": round(atr,2), "fake_signals": fake,
            "entry": round(ltp,1),
            "sl": round(ltp-1.5*atr,1),
            "target": round(ltp+3*atr,1),
        }
    except Exception as e:
        logger.debug("TA error %s: %s", symbol, e)
        return {}

def get_options_signals(broker):
    """Get filtered options signals from signal cache"""
    try:
        import json, os
        cache_file = "data/signal_cache.json"
        if not os.path.exists(cache_file):
            return []
        cache = json.load(open(cache_file))
        sigs = []
        for user, data in cache.items():
            for s in (data if isinstance(data,list) else []):
                if s.get("score",0) > 0.6:
                    sigs.append({
                        "symbol": s.get("symbol",""),
                        "direction": s.get("type",""),
                        "entry": s.get("entry",0),
                        "target": s.get("target",0),
                        "sl": s.get("sl",0),
                        "score": s.get("score",0),
                        "rsi": s.get("rsi",50),
                    })
        return sigs[:5]
    except:
        return []

def get_live_data(broker=None):
    data={}
    if not(broker and broker.connected):return data
    try:
        from engine.rate_limiter import get_rate_limiter
        rl=get_rate_limiter()
        for name,token,exch,typ in SYMBOLS:
            try:
                rl.wait_if_needed("ltpData")
                r=broker.api.ltpData(exch,name,token)
                if r and r.get("data"):
                    ltp=float(r["data"]["ltp"])
                    if ltp>0:data[name]={"ltp":ltp,"type":typ}
            except:pass
    except:pass
    try:
        from data.market import get_vix
        data["VIX"]={"ltp":get_vix() or 18,"type":"index"}
    except:data["VIX"]={"ltp":18,"type":"index"}
    try:
        conn=sqlite3.connect("data/chanakya_v3.db")
        pos=conn.execute("SELECT trading_symbol,entry_price,sl_price,target_price FROM trades WHERE status=? LIMIT 5",("OPEN",)).fetchall()
        conn.close()
        if pos:data["POSITIONS"]=[{"tsym":p[0],"entry":p[1],"sl":p[2],"target":p[3]} for p in pos]
    except:pass
    return data
def build_context(broker=None):
    mkt=get_live_data(broker)
    IST=pytz.timezone("Asia/Kolkata")
    now=datetime.now(IST)
    h,mn=now.hour,now.minute
    nse=(9,15)<=(h,mn)<=(15,30) and now.weekday()<5
    mcx=((9,0)<=(h,mn) or (h,mn)<=(23,30)) and now.weekday()<5
    L=[]
    L.append("Time:"+now.strftime("%H:%M IST %d-%b-%Y"))
    L.append("NSE:"+("OPEN" if nse else "CLOSED")+"|MCX:"+("OPEN" if mcx else "CLOSED"))
    idx=[(n,d["ltp"]) for n,d in mkt.items() if d.get("type")=="index" and n!="VIX" and d["ltp"]>0]
    if idx:L.append("INDICES:"+" | ".join([n+"="+str(int(v)) for n,v in idx]))
    L.append("VIX="+str(mkt.get("VIX",{}).get("ltp",18)))
    comm=[(n,d["ltp"]) for n,d in mkt.items() if d.get("type")=="commodity" and d["ltp"]>0]
    if comm:L.append("MCX:"+" | ".join([n+"="+str(int(v)) for n,v in comm]))
    if mkt.get("POSITIONS"):L.append("TRADES:"+" | ".join([p["tsym"]+" E="+str(p["entry"]) for p in mkt["POSITIONS"][:3]]))
    ctx="\n".join(L)
    logger.info("Groq ctx:%s",ctx[:80])
    return ctx
def extract_stock_mentions(message):
    """Extract stock/index names from user message"""
    import re
    known = ["NIFTY","BANKNIFTY","FINNIFTY","MIDCPNIFTY","CRUDEOIL","NATURALGAS",
             "GOLD","SILVER","COPPER","SENSEX","RELIANCE","TCS","INFY","WIPRO",
             "HDFCBANK","ICICIBANK","SBIN","AXISBANK","BAJFINANCE","TATAMOTORS",
             "ADANIENT","ONGC","COALINDIA","NTPC","POWERGRID","HINDALCO","JSWSTEEL",
             "TATASTEEL","MARUTI","HEROMOTOCO","BAJAJ-AUTO","EICHERMOT","M&M",
             "SUNPHARMA","DRREDDY","CIPLA","DIVISLAB","APOLLOHOSP","ASIANPAINT",
             "ULTRACEMCO","SHREECEM","GRASIM","NESTLEIND","TITAN","TRENT"]
    found = []
    msg_upper = message.upper()
    for s in known:
        if s in msg_upper or s.replace("-","") in msg_upper.replace("-",""):
            found.append(s)
    # Also extract unknown caps words
    words = re.findall(r"[A-Z]{3,}", message.upper())
    for w in words:
        if w not in found and w not in ["LTP","LIVE","AANI","KAAY","AAHE","DNYA","KARU","NSE","MCX","BSE"]:
            found.append(w)
    return list(set(found))

def chat(message,broker=None,extra_context=""):
    client=get_client()
    if not client:return "AI unavailable"
    ctx=build_context(broker)
    # Fetch LTP for any stocks mentioned in message
    extra_ltp = []
    try:
        stocks = extract_stock_mentions(message)
        for sym in stocks[:5]:
            ltp, exch = get_any_ltp(broker, sym)
            if ltp and ltp > 0:
                extra_ltp.append(f"{sym}={ltp:.2f} ({exch})")
        if extra_ltp:
            ctx += "\nMENTIONED STOCKS: " + " | ".join(extra_ltp)
    except: pass
    system="You are Chanakya AI, expert Indian trading assistant.\n\nLIVE DATA:\n"+ctx+"\n\nRULES:\n- Use ONLY above live data\n- Give Entry/Target/SL for signals\n- Mention risk: Low/Medium/High\n- Reply in same language as user\n- Max 3-4 lines"
    try:
        r=client.chat.completions.create(model=MODEL,messages=[{"role":"system","content":system},{"role":"user","content":message}],max_tokens=300,temperature=0.3)
        return r.choices[0].message.content.strip()
    except Exception as e:
        return "AI error:"+str(e)
def analyze_signal(signal_data,broker=None):
    client=get_client()
    if not client:return "AI unavailable"
    ctx=build_context(broker)
    sym=signal_data.get("symbol","");entry=signal_data.get("entry",0)
    sl=signal_data.get("sl",0);target=signal_data.get("target",0)
    rsi=signal_data.get("rsi",50);score=signal_data.get("score",0)
    rr=round((target-entry)/(entry-sl),2) if entry>sl else 0
    prompt="Market:\n"+ctx+"\nSignal:"+sym+" BUY Rs"+str(entry)+" SL="+str(sl)+" T="+str(target)+" RSI="+str(rsi)+" RR="+str(rr)+"\n2-line analysis: Take? Risk?"
    try:
        r=client.chat.completions.create(model=MODEL,messages=[{"role":"user","content":prompt}],max_tokens=100,temperature=0.2)
        return r.choices[0].message.content.strip()
    except Exception as e:
        return "Error:"+str(e)
