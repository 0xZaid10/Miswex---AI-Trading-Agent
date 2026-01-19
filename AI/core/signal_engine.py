import numpy as np

def z_norm(arr):
    arr = np.array(arr, dtype=float)

    mu = arr.mean()
    std = arr.std()

    if std == 0:
        return arr * 0   # avoid explosion

    return (arr - mu) / std


def score(X, B, micro, g):

    if len(X) == 0 or len(B) == 0:
        return 0

    # -------- NORMALIZE --------
    Xn = z_norm(X)
    Bn = z_norm(B)

    if micro:
        micron = z_norm(micro)
    else:
        micron = None

    # -------- ALT FEATURE --------
    feats = []

    for i in g.f_idx:
        if i < len(Xn):
            feats.append(Xn[i])

    if not feats:
        return 0

    alt = (sum(feats) / len(feats)) * g.base_w

    # -------- BTC FEATURE --------
    btc = (sum(Bn) / len(Bn)) * g.btc_w

    # -------- MICRO STRUCTURE --------
    if g.use_micro and micron is not None:
        alt += (sum(micron) / len(micron)) * g.micro_w

    return alt + btc
