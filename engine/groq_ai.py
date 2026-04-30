import os, logging
from groq import Groq
logger = logging.getLogger(__name__)

GROQ_KEY = os.getenv("GROQ_API_KEY","")
MODEL    = "llama-3.3-70b-versatile"

_client = None

def get_client():
    global _client
    if not _client:
        _client = Groq(api_key=GROQ_KEY)
    return _client

def analyze_signal(signal_data):
    sym    = signal_data.get("symbol","")
    entry  = signal_data.get("entry",0)
    sl     = signal_data.get("sl",0)
    target = signal_data.get("target",0)
    rsi    = signal_data.get("rsi",50)
    score  = signal_data.get("score",0)
    regime = signal_data.get("regime","SIDEWAYS")
    prompt = f"""You are Chanakya AI trading assistant. Analyze this trade:
Symbol: {sym}
Entry: Rs{entry} | SL: Rs{sl} | Target: Rs{target}
RSI: {rsi} | Score: {score} | Regime: {regime}
RR: {round((target-entry)/(entry-sl),2) if entry>sl else 0}
Give 2-line analysis: Should I take this trade? Risk level?"""
    try:
        r = get_client().chat.completions.create(
            model=MODEL,
            messages=[{"role":"user","content":prompt}],
            max_tokens=100
        )
        return r.choices[0].message.content.strip()
    except Exception as e:
        logger.error(f"Groq error: {e}")
        return "Analysis unavailable"

def chat(message, context=""):
    system = """You are Chanakya AI — expert Indian stock market trading assistant.
You help with NSE options, MCX commodities, equity trading.
Give concise, actionable advice. Use Rs for currency."""
    msgs = [{"role":"system","content":system}]
    if context:
        msgs.append({"role":"user","content":f"Context: {context}"})
        msgs.append({"role":"assistant","content":"Got it."})
    msgs.append({"role":"user","content":message})
    try:
        r = get_client().chat.completions.create(
            model=MODEL,
            messages=msgs,
            max_tokens=300
        )
        return r.choices[0].message.content.strip()
    except Exception as e:
        logger.error(f"Groq chat error: {e}")
        return "AI unavailable"
