"""Chanakya AI Equity Scanner"""
import logging
logger = logging.getLogger(__name__)

WATCHLIST = [
    {"symbol":"RELIANCE","token":"2885"},{"symbol":"TCS","token":"11536"},
    {"symbol":"INFY","token":"1594"},{"symbol":"HDFCBANK","token":"1333"},
    {"symbol":"ICICIBANK","token":"4963"},{"symbol":"SBIN","token":"3045"},
    {"symbol":"WIPRO","token":"3787"},{"symbol":"TATAMOTORS","token":"3456"},
    {"symbol":"ITC","token":"1660"},{"symbol":"AXISBANK","token":"5900"},
    {"symbol":"BAJFINANCE","token":"317"},{"symbol":"HCLTECH","token":"1232"},
    {"symbol":"MARUTI","token":"10999"},{"symbol":"KOTAKBANK","token":"1922"},
    {"symbol":"SUNPHARMA","token":"3351"},{"symbol":"TITAN","token":"3506"},
    {"symbol":"ASIANPAINT","token":"236"},{"symbol":"BHARTIARTL","token":"10604"},
    {"symbol":"LTIM","token":"17818"},{"symbol":"NESTLEIND","token":"17963"},
]

def _ema(data,p):
    if len(data)<p: return data[-1] if data else 0
    k=2/(p+1); e=sum(data[:p])/p
    for d in data[p:]: e=d*k+e*(1-k)
    return e

def _rsi(closes,p=14):
    if len(closes)<p+1: return 50
    g=[max(closes[i]-closes[i-1],0) for i in range(1,len(closes))]
    l=[max(closes[i-1]-closes[i],0) for i in range(1,len(closes))]
    ag=sum(g[-p:])/p; al=sum(l[-p:])/p
    return round(100-100/(1+ag/al),1) if al>0 else 100

def scan_equity(broker, capital=10000):
    from engine.brokerage_calc import calc_equity_intraday, position_size_equity
    from engine.rate_limiter import get_rate_limiter
    from datetime import datetime
    import pytz
    rl=get_rate_limiter()
    IST=pytz.timezone("Asia/Kolkata")
    signals=[]
    for stock in WATCHLIST:
        try:
            rl.wait_if_needed("candleData")
            now=datetime.now(IST)
            r=broker.api.getCandleData({
                "exchange":"NSE","symboltoken":stock["token"],
                "interval":"FIVE_MINUTE",
                "fromdate":now.strftime("%Y-%m-%d")+" 09:15",
                "todate":now.strftime("%Y-%m-%d %H:%M"),
            })
            if not r or not r.get("data") or len(r["data"])<20: continue
            closes=[float(c[4]) for c in r["data"]]
            vols=[float(c[5]) for c in r["data"]]
            highs=[float(c[2]) for c in r["data"]]
            lows=[float(c[3]) for c in r["data"]]
            ltp=closes[-1]; rsi=_rsi(closes)
            ema9=_ema(closes,9); ema21=_ema(closes,21)
            vol_avg=sum(vols[-20:])/20
            vol_ratio=round(vols[-1]/vol_avg,2) if vol_avg>0 else 1
            bs=0
            if ema9>ema21: bs+=30
            if 45<rsi<70: bs+=25
            if vols[-1]>vol_avg*1.3: bs+=20
            if closes[-1]>closes[-5]: bs+=25
            if bs>=60:
                atr=sum([highs[i]-lows[i] for i in range(-10,0)])/10
                sl=round(ltp-1.5*atr,2); target=round(ltp+3*atr,2)
                from engine.brokerage_calc import position_size_equity
                qty=position_size_equity(capital,1.5,ltp,sl)
                if qty<=0: continue
                brok=calc_equity_intraday(ltp,target,qty)
                if brok["net_pnl"]<30: continue
                signals.append({
                    "symbol":stock["symbol"],"token":stock["token"],
                    "exchange":"NSE","direction":"BUY","ltp":ltp,
                    "entry":ltp,"sl":sl,"target":target,"qty":qty,
                    "score":round(bs/100,3),"rsi":rsi,"vol_ratio":vol_ratio,
                    "net_profit":brok["net_pnl"],"charges":brok["total_charges"],
                    "breakeven":brok["breakeven"],"rr":round(abs(target-ltp)/abs(ltp-sl),2),
                    "type":"EQUITY",
                })
        except Exception as e:
            logger.debug(f"Equity {stock['symbol']}: {e}")
    signals.sort(key=lambda x:x["score"],reverse=True)
    logger.info(f"Equity scan: {len(signals)} signals")
    return signals
