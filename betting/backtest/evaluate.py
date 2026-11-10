"""Stage 2: score the recorded walk-forward predictions. Blend coefficients for test season s are fitted only on
seasons < s (expanding window). Prints and returns metrics; used by report.py."""
import json, math, os, sys
import numpy as np
from backtest.harness import SEASONS, grade
from betlib.models import am_to_dec, implied

MK = {"ml": ("p_home", "ml"), "sp": ("p_home_cover", "sp"), "tot": ("p_over", "tot")}
MNAME = {"ml": "ML", "sp": "Spread", "tot": "Total"}


def lg(p):
    p = np.clip(np.asarray(p, float), 1e-6, 1 - 1e-6)
    return np.log(p / (1 - p))


def outcome(r, m, snap="close"):
    c = r[snap]
    if m == "ml":
        return None if r["hs"] == r["as"] else int(r["hs"] > r["as"])
    if m == "sp":
        v = r["hs"] - r["as"] + c["sp_line"]
        return None if abs(v) < 1e-9 else int(v > 0)
    v = r["hs"] + r["as"] - c["tot_line"]
    return None if abs(v) < 1e-9 else int(v > 0)


def rows(recs, m, seasons, snap="close", need_v1=False):
    out = []
    pk, mk = MK[m]
    for r in recs:
        if r["season"] not in seasons or not r.get(snap) or r[snap].get(mk) is None: continue
        y = outcome(r, m, snap)
        if y is None: continue
        pv2 = r["v2"].get(pk if snap == "close" else "o_" + pk)
        if pv2 is None: continue
        v1 = r.get("v1") or {}
        if need_v1 and v1.get(pk) is None: continue
        out.append((r, y, r[snap][mk], pv2, v1.get(pk)))
    return out


def fit_logit(xm, xmod, y, l2=None):
    """One-parameter blend in log-odds space: logit(p) = (1-b)*logit(market) + b*logit(model), b in [0,1].
    b = how much weight the out-of-sample history says the model deserves next to the closing market.
    (A free 3-parameter fit was tried first; with 250-1,300 games per season it mostly re-scaled the market, i.e. noise.)"""
    lm, lo, y = lg(xm), lg(xmod), np.asarray(y, float)
    best = (1e9, 0.0)
    for b in np.arange(0, 1.0001, 0.01):
        z = (1 - b) * lm + b * lo; p = np.clip(1 / (1 + np.exp(-z)), 1e-6, 1 - 1e-6)
        ll = -(y * np.log(p) + (1 - y) * np.log(1 - p)).mean()
        if ll < best[0] - 1e-12: best = (ll, float(b))
    return {"a": 1 - best[1], "b": best[1], "c": 0.0}


def fit_clv(xm_open, xmod, p_close):
    """b that best predicts the CLOSING no-vig probability from the opener + model (soft cross-entropy)."""
    lm, lo, t = lg(xm_open), lg(xmod), np.asarray(p_close, float)
    best = (1e9, 0.0)
    for b in np.arange(0, 1.0001, 0.01):
        p = np.clip(1 / (1 + np.exp(-((1 - b) * lm + b * lo))), 1e-6, 1 - 1e-6)
        ce = -(t * np.log(p) + (1 - t) * np.log(1 - p)).mean()
        if ce < best[0] - 1e-12: best = (ce, float(b))
    return {"a": 1 - best[1], "b": best[1], "c": 0.0}


def clv_rows(recs, m, seasons):
    """(rec, open_novig, model_at_open_line, close_novig) where open and close are the same line."""
    pk, mk = MK[m]; out = []
    for r in recs:
        if r["season"] not in seasons or not r.get("open") or not r.get("close"): continue
        o, c = r["open"], r["close"]
        if o.get(mk) is None or c.get(mk) is None: continue
        if m == "sp" and abs(o["sp_line"] - c["sp_line"]) > 1e-9: continue
        if m == "tot" and abs(o["tot_line"] - c["tot_line"]) > 1e-9: continue
        pv = r["v2"].get("o_" + pk)
        if pv is None: continue
        out.append((r, o[mk], pv, c[mk]))
    return out


def apply(c, pm, pmod):
    return 1 / (1 + np.exp(-(c["a"] * lg(pm) + c["b"] * lg(pmod) + c["c"])))


def fit_platt(pmod, y, l2=1.0):
    X = np.column_stack([lg(pmod), np.ones(len(y))]); y = np.asarray(y, float); w = np.array([1.0, 0.0])
    for _ in range(50):
        p = 1 / (1 + np.exp(-X @ w)); g = X.T @ (p - y) + l2 * (w - [1, 0])
        H = (X * (p * (1 - p))[:, None]).T @ X + l2 * np.eye(2); s = np.linalg.solve(H, g); w -= s
        if np.abs(s).max() < 1e-8: break
    return w


def isotonic_fit(x, y):
    o = np.argsort(x); xs, ys = np.asarray(x)[o], np.asarray(y, float)[o]
    blocks = []  # [sum, count, xmax]
    for xi, yi in zip(xs, ys):
        blocks.append([yi, 1.0, xi])
        while len(blocks) > 1 and blocks[-2][0] / blocks[-2][1] > blocks[-1][0] / blocks[-1][1]:
            s, c, xm = blocks.pop(); blocks[-1][0] += s; blocks[-1][1] += c; blocks[-1][2] = xm
    xk = np.array([b[2] for b in blocks]); yk = np.array([b[0] / b[1] for b in blocks])
    return xk, np.clip(yk, 0.02, 0.98)


def isotonic_apply(model, x):
    xk, yk = model
    idx = np.searchsorted(xk, x, side="left"); idx = np.clip(idx, 0, len(yk) - 1)
    return yk[idx]


def metrics(p, y, base=None):
    p = np.clip(np.asarray(p, float), 1e-6, 1 - 1e-6); y = np.asarray(y, float)
    ll = -(y * np.log(p) + (1 - y) * np.log(1 - p))
    out = {"n": int(len(y)), "logloss": float(ll.mean()), "brier": float(((p - y) ** 2).mean())}
    if base is not None:
        b = np.clip(np.asarray(base, float), 1e-6, 1 - 1e-6)
        lb = -(y * np.log(b) + (1 - y) * np.log(1 - b))
        d = ll - lb
        out["d_logloss_vs_mkt"] = float(d.mean()); out["se_d"] = float(d.std(ddof=1) / math.sqrt(len(d))) if len(d) > 1 else None
    return out


def calib(p, y, edges=(0, .2, .35, .45, .55, .65, .8, 1.0001)):
    p = np.asarray(p); y = np.asarray(y, float); out = []
    for lo, hi in zip(edges[:-1], edges[1:]):
        k = (p >= lo) & (p < hi)
        if k.sum(): out.append({"bin": f"{lo:.2f}-{min(hi,1):.2f}", "n": int(k.sum()), "pred": float(p[k].mean()), "actual": float(y[k].mean())})
    return out


def profit(win, odds):
    if win is None: return 0.0
    return am_to_dec(odds) - 1 if win else -1.0


def clv(r, mname, side, line, odds):
    """CLV of a bet struck at `odds` (open) vs the closing no-vig prob of the same selection (same line only)."""
    c = r["close"]
    if mname == "ML":
        if c.get("ml") is None: return None
        pc = c["ml"] if side == "home" else 1 - c["ml"]
    elif mname == "Spread":
        if c.get("sp") is None: return None
        cl = c["sp_line"] if side == "home" else -c["sp_line"]
        if abs(cl - line) > 1e-9: return None
        pc = c["sp"] if side == "home" else 1 - c["sp"]
    else:
        if c.get("tot") is None or abs(c["tot_line"] - line) > 1e-9: return None
        pc = c["tot"] if side == "over" else 1 - c["tot"]
    return am_to_dec(odds) * pc - 1


def summarize_picks(lst):
    """lst: (pick, rec, clv or None). Flat 1-unit stakes, graded at the pick's price."""
    out = {}
    for t in ("High", "Medium", "Low", "High+Medium"):
        sel = [x for x in lst if (x[0]["tier"] in ("High", "Medium") if t == "High+Medium" else x[0]["tier"] == t)]
        if not sel: out[t] = {"n": 0}; continue
        w = [grade(p["market"], p["side"], p["line"], r["hs"], r["as"]) for p, r, _ in sel]
        pr = [profit(wi, p["odds"]) for wi, (p, r, _) in zip(w, sel)]
        dec = [x for x in w if x is not None]
        cl = [c for _, _, c in sel if c is not None]
        out[t] = {"n": len(sel), "hit": (sum(dec) / len(dec)) if dec else None, "roi": sum(pr) / len(sel),
                  "units": sum(pr), "clv_n": len(cl), "clv": (sum(cl) / len(cl)) if cl else None,
                  "clv_pos": (sum(1 for c in cl if c > 0) / len(cl)) if cl else None}
    return out


def v1_picks(recs, seasons, snap):
    lst = []
    for r in recs:
        if r["season"] not in seasons or not r.get("v1"): continue
        for p in r["v1"].get("picks_" + snap) or []:
            if p["ev"] <= 0 or p["market"] not in ("ML", "Spread", "Total"): continue
            lst.append((p, r, clv(r, p["market"], p["side"], p["line"], p["odds"]) if snap == "open" else None))
    return lst


# ---------------- v2 picks ----------------
def v2_candidates(r, coefs, snap, mkts=("ml", "sp", "tot")):
    """All priced sides with the blended v2 probability (coefs fitted on earlier seasons only)."""
    c = r[snap]; out = []
    for m in mkts:
        cf = coefs.get(m)
        pk = MK[m][0] if snap == "close" else "o_" + MK[m][0]
        if not cf or c.get(m) is None or r["v2"].get(pk) is None: continue
        pf = float(apply(cf, c[m], r["v2"][pk]))
        if m == "ml":
            sides = (("home", None, c["ml_home"], pf, c["ml"]), ("away", None, c["ml_away"], 1 - pf, 1 - c["ml"]))
        elif m == "sp":
            sides = (("home", c["sp_line"], c["sp_home"], pf, c["sp"]), ("away", -c["sp_line"], c["sp_away"], 1 - pf, 1 - c["sp"]))
        else:
            sides = (("over", c["tot_line"], c["over"], pf, c["tot"]), ("under", c["tot_line"], c["under"], 1 - pf, 1 - c["tot"]))
        for side, line, odds, p, pm in sides:
            ev = p * am_to_dec(odds) - 1   # pushes ignored here (half-point lines dominate)
            out.append({"market": MNAME[m], "m": m, "side": side, "line": line, "odds": odds, "model_prob": p, "market_prob": pm,
                        "edge": p - pm, "ev": ev, "model_raw": r["v2"][pk] if side in ("home", "over") else 1 - r["v2"][pk]})
    return out


CLV_TIERS = {"high": 0.03, "med": 0.01}


def clv_tier(p, th):
    """Tier on predicted CLV = EV at the offered price if the line closes where the model expects."""
    if p["ev"] >= th["high"] and am_to_dec(p["odds"]) <= 5.0: return "High"
    if p["ev"] >= th["med"]: return "Medium"
    return "Low"


def assign_tier(p, th):
    t = th.get(p["m"])
    if not t or p["ev"] <= 0: return "Low"
    if am_to_dec(p["odds"]) > 5.0 and p["edge"] >= t["med"]: return "Medium"
    if p["edge"] >= t["high"] and p["ev"] >= t.get("high_ev", 0.0): return "High"
    if p["edge"] >= t["med"]: return "Medium"
    return "Low"


def evaluate(lk, recs, l2=1.0, tier_q=(0.97, 0.90), verbose=True):
    S = SEASONS[lk]; tr, te = S["train"], S["test"]
    res = {"league": lk, "train": tr, "test": te, "markets": {}, "coefs": {}, "picks": {}, "coverage": {}}
    allseas = tr + te
    for s in allseas:
        n = sum(1 for r in recs if r["season"] == s)
        res["coverage"][s] = {"games": n, "close_ml": sum(1 for r in recs if r["season"] == s and r.get("close") and r["close"].get("ml") is not None),
                              "close_sp": sum(1 for r in recs if r["season"] == s and r.get("close") and r["close"].get("sp") is not None),
                              "close_tot": sum(1 for r in recs if r["season"] == s and r.get("close") and r["close"].get("tot") is not None),
                              "open_ml": sum(1 for r in recs if r["season"] == s and r.get("open") and r["open"].get("ml") is not None)}
    coefs_snap = {"close": {}, "open": {}}
    for snap in ("close", "open"):
        for s_ in te:
            prior = [x for x in allseas if x < s_]
            cs = {}
            for m in MK:
                R = rows(recs, m, prior, snap)
                if len(R) < 100: continue
                cs[m] = fit_logit([x[2] for x in R], [x[3] for x in R], [x[1] for x in R], l2)
                cs[m]["n_fit"] = len(R)
            coefs_snap[snap][s_] = cs
    coefs_snap["clv"] = {}
    for s_ in te:
        prior = [x for x in allseas if x < s_]; cs = {}
        for m in MK:
            R = clv_rows(recs, m, prior)
            if len(R) < 100: continue
            cs[m] = fit_clv([x[1] for x in R], [x[2] for x in R], [x[3] for x in R]); cs[m]["n_fit"] = len(R)
        coefs_snap["clv"][s_] = cs
    res["coefs_clv"] = coefs_snap["clv"]
    coefs_by_season = coefs_snap["close"]
    res["coefs_open"] = coefs_snap["open"]
    res["coefs"] = coefs_by_season
    # final (all seasons) coefficients for the live engine
    res["final_coefs"] = {}
    for snap in ("close", "open"):
        final = {}
        for m in MK:
            R = rows(recs, m, allseas, snap)
            if len(R) >= 100:
                final[m] = fit_logit([x[2] for x in R], [x[3] for x in R], [x[1] for x in R], l2); final[m]["n_fit"] = len(R)
        res["final_coefs"][snap] = final
    fc = {}
    for m in MK:
        R = clv_rows(recs, m, allseas)
        if len(R) >= 100:
            fc[m] = fit_clv([x[1] for x in R], [x[2] for x in R], [x[3] for x in R]); fc[m]["n_fit"] = len(R)
    res["final_coefs"]["clv"] = fc
    # ---- probability metrics on test seasons ----
    has_v1 = any(r.get("v1") for r in recs)
    for m in MK:
        R = rows(recs, m, te, need_v1=has_v1)
        if not R: continue
        y = [x[1] for x in R]; pm = [x[2] for x in R]; v2 = [x[3] for x in R]; v1 = [x[4] for x in R]
        # v1 engine output = dq-weighted blend recorded in picks_close
        eng = []
        for r, *_ in R:
            side = "over" if m == "tot" else "home"
            pp = [p for p in (r.get("v1") or {}).get("picks_close", []) if p["market"] == MNAME[m] and p["side"] == side]
            eng.append(pp[0]["model_prob"] if pp else None)
        fin = np.array([float(apply(coefs_by_season[r["season"]][m], x2, x3)) if m in coefs_by_season[r["season"]] else x2 for (r, _, x2, x3, _) in R])
        # model-only calibration (Platt / isotonic) fitted on earlier seasons
        platt, iso = [], []
        for s in te:
            Rp = rows(recs, m, [x for x in allseas if x < s])
            w = fit_platt([x[3] for x in Rp], [x[1] for x in Rp])
            im = isotonic_fit([x[3] for x in Rp], [x[1] for x in Rp])
            for (r, _, _, x3, _) in R:
                if r["season"] == s:
                    platt.append(float(1 / (1 + np.exp(-(w[0] * lg(x3) + w[1])))))
                    iso.append(float(isotonic_apply(im, np.array([x3]))[0]))
        # keep season order consistent for platt/iso
        order = [i for s in te for i, x in enumerate(R) if x[0]["season"] == s]
        yo = [y[i] for i in order]; pmo = [pm[i] for i in order]
        mm = {"market_close": metrics(pm, y), "v1_raw": metrics(v1, y, pm) if has_v1 else None,
              "v1_engine": metrics([e if e is not None else b for e, b in zip(eng, pm)], y, pm),
              "v2_raw": metrics(v2, y, pm), "v2_platt": metrics(platt, yo, pmo), "v2_isotonic": metrics(iso, yo, pmo),
              "v2_final": metrics(fin, y, pm)}
        mm["calib_v1_engine"] = calib([e if e is not None else b for e, b in zip(eng, pm)], y)
        mm["calib_v2_final"] = calib(fin, y)
        mm["calib_market"] = calib(pm, y)
        # train-season (in-sample for params) raw-model numbers, for reference
        Rt = rows(recs, m, tr, need_v1=True)
        if Rt and has_v1:
            mm["train"] = {"market_close": metrics([x[2] for x in Rt], [x[1] for x in Rt]),
                           "v1_raw": metrics([x[4] for x in Rt], [x[1] for x in Rt], [x[2] for x in Rt]),
                           "v2_raw": metrics([x[3] for x in Rt], [x[1] for x in Rt], [x[2] for x in Rt])}
        Ro = rows(recs, m, te, "open")
        if Ro:
            yo_ = [x[1] for x in Ro]; pmo_ = [x[2] for x in Ro]
            fo = [float(apply(coefs_snap["open"][r["season"]][m], x2, x3)) if m in coefs_snap["open"][r["season"]] else x2 for (r, _, x2, x3, _) in Ro]
            mm["open"] = {"market_open": metrics(pmo_, yo_), "v2_raw": metrics([x[3] for x in Ro], yo_, pmo_), "v2_final": metrics(fo, yo_, pmo_)}
            if m == "ml" and has_v1:
                v1o = [(x[4], x[1], x[2]) for x in Ro if x[4] is not None]
                mm["open"]["v1_raw"] = metrics([a for a, _, _ in v1o], [b for _, b, _ in v1o], [c for _, _, c in v1o])
            # does the model's disagreement with the opener predict where the line closes? (same line only)
            xs, ys = [], []
            mk = MK[m][1]
            for (r, _, x2, x3, _) in Ro:
                c = r.get("close") or {}
                if c.get(mk) is None: continue
                if m == "sp" and abs(c["sp_line"] - r["open"]["sp_line"]) > 1e-9: continue
                if m == "tot" and abs(c["tot_line"] - r["open"]["tot_line"]) > 1e-9: continue
                xs.append(float(lg(x3) - lg(x2))); ys.append(float(lg(c[mk]) - lg(x2)))
            if len(xs) > 30:
                xs, ys = np.array(xs), np.array(ys)
                mm["clv_signal"] = {"n": len(xs), "corr": float(np.corrcoef(xs, ys)[0, 1]), "slope": float((xs * ys).sum() / (xs * xs).sum())}
        res["markets"][m] = mm
    # ---- picks ----
    res["picks"]["v1_close"] = summarize_picks(v1_picks(recs, te, "close"))
    res["picks"]["v1_open"] = summarize_picks(v1_picks(recs, te, "open"))
    # v2 tier thresholds: edge quantiles of positive-EV candidates on seasons < first test season (no test outcomes used)
    th_by_season = {}
    for s in te:
        prior = [x for x in allseas if x < s]
        cf = coefs_snap["open"][s]; th = {}
        for m in MK:
            # only markets where the walk-forward fit gives the model real weight get High/Medium tiers
            if m not in cf or cf[m]["b"] < 0.05: continue
            eds = []
            for r in recs:
                if r["season"] in prior and r.get("open"):
                    eds += [p["edge"] for p in v2_candidates(r, {m: cf[m]}, "open") if p["ev"] > 0]
            if len(eds) < 50: continue
            th[m] = {"high": float(np.quantile(eds, tier_q[0])), "med": float(np.quantile(eds, tier_q[1]))}
        th_by_season[s] = th
    res["tiers"] = th_by_season
    for snap in ("close", "open", "clv"):
        lst = []
        for r in recs:
            src = "open" if snap == "clv" else snap
            if r["season"] not in te or not r.get(src): continue
            for p in v2_candidates(r, coefs_snap[snap][r["season"]], src):
                if snap == "clv":
                    p["tier"] = clv_tier(p, CLV_TIERS)
                    if p["ev"] <= 0: continue
                    lst.append((p, r, clv(r, p["market"], p["side"], p["line"], p["odds"]))); continue
                if p["ev"] <= 0: continue
                p["tier"] = assign_tier(p, th_by_season[r["season"]])
                lst.append((p, r, clv(r, p["market"], p["side"], p["line"], p["odds"]) if snap != "close" else None))
        res["picks"]["v2_" + snap] = summarize_picks(lst)
        res["picks"]["v2_" + snap + "_by_market"] = {MNAME[m]: summarize_picks([x for x in lst if x[0]["m"] == m]) for m in MK}
    res["picks"]["v1_open_by_market"] = {mn: summarize_picks([x for x in v1_picks(recs, te, "open") if x[0]["market"] == mn]) for mn in ("ML", "Spread", "Total")}
    res["picks"]["v1_close_by_market"] = {mn: summarize_picks([x for x in v1_picks(recs, te, "close") if x[0]["market"] == mn]) for mn in ("ML", "Spread", "Total")}
    if verbose:
        show(res)
    return res


def f(x, d=4):
    return "—" if x is None else f"{x:.{d}f}"


def show(res):
    print(f"\n===== {res['league'].upper()}  train {res['train']}  test {res['test']}")
    for s, c in res["coverage"].items(): print("  coverage", s, c)
    for m, mm in res["markets"].items():
        print(f"  [{m}] n={mm['market_close']['n']}")
        for k in ("market_close", "v1_raw", "v1_engine", "v2_raw", "v2_platt", "v2_isotonic", "v2_final"):
            x = mm[k]
            if not x: continue
            print(f"     {k:12s} LL {f(x['logloss'])}  Brier {f(x['brier'])}  dLL {f(x.get('d_logloss_vs_mkt'),5)} ± {f(x.get('se_d'),5)}")
    for m, mm in res["markets"].items():
        if mm.get("open"):
            print(f"  [{m} vs OPEN] " + "  ".join(f"{k} LL {f(x['logloss'])} dLL {f(x.get('d_logloss_vs_mkt'),5)}±{f(x.get('se_d'),5)} n={x['n']}" for k, x in mm["open"].items()))
        if mm.get("clv_signal"): print(f"  [{m}] clv_signal", {k: round(v, 3) for k, v in mm["clv_signal"].items()})
    for s, c in res["coefs_open"].items(): print("  coefs_open", s, {m: round(d["b"], 2) for m, d in c.items()})
    for s, c in res["coefs"].items(): print("  coefs", s, {m: {k: round(v, 3) for k, v in d.items()} for m, d in c.items()})
    print("  tiers", res["tiers"])
    for s, c in res["coefs_clv"].items(): print("  coefs_clv", s, {m: round(d["b"], 2) for m, d in c.items()})
    for k in ("v1_close", "v1_open", "v2_close", "v2_open", "v2_clv"):
        print(f"  picks {k}:")
        for t, x in res["picks"][k].items():
            if x["n"]: print(f"     {t:12s} n={x['n']:5d} hit {f(x['hit'],3)} ROI {x['roi']*100:+.1f}%  CLV {f(x['clv'] and x['clv']*100,2)}% (n={x['clv_n']}, pos {f(x['clv_pos'],2)})")


if __name__ == "__main__":
    lk = sys.argv[1]
    recs = json.load(open(f"backtest/out/{lk}_recs.json"))
    r = evaluate(lk, recs)
    json.dump(r, open(f"backtest/out/{lk}_eval.json", "w"), indent=1, default=float)
