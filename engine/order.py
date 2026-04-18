"""
Chanakya v3 — Smart Order Execution Engine
AngelOne SmartAPI + Paper Mode + Retry Logic
"""
import logging, time, sqlite3
from datetime import datetime
import pytz
from config import config

logger = logging.getLogger(__name__)
IST = pytz.timezone("Asia/Kolkata")

# ── Tick Size Rounding ─────────────────────────────────
TICK_SIZES = {
    "NFO": 0.05, "BSE": 0.05,
    "MCX": 0.05, "NSE": 0.05,
}

def round_tick(price, exchange="NFO"):
    tick = TICK_SIZES.get(exchange, 0.05)
    return round(round(price / tick) * tick, 2)

# ── Smart Entry Price ──────────────────────────────────
def get_smart_entry(bid, ask, exchange="NFO"):
    """
    Calculate smart entry between bid/ask.
    Avoids paying full spread.
    """
    if not bid or not ask or ask <= bid:
        return round_tick(ask or bid or 0, exchange)
    spread = ask - bid
    if spread <= 0.5:
        # Tight spread — mid price
        entry = (bid + ask) / 2
    elif spread <= 2.0:
        # Normal spread — 40% from bid
        entry = bid + spread * 0.40
    else:
        # Wide spread — patient entry at bid
        entry = bid + spread * 0.25
    return round_tick(entry, exchange)

# ── Order Params Builder ───────────────────────────────
def build_order_params(symbol, token, exchange, opt_type,
                       entry, quantity, order_type="LIMIT",
                       product="CARRYFORWARD"):
    """Build AngelOne order params dict"""
    # NSE options use INTRADAY, MCX uses CARRYFORWARD
    if exchange == "NFO":
        product = "INTRADAY"
    return {
        "variety":          "NORMAL",
        "tradingsymbol":    symbol,
        "symboltoken":      token,
        "transactiontype":  "BUY",
        "exchange":         exchange,
        "ordertype":        order_type,
        "producttype":      product,
        "duration":         "DAY",
        "price":            str(round_tick(entry, exchange)),
        "squareoff":        "0",
        "stoploss":         "0",
        "quantity":         str(quantity),
    }

# ── Order Executor ─────────────────────────────────────
class OrderEngine:
    def __init__(self, broker):
        self.broker = broker

    def place_entry(self, trade_params):
        """
        Place entry order.
        Returns order_id or None
        """
        symbol   = trade_params["trading_symbol"]
        token    = trade_params["token"]
        exchange = trade_params["exchange"]
        entry    = trade_params["entry_price"]
        qty      = trade_params["quantity"]

        if config.PAPER_MODE:
            order_id = f"PAPER_{int(time.time())}"
            logger.info(f"📝 PAPER BUY: {symbol} @ ₹{entry} x {qty} = ₹{entry*qty:.0f}")
            return order_id

        # Live order with retry
        params = build_order_params(
            symbol, token, exchange,
            trade_params.get("opt_type", "CE"),
            entry, qty
        )
        for attempt in range(3):
            try:
                resp = self.broker.api.placeOrder(params)
                if resp and resp.get("status"):
                    order_id = resp["data"]["orderid"]
                    logger.info(f"✅ ORDER PLACED: {symbol} | ID: {order_id}")
                    return order_id
                else:
                    logger.warning(f"Order attempt {attempt+1} failed: {resp}")
            except Exception as e:
                logger.error(f"Order error attempt {attempt+1}: {e}")
                # Try reconnect if token expired
                if "token" in str(e).lower() or "session" in str(e).lower():
                    self.broker.connect()
            time.sleep(2)
        return None

    def place_exit(self, trade_id, exit_price, reason="MANUAL"):
        """Exit an open trade"""
        try:
            conn = sqlite3.connect(config.DB_PATH)
            conn.row_factory = sqlite3.Row
            trade = conn.execute(
                "SELECT * FROM trades WHERE id=? AND status='OPEN'", (trade_id,)
            ).fetchone()

            if not trade:
                conn.close()
                return False, "Trade not found"

            symbol   = trade["trading_symbol"] or trade["symbol"]
            token    = trade["token"]
            exchange = trade["exchange"] or "NFO"
            qty      = trade["quantity"]
            entry    = trade["entry_price"]
            lots     = trade["lots"]
            lot_size = trade["lot_size"]

            # Calculate P&L
            pnl = (exit_price - entry) * qty
            pnl_pct = round((exit_price - entry) / entry * 100, 2) if entry > 0 else 0

            if config.PAPER_MODE:
                logger.info(f"📝 PAPER EXIT: {symbol} @ ₹{exit_price} | P&L: ₹{pnl:.0f}")
            else:
                # Place sell order
                params = {
                    "variety":         "NORMAL",
                    "tradingsymbol":   symbol,
                    "symboltoken":     token or "",
                    "transactiontype": "SELL",
                    "exchange":        exchange,
                    "ordertype":       "MARKET",
                    "producttype":     "INTRADAY" if exchange == "NFO" else "CARRYFORWARD",
                    "duration":        "DAY",
                    "price":           "0",
                    "quantity":        str(qty),
                }
                try:
                    resp = self.broker.api.placeOrder(params)
                    if not (resp and resp.get("status")):
                        logger.warning(f"Exit order failed: {resp}")
                except Exception as e:
                    logger.error(f"Exit order error: {e}")

            # Update DB
            now = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S")
            conn.execute("""
                UPDATE trades SET
                    exit_price = ?, pnl = ?, pnl_pct = ?,
                    status = 'CLOSED', exit_reason = ?,
                    closed_at = ?, updated_at = ?
                WHERE id = ?
            """, (exit_price, pnl, pnl_pct, reason, now, now, trade_id))
            conn.commit()
            conn.close()

            result = "WIN" if pnl > 0 else "LOSS"
            logger.info(f"{'✅' if pnl>0 else '❌'} CLOSED: {symbol} | {result} ₹{pnl:.0f} | {reason}")
            return True, {"pnl": pnl, "pnl_pct": pnl_pct, "result": result}

        except Exception as e:
            logger.error(f"Exit error: {e}")
            return False, str(e)

    def save_trade(self, params, order_id):
        """Save new trade to DB"""
        try:
            now = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S")
            conn = sqlite3.connect(config.DB_PATH)

            # Calculate lots
            qty      = params.get("quantity", 1)
            lot_size = params.get("lot_size", 1)
            lots     = max(1, qty // lot_size)

            conn.execute("""
                INSERT INTO trades (
                    symbol, trading_symbol, token, exchange, opt_type, strike, expiry,
                    entry_price, sl_price, target_price, spot_at_entry,
                    quantity, lots, lot_size, status, mode, order_id,
                    strategy, signal_conf, ml_confidence, ce_score, pe_score,
                    vix_at_entry, pcr_at_entry, iv_at_entry, atr_at_entry,
                    planned_rr, created_at, updated_at
                ) VALUES (
                    ?,?,?,?,?,?,?,
                    ?,?,?,?,
                    ?,?,?,'OPEN',?,?,
                    ?,?,?,?,?,
                    ?,?,?,?,
                    ?,?,?
                )
            """, (
                params.get("symbol"), params.get("trading_symbol"),
                params.get("token"), params.get("exchange", "NFO"),
                params.get("opt_type"), params.get("strike", 0),
                params.get("expiry"),
                params.get("entry_price"), params.get("sl_price"),
                params.get("target_price"), params.get("spot", 0),
                qty, lots, lot_size,
                params.get("mode", "PAPER"), order_id,
                params.get("strategy"), params.get("signal_conf", 0),
                params.get("ml_confidence", 0),
                params.get("ce_score", 50), params.get("pe_score", 50),
                params.get("vix", 0), params.get("pcr", 0),
                params.get("iv", 0), params.get("atr", 0),
                params.get("rr", 0),
                now, now
            ))
            conn.commit()
            trade_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            conn.close()
            logger.info(f"✅ Trade saved: ID={trade_id} {params.get('symbol')} {params.get('opt_type')}")
            return trade_id
        except Exception as e:
            logger.error(f"Save trade error: {e}")
            return None

    def monitor_positions(self, broker):
        """
        Check open positions against SL/Target.
        Call this every 30 seconds.
        """
        try:
            conn = sqlite3.connect(config.DB_PATH)
            conn.row_factory = sqlite3.Row
            open_trades = conn.execute(
                "SELECT * FROM trades WHERE status='OPEN'"
            ).fetchall()
            conn.close()

            if not open_trades:
                return

            for trade in open_trades:
                token    = trade["token"]
                exchange = trade["exchange"] or "NFO"
                entry    = trade["entry_price"]
                sl       = trade["sl_price"]
                target   = trade["target_price"]
                trade_id = trade["id"]
                symbol   = trade["trading_symbol"] or trade["symbol"]

                if not token:
                    continue

                # Get current LTP
                ltp = broker.get_ltp(exchange, symbol, token)
                if not ltp or ltp <= 0:
                    continue

                # Update current P&L
                qty = trade["quantity"] or 1
                curr_pnl = (ltp - entry) * qty
                conn = sqlite3.connect(config.DB_PATH)
                conn.execute(
                    "UPDATE trades SET current_price=?, current_pnl=? WHERE id=?",
                    (ltp, curr_pnl, trade_id)
                ) if hasattr(trade, 'keys') and 'current_price' in trade.keys() else None
                conn.commit()
                conn.close()

                # SL hit?
                if sl and ltp <= sl:
                    self.place_exit(trade_id, ltp, "SL_HIT")
                    continue

                # Target hit?
                if target and ltp >= target:
                    self.place_exit(trade_id, ltp, "TARGET_HIT")
                    continue

                logger.debug(f"📊 {symbol}: LTP={ltp} | Entry={entry} | P&L=₹{curr_pnl:.0f}")

        except Exception as e:
            logger.error(f"Monitor error: {e}")

