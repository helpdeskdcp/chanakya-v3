"""Chanakya v3 — Option Chain Engine"""
import logging, sys
sys.path.insert(0, '/root/chanakya_v3')
from angel_live_chain_v3 import get_real_option_chain
logger = logging.getLogger(__name__)

_chain_cache = {}
import time

def get_chain(broker, symbol, force=False):
    global _chain_cache
    now = time.time()
    if not force and symbol in _chain_cache:
        data, ts = _chain_cache[symbol]
        if now - ts < 60:  # 1 min cache
            return data

    # Get spot price
    from config import config
    spot = 0
    idx_tokens = config.INDEX_TOKENS
    if symbol in idx_tokens:
        try:
            d = broker.api.ltpData("NSE", symbol, idx_tokens[symbol])
            if d and d.get("data"):
                spot = float(d["data"]["ltp"])
        except Exception:
            pass

    chain = get_real_option_chain(broker, symbol, spot=spot)
    if chain:
        _chain_cache[symbol] = (chain, now)
    return chain
