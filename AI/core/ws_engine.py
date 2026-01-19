import websocket
import json
import threading
import time
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

        self.lock = threading.Lock()   # thread safety
        self.reconnecting = False

    # --------------------------------------------------
    def _send(self, payload):
        raw = json.dumps(payload)
        self.ws.send(raw)

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

        # extract timeframe from channel
        channel = m.get("channel")
        if not channel:
            return

        # kline.LAST_PRICE.cmt_btcusdt.MINUTE_1
        tf = channel.split(".")[-1]

        d = m["data"][0]

        sym = d["symbol"]
        close = float(d["close"])
        candle_time = d["klineTime"]

        with self.lock:

            if sym not in self.buffers:
                self.buffers[sym] = {}

            if tf not in self.buffers[sym]:
                self.buffers[sym][tf] = {
                    "last_time": None,
                    "closes": []
                }

            buf = self.buffers[sym][tf]

            # avoid duplicates
            if candle_time == buf["last_time"]:
                return

            buf["last_time"] = candle_time
            buf["closes"].append(close)


        for cb in self.callbacks:
            cb(sym, tf, close, candle_time)

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
