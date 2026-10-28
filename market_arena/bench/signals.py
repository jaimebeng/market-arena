"""Textbook taker signals, written against the same `signal(obs)` contract as agent strategies.

They serve as scripted benchmark takers and as the reference set used to label what an agent's
invented strategy most resembles.
"""

TEXTBOOK = {
    "order_book_imbalance": '''
def signal(obs):
    # resting depth imbalance at the top of the book predicts the next move
    return {a: float(np.clip(3 * np.mean(obs.hist(a, "imbalance", 5)), -1, 1)) for a in obs.assets}
''',
    "trade_flow": '''
def signal(obs):
    # recent aggressive buying minus selling (order-flow imbalance)
    out = {}
    for a in obs.assets:
        sv = obs.hist(a, "signed_volume", 30).sum()
        v = obs.hist(a, "volume", 30).sum()
        out[a] = float(np.tanh(2 * sv / v)) if v > 0 else 0.0
    return out
''',
    "momentum": '''
def signal(obs):
    out = {}
    for a in obs.assets:
        m = obs.hist(a, "mid", 101)
        if len(m) < 101:
            out[a] = 0.0
            continue
        vol = np.std(np.diff(m)) * 10 + 1e-9
        out[a] = float(np.tanh((m[-1] - m[0]) / vol))
    return out
''',
    "mean_reversion": '''
def signal(obs):
    out = {}
    for a in obs.assets:
        m = obs.hist(a, "mid", 21)
        if len(m) < 21:
            out[a] = 0.0
            continue
        vol = np.std(np.diff(m)) * 4.5 + 1e-9
        out[a] = float(np.tanh(-(m[-1] - m[0]) / vol))
    return out
''',
    "index_arbitrage": '''
def signal(obs):
    idx = obs.meta.get("index")
    if not idx:
        return {}
    # trade the index back toward the value of its basket; ignore small gaps (costs)
    fair = sum(s * obs.last(c, "mid") for c, s in idx["shares"].items())
    gap_bps = (obs.last(idx["name"], "mid") / fair - 1) * 1e4
    if abs(gap_bps) < 8:
        return {idx["name"]: 0.0}
    return {idx["name"]: float(np.clip(-gap_bps / 20, -1, 1))}
''',
    "venue_arbitrage": '''
def signal(obs):
    out = {}
    for stock, venues in (obs.meta.get("listings") or {}).items():
        home, alt = venues[0], venues[1]
        # buy the cheaper listing and sell the dearer one when their mids differ by more than costs
        gap_bps = (obs.last(alt, "mid") / obs.last(home, "mid") - 1) * 1e4
        s = 0.0 if not abs(gap_bps) >= 6 else float(np.clip(-gap_bps / 15, -1, 1))
        out[alt], out[home] = s, -s
    return out
''',
}
