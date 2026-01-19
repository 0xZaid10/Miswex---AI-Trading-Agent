import time
import requests
from core.weex_api import place_long, close_long, get_account_balance

SYMBOL = "cmt_btcusdt"
NOTIONAL = 10     # USDT
HOLD_TIME = 5 * 60   # 5 minutes


# -----------------------------------------
# Fetch BTC price
# -----------------------------------------
def get_price():

    url = "https://api-contract.weex.com/capi/v2/market/ticker?symbol=cmt_btcusdt"
    res = requests.get(url).json()

    price = float(res[0]["last"])
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

    # 3️⃣ Calculate size
    size = round(NOTIONAL / price, 6)
    print("ORDER SIZE:", size)

    # 4️⃣ OPEN LONG
    open_res = place_long(SYMBOL, size)

    print("\nOPEN RESPONSE:")
    print(open_res)

    if not open_res:
        print("❌ OPEN FAILED")
        exit()

    print("\n✅ POSITION OPENED, WAITING 5 MINUTES...\n")

    # 5️⃣ Wait 5 minutes
    time.sleep(HOLD_TIME)

    # 6️⃣ CLOSE LONG
    close_res = close_long(SYMBOL, size)

    print("\nCLOSE RESPONSE:")
    print(close_res)

    if not close_res:
        print("❌ CLOSE FAILED")
