
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

def get_client():
    global _client
    if not _client:
        try:
            from groq import Groq
            _client=Groq(api_key=GROQ_KEY)
        except Exception as e:
            logger.error("Groq: %s",e)
    return _client
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
