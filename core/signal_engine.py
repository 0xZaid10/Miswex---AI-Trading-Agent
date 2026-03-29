from utils.logger import setup_logger
log = setup_logger()

import os
import hashlib
import numpy as np
import pandas as pd
from sklearn.preprocessing import StandardScaler
import joblib



# ---------- STORAGE ----------

_SCALER_DIR = "scalers"
os.makedirs(_SCALER_DIR, exist_ok=True)


def _key_hash(key):
    return hashlib.md5(str(key).encode()).hexdigest()


def _scaler_path(key):
    return f"{_SCALER_DIR}/{_key_hash(key)}.pkl"



# ---------- NORMALIZER (PRODUCTION SAFE) ----------

_SCALERS = {}   # key -> fitted scaler

# per timeframe fit windows
_MIN_FIT_MAP = {
    "ALT": 99,    # 5m -> 8 hours
    "MICRO": 121, # 1m -> 2 hours
    "BTC": 99
}


def _load_scaler(key):
    path = _scaler_path(key)
    if os.path.exists(path):
        return joblib.load(path)
    return None


def _save_scaler(key, scaler):
    path = _scaler_path(key)
    joblib.dump(scaler, path)


def norm(feats, key):

    X = pd.DataFrame(feats)

    X = X.replace([np.inf, -np.inf], np.nan)
    X = X.ffill().bfill()
    X = X.fillna(0)

    # dynamic window
    tf_type = key[0]   # ALT / MICRO / BTC
    min_fit = _MIN_FIT_MAP.get(tf_type, 96)

    # ---------- OPTION B FIX ----------
    # load saved scaler FIRST (do not wait for min_fit)
    if key not in _SCALERS:
        sc = _load_scaler(key)
        if sc is not None:
            _SCALERS[key] = sc

    # not enough data yet AND no scaler exists
    if key not in _SCALERS and len(X) < min_fit:
        return np.zeros_like(X.values)

    # fit only if still missing
    if key not in _SCALERS:
        sc = StandardScaler()
        sc.fit(X)
        _save_scaler(key, sc)
        _SCALERS[key] = sc
    # ----------------------------------

    return _SCALERS[key].transform(X)



# ---------- FEATURE BUILDERS (exact training math) ----------

def build_alt(df):

    return {
        "r1":np.log(df.close/df.close.shift(1)),
        "r5":np.log(df.close/df.close.shift(5)),
        "r15":np.log(df.close/df.close.shift(15)),
        "vol":df.close.pct_change().rolling(20).std(),
        "vol_chg":df.volume.pct_change(),
        "atr":(df.high-df.low).rolling(14).mean(),
        "trend":df.close-df.close.rolling(50).mean()
    }


def build_btc(df):

    return {
        "btc_r":df.close.pct_change(),
        "btc_vol":df.close.pct_change().rolling(20).std(),
        "btc_trend":df.close-df.close.rolling(50).mean(),
        "btc_vol_chg":df.volume.pct_change()
    }


def build_micro(df):

    return {
        "r":np.log(df.close/df.close.shift(1)),
        "mom":df.close.pct_change(2),
        "vol":df.close.rolling(8).std()
    }



# ---------- SAFE ALIGN ----------

def align(alt_df, micro_df, microN):
    """
    Align micro timeframe to alt timeframe.
    Production-safe: trims to alt length.
    """
    if len(microN) > len(alt_df):
        return microN[-len(alt_df):]

    return microN



# ---------- MAIN ----------

def _sym(g):
    return getattr(g, "symbol", getattr(g, "pair", "UNKNOWN"))

def _tf(g):
    return getattr(g, "tf", getattr(g, "timeframe", "UNKNOWN"))


def score(
    alt_df, btc_df, micro_df,
    g
):

    if len(alt_df)<50 or len(btc_df)<50:
        return 0

    # ---- ONE TIME SCALER STATUS LOG ----
    if not hasattr(score, "_logged"):
        score._logged = True

        fitted = list(_SCALERS.keys())

        s1m = any(k[0]=="MICRO" for k in fitted)
        s5m = any(k[0]=="ALT" and k[2]=="5m" for k in fitted)

        log.info(
            f"[SCALER-STATUS] "
            f"1m={'FITTED' if s1m else 'NOT_FIT'} | "
            f"5m={'FITTED' if s5m else 'NOT_FIT'} | "
            f"keys={fitted}"
        )


    # ----- ALT -----
    alt_feats = build_alt(alt_df)
    altN = norm(alt_feats, ("ALT", _sym(g), _tf(g)))


    # ----- BTC -----
    btc_feats = build_btc(btc_df)
    btcN = norm(btc_feats, ("BTC", "BTC", _tf(g)))


    # ----- MICRO -----
    if g.use_micro and micro_df is not None:

        micro_feats = build_micro(micro_df)
        micro_raw = norm(micro_feats, ("MICRO", _sym(g), "1m"))

        # EXACT alignment
        microN = align(alt_df, micro_df, micro_raw)

    else:
        microN = None


    # ---------- ALT SCORE ----------
    feats = []
    for i in g.f_idx:
        if i < altN.shape[1]:
            feats.append(altN[-1, i])

    if not feats:
        return 0

    alt = (sum(feats)/len(feats)) * g.base_w


    # ---------- BTC SCORE ----------
    btc = btcN[-1].mean() * g.btc_w


    # ---------- MICRO ----------
    if g.use_micro and microN is not None:
        alt += microN[-1].mean() * g.micro_w


    return alt + btc
