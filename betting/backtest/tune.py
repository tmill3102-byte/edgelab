"""Tune RatingBook parameters on the TRAIN season only (coordinate descent over small grids).
Objective: margin params -> home-win log loss; total params -> mean squared error of the game total.
Test seasons are never seen here."""
import json, math, sys
from backtest.harness import run, SEASONS
from betlib import ratings as R

GRIDS = {
    "m_k": [0.5, 0.75, 1.0, 1.33, 2.0], "early": [0.0, 0.5, 1.0, 2.0, 4.0], "carry": [0.3, 0.45, 0.6, 0.75, 0.9],
    "cap": [0.5, 0.75, 1.0, 1.5, 3.0], "hfa": [0.0, 0.5, 0.75, 1.0, 1.25, 1.5], "sd": [0.8, 0.9, 1.0, 1.1, 1.25],
    "b2b": [0.0, 0.5, 1.0, 1.5, 2.0], "rest": [0.0, 0.5, 1.0, 2.0], "new": [0.5, 0.75, 1.0, 1.25],
    "t_k": [0.5, 0.75, 1.0, 1.5, 2.0], "t_carry": [0.0, 0.3, 0.6, 0.9], "a_lr": [0.5, 1.0, 2.0, 4.0], "ot_home": [0.48, 0.5, 0.52, 0.55],
}
MARGIN = ["m_k", "early", "carry", "cap", "hfa", "b2b", "rest", "new", "sd", "ot_home"]
TOTAL = ["t_k", "t_carry", "a_lr"]


ABS = {"carry": [0.3, 0.45, 0.6, 0.75, 0.9], "t_carry": [0.0, 0.3, 0.6, 0.9], "early": [0.0, 0.5, 1.0, 2.0, 4.0],
       "ot_home": [0.48, 0.5, 0.52, 0.55], "rest": [0.0, 0.1, 0.2, 0.4]}
B2B = {"nba": [0.0, 0.75, 1.5, 2.5, 3.5, 4.5, 5.5], "nhl": [0.0, 0.05, 0.1, 0.15, 0.25, 0.35]}


def cands(lk, k, cur):
    if k in ABS: return ABS[k]
    if k == "b2b": return B2B.get(lk, [0.0])
    if k == "new": return [-10.0, -15.0, -20.0, -25.0, -30.0, -35.0]   # FCS starting rating, kept in a sane range
    return [cur * m for m in (0.5, 0.75, 1.0, 1.33, 2.0)]


def objective(lk, params, which, feat=None):
    recs = run(lk, params, v1=False, feat=feat() if feat else None)
    tr = [r for r in recs if r["season"] in SEASONS[lk]["train"]]
    if which == "margin":
        ll, n = 0.0, 0
        for r in tr:
            if r["hs"] == r["as"]: continue
            p = min(max(r["v2"]["p_home"], 1e-4), 1 - 1e-4)
            y = r["hs"] > r["as"]
            ll -= math.log(p if y else 1 - p); n += 1
        return ll / n
    se = [((r["hs"] + r["as"]) - r["v2"]["total"]) ** 2 for r in tr]
    return sum(se) / len(se)


def tune(lk, rounds=3):
    base = dict(R.PARAMS[lk])
    for which, keys in (("margin", MARGIN), ("total", TOTAL)):
        best = objective(lk, base, which)
        print(f"[{lk}] {which} start {best:.5f}", flush=True)
        for _ in range(rounds):
            improved = False
            for k in keys:
                if k not in base: continue
                if k in ("b2b",) and not R.PARAMS[lk]["b2b"] and lk not in ("nba", "nhl"): continue
                if k == "rest" and lk not in ("nfl", "cfb"): continue
                if k == "new" and lk != "cfb": continue
                if k == "ot_home" and lk not in R.GOALS: continue
                cur = base[k]
                for v in cands(lk, k, cur):
                    if abs(v - cur) < 1e-12: continue
                    trial = dict(base, **{k: v})
                    o = objective(lk, trial, which)
                    if o < best - 1e-6:
                        best, base = o, trial; improved = True
                        print(f"   {k}={v:.4g} -> {best:.5f}", flush=True)
            if not improved: break
    if base.get("tsd") is not None:
        recs = run(lk, base, v1=False)
        tr = [r for r in recs if r["season"] in SEASONS[lk]["train"]]
        base["tsd"] = round(math.sqrt(sum(((r["hs"] + r["as"]) - r["v2"]["total"]) ** 2 for r in tr) / len(tr)), 2)
    out = {k: (round(v, 4) if isinstance(v, float) else v) for k, v in base.items()}
    print(lk, json.dumps(out), flush=True)
    return out


if __name__ == "__main__":
    res = {lk: tune(lk) for lk in sys.argv[1:]}
    json.dump(res, open(f"backtest/out/tuned_{'_'.join(sys.argv[1:])}.json", "w"), indent=1)
