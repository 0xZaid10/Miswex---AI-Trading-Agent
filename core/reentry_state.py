import numpy as np

# ------------------------------
# Helpers
# ------------------------------

def bucket_return(x):
    if x > 0.015: return "++"
    if x > 0.003: return "+"
    if x > -0.003: return "0"
    if x > -0.01: return "-"
    return "--"

def bucket_depth(x):
    if x < 0.005: return "shallow"
    if x < 0.015: return "medium"
    return "deep"

def bucket_speed(x):
    if x < 0.002: return "slow"
    if x < 0.006: return "medium"
    return "fast"

def bucket_rsi_slope(x):
    if x > 5: return "rebound"
    if x < -5: return "accelerating"
    return "flat"


# ------------------------------
# Score (relative to strategy entry)
# ------------------------------

def bucket_score_relative(score, entry):
    """
    Score context ONLY.
    No hard thresholds used for decisions.
    """
    if score is None or entry is None:
        return "unknown"

    ratio = score / max(entry, 1e-6)

    if ratio < 1.05:
        return "just_above"
    if ratio < 1.25:
        return "healthy"
    if ratio < 1.6:
        return "extended"
    return "extreme"


# ------------------------------
# RSI (minimal, local)
# ------------------------------

def compute_rsi(prices, period=14):
    if len(prices) < period + 1:
        return None

    deltas = np.diff(prices)
    gains = np.maximum(deltas, 0)
    losses = -np.minimum(deltas, 0)

    avg_gain = np.mean(gains[-period:])
    avg_loss = np.mean(losses[-period:]) + 1e-9

    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


# ------------------------------
# State builder
# ------------------------------

def build_reentry_state(
    alt_5m_df,
    alt_1m_df,
    exit_reason,
    score_now=None,
    entry_threshold=None
):
    """
    Returns:
        state (tuple)
        debug (dict)
    """

    closes_5m = alt_5m_df.close.values
    closes_1m = alt_1m_df.close.values

    # ---- 5m returns (last 4)
    rets = []
    for i in range(-4, 0):
        r = (closes_5m[i] - closes_5m[i-1]) / closes_5m[i-1]
        rets.append(bucket_return(r))

    macro_sig = "".join(rets)

    # ---- dump depth (from local high)
    local_high = np.max(closes_5m[-6:])
    depth = (local_high - closes_5m[-1]) / local_high
    depth_b = bucket_depth(depth)

    # ---- dump speed
    speed = abs(rets.count("-") + rets.count("--")) * depth
    speed_b = bucket_speed(speed)

    # ---- 1m RSI slope
    rsi_now = compute_rsi(closes_1m)
    rsi_prev = compute_rsi(closes_1m[:-2])

    if rsi_now is None or rsi_prev is None:
        rsi_slope_b = "unknown"
        rsi_slope = None
    else:
        rsi_slope = rsi_now - rsi_prev
        rsi_slope_b = bucket_rsi_slope(rsi_slope)

    # ---- score context (learned, not enforced)
    score_rel = bucket_score_relative(score_now, entry_threshold)

    state = (
        macro_sig,
        depth_b,
        speed_b,
        rsi_slope_b,
        score_rel,      # 🧠 context only
        exit_reason
    )

    debug = {
        "macro_5m": macro_sig,
        "dump_depth_pct": round(depth * 100, 2),
        "dump_speed": speed_b,
        "rsi_slope": None if rsi_slope is None else round(rsi_slope, 2),
        "score_relative": score_rel,
        "exit_reason": exit_reason
    }

    return state, debug


# ------------------------------
# ENTRY FEATURES (numeric, AI-use)
# ------------------------------

def build_entry_features(
    alt_5m_df,
    alt_1m_df,
    minutes_waited,
    exit_mode
):
    closes_1m = alt_1m_df.close.values
    closes_5m = alt_5m_df.close.values

    # ---- RSI
    rsi = compute_rsi(closes_1m)

    # ---- dump speed (last 3x 5m candles)
    if len(closes_5m) >= 4:
        rets = [
            abs((closes_5m[-i] - closes_5m[-i-1]) / closes_5m[-i-1])
            for i in range(1, 4)
        ]
        dump_speed = sum(rets)
    else:
        dump_speed = 0.0

    # ---- stabilization (deceleration)
    if len(closes_1m) >= 6:
        recent = abs(closes_1m[-1] - closes_1m[-3])
        prev = abs(closes_1m[-3] - closes_1m[-6]) + 1e-9
        stability = prev / recent
    else:
        stability = 0.0

    return {
        "rsi": rsi,
        "dump_speed": dump_speed,
        "stability": stability,
        "minutes_waited": minutes_waited,
        "exit_mode": exit_mode
    }
