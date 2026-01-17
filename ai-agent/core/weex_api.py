import time, requests
from utils.signer import sign
from config import BASE_URL, API_KEY, API_SECRET, PASSPHRASE, DRY_RUN

from utils.logger import setup_logger
log = setup_logger()


def headers(path):

    ts = str(int(time.time()*1000))
    msg = ts + path

    return {
        "ACCESS-KEY": API_KEY,
        "ACCESS-SIGN": sign(API_SECRET, msg),
        "ACCESS-PASSPHRASE": PASSPHRASE,
        "ACCESS-TIMESTAMP": ts,
        "Content-Type": "application/json"
    }


def place_long(symbol, size):

    # ✅ DRY RUN MODE
    if DRY_RUN:
        log.info(f"[DRY RUN] OPEN {symbol} size={size}")
        return {"mock": "open"}

    path = "/capi/v2/order/placeOrder"
    url = BASE_URL + path

    data = {
        "symbol": symbol,
        "client_oid": str(int(time.time()*1000)),
        "size": str(size),
        "type": "1",
        "order_type": "3",
        "match_price": "1"
    }

    res = requests.post(url, json=data, headers=headers(path))
    log.info(f"PLACE LONG {symbol} -> {res.text}")

    return res.json()


def close_long(symbol, size):

    # ✅ DRY RUN MODE
    if DRY_RUN:
        log.info(f"[DRY RUN] CLOSE {symbol} size={size}")
        return {"mock": "close"}

    path = "/capi/v2/order/placeOrder"
    url = BASE_URL + path

    data = {
        "symbol": symbol,
        "client_oid": str(int(time.time()*1000)),
        "size": str(size),
        "type": "3",
        "order_type": "3",
        "match_price": "1"
    }

    res = requests.post(url, json=data, headers=headers(path))
    log.info(f"CLOSE LONG {symbol} -> {res.text}")

    return res.json()
