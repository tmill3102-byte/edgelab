"""Walk-forward backtest. Stage 1 (this file's `run`) replays every game in date order and records, for each game,
the predictions each model would have made BEFORE kick-off using only earlier games, plus the market at open and close.
Nothing after the game's start time is used for its prediction (ratings update only after the prediction is stored).
"""
import copy, json, math, os, sys, datetime as dt
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
from betlib.models import no_vig, team_profile, am_to_dec, implied
from betlib.leagues import LEAGUES
from betlib import analysis, ratings as R

DATA = os.path.join(HERE, "data")
SEASONS = {  # ESPN season year labels. warm = scores only (rating warm-up), train = parameter tuning, test = out-of-sample
    "nba": dict(warm=[2024], train=[2025], test=[2026, 2027]),
    "nhl": dict(warm=[2024], train=[2025], test=[2026, 2027]),
    "nfl": dict(warm=[2023], train=[2024], test=[2025, 2026]),
    "cfb": dict(warm=[2023], train=[2024], test=[2025, 2026]),
    "mlb": dict(warm=[2024], train=[2025], test=[2026]),
}
SEASON_NAME = {"nba": {2024: "2023-24", 2025: "2024-25", 2026: "2025-26", 2027: "2026-27 to Nov 9"},
               "nhl": {2024: "2023-24", 2025: "2024-25", 2026: "2025-26", 2027: "2026-27 to Nov 9"},
               "nfl": {2023: "2023", 2024: "2024", 2025: "2025", 2026: "2026 to Nov 9"},
               "cfb": {2023: "2023", 2024: "2024", 2025: "2025", 2026: "2026 to Nov 9"},
               "mlb": {2024: "2024", 2025: "2025", 2026: "2026"}}


def parse(s):
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))


def load(lk):
    out = {}
    for fn in (f"{lk}_warm.jsonl", f"{lk}.jsonl"):
        p = os.path.join(DATA, fn)
        if os.path.exists(p):
            for line in open(p):
                g = json.loads(line)
                g["when"] = parse(g["date"])
                out[g["id"]] = g
    return sorted(out.values(), key=lambda g: g["when"])


def _valid2(a, b):
    if a is None or b is None: return None
    try:
        nv, ov = no_vig([a, b])
    except Exception:
        return None
    if ov is None or ov < -0.005 or ov > 0.15:   # broken / stale quotes are dropped, never repaired
        return None
    return nv


def market(o, tag):
    """No-vig market probabilities + prices for one snapshot ('open' or 'close')."""
    if not o: return None
    m = {}
    nv = _valid2(o.get(f"ml_home_{tag}"), o.get(f"ml_away_{tag}"))
    if nv: m.update(ml=nv[0], ml_home=o[f"ml_home_{tag}"], ml_away=o[f"ml_away_{tag}"])
    nv = _valid2(o.get(f"spread_home_odds_{tag}"), o.get(f"spread_away_odds_{tag}"))
    if nv and o.get(f"spread_home_{tag}") is not None:
        m.update(sp=nv[0], sp_line=o[f"spread_home_{tag}"], sp_home=o[f"spread_home_odds_{tag}"], sp_away=o[f"spread_away_odds_{tag}"])
    nv = _valid2(o.get(f"over_{tag}"), o.get(f"under_{tag}"))
    if nv and o.get(f"total_{tag}") is not None:
        m.update(tot=nv[0], tot_line=o[f"total_{tag}"], over=o[f"over_{tag}"], under=o[f"under_{tag}"])
    return m or None


def live_odds(mc, mo):
    """Build the engine's live odds dict (current = mc snapshot, open = mo snapshot) so analysis._picks runs unchanged."""
    o = {"ml_home": mc.get("ml_home"), "ml_away": mc.get("ml_away"), "ml_draw": None,
         "ml_home_open": (mo or {}).get("ml_home"), "ml_away_open": (mo or {}).get("ml_away"),
         "spread_home": mc.get("sp_line"), "spread_home_odds": mc.get("sp_home"), "spread_away_odds": mc.get("sp_away"),
         "spread_home_open": (mo or {}).get("sp_line"),
         "total": mc.get("tot_line"), "over_odds": mc.get("over"), "under_odds": mc.get("under"), "total_open": (mo or {}).get("tot_line")}
    return o


# ---------------- v1 (current engine) replay ----------------
def v1_model(lk, g, hist, league_pts):
    """Exactly the live engine's model code, fed with season-to-date results from the dataset.
    Not replicable historically (so absent here): ESPN matchup predictor blend, injury adjustments."""
    L = LEAGUES[lk]
    when = g["when"]
    profs = {s: team_profile(hist.get((g[s]["id"], g["season"]), []), L, when) for s in ("home", "away")}
    res = {"flags": [], "notes": [], "profiles": profs}
    nmin = min(profs["home"]["n"], profs["away"]["n"])
    if nmin == 0:
        res["flags"].append("!no completed games this season for at least one team")
    elif nmin < (4 if L["kind"] == "pts" and lk in ("nfl", "cfb") else 6):
        res["flags"].append(f"thin sample (min {nmin} games played)")
    checked = lk in ("nfl", "nba", "nhl", "wnba", "mlb")
    if not checked:
        res["flags"].append("injury report not available for this league")
    inj = {s: {"list": [], "key": [], "checked": checked} for s in ("home", "away")}
    gg = {"home": dict(g["home"]), "away": dict(g["away"]), "neutral": g["neutral"]}
    if L["kind"] == "pts":
        analysis._pts_model(lk, L, gg, res, profs, inj, None)
    else:
        tot, n = league_pts.get(g["season"], (0.0, 0))
        avg = tot / n if n >= 30 else None
        analysis._AVG[lk] = avg
        analysis._goals_model(lk, L, gg, res, profs, inj)
    return res, gg, inj


def grade(market_, side, line, hs, as_):
    """1 win, 0 loss, None push."""
    if market_ == "ML":
        if hs == as_: return None
        w = hs > as_
        return int(w if side == "home" else not w)
    if market_ == "Spread":
        v = (hs - as_ + line) if side == "home" else (as_ - hs + line)
        return None if abs(v) < 1e-9 else int(v > 0)
    if market_ == "Total":
        t = hs + as_
        if abs(t - line) < 1e-9: return None
        return int(t > line) if side == "over" else int(t < line)


def run(lk, params=None, v1=True, feat=None):
    games = load(lk)
    S = SEASONS[lk]
    book = R.RatingBook(lk, params)
    hist, league_pts, recs = {}, {}, []
    for g in games:
        hs, as_ = g["home"]["score"], g["away"]["score"]
        h, a = g["home"]["id"], g["away"]["id"]
        adj_m, adj_t, why = feat.pre(g) if feat else (0.0, 0.0, [])
        pred = book.predict(h, a, g["when"], g["neutral"], g["season"], adj_m, adj_t, why)
        rec = None
        if g["season"] not in S["warm"]:
            mc, mo = market(g.get("odds"), "close"), market(g.get("odds"), "open")
            rec = {"id": g["id"], "season": g["season"], "date": g["date"], "hs": hs, "as": as_, "neutral": g["neutral"],
                   "home": g["home"]["abbr"], "away": g["away"]["abbr"], "stype": g["stype"],
                   "close": mc, "open": mo, "v2": {"margin": pred["margin"], "total": pred["total"],
                                                   "n_home": pred["n_home"], "n_away": pred["n_away"], "adj_m": adj_m, "adj_t": adj_t}}
            pc = R.probs(lk, pred, (mc or {}).get("sp_line"), (mc or {}).get("tot_line"))
            rec["v2"].update({k: pc.get(k) for k in ("p_home", "p_home_cover", "p_over")})
            if mo:
                po = R.probs(lk, pred, mo.get("sp_line"), mo.get("tot_line"))
                rec["v2"].update({"o_" + k: po.get(k) for k in ("p_home", "p_home_cover", "p_over")})
            if v1 and mc:
                res, gg, inj = v1_model(lk, g, hist, league_pts)
                m = res["model"]
                rec["v1"] = {"p_home": m["p_home"], "flags": list(res["flags"])}
                if mc.get("sp_line") is not None:
                    pw, pp = analysis._cover_prob(res, LEAGUES[lk], mc["sp_line"], True)
                    rec["v1"]["p_home_cover"] = analysis._norm_pushless(pw, pp)
                if mc.get("tot_line") is not None:
                    pw, pp = analysis._total_prob(res, LEAGUES[lk], mc["tot_line"], True)
                    rec["v1"]["p_over"] = analysis._norm_pushless(pw, pp) if pw is not None else None
                for tag, cur, op in (("close", mc, mo), ("open", mo, None)):
                    if not cur: continue
                    gg["odds"] = live_odds(cur, op)
                    r2 = dict(res, flags=list(res["flags"]), notes=[])
                    analysis._picks(lk, LEAGUES[lk], gg, r2, inj)
                    rec["v1"]["picks_" + tag] = [{k: p[k] for k in ("market", "side", "line", "odds", "model_prob", "market_prob", "edge", "ev", "tier")}
                                                 for p in r2["picks"]]
            recs.append(rec)
        # ---- after the game: update state ----
        upd = getattr(feat, "adj_in_update", True)
        book.update(h, a, hs, as_, g["when"], g["neutral"], g["season"], adj_m if upd else 0.0, adj_t if upd else 0.0)
        if feat: feat.post(g)
        for s, pf, pa in (("home", hs, as_), ("away", as_, hs)):
            hist.setdefault((g[s]["id"], g["season"]), []).append({"date": g["when"], "home": s == "home", "pf": pf, "pa": pa, "opp": None})
        t, n = league_pts.get(g["season"], (0.0, 0)); league_pts[g["season"]] = (t + hs + as_, n + 2)
    return recs


def default_feat(lk):
    """Feature set used for the reported v2 numbers (= what the live engine uses)."""
    if lk == "mlb":   # live: betlib/mlb_pitchers.live_adjustment at prediction time only (not in rating updates)
        from backtest.features import MLBPitchers
        return MLBPitchers(w=0.5, adj_in_update=False)
    return R.make_feature(lk)


if __name__ == "__main__":
    lk = sys.argv[1]
    recs = run(lk, feat=default_feat(lk))
    os.makedirs(os.path.join(HERE, "out"), exist_ok=True)
    json.dump(recs, open(os.path.join(HERE, "out", f"{lk}_recs.json"), "w"))
    print(lk, len(recs), "records")
