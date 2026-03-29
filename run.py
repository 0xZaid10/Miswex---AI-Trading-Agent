from core.ai_logger import upload_gemini_log
from core.weex_api import close_all_positions
import time

# ✅ IMPORTS (ADD THESE)
from core.reentry_ai import ReentryAI
from core.reentry_state import build_reentry_state
from core.reentry_state import build_entry_features
import time
import json
import requests
from utils.signer import sign
from config import BASE_URL, API_KEY, API_SECRET, PASSPHRASE, DRY_RUN
from utils.logger import setup_logger
from core.weex_api import close_all_positions



# 🧩 STEP 1 — RSI HELPER
import numpy as np

def compute_rsi(prices, period=14):
    prices = np.asarray(prices, dtype=float)

    if len(prices) < period + 1:
        return None

    deltas = np.diff(prices)
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)

    # --- Wilder initialization ---
    avg_gain = np.mean(gains[:period])
    avg_loss = np.mean(losses[:period])

    # --- Wilder smoothing ---
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period

    if avg_loss == 0:
        return 100.0

    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))



TRADING_UNLOCK_TIME = time.time() + (1 * 60 * 60)

MAX_POSITIONS = 2

# ================= CAPITAL / FEE BUFFERS =================

FIRST_ENTRY_BUFFER = 0.997   # conservative, covers fees + slippage
SECOND_ENTRY_BUFFER = 0.993   # aggressive, deploy remaining capital



ORDER_FAIL_UNTIL = 0

def trading_allowed_with_reason():
    if time.time() < TRADING_UNLOCK_TIME:
        return False, (
            "Trading paused. System is accumulating market data "
            "to stabilize indicators, scalers, and regime detection."
        )
    return True, None


from utils.logger import setup_logger
log = setup_logger()

from core.gemini_agent import GeminiSupervisor
gemini = GeminiSupervisor(log)

log.warning("FORCING CLEAN START — DUE TO ERROR IN BOT")
close_all_positions()
time.sleep(3)
log = setup_logger()

# ================= REENTRY EXPLANATION =================
def describe_reentry(state, wait):
    if not isinstance(state, (list, tuple)) or len(state) < 5:
        return "Reentry conditions evaluated"

    macro_sig, depth_b, speed_b, rsi_slope_b, exit_reason, *_ = state

    if rsi_slope_b == "rebound":
        return "Momentum turned positive after pullback"

    if depth_b in ("shallow", "medium") and wait >= 2:
        return "Price stabilized after exit"

    if exit_reason == "SCORE":
        return "Previous exit was signal-based, conditions improved"

    return "Reentry conditions satisfied after cooldown"


import csv
import os
import math
import requests
import pandas as pd
from datetime import datetime, timezone

GEMINI_THROTTLE_UNTIL_TS = datetime(
    year=2026, month=2, day=9,
    hour=17, minute=0, tzinfo=timezone.utc
).timestamp()

GEMINI_LAST_CALL_TS = 0
GEMINI_MIN_INTERVAL = 60 * 60  # 1 hour

GEMINI_UPLOAD_UNLOCK_TS = datetime(
    year=2026, month=2, day=9,
    hour=12, minute=40, tzinfo=timezone.utc
).timestamp()

from core.strategy_loader import load
from core.signal_engine import score
from core.position import Position
from core.portfolio import Portfolio
from core.weex_api import (
    place_long,
    close_long,
    get_account_balance,
    get_all_positions
)
from core.ws_engine import WS
from config import SYMBOL_MAP, BTC_SYMBOL

def upload_gemini_log_guarded(
    *,
    action_type: str,
    decision: str,
    explanation: str,
    order_id: str | None
):
    if time.time() < GEMINI_UPLOAD_UNLOCK_TS:
        return  # silent skip

    upload_gemini_log(
        action_type=action_type,
        decision=decision,
        explanation=explanation,
        order_id=order_id
    )

def gemini_call_allowed():
    global GEMINI_LAST_CALL_TS

    now = time.time()

    # After 17:00 UTC → unrestricted
    if now >= GEMINI_THROTTLE_UNTIL_TS:
        GEMINI_LAST_CALL_TS = now
        return True

    # Before 17:00 UTC → hourly throttle
    if now - GEMINI_LAST_CALL_TS >= GEMINI_MIN_INTERVAL:
        GEMINI_LAST_CALL_TS = now
        return True

    return False

# ================= CANDLE COUNT =================

candle_count = {
    "5m": 0
}

# ================= RE-ENTRY RULE (PER SYMBOL) =================

last_close = {
    # symbol: {
    #   "state": tuple,
    #   "candle_idx": int,
    #   "action": optional
    # }
}

# ================= REENTRY AI CONTROL =================

reentry_gate = {
    # symbol: bool (is reentry currently allowed)
}

last_reentry_decision = {
    # symbol: {"allowed": bool, "action": action}
}

# 🧩 STEP 2 — PENDING ENTRY BUFFER
pending_entry = {
    # symbol: {
    #   "expires_at": timestamp,
    #   "genome": g,
    #   "sid": sid
    # }
}

# ✅ INITIALIZE REENTRY AI (ONCE)
reentry_ai = ReentryAI(log)

def is_symbol_open(pf, symbol):
    return any(p.symbol == symbol for p in pf.open)



# ================= STEP SIZE =================

BASE = "https://api-contract.weex.com"
STEP_MAP = {}

def fetch_contract_steps():
    url = BASE + "/capi/v2/market/contracts"
    r = requests.get(url, timeout=10)
    data = r.json()

    if isinstance(data, dict):
        if data.get("code") != "00000":
            raise Exception("FAILED TO LOAD CONTRACTS")
        rows = data["data"]
    else:
        rows = data

    for c in rows:
        sym = c["symbol"]
        precision = int(c["size_increment"])
        precision_step = 10 ** (-precision)
        min_step = float(c["minOrderSize"])
        step = max(precision_step, min_step)
        STEP_MAP[sym] = step


def normalize_size(symbol, size):
    step = STEP_MAP[symbol]
    fixed = math.floor(size / step) * step
    return round(fixed, 8)

import logging

def log_gemini_local(
    log: logging.Logger,
    action_type: str,
    symbol: str,
    explanation: str,
    decision: str = None,
    order_id: str = None
):
    header = (
        f"[GEMINI] action={action_type} "
        f"symbol={symbol} "
        f"decision={decision} "
        f"order_id={order_id}"
    )

    log.info(header)
    for line in explanation.splitlines():
        log.info(f"[GEMINI] {line}")

# ================= BUFFER STORAGE =================

BUFFER_DIR = "data/buffers"
os.makedirs(BUFFER_DIR, exist_ok=True)


def persist_candle(symbol, tf, ts, o, h, l, c, v):
    path = f"{BUFFER_DIR}/{symbol}_{tf}.csv"
    with open(path, "a", newline="") as f:
        w = csv.writer(f)
        w.writerow([ts, o, h, l, c, v])


def load_buffers(ws):
    if not os.path.exists(BUFFER_DIR):
        return

    for file in os.listdir(BUFFER_DIR):
        if not file.endswith(".csv"):
            continue

        parts = file.replace(".csv","").split("_")

        sym = parts[0] + "_" + parts[1]
        tf  = parts[-2] + "_" + parts[-1]

        if tf == "MINUTE_5":
            mapped_tf = "MINUTE_5"
        elif tf == "MINUTE_1":
            mapped_tf = "MINUTE_1"
        else:
            continue

        log.info(f"[BUFFER DEBUG] FILE={file} -> sym={sym} tf={tf}")

        path = f"{BUFFER_DIR}/{file}"

        ws.buffers.setdefault(sym, {})
        ws.buffers[sym].setdefault(mapped_tf, {
            "time": [],
            "open": [],
            "high": [],
            "low": [],
            "close": [],
            "volume": []
        })

        with open(path) as f:
            r = csv.reader(f)
            for ts, o, h, l, c, v in r:
                ws.buffers[sym][mapped_tf]["time"].append(int(ts))
                ws.buffers[sym][mapped_tf]["open"].append(float(o))
                ws.buffers[sym][mapped_tf]["high"].append(float(h))
                ws.buffers[sym][mapped_tf]["low"].append(float(l))
                ws.buffers[sym][mapped_tf]["close"].append(float(c))
                ws.buffers[sym][mapped_tf]["volume"].append(float(v))

        for k in ["time", "open", "high", "low", "close", "volume"]:
            ws.buffers[sym][mapped_tf][k] = ws.buffers[sym][mapped_tf][k][-500:]

        if ws.buffers[sym][mapped_tf]["time"]:
            ws.buffers[sym][mapped_tf]["last_time"] = ws.buffers[sym][mapped_tf]["time"][-1]
        else:
            ws.buffers[sym][mapped_tf]["last_time"] = 0

        log.info(
            f"BUFFER LOADED -> {sym} {mapped_tf} "
            f"({len(ws.buffers[sym][mapped_tf]['close'])})"
        )


# ================= DATAFRAME =================

def buf_to_df(buf):
    return pd.DataFrame({
        "time": buf["time"],
        "open": buf["open"],
        "high": buf["high"],
        "low": buf["low"],
        "close": buf["close"],
        "volume": buf["volume"]
    })


# ---------------- TRADE LOGGER ----------------
TRADE_LOG = "logs/trades.csv"
os.makedirs("logs", exist_ok=True)

if not os.path.exists(TRADE_LOG):
    with open(TRADE_LOG, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow([
            "time",
            "symbol",
            "tf",
            "side",
            "size",
            "entry",
            "exit",
            "pnl_pct",
            "open_order_id",
            "close_order_id",
            "reason",
            "strat_id"
        ])

def log_trade(row):
    with open(TRADE_LOG, "a", newline="") as f:
        csv.writer(f).writerow(row)


last_float_log = 0
LOG_INTERVAL = 60

MIN_BUF = 60
MIN_MICRO = 8


# ================ TRAILING STOP LADDER ============
# Ordered from high -> low profit

TRAIL_LADDER = [
    (0.5, 0.25),
    (0.25, 0.23),
    (0.13, 0.1),
    (0.1, 0.07),
    (0.07, 0.027),
    (0.05, 0.017),
    (0.03, 0.017),
    (0.01, 0.017)
]

# ---------------- LOAD STRATEGIES ----------------
STRATS = {"5m": {}}
for k in SYMBOL_MAP:
    STRATS["5m"][k] = load(f"strategies/{k}_5m.pkl")


pf = Portfolio()
def sync_open_positions():
    positions = get_all_positions()

    if not positions:
        log.info("[SYNC] No open positions on exchange")
        return

    for p in positions:
        symbol = p["symbol"]
        size = p["size"]
        entry = p["entry_price"]

        pos = Position(entry, size, None, symbol, order_id="RESTORED")
        pos.tf = "5m"
        pos.entry_candle_idx = candle_count["5m"]
        pos.exit_mode = "NORMAL"
        pos.entry_score = 0
        pos.last_5m_score = 0
        pos.max = entry
        pos.max_dd_pct = 0


        pf.register(pos)

        log.info(
            f"[SYNC] Restored {symbol} "
            f"size={size} entry={round(entry,6)}"
        )

def portfolio_snapshot(pf):
    return {
        "open_positions": len(pf.open),
        "wins": pf.wins,
        "losses": pf.losses,
        "total_pnl_pct": round(pf.total_pnl * 100, 2),
    }

ws = WS()

load_buffers(ws)
fetch_contract_steps()
sync_open_positions()

# DEBUG: dump critical contract constraints once
for sym in ["cmt_solusdt", "cmt_dogeusdt"]:
    if sym in STEP_MAP:
        log.info(
            f"[CONTRACT DEBUG] {sym} "
            f"step={STEP_MAP[sym]} "
        )


log.info(f"STEP MAP LOADED -> {STEP_MAP}")

TF_MAP = {"MINUTE_5": "5m"}
MICRO_TF = "MINUTE_1"


# -------------------------------------------------
# CANDLE CALLBACK
# -------------------------------------------------

def on_candle(symbol, tf, o, h, l, c, v, ts):

    # ================= 1m ENTRY AI EXECUTION =================
    if tf == "MINUTE_1" and symbol in pending_entry and len(pf.open) < MAX_POSITIONS:

         # 🔒 HARD BLOCK — never re-enter same symbol
        if is_symbol_open(pf, symbol):
            del pending_entry[symbol]
            log.info(f"[ENTRY_CANCELLED] {symbol} already has open position")
            return


        pe = pending_entry[symbol]

        # ===== ENTRY AI DECISION =====
        minutes_waited = max(
            0, 
            int((time.time() - (pe["expires_at"] - 4.8 * 60)) / 60)
        )
        
       
        alt_df_5m = buf_to_df(ws.buffers[symbol]["MINUTE_5"])

        if len(alt_df_5m) >= 20:
            recent_high = alt_df_5m.high.iloc[-20:].max()
            dump_depth = (recent_high - c) / recent_high
            recent_range = (
                alt_df_5m.high.iloc[-5:].max() -
                alt_df_5m.low.iloc[-5:].min()
            ) / c
        else:
            dump_depth = 0.0
            recent_range = 0.0

        features = build_entry_features(
            alt_5m_df=buf_to_df(ws.buffers[symbol]["MINUTE_5"]),
            alt_1m_df=buf_to_df(ws.buffers[symbol]["MINUTE_1"]),
            minutes_waited=minutes_waited,
            exit_mode=pe.get("exit_mode", "NORMAL")
        )

        decision, entry_score = reentry_ai.entry_decide(features)


        if decision == "WAIT":
            return

        if decision == "ABORT":
            del pending_entry[symbol]
            return

        # ===== ORDER EXECUTION (UNCHANGED LOGIC BELOW) =====
        g = pe["genome"]
        sid = pe["sid"]

        global ORDER_FAIL_UNTIL

        # ---- CIRCUIT BREAKER ----
        if time.time() < ORDER_FAIL_UNTIL:
            log.warning("[CIRCUIT BREAKER] Entry blocked (recent order failure)")
            return

        balance = get_account_balance()
        if not balance:
            return

        if len(pf.open) == 0:
            # 🥇 First position → half of buffered balance
            capital = (balance * FIRST_ENTRY_BUFFER) / MAX_POSITIONS
        else:
            # 🥈 Second position → almost all remaining balance
            capital = balance * SECOND_ENTRY_BUFFER

        # ---- DUST / SAFETY CHECK ----
        if capital <= 0:
            log.warning(
                f"[CAPITAL BLOCKED] {symbol} | "
                f"balance={balance:.4f} capital={capital:.4f}"
            )
            return

        raw_size = capital / c
        size = normalize_size(symbol, raw_size)

        log.error(
            f"[SIZE DEBUG] {symbol} | "
            f"price={c:.4f} "
            f"balance={balance:.2f} "
            f"capital={capital:.2f} "
            f"raw_size={raw_size:.8f} "
            f"normalized_size={size}"
        )



        micro_df = buf_to_df(ws.buffers[symbol]["MINUTE_1"])
        btc_df   = buf_to_df(ws.buffers[BTC_SYMBOL]["MINUTE_5"])

        # ================= GEMINI SUPERVISION =================
        allowed, reason = trading_allowed_with_reason()

        if not allowed:
            warmup_text = (
                "Accumulating sufficient market data. "
                "Indicators, volatility estimates, and regime "
                "classification are still stabilizing."
            )

            upload_gemini_log_guarded(
                action_type="ENTRY",
                decision="BLOCK",
                explanation=warmup_text,
                order_id=None
            )

            log_gemini_local(
                log,
                action_type="ENTRY",
                symbol=symbol,
                decision="BLOCK",
                explanation=warmup_text,
                order_id=None
            )

            return

        entry_context = {
            "system_state": {
                "trading_allowed": allowed,
                "note": reason
            },
            "symbol": symbol,
            "timeframe": "5m",
            "quant_score": round(entry_score, 4),
            "entry_threshold": round(g.entry, 4),
            "score_margin": round(entry_score - g.entry, 4),
            "position_size": size,
            "notional_usd": round(size * c, 2),
            "leverage": 1,
            "exit_mode": pe.get("exit_mode"),
            "indicators": {
                "5m": {
                "r1": round(float(alt_df_5m.close.pct_change().iloc[-1]), 6),
                "r5": round(float(alt_df_5m.close.pct_change(5).iloc[-1]), 6),
                "r15": round(
                    float(alt_df_5m.close.pct_change(15).iloc[-1]), 6
                ) if len(alt_df_5m) >= 16 else None,
                "trend": round(
                    float(alt_df_5m.close.iloc[-1] - alt_df_5m.close.rolling(50).mean().iloc[-1]), 4
                ) if len(alt_df_5m) >= 50 else None,
                "volatility": round(
                    float(alt_df_5m.close.pct_change().rolling(20).std().iloc[-1]), 6
                ),
                "vol_chg": round(
                    float(
                        alt_df_5m.close.pct_change().rolling(10).std().iloc[-1]
                    ),
                    6
                ),
                "atr": round(
                    float((alt_df_5m.high - alt_df_5m.low).rolling(14).mean().iloc[-1]), 6
                ) if len(alt_df_5m) >= 14 else None,
            },
                "micro_1m": {
                "r": round(float(micro_df.close.pct_change().iloc[-1]), 6),
                "mom": round(float(micro_df.close.diff().iloc[-1]), 6),
                "vol": round(float(micro_df.close.pct_change().std()), 6)
                }
            },
            "btc_regime": {
                "btc_r": round(float(btc_df.close.pct_change().iloc[-1]), 6),
                "btc_trend": round(float(btc_df.close.diff().mean()), 4),
                "btc_vol": round(float(btc_df.close.pct_change().std()), 6)
            },
            "portfolio": {
                **portfolio_snapshot(pf),
                "balance":round(balance, 2)
            },
            "trend_type": "normalized_strength",
            "market_state": {
                "dump_depth": round(dump_depth, 4),
                "recent_range": round(recent_range, 4)
            }
        }

        time.sleep(0.4)

        entry_decision = gemini.decide(entry_context, action_type="ENTRY")

        if entry_decision["decision"] == "BLOCK":
            upload_gemini_log_guarded(
                action_type="ENTRY",
                decision="BLOCK",
                explanation=entry_decision["ai_log"]["explanation"],
                order_id=None
            )

            log_gemini_local(
                log,
                action_type="ENTRY",
                symbol=symbol,
                decision="BLOCK",
                explanation=entry_decision["ai_log"]["explanation"],
                order_id=None
            )
            log.info(f"[GEMINI BLOCK] {symbol}")
            del pending_entry[symbol]
            return

        log.error(
            f"[ORDER SUBMIT] {symbol} "
            f"size={size} "
            f"len_open={len(pf.open)} "
            f"pending={len(pending_entry)}"
        )



        res = place_long(symbol, size)
        if not res or "order_id" not in res:
            ORDER_FAIL_UNTIL = time.time() + 30

            log.error(
                f"[ORDER FAILED] {symbol} | "
                f"size={size} "
                f"raw_size={raw_size:.8f} "
                f"capital={capital:.2f} "
                f"balance={balance:.2f} "
                f"step={STEP_MAP.get(symbol)}"
            )
            return


        order_id = res["order_id"]

        upload_gemini_log_guarded(
            action_type="ENTRY",
            decision="ALLOW",
            explanation=entry_decision["ai_log"]["explanation"],
            order_id=order_id
        )

        log_gemini_local(
            log,
            action_type="ENTRY",
            symbol=symbol,
            decision=entry_decision["decision"],
            explanation=entry_decision["ai_log"]["explanation"],
            order_id=order_id
        )


        pos = Position(c, size, g, symbol, order_id)
        pos.entry_features = features
        pos.exit_mode = "NORMAL"
        pos.entry_score = round(entry_score, 4)
        pos.last_5m_score = round(entry_score, 4)

        alt_df_5m = buf_to_df(ws.buffers[symbol]["MINUTE_5"])

        if len(alt_df_5m) >= 20:
            recent_high = alt_df_5m.high.iloc[-20:].max()
            dump_depth = (recent_high - c) / recent_high
            recent_range = (
                alt_df_5m.high.iloc[-5:].max() -
                alt_df_5m.low.iloc[-5:].min()
            ) / c
        else:
            dump_depth = 0.0
            recent_range = 0.0

        if dump_depth >= 0.025 or recent_range >= 0.01:
            pos.exit_mode = "RECOVERY"

        lc = last_close.get(symbol)
        if lc:
            pos.reentry_state = lc["state"]
            pos.reentry_action = lc.get("action")

        pos.tf = "5m"
        pos.entry_candle_idx = candle_count["5m"]
        pf.register(pos)

        log_trade([
            datetime.now(timezone.utc),
            symbol,
            "5m",
            "LONG",
            size,
            c,
            "",
            "",
            order_id,
            "",
            "OPEN",
            sid
        ])

        del pending_entry[symbol]
        return

    if tf == "MINUTE_5" and symbol == BTC_SYMBOL:
        candle_count["5m"] += 1

    persist_candle(symbol, tf, ts, o, h, l, c, v)

    # Only evaluate scores on 5m candle close
    if tf != "MINUTE_5":
        return


    if tf not in TF_MAP:
        return

    if BTC_SYMBOL not in ws.buffers or tf not in ws.buffers[BTC_SYMBOL]:
        return

    if len(ws.buffers[BTC_SYMBOL][tf]["close"]) < MIN_BUF:
        return

    now = time.time()
    for sym, pe in list(pending_entry.items()):
        if now > pe["expires_at"]:
            del pending_entry[sym]
            log.info(f"[ENTRY_EXPIRED_TIMER] {sym}")

    for key, strats in STRATS["5m"].items():

        sym = SYMBOL_MAP[key]
        if sym != symbol:
            continue

        if sym not in ws.buffers or tf not in ws.buffers[sym]:
            continue
        if MICRO_TF not in ws.buffers[sym]:
            continue

        if len(ws.buffers[sym][tf]["close"]) < MIN_BUF:
            continue
        if len(ws.buffers[sym][MICRO_TF]["close"]) < MIN_MICRO:
            continue

        alt_df   = buf_to_df(ws.buffers[sym][tf])
        btc_df   = buf_to_df(ws.buffers[BTC_SYMBOL][tf])
        micro_df = buf_to_df(ws.buffers[sym][MICRO_TF])

        for sid, g in enumerate(strats):

            if is_symbol_open(pf, sym):
                continue

            if len(pf.open) >= MAX_POSITIONS:
                continue

            s = score(alt_df, btc_df, micro_df, g)
            for p in pf.open:
                if p.symbol == sym:
                    p.last_5m_score = round(s, 4)

            if tf == "MINUTE_5" and not is_symbol_open(pf, sym):
                analysis_context = {
                    "symbol": sym,
                    "quant_score": round(s, 4),
                    "entry_threshold": round(g.entry, 4),
                    "btc_regime": {
                        "btc_r": round(float(btc_df.close.pct_change().iloc[-1]), 6),
                        "btc_vol": round(float(btc_df.close.pct_change().std()), 6)
                    },
                    "score_margin": round(s - g.entry, 4),
                    "momentum": {
                        "r1": round(float(alt_df.close.pct_change().iloc[-1]), 6),
                        "r5": round(float(alt_df.close.pct_change(5).iloc[-1]), 6),
                        "r15": round(
                            float(alt_df.close.pct_change(15).iloc[-1]), 6
                        ) if len(alt_df) >= 16 else None,
                    },
                    "volatility": {
                        "asset_vol": round(
                            float(alt_df.close.pct_change().rolling(20).std().iloc[-1]), 6
                        ),
                        "btc_vol": round(float(btc_df.close.pct_change().std()), 6)
                    }
                }

                if gemini_call_allowed():
                    analysis_text = gemini.analyze(analysis_context)["analysis"]
                else:
                    analysis_text = (
                        "Hourly analysis throttle active. "
                        "Market conditions are being monitored and logged."
                    )

                upload_gemini_log_guarded(
                    action_type="ANALYSIS",
                    decision="OBSERVE",
                    explanation=analysis_text,
                    order_id=None
                )

                log_gemini_local(
                    log,
                    action_type="ANALYSIS",
                    symbol=sym,
                    explanation=analysis_text
                )


            log.info(
                f"[STRAT-5m] {key} | id={sid} | "
                f"score={round(s,4)} | entry={round(g.entry,4)} | "
                f"SIGNAL={'OPEN' if s > g.entry else 'NO'}"
            )

            lc = last_close.get(sym)

            if not lc:
                reentry_gate[sym] = True

            if lc:
                wait = candle_count["5m"] - lc["candle_idx"]

                if wait == 0:
                    continue

                action = reentry_ai.choose(lc["state"])

                try:
                    action = int(action)
                except:
                    action = None


                log.error(f"[REENTRY DEBUG] action={action} type={type(action)} wait={wait} type_wait={type(wait)}")

                allowed = False

                if isinstance(action, (int, float)):
                    allowed = wait >= action


                # update gate (single source of truth)
                reentry_gate[sym] = allowed

                prev = last_reentry_decision.get(sym)

                # log ONLY on decision change
                if not prev or prev["allowed"] != allowed:
                    last_reentry_decision[sym] = {
                        "allowed": allowed,
                        "action": action
                    }

                # store chosen action for learning
                lc["action"] = action

            gate_ok = reentry_gate.get(sym, True)

            if s > g.entry and s > 0 and not gate_ok:
                continue

            if (
                s > g.entry
                and s > 0
                and gate_ok
                and sym not in pending_entry
                and not is_symbol_open(pf, sym)
            ):
                if len(alt_df) >= 20:
                    recent_high = alt_df.high.iloc[-20:].max()
                    dump_depth = (recent_high - alt_df.close.iloc[-1]) / recent_high

                    recent_range = (
                        alt_df.high.iloc[-5:].max() -
                        alt_df.low.iloc[-5:].min()
                    ) / alt_df.close.iloc[-1]
                else:
                    dump_depth = 0.0
                    recent_range = 0.0

                # ================= ARM ENTRY (5m SCORE) =================
                pending_entry[sym] = {
                    "expires_at": time.time() + 4.8 * 60,
                    "genome": g,
                    "sid": sid,
                    "exit_mode": "RECOVERY" if (
                        dump_depth>= 0.025 or recent_range >= 0.01
                    ) else "NORMAL"
            
                }

                log.info(
                    f"[ENTRY_ARMED] {sym} | score={round(s,4)} "
                )

                if len(pf.open) + len(pending_entry) >= MAX_POSITIONS:
                    continue


# -------------------------------------------------
def manage():
    global last_float_log

    now = time.time()

    for pos in pf.open.copy():

        alt_df = buf_to_df(ws.buffers[pos.symbol]["MINUTE_5"])
        btc_df = buf_to_df(ws.buffers[BTC_SYMBOL]["MINUTE_5"])
        micro_df = buf_to_df(ws.buffers[pos.symbol]["MINUTE_1"])

        price_5m = alt_df.close.iloc[-1]
        price_1m = micro_df.close.iloc[-1]

        pos.update(price_1m)

        pnl = (price_1m - pos.entry) / pos.entry
        g = pos.strat

        held = candle_count["5m"] - getattr(pos, "entry_candle_idx", candle_count["5m"])

        s = getattr(pos, "last_5m_score", pos.entry_score)
        reason = None

        current_5m = candle_count["5m"]

        if pos.last_gemini_5m_candle != current_5m:
            pos.last_gemini_5m_candle = current_5m

            analysis_context = {
                "symbol": pos.symbol,
                "pnl_pct": round(pnl * 100, 2),
                "held_candles": held,
                "exit_mode": pos.exit_mode,
                "quant_score": round(s, 4),
                "btc_regime": {
                    "btc_r": round(float(btc_df.close.pct_change().iloc[-1]), 6),
                    "btc_vol": round(float(btc_df.close.pct_change().std()), 6)
                },
                "momentum": {
                    "r1": round(float(alt_df.close.pct_change().iloc[-1]), 6),
                    "r5": round(float(alt_df.close.pct_change(5).iloc[-1]), 6),
                    "r15": round(
                        float(alt_df.close.pct_change(15).iloc[-1]), 6
                        ) if len(alt_df) >= 16 else None,
                    },
                "volatility": {
                    "asset_vol": round(
                        float(alt_df.close.pct_change().rolling(20).std().iloc[-1]), 6
                        ),
                        "btc_vol": round(float(btc_df.close.pct_change().std()), 6)
                    }
            }

            if gemini_call_allowed():
                analysis_text = gemini.analyze(analysis_context)["analysis"]
            else:
                analysis_text = (
                    "Hourly analysis throttle active. "
                    "Market conditions are being monitored and logged."
                )
 
            upload_gemini_log_guarded(
                action_type="ANALYSIS",
                decision="OBSERVE",
                explanation=analysis_text,
                order_id=None
            )

            log_gemini_local(
                log,
                action_type="ANALYSIS",
                symbol=pos.symbol,
                explanation=analysis_text
            )


        closes_1m = micro_df.close.values
        rsi_1m = compute_rsi(closes_1m)

        if rsi_1m is None:
            rsi_1m = 51

        if pnl <= -0.003:
            reason = "HARD_STOP"

        elif pnl >= 0.01:
            for min_pnl, pullback in TRAIL_LADDER:
                if pnl >= min_pnl:
                   drawdown = (pos.max - price_1m) / pos.max
                   if drawdown >= pullback:
                       reason = f"TRAIL_{int(min_pnl*100)}"
                   break

        elif (
            pos.exit_mode == "NORMAL"
            and pnl >= 0.005
            and rsi_1m < 55
        ):
            reason = "TREND_CHANGE_NORMAL"
        elif (
            pos.exit_mode == "RECOVERY"
            and pnl >= 0.007
            and rsi_1m < 45
        ):
            reason = "TREND_CHANGE_RECOVERY"


        if reason:

            micro_df = buf_to_df(ws.buffers[pos.symbol]["MINUTE_1"])
            btc_df   = buf_to_df(ws.buffers[BTC_SYMBOL]["MINUTE_5"])

            balance = get_account_balance() or 0

            # ================= GEMINI EXIT SUPERVISION =================
            exit_context = {
                "symbol": pos.symbol,
                "current_pnl_pct": round(pnl * 100, 2),
                "exit_reason": reason,
                "held_candles": held,
                "exit_mode": pos.exit_mode,
                "quant_score": round(s, 4),
                "indicators": {
                    "5m": {
                        "r1": round(float(alt_df.close.pct_change().iloc[-1]), 6),
                        "r5": round(float(alt_df.close.pct_change(5).iloc[-1]), 6),
                        "r15": round(
                            float(alt_df.close.pct_change(15).iloc[-1]), 6
                        ) if len(alt_df) >= 16 else None,
                        "trend": round(
                            float(alt_df.close.iloc[-1] - alt_df.close.rolling(50).mean().iloc[-1]), 4
                        ) if len(alt_df) >= 50 else None,
                        "volatility": round(
                            float(alt_df.close.pct_change().rolling(20).std().iloc[-1]), 6
                        ),
                        "atr": round(
                            float((alt_df.high - alt_df.low).rolling(14).mean().iloc[-1]), 6
                        ) if len(alt_df) >= 14 else None,
                        "vol_chg": round(
                            float(
                                alt_df.close.pct_change().rolling(10).std().iloc[-1]
                            ),
                            6
                        )
                    },
                    "micro_1m": {
                        "r": round(float(micro_df.close.pct_change().iloc[-1]), 6),
                        "mom": round(float(micro_df.close.diff().iloc[-1]), 6),
                        "vol": round(float(micro_df.close.pct_change().std()), 6)
                    },
                },
                "btc_regime": {
                        "btc_r": round(float(btc_df.close.pct_change().iloc[-1]), 6),
                        "btc_trend": round(float(btc_df.close.diff().mean()), 4),
                        "btc_vol": round(float(btc_df.close.pct_change().std()), 6)
                },
                "portfolio": {
                    **portfolio_snapshot(pf),
                    "balance": round(balance, 2)
                },
                "trend_type": "normalized_strength"
            }

            time.sleep(0.4)
            # 🔴 SAFETY OVERRIDE — NEVER BLOCK THESE
            FORCED_EXIT_REASONS = {"HARD_STOP"}

            if reason in FORCED_EXIT_REASONS:
                # 1️⃣ FORCE EXIT FIRST (NO AI)
                res = close_long(pos.symbol, pos.size)
                if not res or "order_id" not in res:
                    log.error("[HARD_STOP] Close order failed")
                    continue

                close_order_id = res["order_id"]

                # 2️⃣ Gemini explanation ONLY (no decision)
                stop_context = {
                    "symbol": pos.symbol,
                    "current_pnl_pct": round(pnl * 100, 2),
                    "exit_reason": "HARD_STOP",
                    "held_candles": held,
                    "exit_mode": pos.exit_mode,
                    "quant_score": round(s, 4),
                    "risk_note": "Forced stop-loss to prevent further downside risk",
                    "order_id": close_order_id
                }

                try:
                   stop_explanation = gemini.analyze(stop_context)["analysis"]
                except Exception:
                   stop_explanation = (
                       "Stop-loss triggered due to adverse price movement. "
                       "Position closed immediately to preserve capital."
                    )

                # 3️⃣ Log Gemini explanation WITH order_id
                upload_gemini_log_guarded(
                    action_type="EXIT",
                    decision="ALLOW",
                    explanation=stop_explanation,
                    order_id=close_order_id
                )

                # 4️⃣ Finalize position locally
                pos.close(price_1m, close_order_id)
                pf.close(pos)

                log_trade([
                    datetime.now(timezone.utc),
                    pos.symbol,
                    "5m",
                    "LONG",
                    pos.size,
                    pos.entry,
                    price_1m,
                    round(pnl * 100, 4),
                    pos.order_id,
                    close_order_id,
                    "HARD_STOP",
                    ""
                    ])

                log_gemini_local(
                    log,
                    action_type="EXIT",
                    symbol=pos.symbol,
                    decision="ALLOW",
                    explanation=stop_explanation,
                    order_id=close_order_id
                )

                continue

            else:
                exit_decision = gemini.decide(exit_context, action_type="EXIT")


            # ❌ Gemini blocks exit
            if exit_decision["decision"] == "BLOCK":
                upload_gemini_log_guarded(
                    action_type="EXIT",
                    decision="BLOCK",
                    explanation=exit_decision["ai_log"]["explanation"],
                    order_id=None
                )

                log_gemini_local(
                    log,
                    action_type="EXIT",
                    symbol=pos.symbol,
                    decision=exit_decision["decision"],
                    explanation=exit_decision["ai_log"]["explanation"],
                    order_id=None
                )
                log.info(f"[GEMINI BLOCK EXIT] {pos.symbol} | reason={reason}")
                continue

               



            # ✅ Gemini allows exit → proceed

            res = close_long(pos.symbol, pos.size)
            if not res or "order_id" not in res:
                continue

            close_order_id = res["order_id"]

            upload_gemini_log_guarded(
                action_type="EXIT",
                decision="ALLOW",
                explanation=exit_decision["ai_log"]["explanation"],
                order_id=close_order_id
            )

            log_gemini_local(
                log,
                action_type="EXIT",
                symbol=pos.symbol,
                decision=exit_decision["decision"],
                explanation=exit_decision["ai_log"]["explanation"],
                order_id=close_order_id
            )



            pos.close(price_1m, res["order_id"])
            pf.close(pos)

            # ===== ENTRY AI REWARD =====
            reentry_ai.reward_entry(
                features=getattr(pos, "entry_features", None),
                pnl=pnl,
                max_dd=pos.max_dd_pct
            )


            log_trade([
                datetime.now(timezone.utc),
                pos.symbol,
                "5m",
                "LONG",
                pos.size,
                pos.entry,
                price_1m,
                round(pnl * 100, 4),
                pos.order_id,
                res["order_id"],
                reason,
                ""
            ])

            try:
                if getattr(pos, "reentry_action", None) is not None:
                    reentry_ai.reward(
                        state=pos.reentry_state,
                        action=pos.reentry_action,
                        pnl_pct=pnl,
                        max_dd_pct=pos.max_dd_pct,
                        held_candles=held
                    )

            except Exception as e:
                log.error(f"[REENTRY_AI] reward failed: {e}")

            state, debug = build_reentry_state(
                alt_df,
                micro_df,
                reason,
                score_now=s,
                entry_threshold=g.entry
            )

            last_close[pos.symbol] = {
                "state": state,
                "candle_idx": candle_count["5m"]
            }

        if now - last_float_log > LOG_INTERVAL:
            log.info(
                f"[FLOAT-5m] {pos.symbol} | "
                f"pnl={round(pnl * 100, 2)}% | "
                f"held_candles={held}"
            )

    if now - last_float_log > LOG_INTERVAL:
        last_float_log = now


# -------------------------------------------------
ws.callbacks.append(on_candle)
ws.start()

TFS = ["1m","5m"]

while not ws.connected:
    time.sleep(0.2)

for k in SYMBOL_MAP:
    for tf in TFS:
        ws.subscribe(SYMBOL_MAP[k], tf)
        time.sleep(0.3)

for tf in TFS:
    ws.subscribe(BTC_SYMBOL, tf)
    time.sleep(0.3)

while True:
    manage()
    time.sleep(1)
