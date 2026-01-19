import time
import json
import requests
from utils.signer import sign
from config import BASE_URL, API_KEY, API_SECRET, PASSPHRASE, DRY_RUN
from utils.logger import setup_logger

log = setup_logger()

TIMEOUT = 8
RETRIES = 2


# --------------------------------------------------
def _build_headers(method, path, body=""):

    ts = str(int(time.time() * 1000))

    msg = ts + method + path + body
    sig = sign(API_SECRET, msg)

    headers = {
        "ACCESS-KEY": API_KEY,
        "ACCESS-SIGN": sig,
        "ACCESS-PASSPHRASE": PASSPHRASE,
        "ACCESS-TIMESTAMP": ts,
        "Content-Type": "application/json",
        "Accept": "application/json",
        "locale": "en-US",
        "User-Agent": "weex-bot/1.0"
    }

    # DEBUG
    log.info("----- SIGN DEBUG -----")
    log.info(f"METHOD   : {method}")
    log.info(f"PATH     : {path}")
    log.info(f"BODY     : {body}")
    log.info(f"TIMESTAMP: {ts}")
    log.info(f"SIGN_STR : {msg}")
    log.info(f"SIGNATURE: {sig}")
    log.info(f"HEADERS  : {headers}")
    log.info("----------------------")

    return headers


# --------------------------------------------------
def _post(path, data):

    url = BASE_URL + path
    body = json.dumps(data)
    headers = _build_headers("POST", path, body)

    for _ in range(RETRIES + 1):

        try:
            res = requests.post(
                url,
                data=body,
                headers=headers,
                timeout=TIMEOUT
            )

            log.info("----- HTTP DEBUG -----")
            log.info(f"URL    : {url}")
            log.info(f"STATUS : {res.status_code}")
            log.info(f"RAW    : {res.text}")
            log.info("----------------------")

            if res.status_code != 200:
                time.sleep(1)
                continue

            try:
                return res.json()
            except Exception as e:
                log.error(f"JSON PARSE ERROR -> {e}")
                return None

        except Exception as e:
            log.error(f"REQUEST ERROR -> {e}")
            time.sleep(1)

    return None


# --------------------------------------------------
def _get(path):

    url = BASE_URL + path
    headers = _build_headers("GET", path)

    for _ in range(RETRIES + 1):

        try:
            res = requests.get(
                url,
                headers=headers,
                timeout=TIMEOUT
            )

            log.info("----- HTTP DEBUG -----")
            log.info(f"URL    : {url}")
            log.info(f"STATUS : {res.status_code}")
            log.info(f"RAW    : {res.text}")
            log.info("----------------------")

            if res.status_code != 200:
                time.sleep(1)
                continue

            try:
                return res.json()
            except Exception as e:
                log.error(f"JSON PARSE ERROR -> {e}")
                return None

        except Exception as e:
            log.error(f"REQUEST ERROR -> {e}")
            time.sleep(1)

    return None


# --------------------------------------------------
# GET ACCOUNT BALANCE
# --------------------------------------------------
def get_account_balance():

    path = "/capi/v2/account/assets"
    res = _get(path)

    if not res:
        log.error("BALANCE FETCH FAILED")
        return None

    for c in res:
        if c["coinName"] == "USDT":
            return float(c["available"])

    return None


# --------------------------------------------------
# OPEN LONG (MARKET)
# --------------------------------------------------
def place_long(symbol, size):

    if DRY_RUN:
        log.info(f"[DRY RUN] OPEN {symbol} size={size}")
        return {"mock": "open"}

    path = "/capi/v2/order/placeOrder"

    data = {
        "symbol": symbol,
        "client_oid": str(int(time.time() * 1000)),
        "size": str(size),
        "type": "1",        # OPEN LONG
        "order_type": "3", # IOC
        "match_price": "1" # MARKET
    }

    res = _post(path, data)

    if not res:
        log.error("PLACE LONG FAILED -> no response")
        return None

    log.info(f"PLACE LONG RESPONSE -> {res}")
    return res


# --------------------------------------------------
# CLOSE LONG (MARKET)
# --------------------------------------------------
def close_long(symbol, size):

    if DRY_RUN:
        log.info(f"[DRY RUN] CLOSE {symbol} size={size}")
        return {"mock": "close"}

    path = "/capi/v2/order/placeOrder"

    data = {
        "symbol": symbol,
        "client_oid": str(int(time.time() * 1000)),
        "size": str(size),
        "type": "3",        # CLOSE LONG
        "order_type": "3", # IOC
        "match_price": "1" # MARKET
    }

    res = _post(path, data)

    if not res:
        log.error("CLOSE LONG FAILED -> no response")
        return None

    log.info(f"CLOSE LONG RESPONSE -> {res}")
    return res
