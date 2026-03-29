import websocket
import json
import threading
import time

print("WS ENGINE v2 LOADED")

from config import WS_PUBLIC, TF_MAP
from utils.logger import setup_logger

log = setup_logger()


class WS:

    def __init__(self):
        self.buffers = {}
        self.callbacks = []

        self.subscriptions = set()
        self.ws = None
        self.connected = False
        self.first_connect = True

        self.lock = threading.Lock()
        self.reconnecting = False

    # --------------------------------------------------
    def _send(self, payload):
        self.ws.send(json.dumps(payload))

    # --------------------------------------------------
    def subscribe(self, symbol, tf):

        ch = f"kline.LAST_PRICE.{symbol}.{TF_MAP[tf]}"

        if ch in self.subscriptions:
            return

        self.subscriptions.add(ch)

        if self.ws and self.ws.sock and self.ws.sock.connected:
            self._send({
                "event": "subscribe",
                "channel": ch
            })
            log.info(f"SUBSCRIBED -> {ch}")

    # --------------------------------------------------
    def on_open(self, ws):
        self.connected = True
        self.reconnecting = False
        log.info("WS CONNECTED")

        # auto re-subscribe ONLY on reconnect
        if not self.first_connect:
            for ch in list(self.subscriptions):
                self._send({
                    "event": "subscribe",
                    "channel": ch
                })
                time.sleep(0.4)

        self.first_connect = False

    # --------------------------------------------------
    def on_message(self, ws, msg):

        m = json.loads(msg)

        # ping
        if m.get("event") == "ping":
            self._send({
                "event": "pong",
                "time": m["time"]
            })
            return

        # server error
        if m.get("event") == "error":
            log.error(f"WS SERVER ERROR -> {m}")
            return

        if m.get("event") != "payload":
            return

        channel = m.get("channel")
        if not channel:
            return

        # kline.LAST_PRICE.cmt_btcusdt.MINUTE_1
        tf = channel.split(".")[-1]

        rows = m.get("data")
        if not isinstance(rows, list) or not rows:
            return

        row = rows[-1]

        # -------- FIX: handle LIST payload --------
        if isinstance(row, list):
            try:
                t, o, h, l, c, v, *_ = row
                sym = channel.split(".")[2]
            except Exception as e:
                log.error(f"KLINE_UNPACK_FAIL: {e} | raw={row}")
                return  
        else:
            sym = row["symbol"]
            t = int(row["klineTime"])
            o = float(row["open"])
            h = float(row["high"])
            l = float(row["low"])
            c = float(row["close"])
            v = float(row["size"])
        # ------------------------------------------

        t = int(t)
        o = float(o)
        h = float(h)
        l = float(l)
        c = float(c)
        v = float(v)

        with self.lock:

            self.buffers.setdefault(sym, {})
            self.buffers[sym].setdefault(tf, {
                "last_time": None,
                "time": [],
                "open": [],
                "high": [],
                "low": [],
                "close": [],
                "volume": []
            })

            buf = self.buffers[sym][tf]

            # avoid duplicates
            if t == buf["last_time"]:
                return

            buf["last_time"] = t

            buf["time"].append(t)
            buf["open"].append(o)
            buf["high"].append(h)
            buf["low"].append(l)
            buf["close"].append(c)
            buf["volume"].append(v)

            # cap buffer size
            for k in ["time","open","high","low","close","volume"]:
                buf[k] = buf[k][-500:]

        # callbacks
        for cb in self.callbacks:
            cb(sym, tf, o, h, l, c, v, t)

    # --------------------------------------------------
    def on_close(self, ws, code, msg):

        if self.reconnecting:
            return

        self.reconnecting = True
        self.connected = False

        log.warning("WS CLOSED -> reconnecting...")
        time.sleep(3)
        self.connect()

    def on_error(self, ws, err):
        log.error(f"WS ERROR -> {err}")

    # --------------------------------------------------
    def connect(self):

        headers = {
            "User-Agent": "weex-bot/1.0"
        }

        self.ws = websocket.WebSocketApp(
            WS_PUBLIC,
            header=[f"{k}: {v}" for k, v in headers.items()],
            on_open=self.on_open,
            on_message=self.on_message,
            on_close=self.on_close,
            on_error=self.on_error
        )

        threading.Thread(
            target=self.ws.run_forever,
            kwargs={"ping_interval": 20, "ping_timeout": 10},
            daemon=True
        ).start()

    # --------------------------------------------------
    def start(self):
        self.connect()
