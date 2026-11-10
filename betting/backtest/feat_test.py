"""Pick a feature weight on the TRAIN season (home-win log loss), then report what it does out of sample."""
import json, math, sys
from backtest.harness import run, SEASONS
from backtest.evaluate import evaluate
from backtest import features as Fe


def ll(recs, seasons, key="p_home"):
    s = n = 0
    for r in recs:
        if r["season"] not in seasons or r["hs"] == r["as"]: continue
        p = min(max(r["v2"][key], 1e-4), 1 - 1e-4); y = r["hs"] > r["as"]
        s -= math.log(p if y else 1 - p); n += 1
    return s / n


def tse(recs, seasons):
    x = [((r["hs"] + r["as"]) - r["v2"]["total"]) ** 2 for r in recs if r["season"] in seasons]
    return sum(x) / len(x)


if __name__ == "__main__":
    lk, cls, arg = sys.argv[1], sys.argv[2], sys.argv[3]
    extra = json.loads(sys.argv[5]) if len(sys.argv) > 5 else {}
    S = SEASONS[lk]
    out = []
    for v in [float(x) for x in sys.argv[4].split(",")]:
        recs = run(lk, None, v1=False, feat=getattr(Fe, cls)(**{arg: v}, **extra))
        ev = evaluate(lk, recs, verbose=False)
        m = ev["markets"]["ml"]
        out.append((v, ll(recs, S["train"]), ll(recs, S["test"]), tse(recs, S["train"]), tse(recs, S["test"]),
                    m["v2_final"]["d_logloss_vs_mkt"], m["open"]["v2_final"]["d_logloss_vs_mkt"], ev["markets"].get("tot", {}).get("v2_final", {}).get("d_logloss_vs_mkt")))
        print(f"{arg}={v}: train ML LL {out[-1][1]:.5f} | test ML LL {out[-1][2]:.5f} | train tot MSE {out[-1][3]:.3f} | test tot MSE {out[-1][4]:.3f} | test final dLL close {out[-1][5]:+.5f} open {out[-1][6]:+.5f} tot {out[-1][7] if out[-1][7] is None else round(out[-1][7],5)}", flush=True)
