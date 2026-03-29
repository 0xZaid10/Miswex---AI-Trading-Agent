import time
import requests
import csv
import os
from datetime import datetime

from core.weex_api import place_long, close_long, get_account_balance
from core.ai_logger import push_ai_log   # <-- ADDED

SYMBOL = "cmt_btcusdt"
NOTIONAL = 10     # USDT
HOLD_TIME = 5 * 60   # 5 minutes

STEP = 0.0001   # WEEX step size


# -----------------------------------------
# SIMPLE TRADE LOGGER
# -----------------------------------------
LOG_FILE = "logs/simple_trades.csv"
os.makedirs("logs", exist_ok=True)

if not os.path.exists(LOG_FILE):
    with open(LOG_FILE, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow([
            "time",
            "symbol",
            "action",
            "size",
            "order_id"
        ])

def log_trade(action, symbol, size, order_id):
    with open(LOG_FILE, "a", newline="") as f:
        w = csv.writer(f)
        w.writerow([
            datetime.utcnow(),
            symbol,
            action,
            size,
            order_id
        ])


# -----------------------------------------
# Fetch BTC price
# -----------------------------------------
def get_price():

    url = "https://api-contract.weex.com/capi/v2/market/ticker?symbol=cmt_btcusdt"
    res = requests.get(url).json()

    price = float(res["last"])
    return price


# -----------------------------------------
# Main test
# -----------------------------------------
if __name__ == "__main__":

    # 1️⃣ Get account balance
    balance = get_account_balance()
    print("AVAILABLE USDT BALANCE:", balance)

    if not balance or balance < NOTIONAL:
        print("❌ Not enough balance to place order")
        exit()

    # 2️⃣ Get BTC price
    price = get_price()
    print("BTC PRICE:", price)

    # 3️⃣ Calculate size (FIXED)
    raw_size = NOTIONAL / price
    size = int(raw_size / STEP) * STEP
    size = round(size, 4)

    print("ORDER SIZE:", size)

    # -------- AI LOG (DECISION) --------
    push_ai_log(
        stage="Decision Making",
        genome={"mode": "manual_test"},
        X=[price],
        btc=[],
        micro=[],
        score=1,
        decision="OPEN_LONG_TEST"
    )

    # 4️⃣ OPEN LONG
    open_res = place_long(SYMBOL, size)

    print("\nOPEN RESPONSE:")
    print(open_res)

    if not open_res:
        print("❌ OPEN FAILED")
        exit()

    # -------- LOG OPEN --------
    if "order_id" in open_res:
        log_trade("OPEN", SYMBOL, size, open_res["order_id"])

        # -------- AI LOG (EXECUTION) --------
        push_ai_log(
            stage="Execution",
            genome={"mode": "manual_test"},
            X=[],
            btc=[],
            micro=[],
            score=1,
            decision="ORDER_PLACED",
            order_id=open_res["order_id"]
        )

    print("\n✅ POSITION OPENED, WAITING 5 MINUTES...\n")

    # 5️⃣ Wait 5 minutes
    time.sleep(HOLD_TIME)

    # -------- AI LOG (CLOSE DECISION) --------
    push_ai_log(
        stage="Decision Making",
        genome={"mode": "manual_test"},
        X=[],
        btc=[],
        micro=[],
        score=1,
        decision="CLOSE_TEST",
        order_id=open_res["order_id"]
    )

    # 6️⃣ CLOSE LONG
    close_res = close_long(SYMBOL, size)

    print("\nCLOSE RESPONSE:")
    print(close_res)

    if not close_res:
        print("❌ CLOSE FAILED")
        exit()

    # -------- LOG CLOSE --------
    if "order_id" in close_res:
        log_trade("CLOSE", SYMBOL, size, close_res["order_id"])
