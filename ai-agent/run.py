from utils.logger import setup_logger
log = setup_logger()

import time

from core.strategy_loader import load
from core.signal_engine import score
from core.position import Position
from core.portfolio import Portfolio
from core.weex_api import place_long, close_long
from core.ws_engine import WS
from config import SYMBOL_MAP, BTC_SYMBOL

# throttle timer
last_float_log = 0

STRATS = {}
for k in SYMBOL_MAP:
    STRATS[k] = load(f"strategies/{k}.pkl")

pf = Portfolio()
ws = WS()

def on_tick(symbol):

    if BTC_SYMBOL not in ws.buffers:
        return

    btc = ws.buffers[BTC_SYMBOL][-20:]

    for key, strats in STRATS.items():

        sym = SYMBOL_MAP[key]

        if sym != symbol:
            continue
        if len(ws.buffers[sym]) < 30:
            continue

        X = ws.buffers[sym][-20:]
        B = btc
        micro = X[-5:]
        price = X[-1]

        for g in strats:

            if not pf.can_open(g):
                continue

            s = score(X, B, micro, g)

            if s > g.entry:

                size = g.scale   # strategy decides size

                place_long(sym, size)

                pos = Position(price, size, g, sym)
                pf.register(pos)

                log.info(f"OPEN {sym} size={size}")

def manage():
    global last_float_log

    now = time.time()

    for pos in pf.open.copy():

        price = ws.buffers[pos.symbol][-1]
        pos.update(price)

        pnl = (price - pos.entry) / pos.entry
        g = pos.strat

        # FLOATING PnL (every 60 seconds)
        if now - last_float_log > 60:
            log.info(
                f"FLOAT {pos.symbol} | "
                f"Entry={pos.entry:.4f} "
                f"Now={price:.4f} "
                f"PnL={pnl*100:.2f}% "
                f"Balance={pf.balance:.2f}"
            )

        if pnl > g.tp / 100 or pnl < -g.sl / 100:

            close_long(pos.symbol, pos.size)

            pos.close(price)
            pf.close(pos)

            log.info(
                f"CLOSE {pos.symbol} | "
                f"Trade={pnl*100:.2f}% | "
                f"Balance={pf.balance:.2f} | "
                f"W:{pf.wins} L:{pf.losses}"
            )

        elif (pos.max - price) / pos.max > g.trail / 100:

            close_long(pos.symbol, pos.size)

            pos.close(price)
            pf.close(pos)

            log.info(
                f"TRAIL CLOSE {pos.symbol} | "
                f"Trade={pnl*100:.2f}% | "
                f"Balance={pf.balance:.2f} | "
                f"W:{pf.wins} L:{pf.losses}"
            )

    # update timer AFTER loop
    if now - last_float_log > 60:
        last_float_log = now

ws.callbacks.append(on_tick)
ws.start()

# subs
for k in SYMBOL_MAP:
    ws.subscribe(SYMBOL_MAP[k], k.split("_")[1])

ws.subscribe(BTC_SYMBOL, "5m")

while True:
    manage()
    time.sleep(0.2)   # prevents CPU burn
