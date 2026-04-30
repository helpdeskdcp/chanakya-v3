import os,logging,sqlite3,json
from datetime import datetime,timedelta
import pytz
logger=logging.getLogger(__name__)
GROQ_KEY=os.getenv("GROQ_API_KEY","")
MODEL="llama-3.3-70b-versatile"
_client=None
IST=pytz.timezone("Asia/Kolkata")

SYMBOLS=[
    ("NIFTY","99926000","NSE","index"),
    ("BANKNIFTY","99926009","NSE","index"),
    ("FINNIFTY","99926037","NSE","index"),
    ("CRUDEOIL","488290","MCX","commodity"),
    ("NATURALGAS","488505","MCX","commodity"),
    ("GOLD","67694","MCX","commodity"),
]

_scrip_master=None
def load_scrip_master():
    global _scrip_master
    if _scrip_master is None:
        try:
            data=json.load(open("data/scrip_master.json"))
            _scrip_master={}
            for s in data:
                sym=s.get("symbol","").upper().replace("-EQ","")
                if sym not in _scrip_master:
                    _scrip_master[sym]={"token":s.get("token",""),"exch":s.get("exch_seg","NSE"),"name":s.get("symbol","")}
        except Exception as e:
            logger.error("Scrip master: %s",e)
            _scrip_master={}
    return _scrip_master

def find_stock_token(broker,symbol):
    master=load_scrip_master()
    sym=symbol.upper().replace("-EQ","")
    return master.get(sym)

def get_client():
    global _client
    if not _client:
        try:
            from groq import Groq
            _client=Groq(api_key=GROQ_KEY)
        except Exception as e:
            logger.error("Groq: %s",e)
    return _client

def _ema(data,period):
    if len(data)<period:return data[-1] if data else 0
    k=2/(period+1);ema=sum(data[:period])/period
    for v in data[period:]:ema=v*k+ema*(1-k)
    return round(ema,2)

def _rsi(closes,period=14):
    if len(closes)<period+1:return 50
    gains,losses=[],[]
    for i in range(1,len(closes)):
        d=closes[i]-closes[i-1]
        gains.append(max(d,0));losses.append(max(-d,0))
    ag=sum(gains[-period:])/period;al=sum(losses[-period:])/period
    return round(100-(100/(1+ag/al)) if al>0 else 100,1)

def _macd(closes):
    if len(closes)<26:return 0,0
    ema12=_ema(closes,12);ema26=_ema(closes,26)
    macd=ema12-ema26
    # Signal line (9 EMA of MACD) approximation
    return round(macd,2),round(macd*0.15,2)

def _vwap(candles):
    tv=0;tpv=0
    for c in candles:
        p=(float(c[2])+float(c[3])+float(c[4]))/3
        v=float(c[5]);tv+=v;tpv+=p*v
    return round(tpv/tv,2) if tv>0 else 0

def fetch_candles(broker,token,exch,interval,days=2):
    try:
        from engine.rate_limiter import get_rate_limiter
        rl=get_rate_limiter()
        now=datetime.now(IST)
        rl.wait_if_needed("candleData")
        r=broker.api.getCandleData({
            "exchange":exch,"symboltoken":token,"interval":interval,
            "fromdate":(now-timedelta(days=days)).strftime("%Y-%m-%d")+" 09:00",
            "todate":now.strftime("%Y-%m-%d %H:%M"),
        })
        if r and r.get("data") and len(r["data"])>=5:
            return r["data"]
    except Exception as e:
        logger.debug("Candle %s %s: %s",token,interval,e)
    return []

def analyze_timeframe(candles,tf_name):
    if not candles or len(candles)<5:
        return None
    closes=[float(c[4]) for c in candles]
    highs=[float(c[2]) for c in candles]
    lows=[float(c[3]) for c in candles]
    vols=[float(c[5]) for c in candles]
    ltp=closes[-1]
    rsi=_rsi(closes)
    ema9=_ema(closes,9);ema21=_ema(closes,21);ema50=_ema(closes[-50:] if len(closes)>=50 else closes,50)
    macd_v,macd_h=_macd(closes)
    vwap=_vwap(candles[-50:] if len(candles)>=50 else candles)
    atr=sum([highs[i]-lows[i] for i in range(-min(10,len(highs)),0)])/min(10,len(highs))
    vol_avg=sum(vols)/len(vols)
    vol_ratio=round(vols[-1]/vol_avg,2) if vol_avg>0 else 1
    # Trend
    if ema9>ema21>ema50:trend="STRONG_UP"
    elif ema9>ema21:trend="UP"
    elif ema9<ema21<ema50:trend="STRONG_DOWN"
    elif ema9<ema21:trend="DOWN"
    else:trend="SIDEWAYS"
    # VWAP bias
    vwap_bias="ABOVE" if ltp>vwap else "BELOW"
    # MACD signal
    macd_sig="BULL" if macd_h>0 else "BEAR"
    # RSI zone
    if rsi>70:rsi_zone="OVERBOUGHT"
    elif rsi<30:rsi_zone="OVERSOLD"
    elif rsi>55:rsi_zone="BULLISH"
    elif rsi<45:rsi_zone="BEARISH"
    else:rsi_zone="NEUTRAL"
    # Fake signal check
    fake=[]
    if vol_ratio<0.7:fake.append("LowVol")
    if abs(macd_h)<0.05*ltp/100:fake.append("WeakMACD")
    if rsi_zone=="NEUTRAL":fake.append("NeutralRSI")
    # Score
    score=0
    if trend in ["STRONG_UP","UP"]:score+=30
    if vwap_bias=="ABOVE":score+=20
    if macd_sig=="BULL":score+=20
    if rsi_zone in ["BULLISH","OVERSOLD"]:score+=15
    if vol_ratio>=1.2:score+=15
    if fake:score-=len(fake)*10
    return {
        "tf":tf_name,"ltp":ltp,"rsi":rsi,"rsi_zone":rsi_zone,
        "ema9":ema9,"ema21":ema21,"ema50":ema50,
        "macd":macd_v,"macd_hist":macd_h,"macd_signal":macd_sig,
        "vwap":vwap,"vwap_bias":vwap_bias,
        "trend":trend,"vol_ratio":vol_ratio,"atr":round(atr,2),
        "score":score,"fake":fake,
        "sl":round(ltp-1.5*atr,2),"target":round(ltp+3*atr,2),
    }

def get_mtf_analysis(broker,symbol,token,exch="NSE"):
    """Multi-timeframe analysis: 1m 5m 15m 30m 1hr"""
    intervals=[
        ("ONE_MINUTE","1m",1),
        ("FIVE_MINUTE","5m",2),
        ("FIFTEEN_MINUTE","15m",5),
        ("THIRTY_MINUTE","30m",10),
        ("ONE_HOUR","1hr",20),
    ]
    results={}
    for interval,name,days in intervals:
        candles=fetch_candles(broker,token,exch,interval,days)
        ta=analyze_timeframe(candles,name)
        if ta:results[name]=ta
    # Confluence score
    if results:
        scores=[v["score"] for v in results.values()]
        confluence=round(sum(scores)/len(scores),1)
        trends=[v["trend"] for v in results.values()]
        bull_count=sum(1 for t in trends if "UP" in t)
        bear_count=sum(1 for t in trends if "DOWN" in t)
        if bull_count>=3:overall="BULLISH"
        elif bear_count>=3:overall="BEARISH"
        else:overall="SIDEWAYS"
        results["confluence"]={"score":confluence,"overall":overall,"bull_tf":bull_count,"bear_tf":bear_count}
    return results

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
    # Options signals cache
    try:
        cache=json.load(open("data/signal_cache.json"))
        sigs=[]
        for u,d in cache.items():
            for s in (d if isinstance(d,list) else []):
                if s.get("score",0)>0.6:
                    sigs.append(f"{s.get('symbol','')} {s.get('type','')} E={s.get('entry',0)} T={s.get('target',0)} SL={s.get('sl',0)} score={s.get('score',0):.0%}")
        if sigs:data["OPTIONS_SIGNALS"]=sigs[:5]
    except:pass
    return data

def build_context(broker=None):
    mkt=get_live_data(broker)
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
    if mkt.get("POSITIONS"):
        L.append("OPEN_TRADES:"+" | ".join([p["tsym"]+" E="+str(p["entry"]) for p in mkt["POSITIONS"][:3]]))
    if mkt.get("OPTIONS_SIGNALS"):
        L.append("FILTERED_OPTIONS:"+" | ".join(mkt["OPTIONS_SIGNALS"][:3]))
    ctx="\n".join(L)
    logger.info("Groq ctx: %s",ctx[:100])
    return ctx

def extract_stock_mentions(message):
    import re
    known=["NIFTY","BANKNIFTY","FINNIFTY","MIDCPNIFTY","CRUDEOIL","NATURALGAS",
           "GOLD","SILVER","COPPER","SENSEX","RELIANCE","TCS","INFY","WIPRO",
           "HDFCBANK","ICICIBANK","SBIN","AXISBANK","BAJFINANCE","TATAMOTORS",
           "ADANIENT","ONGC","COALINDIA","NTPC","POWERGRID","HINDALCO","JSWSTEEL",
           "TATASTEEL","MARUTI","HEROMOTOCO","BAJAJ-AUTO","EICHERMOT","M&M",
           "SUNPHARMA","DRREDDY","CIPLA","DIVISLAB","APOLLOHOSP","ASIANPAINT",
           "ULTRACEMCO","NESTLEIND","TITAN","TRENT","SUZLON","YESBANK","IRFC",
           "NHPC","RVNL","IRCTC","SAIL","IDEA","VEDL","BPCL","IOC","GAIL"]
    found=[]
    msg_upper=message.upper()
    for s in known:
        if s in msg_upper:found.append(s)
    words=re.findall(r"[A-Z]{3,}",message.upper())
    skip={"LTP","LIVE","AANI","KAAY","AAHE","DNYA","KARU","NSE","MCX","BSE","VWAP","MACD","RSI","EMA","ATR","BUY","SELL","SIGNAL","ANALYSIS","TECHNICAL"}
    for w in words:
        if w not in found and w not in skip:found.append(w)
    return list(set(found))

def chat(message,broker=None,extra_context=""):
    client=get_client()
    if not client:return "AI unavailable"
    ctx=build_context(broker)
    # MTF analysis for mentioned stocks
    mtf_ctx=""
    try:
        now=datetime.now(IST)
        h,mn=now.hour,now.minute
        market_open=(9,15)<=(h,mn)<=(15,30) and now.weekday()<5
        mcx_open=((9,0)<=(h,mn) or (h,mn)<=(23,30)) and now.weekday()<5
        stocks=extract_stock_mentions(message)
        for sym in stocks[:2]:
            # Find token
            info=None
            for name,token,exch,typ in SYMBOLS:
                if name==sym:
                    info={"token":token,"exch":exch,"name":name}
                    break
            if not info:
                info=find_stock_token(broker,sym)
            if info and broker and broker.connected:
                exch=info["exch"]
                is_open=(market_open and exch=="NSE") or (mcx_open and exch=="MCX")
                if is_open:
                    mtf=get_mtf_analysis(broker,sym,info["token"],exch)
                    if mtf:
                        parts=[f"=== {sym} MTF ANALYSIS ==="]
                        for tf,ta in mtf.items():
                            if tf=="confluence":
                                parts.append(f"CONFLUENCE: score={ta['score']} overall={ta['overall']} bull_tf={ta['bull_tf']}/5 bear_tf={ta['bear_tf']}/5")
                            else:
                                fake_warn=(" FAKE:"+str(ta["fake"])) if ta.get("fake") else ""
                                parts.append(f"{tf}: trend={ta['trend']} RSI={ta['rsi']}({ta['rsi_zone']}) VWAP={ta['vwap_bias']} MACD={ta['macd_signal']} vol={ta['vol_ratio']}x score={ta['score']}{fake_warn}")
                        if any("confluence" in k for k in mtf):
                            conf=mtf["confluence"]
                            ltp_val=mtf.get("5m",{}).get("ltp",0) or mtf.get("15m",{}).get("ltp",0)
                            atr_val=mtf.get("5m",{}).get("atr",0) or mtf.get("15m",{}).get("atr",0)
                            if ltp_val>0 and atr_val>0:
                                parts.append(f"LEVELS: Entry={ltp_val} SL={round(ltp_val-1.5*atr_val,1)} Target={round(ltp_val+3*atr_val,1)}")
                        mtf_ctx+="\n".join(parts)+"\n"
                else:
                    # Market closed — prev close
                    parts=[f"=== {sym} PREV DATA ==="]
                    candles=fetch_candles(broker,info["token"],exch,"FIVE_MINUTE",3)
                    if candles:
                        ta=analyze_timeframe(candles,"prev")
                        if ta:
                            parts.append(f"Prev close={ta['ltp']} trend={ta['trend']} RSI={ta['rsi']} VWAP={ta['vwap_bias']} score={ta['score']}")
                            parts.append(f"Levels: Entry={ta['ltp']} SL={ta['sl']} Target={ta['target']}")
                    mtf_ctx+="\n".join(parts)+"\n"
    except Exception as e:
        logger.error("MTF chat: %s",e)

    system=("You are Chanakya AI — expert Indian trading assistant with deep technical analysis expertise.\n\n"
            "LIVE MARKET DATA:\n"+ctx+"\n\n"
            +(("MULTI-TIMEFRAME ANALYSIS:\n"+mtf_ctx+"\n") if mtf_ctx else "")
            +"PREDICTION RULES:\n"
            "- Analyze 1m+5m+15m+30m+1hr confluence for prediction\n"
            "- STRONG signal = 3+ timeframes agree\n"
            "- VWAP above + EMA bullish + MACD bull = HIGH probability BUY\n"
            "- Filter fakes: low volume + weak MACD = SKIP\n"
            "- Always give: Direction, Entry, Target, SL, Confidence%\n"
            "- Mention which timeframes agree (confluence)\n"
            "- If fake signals detected, WARN user\n"
            "- Market closed: use prev data + next session prediction\n"
            "- Reply in same language as user (Marathi/Hindi/English)\n"
            "- Max 5 lines — be precise")
    try:
        r=client.chat.completions.create(
            model=MODEL,
            messages=[{"role":"system","content":system},{"role":"user","content":message}],
            max_tokens=400,temperature=0.2)
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
    prompt="Market:\n"+ctx+"\nSignal:"+sym+" BUY Rs"+str(entry)+" SL="+str(sl)+" T="+str(target)+" RSI="+str(rsi)+" RR="+str(rr)+"\n2-line analysis: Take? Risk? Confidence%?"
    try:
        r=client.chat.completions.create(
            model=MODEL,
            messages=[{"role":"user","content":prompt}],
            max_tokens=150,temperature=0.2)
        return r.choices[0].message.content.strip()
    except Exception as e:
        return "Error:"+str(e)
