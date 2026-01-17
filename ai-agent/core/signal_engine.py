def score(X, B, micro, g):

    alt = sum([X[i] for i in g.f_idx]) / len(g.f_idx) * g.base_w
    btc = sum(B) / len(B) * g.btc_w

    if g.use_micro:
        alt += sum(micro) / len(micro) * g.micro_w

    return alt + btc
