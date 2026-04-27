"""
Chanakya AI — Broker Live Position Sync + Auto Exit
Syncs Angel One open positions → DB → Trailing SL → Auto Exit
"""
import sqlite3, logging, time
from datetime import datetime
import pytz

logger = logging.getLogger(__name__)
IST = pytz.timezone("Asia/Kolkata")

LOT_SIZES = {"NIFTY":75,"BANKNIFTY":30,"FINNIFTY":40,
             "CRUDEOIL":100,"NATURALGAS":250,"SENSEX":10}

EXCH_MAP = {"NFO":"NFO","MCX":"MCX","NSE":"NSE","BSE":"BSE"}

# Trailing SL config
TRAIL_CONFIG = {
    "profit_to_trail":  0.20,  # Start trailing at 20% profit
    "trail_pct":        0.10,  # Trail SL at 10% below current LTP
    "hard_sl_pct":      0.30,  # Hard stop loss 30%
    "target1_pct":      0.50,  # First target 50%
    "target2_pct":      0.75,  # Second target 75%
    "target3_pct":      1.00,  # Third target 100%
}


def sync_broker_positions(broker, username, db_path="data/chanakya_v3.db"):
    """Fetch open positions from Angel One and sync to DB"""
    try:
        r = broker.api.position()
        if not r or not r.get("data"):
            return 0

        positions = r["data"]
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        synced = 0

        for pos in positions:
            try:
                # Skip closed positions
                netqty = int(pos.get("netqty", 0))
                if netqty == 0:
                    continue

                symbol    = pos.get("tradingsymbol", "")
                token     = pos.get("symboltoken", "")
                exchange  = pos.get("exchange", "NFO")
                prod_type = pos.get("producttype", "")
                # Angel One — accurate entry price
                avg_price = float(
                    pos.get("netprice") or
                    pos.get("avgnetprice") or
                    pos.get("totalbuyavgprice") or
                    pos.get("buyavgprice") or 0
                )
                # If netprice is 0 (mixed buy/sell), use buyavgprice
                if avg_price == 0:
                    avg_price = float(pos.get("buyavgprice") or 0)
                ltp       = float(pos.get("ltp") or 0)
                qty       = abs(netqty)
                opt_type  = "CE" if symbol.endswith("CE") else "PE" if symbol.endswith("PE") else "CE"

                # Get base symbol
                base_sym = "NIFTY"
                for s in LOT_SIZES:
                    if symbol.startswith(s):
                        base_sym = s
                        break

                lot_size_api = int(pos.get("lotsize") or 0)
                lot_size = lot_size_api if lot_size_api > 0 else LOT_SIZES.get(base_sym, 1)
                # For NATURALGAS — 1 lot = 1250 qty (as per Angel One)
                # but our lot_size should match our system
                sys_lot = LOT_SIZES.get(base_sym, lot_size)
                lots = max(1, qty // sys_lot) if sys_lot > 0 else 1
                lots = max(1, qty // lot_size)

                if avg_price <= 0:
                    continue

                # Check if already in DB
                ex = conn.execute(
                    "SELECT id,entry_price,sl_price,target_price FROM trades WHERE trading_symbol=? AND status='OPEN' AND username=?",
                    (symbol, username)
                ).fetchone()

                if not ex:
                    # New broker position — add to DB
                    now = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S")
                    # SL: -30% from entry
                    sl     = round(avg_price * (1 - TRAIL_CONFIG["hard_sl_pct"]), 2)
                    # Target: +50% from entry
                    target = round(avg_price * (1 + TRAIL_CONFIG["target1_pct"]), 2)
                    # Target 2 and 3 stored as metadata
                    t2 = round(avg_price * (1 + TRAIL_CONFIG["target2_pct"]), 2)
                    t3 = round(avg_price * (1 + TRAIL_CONFIG["target3_pct"]), 2)
                    logger.info(f"📊 {symbol}: E=₹{avg_price} SL=₹{sl} T1=₹{target} T2=₹{t2} T3=₹{t3}")

                    conn.execute("""
                        INSERT INTO trades
                        (username,symbol,exchange,opt_type,trading_symbol,token,
                         entry_price,sl_price,target_price,lots,lot_size,quantity,
                         status,mode,strategy,created_at,updated_at)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """, (username, base_sym, exchange, opt_type, symbol, token,
                          avg_price, sl, target, lots, sys_lot, qty,
                          "OPEN", "LIVE", "BROKER_SYNC", now, now))
                    logger.info(f"✅ Synced broker position: {symbol} E=₹{avg_price} qty={qty}")
                    synced += 1
                else:
                    # Update LTP
                    conn.execute(
                        "UPDATE trades SET updated_at=? WHERE id=?",
                        (datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S"), ex["id"])
                    )

            except Exception as e:
                logger.debug(f"Sync pos error: {e}")
                continue

        conn.commit()
        conn.close()
        return synced

    except Exception as e:
        logger.error(f"sync_broker_positions: {e}")
        return 0


def monitor_and_trail(broker, username, db_path="data/chanakya_v3.db"):
    """Monitor open positions — trailing SL + auto exit"""
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        positions = conn.execute(
            "SELECT * FROM trades WHERE status='OPEN' AND username=?",
            (username,)
        ).fetchall()
        conn.close()

        if not positions:
            return

        for pos in positions:
            try:
                _process_position(broker, pos, username, db_path)
            except Exception as e:
                logger.debug(f"Monitor error #{pos['id']}: {e}")

    except Exception as e:
        logger.error(f"monitor_and_trail: {e}")


def _process_position(broker, pos, username, db_path):
    """Process single position — get LTP, trail SL, auto exit"""
    # Get live LTP
    if not pos["trading_symbol"] or not pos["token"]:
        return

    r = broker.api.ltpData(
        pos["exchange"] or "NFO",
        pos["trading_symbol"],
        str(pos["token"])
    )
    if not r or not r.get("data"):
        return

    ltp    = float(r["data"]["ltp"])
    entry  = float(pos["entry_price"] or 0)
    sl     = float(pos["sl_price"] or 0)
    target = float(pos["target_price"] or 0)
    qty    = int(pos["quantity"] or pos["lot_size"] or 1)
    pid    = pos["id"]

    if entry <= 0 or ltp <= 0:
        return

    pnl     = (ltp - entry) * qty
    pnl_pct = (ltp - entry) / entry * 100

    conn = sqlite3.connect(db_path)
    now  = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S")

    # ── STOP LOSS HIT ──
    if ltp <= sl:
        logger.info(f"🛑 SL HIT #{pid} {pos['trading_symbol']} LTP=₹{ltp} SL=₹{sl} PnL=₹{pnl:.0f}")
        _exit_position(conn, pid, ltp, pnl, "SL_HIT", now, broker, pos, username)
        conn.commit()
        conn.close()
        return

    # ── TARGET HIT ──
    if ltp >= target:
        logger.info(f"🎯 TARGET HIT #{pid} {pos['trading_symbol']} LTP=₹{ltp} T=₹{target} PnL=₹{pnl:.0f}")
        _exit_position(conn, pid, ltp, pnl, "TARGET_HIT", now, broker, pos, username)
        conn.commit()
        conn.close()
        return

    # ── TRAILING SL ──
    if pnl_pct >= TRAIL_CONFIG["profit_to_trail"] * 100:
        # Trail SL to 10% below current LTP
        new_sl = round(ltp * (1 - TRAIL_CONFIG["trail_pct"]), 1)
        if new_sl > sl:
            conn.execute(
                "UPDATE trades SET sl_price=?,updated_at=? WHERE id=?",
                (new_sl, now, pid)
            )
            logger.info(f"📈 TRAIL SL #{pid} {pos['symbol']} {sl}→{new_sl} (LTP=₹{ltp} +{pnl_pct:.1f}%)")

    # Update current P&L
    conn.execute(
        "UPDATE trades SET updated_at=? WHERE id=?",
        (now, pid)
    )
    conn.commit()
    conn.close()


def _exit_position(conn, pid, ltp, pnl, reason, now, broker, pos, username):
    """Exit a position — paper or live"""
    pnl_pct = round((ltp - float(pos["entry_price"])) / float(pos["entry_price"]) * 100, 2)

    # Update DB
    conn.execute("""
        UPDATE trades SET
            status='CLOSED', exit_price=?, pnl=?, pnl_pct=?,
            exit_reason=?, closed_at=?, updated_at=?
        WHERE id=?
    """, (ltp, round(pnl, 2), pnl_pct, reason, now, now, pid))

    # Place REAL exit order on Angel One
    mode = pos.get("mode", "PAPER")
    if mode == "LIVE":
        try:
            trading_symbol = pos.get("trading_symbol","")
            token          = str(pos.get("token",""))
            exchange       = pos.get("exchange","NFO")
            qty            = int(pos.get("quantity") or pos.get("lot_size") or 0)

            if trading_symbol and token and qty > 0:
                # Place SELL order at market price
                order_params = {
                    "variety":         "NORMAL",
                    "tradingsymbol":   trading_symbol,
                    "symboltoken":     token,
                    "transactiontype": "SELL",
                    "exchange":        exchange,
                    "ordertype":       "MARKET",
                    "producttype":     "INTRADAY",
                    "duration":        "DAY",
                    "quantity":        str(qty),
                    "price":           "0",
                    "triggerprice":    "0",
                }
                result = broker.api.placeOrder(order_params)
                logger.info(f"🔴 LIVE EXIT ORDER: {trading_symbol} qty={qty} reason={reason} → {result}")
            else:
                logger.warning(f"Exit skipped — missing symbol/token/qty for #{pid}")
        except Exception as e:
            logger.error(f"Live exit failed #{pid}: {e}")

    result = "WIN" if pnl > 0 else "LOSS"
    logger.info(f"{'✅' if pnl>0 else '❌'} EXIT #{pid} {pos['symbol']} {result} ₹{pnl:.0f} | {reason}")
