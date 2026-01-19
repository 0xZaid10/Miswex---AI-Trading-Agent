from utils.logger import setup_logger
log = setup_logger()

import time
import csv
import os
from datetime import datetime

from core.strategy_loader import load
from core.signal_engine import score
from core.position import Position
from core.portfolio import Portfolio
from core.weex_api import place_long, close_long, get_account_balance
from core.ws_engine import WS
from config import SYMBOL_MAP, BTC_SYMBOL

# ---------------- TRAIL OVERRIDES ----------------
TRAIL_OVERRIDE = {
    "DOGE_5m": 0.9,
    "SOL_5m": 0.9
}

# ---------------- TRADE LOGGER ----------------
TRADE_LOG = "logs/trades.csv"
os.makedirs("logs", exist_ok=True)

if not os.path.exists(TRADE_LOG):
    with open(TRADE_LOG, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow([
            "time","symbol","tf","side","size",
            "entry","exit","pnl_pct",
            "open_order_id","close_order_id",
            "reason","strat_id"
        ])

def log_trade(row):
    with open(TRADE_LOG, "a", newline="") as f:
        w = csv.writer(f)
        w.writerow(row)

# throttle timer
last_float_log = 0
LOG_INTERVAL = 60   # seconds

# REQUIRED LOOKBACK
MIN_BUF = 60
MIN_MICRO = 8

MAX_POSITIONS = 2

# ---------------- LOAD STRATEGIES ----------------
STRATS = {
    "5m": {}
}

for k in SYMBOL_MAP:
    STRATS["5m"][k]  = load(f"strategies/{k}_5m.pkl")

pf = Portfolio()
ws = WS()

# TF mapping
TF_MAP = {
    "MINUTE_5": "5m"
}

MICRO_TF = "MINUTE_1"

# -------------------------------------------------
# CANDLE CALLBACK
# -------------------------------------------------
def on_candle(symbol, tf, close, ts):

    if tf not in TF_MAP:
        return

    tf_key = TF_MAP[tf]

    # wait until BTC ready
    if BTC_SYMBOL not in ws.buffers:
        return
    if tf not in ws.buffers[BTC_SYMBOL]:
        return

    btc_buf = ws.buffers[BTC_SYMBOL][tf]["closes"]
    if len(btc_buf) < MIN_BUF:
        return

    btc = btc_buf[-50:]

    for key, strats in STRATS[tf_key].items():

        sym = SYMBOL_MAP[key]

        if sym != symbol:
            continue

        if sym not in ws.buffers:
            continue
        if tf not in ws.buffers[sym]:
            continue
        if MICRO_TF not in ws.buffers[sym]:
            continue

        buf = ws.buffers[sym][tf]["closes"]
        micro_buf = ws.buffers[sym][MICRO_TF]["closes"]

        if len(buf) < MIN_BUF:
            continue
        if len(micro_buf) < MIN_MICRO:
            continue

        X = buf[-50:]
        micro = micro_buf[-5:]
        price = close

        for sid, g in enumerate(strats):

            if not pf.can_open(g):
                continue

            s = score(X, btc, micro, g)

            log.info(
                f"[STRAT-{tf_key}] {key} | id={sid} | "
                f"score={round(s,4)} | entry={round(g.entry,4)} | "
                f"SIGNAL={'OPEN' if s > g.entry else 'NO'}"
            )

            if s > g.entry:

                # -------- DYNAMIC SIZING --------
                balance = get_account_balance()
                if not balance:
                    log.error("BALANCE FETCH FAILED")
                    return

                capital_per_trade = balance / MAX_POSITIONS
                size = round(capital_per_trade / price, 6)

                log.info(
                    f"SIZING -> balance={balance} "
                    f"cap_per_trade={capital_per_trade} size={size}"
                )

                res = place_long(sym, size)

                if not res or "order_id" not in res:
                    log.error(f"OPEN FAILED -> {sym}")
                    return

                open_order_id = res["order_id"]

                pos = Position(price, size, g, sym, open_order_id)
                pos.tf = tf_key
                pf.register(pos)

                log.info(
                    f"OPEN {sym} TF={tf_key} size={size} "
                    f"order_id={open_order_id}"
                )

                # ----- TRADE LOG -----
                log_trade([
                    datetime.utcnow(),
                    sym,
                    tf_key,
                    "LONG",
                    size,
                    price,
                    "",
                    "",
                    open_order_id,
                    "",
                    "OPEN",
                    sid
                ])

# -------------------------------------------------
def manage():
    global last_float_log
    now = time.time()

    for pos in pf.open.copy():

        tf = "MINUTE_5"

        if pos.symbol not in ws.buffers:
            continue
        if tf not in ws.buffers[pos.symbol]:
            continue
        if BTC_SYMBOL not in ws.buffers:
            continue
        if tf not in ws.buffers[BTC_SYMBOL]:
            continue

        buf = ws.buffers[pos.symbol][tf]["closes"]
        btc_buf = ws.buffers[BTC_SYMBOL][tf]["closes"]
        micro_buf = ws.buffers[pos.symbol]["MINUTE_1"]["closes"]

        if len(buf) < MIN_BUF:
            continue
        if len(btc_buf) < MIN_BUF:
            continue
        if len(micro_buf) < MIN_MICRO:
            continue

        X = buf[-50:]
        btc = btc_buf[-50:]
        micro = micro_buf[-5:]

        price = buf[-1]

        pos.update(price)

        pnl = (price - pos.entry) / pos.entry
        g = pos.strat

        if now - last_float_log > LOG_INTERVAL:
            log.info(
                f"[FLOAT-{pos.tf}] {pos.symbol} | "
                f"pnl={round(pnl*100,2)}% | "
                f"tp={g.tp} | sl={g.sl} | trail={g.trail} | "
                f"age={pos.age}"
            )

        s = score(X, btc, micro, g)

        reason = None

        if pnl > g.tp / 100 or pnl < -g.sl / 100:
            reason = "TP_SL"

        # -------- TRAIL OVERRIDE LOGIC --------
        else:
            key = f"{pos.symbol.split('_')[0]}_{pos.tf}"
            trail_pct = g.trail

            if key in TRAIL_OVERRIDE:
                trail_pct = TRAIL_OVERRIDE[key]

            if (pos.max - price) / pos.max > trail_pct / 100:
                reason = "TRAIL"

        if not reason and pos.age > g.min_hold and s < 0:
            reason = "TIME_SCORE"

        if reason:

            res = close_long(pos.symbol, pos.size)
            if not res or "order_id" not in res:
                log.error(f"CLOSE FAILED -> {pos.symbol}")
                continue

            close_order_id = res["order_id"]

            pos.close(price, close_order_id)
            pf.close(pos)

            log.info(
                f"[CLOSE-{pos.tf}] {pos.symbol} | "
                f"reason={reason} close_id={close_order_id}"
            )

            # ----- TRADE LOG -----
            log_trade([
                datetime.utcnow(),
                pos.symbol,
                pos.tf,
                "LONG",
                pos.size,
                pos.entry,
                price,
                round(pnl*100,4),
                pos.order_id,
                close_order_id,
                reason,
                ""
            ])

    if now - last_float_log > LOG_INTERVAL:
        last_float_log = now

# -------------------------------------------------
# WIRE
# -------------------------------------------------
ws.callbacks.append(on_candle)
ws.start()

TFS = ["1m","5m"]

while not ws.connected:
    time.sleep(0.2)

for k in SYMBOL_MAP:
    sym = SYMBOL_MAP[k]
    for tf in TFS:
        ws.subscribe(sym, tf)
        time.sleep(0.3)

for tf in TFS:
    ws.subscribe(BTC_SYMBOL, tf)
    time.sleep(0.3)

# -------------------------------------------------
# LOOP
# -------------------------------------------------
while True:
    manage()
    time.sleep(1)
