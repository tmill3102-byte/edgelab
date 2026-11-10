"""Ship the rating state at the end of the last COMPLETED season so the live engine only replays the current season."""
import json, os, sys
from backtest.harness import load
from betlib.ratings import RatingBook, make_feature

LAST_DONE = {"nba": 2026, "nhl": 2026, "nfl": 2025, "cfb": 2025, "mlb": 2026}
out_path = "betlib/data/ratings_seed.json"
seed = json.load(open(out_path)) if os.path.exists(out_path) else {}
for lk in sys.argv[1:] or LAST_DONE:
    b = RatingBook(lk)
    feat = make_feature(lk)
    n = 0
    for g in load(lk):
        if g["season"] > LAST_DONE[lk]: continue
        am, at, _ = feat.pre(g) if feat else (0.0, 0.0, [])
        b.update(g["home"]["id"], g["away"]["id"], g["home"]["score"], g["away"]["score"], g["when"], g["neutral"], g["season"], am, at); n += 1
        if feat: feat.post(g)
    seed[lk] = {"season": LAST_DONE[lk], "games": n, "params": b.p,
                "state": {"r": b.r, "t": b.t, "n": b.n, "season": b.season, "last": {k: v.isoformat() for k, v in b.last.items()}, "avg": b.avg, "feature": feat.state() if feat else None}}
    print(lk, "seed after", n, "games; season", LAST_DONE[lk])
json.dump(seed, open(out_path, "w"))
