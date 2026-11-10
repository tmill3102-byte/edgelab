"""Stage 3: per-league market enable/blend decisions (pre-registered rule), the 'v2 as shipped' pick backtest,
betlib/data/blend.json for the live engine, and BACKTEST.md tables (backtest/out/summary.json)."""
import json, math, os, sys
import numpy as np
from backtest.harness import SEASONS, SEASON_NAME
from backtest import evaluate as E
from betlib.models import am_to_dec

LEAGUES = ["nba", "nhl", "nfl", "cfb", "mlb"]


def fit_b(recs, m, seasons, kind):
    if kind == "open":
        R = E.rows(recs, m, seasons, "open")
        return (E.fit_logit([x[2] for x in R], [x[3] for x in R], [x[1] for x in R])["b"], len(R)) if len(R) >= 100 else (None, len(R))
    R = E.clv_rows(recs, m, seasons)
    return (E.fit_clv([x[1] for x in R], [x[2] for x in R], [x[3] for x in R])["b"], len(R)) if len(R) >= 100 else (None, len(R))


def season_dll_open(recs, m, b, season):
    R = E.rows(recs, m, [season], "open")
    if not R: return None, 0
    y = [x[1] for x in R]; pm = [x[2] for x in R]
    fin = E.apply({"a": 1 - b, "b": b, "c": 0}, np.array(pm), np.array([x[3] for x in R]))
    mt = E.metrics(fin, y, pm)
    return mt["d_logloss_vs_mkt"], mt["n"]


def picks_for(recs, lk, m, b, seasons, snap):
    lst = []
    for r in recs:
        if r["season"] not in seasons or not r.get(snap): continue
        for p in E.v2_candidates(r, {m: {"a": 1 - b, "b": b, "c": 0.0}}, snap, mkts=(m,)):
            if p["ev"] <= 0: continue
            d = am_to_dec(p["odds"])
            inrange = 1.25 <= d <= 5.0      # -400 .. +400: outside this, CLV/ROI are dominated by longshot noise
            p["tier"] = "High" if (p["ev"] >= 0.03 and inrange) else ("Medium" if (p["ev"] >= 0.01 and inrange) else "Low")
            # (v1 downgraded picks whose raw model was >12 pp from the market; the backtest found those picks had no worse
            #  CLV than the rest, so v2 keeps it as an informational note only - mirrored here)
            lst.append((p, r, E.clv(r, p["market"], p["side"], p["line"], p["odds"]) if snap == "open" else None))
    return lst


def decide(recs, lk, m, eval_season, fit_seasons):
    """Pre-registered rule. (a) log-loss route: b fitted on fit_seasons vs the opener improves log loss on eval_season.
    (b) CLV route: CLV-fitted b >= 0.05 and the High+Medium picks it makes on eval_season (at the opener) beat the
    closing line on average with n >= 30."""
    out = {"market": m, "eval_season": eval_season}
    bo, n_o = fit_b(recs, m, fit_seasons, "open")
    if bo is not None:
        d, n = season_dll_open(recs, m, bo, eval_season)
        out.update(b_open=bo, dll_open=d, n_eval=n)
        if d is not None and d < 0 and bo >= 0.02:
            out.update(route="logloss", ok=True); return out
    bc, n_c = fit_b(recs, m, fit_seasons, "clv")
    if bc is not None:
        out["b_clv"] = bc
        if bc >= 0.05:
            pk = [x for x in picks_for(recs, lk, m, bc, [eval_season], "open") if x[0]["tier"] in ("High", "Medium") and x[2] is not None]
            out.update(clv_n=len(pk), clv_mean=(sum(x[2] for x in pk) / len(pk)) if pk else None)
            if len(pk) >= 30 and out["clv_mean"] > 0:
                out.update(route="clv", ok=True); return out
    out["ok"] = False
    return out


def run_league(lk):
    recs = json.load(open(f"backtest/out/{lk}_recs.json"))
    ev = E.evaluate(lk, recs, verbose=False)
    S = SEASONS[lk]; tr, te = S["train"], S["test"]
    allseas = tr + te
    summary = {"eval": ev, "live": {}, "final": {}}
    # v2-as-shipped, genuinely out of sample: decide on te[0] (fit on train), refit b on train+te[0], test on te[1]
    if len(te) >= 2:
        for m in ("ml", "sp", "tot"):
            dcs = decide(recs, lk, m, te[0], tr)
            lst = []
            if dcs["ok"]:
                b, _ = fit_b(recs, m, tr + [te[0]], "open" if dcs["route"] == "logloss" else "clv")
                dcs["b_used"] = b
                lst_open = picks_for(recs, lk, m, b, [te[1]], "open")
                lst_close = picks_for(recs, lk, m, b, [te[1]], "close")
                dcs["picks_open"] = E.summarize_picks(lst_open); dcs["picks_close"] = E.summarize_picks(lst_close)
            summary["live"][m] = dcs
    # shipped config: pooled walk-forward evidence over ALL test seasons (each season's b fitted only on earlier seasons)
    blend, wf = {}, {}
    for m in ("ml", "sp", "tot"):
        mm = ev["markets"].get(m, {}); op = (mm.get("open") or {}).get("v2_final") or {}
        lst_c, lst_o = [], []
        for s_ in te:
            bc = (ev["coefs_clv"].get(s_) or {}).get(m, {}).get("b")
            if bc is not None and bc > 0:
                lst_c += picks_for(recs, lk, m, bc, [s_], "open")
            bo = (ev["coefs_open"].get(s_) or {}).get(m, {}).get("b")
            if bo is not None and bo > 0:
                lst_o += [x for x in picks_for(recs, lk, m, bo, [s_], "open")]
        sc, so = E.summarize_picks(lst_c), E.summarize_picks(lst_o)
        hm = sc["High+Medium"]
        w = {"dll_open": op.get("d_logloss_vs_mkt"), "se": op.get("se_d"), "n_open": op.get("n"), "clv_picks": sc, "open_picks": so}
        wf[m] = w
        om = so["High+Medium"]
        if (w["dll_open"] is not None and w["se"] is not None and w["dll_open"] < -1e-4 and w["dll_open"] + w["se"] < 0
                and not (om.get("clv_n", 0) >= 30 and om.get("clv") is not None and om["clv"] < 0)):
            route = "logloss"
        elif hm["n"] >= 30 and hm.get("clv") is not None and hm["clv"] > 0:
            route = "clv"
        else:
            route = None
        if route:
            b, n = fit_b(recs, m, allseas, "open" if route == "logloss" else "clv")
            if not b:
                route = None
        if route:
            why = (f"walk-forward blend beat the opening line's log loss over {w['n_open']} test games (dLL {w['dll_open']:+.4f} ± {w['se']:.4f})" if route == "logloss"
                   else f"walk-forward High+Medium picks beat the closing line by {hm['clv']*100:+.1f}% on average (n={hm['clv_n']})")
            blend[m] = {"enabled": True, "b": round(b, 3), "basis": "fit on " + ", ".join(SEASON_NAME[lk][s_] for s_ in allseas), "route": route, "n_fit": n, "why": why}
        else:
            blend[m] = {"enabled": False, "b": 0.0, "why": f"walk-forward dLL vs opener {w['dll_open'] if w['dll_open'] is None else round(w['dll_open'], 4)}, "
                                                          f"CLV picks n={hm['n']} mean CLV {None if hm.get('clv') is None else round(hm['clv'], 4)}"}
    summary["walkforward"] = wf
    summary["final"] = blend
    return summary


if __name__ == "__main__":
    lks = sys.argv[1:] or [l for l in LEAGUES if os.path.exists(f"backtest/out/{l}_recs.json")]
    allsum = {}
    for lk in lks:
        allsum[lk] = run_league(lk)
        print(lk, json.dumps({m: {k: v for k, v in d.items() if k in ("ok", "route", "b_open", "dll_open", "b_clv", "clv_n", "clv_mean", "b_used")} for m, d in allsum[lk]["live"].items()}, default=float))
        print("   final", json.dumps(allsum[lk]["final"], default=float))
        for m, w in allsum[lk]["walkforward"].items():
            print("   wf", m, "dLL_open", w["dll_open"], "clv-picks", {t: (x["n"], x.get("clv") and round(x["clv"], 4), x.get("roi") and round(x["roi"], 3)) for t, x in w["clv_picks"].items()},
                  "open-fit picks", {t: (x["n"], x.get("clv") and round(x["clv"], 4), x.get("roi") and round(x["roi"], 3)) for t, x in w["open_picks"].items()})
        for m, d in allsum[lk]["live"].items():
            if d.get("picks_open"):
                print("   live", m, "open", {t: (x["n"], x.get("roi") and round(x["roi"], 3), x.get("clv") and round(x["clv"], 4)) for t, x in d["picks_open"].items()},
                      "close", {t: (x["n"], x.get("roi") and round(x["roi"], 3)) for t, x in d["picks_close"].items()})
    old = json.load(open("backtest/out/summary.json")) if os.path.exists("backtest/out/summary.json") else {}
    old.update(allsum)
    json.dump(old, open("backtest/out/summary.json", "w"), indent=1, default=float)
    blend = {lk: v["final"] for lk, v in old.items()}
    json.dump(blend, open("betlib/data/blend.json", "w"), indent=1, default=float)
