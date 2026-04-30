import logging
logger = logging.getLogger(__name__)

SEGMENT_RULES = {
    "NSE_OPTIONS": {"min_score":70,"min_rr":2.5,"max_sl_pct":30,"min_volume_ratio":1.3,"rsi_buy":(48,68),"rsi_sell":(32,52),"max_vix":22,"block_sideways":True,"min_net_profit":150},
    "MCX_OPTIONS": {"min_score":70,"min_rr":2.0,"max_sl_pct":35,"min_volume_ratio":1.2,"rsi_buy":(45,70),"rsi_sell":(30,55),"max_vix":25,"block_sideways":True,"min_net_profit":200},
    "NSE_EQUITY":  {"min_score":65,"min_rr":2.0,"max_sl_pct":2.0,"min_volume_ratio":1.5,"rsi_buy":(50,68),"rsi_sell":(32,50),"max_vix":20,"block_sideways":True,"min_net_profit":100},
}
MCX_SYMS={"CRUDEOIL","NATURALGAS","GOLD","SILVER","COPPER"}

def detect_segment(d):
    exch=str(d.get("exchange","")).upper();sym=str(d.get("symbol","")).upper()
    stype=str(d.get("type","")).upper();opt=d.get("opt_type","")
    if stype=="EQUITY" or (exch=="NSE" and not opt):return "NSE_EQUITY"
    if exch=="MCX" or sym in MCX_SYMS:return "MCX_OPTIONS"
    return "NSE_OPTIONS"

def check_all(signal_data,market_data=None):
    passed=[];failed=[];d=signal_data;m=market_data or {}
    seg=detect_segment(d);rules=SEGMENT_RULES[seg]
    entry=float(d.get("entry",d.get("ltp",0)));sl=float(d.get("sl",d.get("sl_price",0)))
    target=float(d.get("target",d.get("target_price",0)))
    score=float(d.get("score_pct",d.get("score",0)))
    if score<1:score*=100
    rsi=float(d.get("rsi",50));vol=float(d.get("vol_ratio",1))
    net=float(d.get("net_profit",0));dirn=str(d.get("direction",d.get("opt_type","BUY"))).upper()
    vix=float(m.get("vix",d.get("vix",18)));regime=str(m.get("regime",d.get("regime","SIDEWAYS"))).upper()
    ltp=float(d.get("ltp",entry))
    if score>=rules["min_score"]:passed.append("Score ok")
    else:failed.append("Score low")
    rr=0
    if entry>0 and sl>0 and target>0:
        if dirn in ("BUY","CE"):rr=round((target-entry)/(entry-sl),2) if (entry-sl)>0 else 0
        else:rr=round((entry-target)/(sl-entry),2) if (sl-entry)>0 else 0
    if rr>=rules["min_rr"]:passed.append("RR ok")
    else:failed.append("RR low "+str(rr))
    if net<=0:passed.append("Net skip")
    elif net>=rules["min_net_profit"]:passed.append("Net ok")
    else:failed.append("Net low")
    if entry>0 and sl>0:
        sl_pct=abs(entry-sl)/entry*100
        if sl_pct<=rules["max_sl_pct"]:passed.append("SL ok")
        else:failed.append("SL high")
    if vol>=rules["min_volume_ratio"]:passed.append("Vol ok")
    elif vol==1.0:passed.append("Vol skip")
    else:failed.append("Vol low")
    rng=rules["rsi_buy"] if dirn in ("BUY","CE") else rules["rsi_sell"]
    if rng[0]<=rsi<=rng[1]:passed.append("RSI ok")
    else:failed.append("RSI out "+str(rsi))
    if rules["block_sideways"] and regime=="SIDEWAYS":failed.append("SIDEWAYS")
    elif dirn in ("BUY","CE") and "UP" in regime:passed.append("Regime ok")
    elif dirn in ("SELL","PE") and "DOWN" in regime:passed.append("Regime ok")
    else:passed.append("Regime neutral")
    if vix<=rules["max_vix"]:passed.append("VIX ok")
    else:failed.append("VIX high")
    from datetime import datetime;import pytz
    now=datetime.now(pytz.timezone("Asia/Kolkata"));h,mn=now.hour,now.minute
    if seg=="NSE_EQUITY":
        if (9,30)<=(h,mn)<=(15,25):passed.append("NSE open")
        elif (9,15)<=(h,mn)<(9,30):failed.append("no-trade")
        else:failed.append("NSE closed")
    elif seg=="MCX_OPTIONS":
        if (9,0)<=(h,mn)<=(23,30):passed.append("MCX open")
        else:failed.append("MCX closed")
    else:
        if (9,30)<=(h,mn)<=(15,30):passed.append("NSE open")
        else:failed.append("NSE closed")
    crit=["Score","RR","SL","RSI","SIDEWAYS","closed","no-trade"]
    ok=len([f for f in failed if any(k in f for k in crit)])==0
    logger.info("[%s] %s p=%d f=%d",seg,d.get("symbol",""),len(passed),len(failed))
    return ok,passed,failed

def filter_signals(signals,market_data=None):
    approved=[]
    for sig in signals:
        ok,p,f=check_all(sig,market_data)
        sig["guard_passed"]=ok;sig["guard_reasons"]=p;sig["guard_failed"]=f;sig["segment"]=detect_segment(sig)
        if ok:approved.append(sig)
    logger.info("Guard: %d/%d",len(approved),len(signals))
    return approved
