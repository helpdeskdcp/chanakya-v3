import os, logging
logger = logging.getLogger(__name__)

GROQ_KEY = os.getenv("GROQ_API_KEY","")
MODEL    = "llama-3.3-70b-versatile"
_client  = None

def get_client():
    global _client
    if not _client:
        try:
            from groq import Groq
            _client = Groq(api_key=GROQ_KEY)
        except Exception as e:
            logger.error(f"Groq init: {e}")
    return _client

def get_market_context(broker=None):
    """Get live market data from tickers cache"""
    ctx = {"vix": 18}
    try:
        from engine.token_manager import get_all_tokens
        from engine.rate_limiter import get_rate_limiter
        rl = get_rate_limiter()
        symbols = [
            ("NIFTY",      "99926000", "NSE"),
            ("BANKNIFTY",  "99926009", "NSE"),
            ("FINNIFTY",   "99926037", "NSE"),
            ("CRUDEOIL",   "488290",   "MCX"),
            ("NATURALGAS", "488505",   "MCX"),
        ]
        if broker and broker.connected:
            for name, token, exch in symbols:
                try:
                    rl.wait_if_needed("ltpData")
                    r = broker.api.ltpData(exch, name, token)
                    if r and r.get("data") and float(r["data"]["ltp"]) > 0:
                        ctx[name] = float(r["data"]["ltp"])
                except: pass
        from data.market import get_vix
        ctx["vix"] = get_vix() or 18
    except: pass
    return ctx

def build_context(broker=None):
    """Build rich context string for AI"""
    mkt = get_market_context(broker)
    parts = []
    if mkt.get("NIFTY"): parts.append(f"NIFTY={mkt['NIFTY']:.0f}")
    if mkt.get("BANKNIFTY"): parts.append(f"BANKNIFTY={mkt['BANKNIFTY']:.0f}")
    if mkt.get("CRUDEOIL"): parts.append(f"CRUDEOIL={mkt['CRUDEOIL']:.0f}")
    parts.append(f"VIX={mkt.get('vix',18)}")
    from datetime import datetime
    import pytz
    now = datetime.now(pytz.timezone("Asia/Kolkata"))
    parts.append(f"Time={now.strftime('%H:%M IST')}")
    ctx_str = " | ".join(parts)
    import logging; logging.getLogger(__name__).info(f"Groq context: {ctx_str}")
    return ctx_str

def chat(message, broker=None, extra_context=""):
    """Smart chat with live market context"""
    client = get_client()
    if not client: return "AI unavailable — groq not configured"
    live_ctx = build_context(broker)
    system = f"""You are Chanakya AI — expert Indian stock market trading assistant.
Current market: {live_ctx}
You help with NSE/NFO options, MCX commodities, equity trading.
Give concise, actionable advice in 2-3 lines. Use Rs for currency.
If user asks for signal, give: Direction, Entry, Target, SL."""
    try:
        r = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role":"system","content":system},
                {"role":"user","content":message}
            ],
            max_tokens=250
        )
        return r.choices[0].message.content.strip()
    except Exception as e:
        logger.error(f"Groq chat: {e}")
        return f"AI error: {e}"

def analyze_signal(signal_data, broker=None):
    """Analyze a trading signal with AI"""
    client = get_client()
    if not client: return "AI unavailable"
    sym    = signal_data.get("symbol","")
    entry  = signal_data.get("entry",0)
    sl     = signal_data.get("sl",0)
    target = signal_data.get("target",0)
    rsi    = signal_data.get("rsi",50)
    score  = signal_data.get("score",0)
    rr     = round((target-entry)/(entry-sl),2) if entry>sl else 0
    live_ctx = build_context(broker)
    prompt = f"""Market: {live_ctx}
Signal: {sym} BUY @ Rs{entry} | SL Rs{sl} | Target Rs{target}
RSI={rsi} Score={score} RR={rr}
2-line analysis: Take this trade? Risk?"""
    try:
        r = client.chat.completions.create(
            model=MODEL,
            messages=[{"role":"user","content":prompt}],
            max_tokens=100
        )
        return r.choices[0].message.content.strip()
    except Exception as e:
        return f"Analysis error: {e}"
