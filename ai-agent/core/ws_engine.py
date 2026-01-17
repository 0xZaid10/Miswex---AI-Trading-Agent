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
        self.subscriptions = []
        self.ws = None

    def subscribe(self, symbol, tf):
        ch = f"kline.LAST_PRICE.{symbol}.{TF_MAP[tf]}"
        self.subscriptions.append(ch)

        if self.ws and self.ws.sock and self.ws.sock.connected:
            self.ws.send(json.dumps({
                "event": "subscribe",
                "channel": ch
            }))

    def on_message(self, ws, msg):

        m = json.loads(msg)

        # WEEX ping
        if m.get("event") == "ping":
            ws.send(json.dumps({
                "event": "pong",
                "time": m["time"]
            }))
            return

        if m.get("event") != "payload":
            return

        d = m["data"][0]
        sym = d["symbol"]

        if sym not in self.buffers:
            self.buffers[sym] = []

        self.buffers[sym].append(float(d["close"]))

        for cb in self.callbacks:
            cb(sym)

    def on_close(self, ws, code, msg):
        log.warning("WS CLOSED -> reconnecting...")
        time.sleep(3)
        self.connect()

    def on_error(self, ws, err):
        log.error(f"WS ERROR: {err}")

    def connect(self):

        # REQUIRED by WEEX (User-Agent header)
        headers = {
            "User-Agent": "weex-bot/1.0"
        }

        self.ws = websocket.WebSocketApp(
            WS_PUBLIC,
            header=[f"{k}: {v}" for k, v in headers.items()],
            on_message=self.on_message,
            on_close=self.on_close,
            on_error=self.on_error
        )

        threading.Thread(
            target=self.ws.run_forever,
            kwargs={"ping_interval": 20, "ping_timeout": 10}
        ).start()

        time.sleep(2)

        # re-subscribe after reconnect
        for ch in self.subscriptions:
            if self.ws.sock and self.ws.sock.connected:
                self.ws.send(json.dumps({
                    "event": "subscribe",
                    "channel": ch
                }))

        log.info("WS CONNECTED")

    def start(self):
        self.connect()
