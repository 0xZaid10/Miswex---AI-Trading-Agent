from core.ai_logger import push_ai_log
from core.weex_api import close_all_positions
import time

# ✅ IMPORTS (ADD THESE)
from core.reentry_ai import ReentryAI
from core.reentry_state import build_reentry_state
from core.reentry_state import build_entry_features



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



# ---- STARTUP SAFETY ----
res = close_all_positions()  # close EVERYTHING

if isinstance(res, list):
    for r in res:
        if r.get("success"):
            push_ai_log(
                stage="SYSTEM_RESET",
                genome=None,
                X=[],
                btc=[],
                micro=[],
                score=0,
                decision="FORCE_CLOSE_STARTUP",
                order_id=str(r["successOrderId"])
            )

# ✅ INITIALIZE GEMINI SUPERVISOR


TRADING_UNLOCK_TIME = time.time() + (5 * 60)

ORDER_FAIL_UNTIL = 0

def trading_allowed():
    return time.time() >= TRADING_UNLOCK_TIME


from utils.logger import setup_logger
log = setup_logger()

from core.gemini_agent import GeminiSupervisor
gemini = GeminiSupervisor(log)

# ================= WS-SAFE AI LOG WRAPPER =================
def safe_ai_log(**kwargs):
    try:
        push_ai_log(**kwargs)
    except Exception as e:
        log.error(f"AI_LOG_FAILED: {e}")

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

from core.strategy_loader import load
from core.signal_engine import score
from core.position import Position
from core.portfolio import Portfolio
from core.weex_api import (
    place_long,
    close_long,
    get_account_balance
)
from core.ws_engine import WS
from config import SYMBOL_MAP, BTC_SYMBOL


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

log.info(f"STEP MAP LOADED -> {STEP_MAP}")

TF_MAP = {"MINUTE_5": "5m"}
MICRO_TF = "MINUTE_1"


# -------------------------------------------------
# CANDLE CALLBACK
# -------------------------------------------------

def on_candle(symbol, tf, o, h, l, c, v, ts):

    # ================= 1m ENTRY AI EXECUTION =================
    if tf == "MINUTE_1" and symbol in pending_entry and len(pf.open) == 0:

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

        safe_ai_log(
            stage="ENTRY_AI_DECISION",
            genome=pe["genome"],
            X=[],
            btc=[],
            micro=[],
            score=entry_score,
            decision=decision,
            meta=features
        )

        if decision == "WAIT":
            return

        if decision == "ABORT":
            del pending_entry[symbol]
            return

        # ===== ORDER EXECUTION (UNCHANGED LOGIC BELOW) =====
        g = pe["genome"]
        sid = pe["sid"]

        if not trading_allowed():
            return

        global ORDER_FAIL_UNTIL

        # ---- CIRCUIT BREAKER ----
        if time.time() < ORDER_FAIL_UNTIL:
            log.warning("[CIRCUIT BREAKER] Entry blocked (recent order failure)")
            return

        balance = get_account_balance()
        if not balance:
            return

        size = normalize_size(symbol, (balance * 0.997) / c)

        micro_df = buf_to_df(ws.buffers[symbol]["MINUTE_1"])
        btc_df   = buf_to_df(ws.buffers[BTC_SYMBOL]["MINUTE_5"])

        # ================= GEMINI SUPERVISION =================

        entry_context = {
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
                "r1": round(float(g.r1), 6) if hasattr(g, "r1") else None,
                "r5": round(float(g.r5), 6) if hasattr(g, "r5") else None,
                "r15": round(float(g.r15), 6) if hasattr(g, "r15") else None,
                "trend": round(float(g.trend), 2) if hasattr(g, "trend") else None,
                "volatility": round(float(g.vol), 6) if hasattr(g, "vol") else None,
                "atr": round(float(g.atr), 4) if hasattr(g, "atr") else None
            },
                "micro_1m": {
                "r": round(float(micro_df.close.pct_change().iloc[-1]), 6),
                "mom": round(float(micro_df.close.diff().iloc[-1]), 6)
                }
            },
            "btc_regime": {
                "btc_r": round(float(btc_df.close.pct_change().iloc[-1]), 6),
                "btc_trend": round(float(btc_df.close.diff().mean()), 4),
                "btc_vol": round(float(btc_df.close.pct_change().std()), 6)
            },
            "portfolio": portfolio_snapshot(pf),
            "market_state": {
                "dump_depth": round(dump_depth, 4),
                "recent_range": round(recent_range, 4)
            }
        }

        time.sleep(0.4)

        entry_decision = gemini.decide(entry_context, action_type="ENTRY")

        safe_ai_log(
            stage="GEMINI_DECISION",
            genome=g,
            X=[],
            btc=[],
            micro=[],
            score=entry_score,
            decision=entry_decision["decision"],
            meta={
                "explanation": entry_decision["ai_log"]["explanation"]
            }
        )

        if entry_decision["decision"] == "BLOCK":
            log.info(f"[GEMINI BLOCK] {symbol}")
            del pending_entry[symbol]
            return


        res = place_long(symbol, size)
        if not res or "order_id" not in res:
            ORDER_FAIL_UNTIL = time.time() + 30
            log.error("[ORDER FAILED] Pausing new entries for 60s")
            return

        order_id = res["order_id"]

        pos = Position(c, size, g, symbol, order_id)
        pos.entry_features = features
        pos.exit_mode = "NORMAL"

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

        safe_ai_log(
            stage="Execution",
            genome=g,
            X=[],
            btc=[],
            micro=[],
            score=entry_score,
            decision="ORDER_PLACED",
            order_id=order_id
        )

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

            if len(pf.open) >= 1:
                break

            s = score(alt_df, btc_df, micro_df, g)

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

                allowed = (
                    action is not None and
                    action != "SKIP" and
                    wait >= action
                )

                # update gate (single source of truth)
                reentry_gate[sym] = allowed

                prev = last_reentry_decision.get(sym)

                # log ONLY on decision change
                if not prev or prev["allowed"] != allowed:
                    last_reentry_decision[sym] = {
                        "allowed": allowed,
                        "action": action
                    }

                    safe_ai_log(
                        stage="REENTRY_AI_DECISION",
                        genome=None,
                        X=[],
                        btc=[],
                        micro=[],
                        score=None,
                        decision="REENTRY_ALLOWED" if allowed else "REENTRY_BLOCKED",
                        meta={
                            "symbol": sym,
                            "wait_candles": wait,
                            "action": action,
                            "state": lc["state"]
                        }
                    )

                # store chosen action for learning
                lc["action"] = action

            gate_ok = reentry_gate.get(sym, True)

            if s > g.entry and s > 0 and not gate_ok:
                safe_ai_log(
                    stage="ENTRY_BLOCKED",
                    genome=None,
                    X=[],
                    btc=[],
                    micro=[],
                    score=s,
                    decision="ENTRY_BLOCKED_BY_REENTRY_AI",
                    meta={"symbol": sym}
                )

            if s > g.entry and s > 0 and gate_ok and sym not in pending_entry:
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

                safe_ai_log(
                    stage="ENTRY_ARMED",
                    genome=g,
                    X=[],
                    btc=[],
                    micro=[],
                    score=s,
                    decision="ENTRY_ARMED_BY_REENTRY_AI",
                    meta={
                        "symbol": sym,
                        "reentry_action": last_reentry_decision.get(sym, {}).get("action")
                    }
                )

                log.info(
                    f"[ENTRY_ARMED] {sym} | score={round(s,4)} "
                )

                break


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

        s = score(alt_df, btc_df, micro_df, g)
        reason = None

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
            and rsi_1m < 51
        ):
            reason = "TREND_CHANGE_NORMAL"
        elif (
            pos.exit_mode == "RECOVERY"
            and pnl >= 0.007
            and rsi_1m < 41
        ):
            reason = "TREND_CHANGE_RECOVERY"


        if reason:

            micro_df = buf_to_df(ws.buffers[pos.symbol]["MINUTE_1"])
            btc_df   = buf_to_df(ws.buffers[BTC_SYMBOL]["MINUTE_5"])
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
                        "r1": round(float(g.r1), 6) if hasattr(g, "r1") else None,
                        "r5": round(float(g.r5), 6) if hasattr(g, "r5") else None,
                        "r15": round(float(g.r15), 6) if hasattr(g, "r15") else None,
                        "trend": round(float(g.trend), 2) if hasattr(g, "trend") else None,
                        "volatility": round(float(g.vol), 6) if hasattr(g, "vol") else None
                    },
                    "micro_1m": {
                        "r": round(float(micro_df.close.pct_change().iloc[-1]), 6),
                        "mom": round(float(micro_df.close.diff().iloc[-1]), 6)
                    },
                },
                "btc_regime": {
                        "btc_r": round(float(btc_df.close.pct_change().iloc[-1]), 6),
                        "btc_trend": round(float(btc_df.close.diff().mean()), 4),
                        "btc_vol": round(float(btc_df.close.pct_change().std()), 6)
                },
                "portfolio": portfolio_snapshot(pf)
            }

            time.sleep(0.4)
            # 🔴 SAFETY OVERRIDE — NEVER BLOCK THESE
            FORCED_EXIT_REASONS = {"HARD_STOP"}

            if reason in FORCED_EXIT_REASONS:
                exit_decision = {
                    "decision": "ALLOW",
                    "ai_log" :{
                        "explanation" : "Stop Loss Hit - forced safety exit"
                    }
                }
            else:
                exit_decision = gemini.decide(exit_context, action_type="EXIT")

            safe_ai_log(
                stage="GEMINI_EXIT_DECISION",
                genome=g,
                X=[],
                btc=[],
                micro=[],
                score=s,
                decision=exit_decision["decision"],
                meta={
                    "reason": reason,
                    "explanation": exit_decision["ai_log"]["explanation"]
                }
            )

            # ❌ Gemini blocks exit
            if exit_decision["decision"] == "BLOCK":
                log.info(f"[GEMINI BLOCK EXIT] {pos.symbol} | reason={reason}")
                continue


            # ✅ Gemini allows exit → proceed

            res = close_long(pos.symbol, pos.size)
            if not res or "order_id" not in res:
                continue

            close_order_id = res["order_id"]

            safe_ai_log(
                stage="Decision Making",
                genome=g,
                X=alt_df,
                btc=btc_df,
                micro=micro_df,
                score=s,
                decision=f"CLOSE_{reason}",
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

                    safe_ai_log(
                        stage="REENTRY_AI_LEARN",
                        genome=None,
                        X=[],
                        btc=[],
                        micro=[],
                        score=None,
                        decision="LEARN",
                        meta={"symbol": pos.symbol}
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
