import time
import json
import requests
from utils.signer import sign
from config import BASE_URL, API_KEY, API_SECRET, PASSPHRASE, DRY_RUN
from utils.logger import setup_logger

log = setup_logger()

TIMEOUT = 12
RETRIES = 2

_LEVERAGE_SET = set()

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
    log.debug("----- SIGN DEBUG -----")
    log.debug(f"METHOD   : {method}")
    log.debug(f"PATH     : {path}")
    log.debug(f"BODY     : {body}")
    log.debug(f"TIMESTAMP: {ts}")
    log.debug(f"SIGN_STR : {msg}")
    log.debug(f"SIGNATURE: {sig}")
    log.debug(f"HEADERS  : {headers}")
    log.debug("----------------------")

    return headers


# --------------------------------------------------
def _post(path, data):

    url = BASE_URL + path
    body = json.dumps(data)

    for _ in range(RETRIES + 1):

        headers = _build_headers("POST", path, body)

        try:
            res = requests.post(
                url,
                data=body,
                headers=headers,
                timeout=TIMEOUT
            )

            log.debug("----- HTTP DEBUG -----")
            log.debug(f"URL    : {url}")
            log.debug(f"STATUS : {res.status_code}")
            log.debug(f"RAW    : {res.text}")
            log.debug("----------------------")

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

    for _ in range(RETRIES + 1):

        headers = _build_headers("GET", path)

        try:
            res = requests.get(
                url,
                headers=headers,
                timeout=TIMEOUT
            )

            log.debug("----- HTTP DEBUG -----")
            log.debug(f"URL    : {url}")
            log.debug(f"STATUS : {res.status_code}")
            log.debug(f"RAW    : {res.text}")
            log.debug("----------------------")

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
# FORCE LEVERAGE (FIXED - WEEX COMPLIANT)
# --------------------------------------------------
def set_leverage(symbol, lev, mode=1):
    """
    mode:
    1 = Cross
    3 = Isolated
    """

    path = "/capi/v2/account/leverage"

    body = {
        "symbol": symbol,
        "marginMode": mode,
        "longLeverage": str(lev),
        "shortLeverage": str(lev)
    }

    return _post(path, body)


# --------------------------------------------------
# OPEN LONG (MARKET)
# --------------------------------------------------
def place_long(symbol, size):

    # FORCE 1x LEVERAGE (MANDATORY)
    if symbol not in _LEVERAGE_SET:
        set_leverage(symbol, 1)
        _LEVERAGE_SET.add(symbol)

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


# --------------------------------------------------
# CLOSE ALL POSITIONS (WEEX COMPLIANT)
# --------------------------------------------------
def close_all_positions(symbol=None):

    path = "/capi/v2/order/closePositions"

    data = {}
    if symbol:
        data["symbol"] = symbol  # optional

    log.info("CLOSING ALL OPEN POSITIONS")

    if DRY_RUN:
        log.info("[DRY RUN] CLOSE ALL POSITIONS")
        return {"mock": "close_all"}

    res = _post(path, data)

    if not res:
        log.error("CLOSE ALL POSITIONS FAILED -> no response")
        return None

    log.info(f"CLOSE ALL RESPONSE -> {res}")
    return res


# --------------------------------------------------
# UPLOAD AI LOG (WEEX COMPLIANCE)
# --------------------------------------------------
def upload_ai_log(order_id, stage, model, input_data, output_data, explanation):

    path = "/capi/v2/order/uploadAiLog"

    data = {
        "orderId": order_id,
        "stage": stage,
        "model": model,
        "input": input_data,
        "output": output_data,
        "explanation": explanation[:1000]
    }

    log.debug("----- AI LOG UPLOAD -----")
    log.debug(json.dumps(data, indent=2))
    log.debug("-------------------------")

    if DRY_RUN:
        log.info("[DRY RUN] AI LOG UPLOAD SKIPPED")
        return {"mock": "ai_log"}

    return _post(path, data)
