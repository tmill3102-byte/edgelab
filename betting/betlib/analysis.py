"""Game + prop evaluation built on espn.py data and models.py math."""
import math, statistics, datetime as dt
from . import espn
from .models import *
from .leagues import LEAGUES
from . import ratings as RT

ENGINE_VERSION = "2.0"

KEY_POS = {"nfl": {"QB"}, "cfb": {"QB"}}


def min_price(p, ev=0.02):
    """American price at which a bet with true prob p returns `ev` per unit -> 'playable at X or better'."""
    if not p or p <= 0:
        return None
    d = (1 + ev) / p
    return dec_to_am(d) if d > 1.01 else None


def _inj_block(lk, s, g):
    inj = espn.injuries_from_summary(s)
    if not inj and lk in ("nfl", "nba", "nhl", "wnba", "mlb"):
        inj = espn.injuries_from_league(lk)
    leaders = espn.leaders_from_summary(s)
    out = {}
    for side in ("home", "away"):
        tid = str(g[side]["id"])
        lst = [i for i in inj.get(tid, []) if (i.get("status") or "").lower() not in ("active", "")]
        key = []
        for i in lst:
            st = (i.get("status") or "").lower()
            is_key = i["id"] in leaders.get(tid, set()) or (i.get("pos") in KEY_POS.get(lk, set()) and st == "out")
            i["key"] = is_key
            if is_key:
                key.append(i)
        out[side] = {"list": lst, "key": key, "checked": bool(inj)}
    return out


def evaluate_game(lk, g, s=None, with_picks=True):
    """Return analysis dict for one game: model numbers, picks per market, notes."""
    L = LEAGUES[lk]
    if s is None:
        s = espn.summary(lk, g["id"])
    if not g.get("odds") and s:
        g["odds"] = espn.odds_from_summary(s)
    when = espn.parse_iso(g.get("date"))
    res = {"league": lk, "event_id": g["id"], "name": g.get("name"), "start": g.get("date"),
           "start_local": espn.local_time(g.get("date")), "status": g["status"].get("shortDetail") or g["status"].get("description"),
           "state": g["status"].get("state"), "home": g["home"], "away": g["away"], "odds": g.get("odds"),
           "picks": [], "notes": [], "flags": []}
    flags = res["flags"]
    if not g.get("odds"):
        flags.append("!no odds from ESPN/DraftKings feed for this event")
    profs = {}
    for side in ("home", "away"):
        r, _ = espn.team_results(lk, g[side]["id"], before=when)
        profs[side] = team_profile(r, L, when)
    res["profiles"] = profs
    nmin = min(profs["home"]["n"], profs["away"]["n"])
    if nmin == 0:
        flags.append("!no completed games this season for at least one team")
    elif nmin < (4 if L["kind"] == "pts" and lk in ("nfl", "cfb") else 6):
        flags.append(f"thin sample (min {nmin} games played)")
    inj = _inj_block(lk, s, g)
    res["injuries"] = inj
    if not inj["home"]["checked"]:
        flags.append("injury report not available for this league")
    pred = espn.predictor_from_summary(s)
    res["espn_predictor"] = pred
    res["engine"] = ENGINE_VERSION
    done = False
    if lk in RT.PARAMS and V2_ENABLED:
        try:
            _v2_model(lk, L, g, res, inj, when, pred)
            done = True
        except Exception as e:  # network trouble building ratings -> fall back to the v1 model, and say so
            res["notes"].append(f"v2 ratings unavailable ({type(e).__name__}); fell back to the v1 season-average model.")
    if not done and L["kind"] == "pts":
        _pts_model(lk, L, g, res, profs, inj, pred)
    elif not done:
        _goals_model(lk, L, g, res, profs, inj)
    if with_picks and g.get("odds") and res["state"] == "pre":
        _picks(lk, L, g, res, inj)
    elif res["state"] != "pre":
        res["notes"].append(f"Game state is '{res['state']}' - picks only generated for games not yet started.")
    return res


V2_ENABLED = True


def _v2_model(lk, L, g, res, inj, when, pred):
    """v2: backtested team ratings (betlib/ratings.py) built from the shipped seed + every completed game since."""
    from . import ratings_live as RL
    bk = RL.book(lk, when)
    season = RL.season_for(lk, when)
    am = at = 0.0
    feat = getattr(bk, "feature", None)
    pnotes = []
    if feat:
        am, at, _ = feat.pre({"home": {"id": str(g["home"]["id"])}, "away": {"id": str(g["away"]["id"])}})
    if lk == "mlb":
        from . import mlb_pitchers
        try:
            am, at, pnotes = mlb_pitchers.live_adjustment(when, season, g["home"].get("name"), g["away"].get("name"))
        except Exception as e:
            pnotes = [f"probable-pitcher lookup failed ({type(e).__name__}); no starter adjustment"]
    p = bk.predict(str(g["home"]["id"]), str(g["away"]["id"]), when, bool(g.get("neutral")), season, am, at)
    hA, aA = g["home"]["abbr"], g["away"]["abbr"]
    why = []
    why += pnotes
    if lk == "mlb" and any("not announced" in n or "failed" in n for n in pnotes):
        res["flags"].append("MLB probable pitchers not available: no starter adjustment")
    if at and lk == "nba":
        why.append(f"pace: projected total {at:+.1f} vs these teams' rating-only total (recent shot volume)")
    if abs(p["adj"] - am) > 1e-9:
        why.append(f"rest/back-to-back adjustment {p['adj'] - am:+.2f} to {hA}'s margin ({', '.join(p['notes'])})" if p["notes"] else f"rest adjustment {p['adj'] - am:+.2f}")
    for side in ("home", "away"):
        outs = [i for i in inj[side]["key"] if (i["status"] or "").lower() in ("out", "doubtful")]
        if outs:
            why.append(f"{g[side]['abbr']} key player(s) out: {', '.join(i['name'] for i in outs)} (not in the rating; the market has usually priced this)")
    pr = RT.probs(lk, p)
    res["model"] = {"type": "ratings-v2", "home_rating": round(p["r_home"], 2), "away_rating": round(p["r_away"], 2), "hfa": round(p["hfa"], 2),
                    "adjust": round(p["adj"], 2), "exp_margin_home": round(p["margin"], 2), "exp_total": round(p["total"], 2),
                    "p_home": round(pr["p_home"], 4), "games_home": p["n_home"], "games_away": p["n_away"], "adj_notes": why,
                    "sd": RT.PARAMS[lk]["sd"], "tsd": RT.PARAMS[lk]["tsd"], "_pred": {"margin": p["margin"], "total": p["total"]},
                    "rating_games_replayed": getattr(bk, "replayed", None)}
    res["model"].update(own_margin=round(p["margin"], 2), source="ratings-v2")    # v1-compatible keys
    if "lam_home" in pr:
        pd_ = pr["p_draw_reg"]; ph_reg = pr["p_home"] - pd_ * RT.PARAMS[lk].get("ot_home", 0.5)
        res["model"].update(lam_home=round(pr["lam_home"], 3), lam_away=round(pr["lam_away"], 3),
                            p_home_reg=round(ph_reg, 4), p_draw=round(pd_, 4), p_away_reg=round(1 - ph_reg - pd_, 4), mx=(25 if lk == "mlb" else 14))
    if pred:
        res["notes"].append(f"ESPN matchup predictor: {hA} {pred['home']*100:.1f}% (shown for reference only; it can't be backtested, so v2 doesn't use it).")
    res["notes"].append(f"v2 ratings: margin {hA} {p['margin']:+.1f}, total {p['total']:.1f}; probabilities are then blended with the market using backtested weights (BACKTEST.md).")


def _v2_tier(lk, mkey):
    ok = RT.enabled(lk, mkey)
    def f(edge, ev, dq, dec):
        if not ok or dq == "Low" or ev is None:
            return "Low"
        if ev >= RT.TIERS["high_ev"] and dq == "High" and dec <= 5.0:
            return "High"
        if ev >= RT.TIERS["med_ev"]:
            return "Medium"
        return "Low"
    return f


def _v2_side_probs(lk, m, mkey, line):
    """Raw v2 model prob for the home/over side of a market at `line`."""
    pr = RT.probs(lk, m["_pred"], line if mkey == "sp" else None, line if mkey == "tot" else None)
    return {"ml": pr.get("p_home"), "sp": pr.get("p_home_cover"), "tot": pr.get("p_over")}[mkey]


def _pts_model(lk, L, g, res, profs, inj, pred):
    h, a = profs["home"], profs["away"]
    rh, ra = pts_rating(h, L), pts_rating(a, L)
    hfa = 0.0 if g.get("neutral") else L["hfa"]
    adj, why = 0.0, []
    # rest / back-to-back
    if L.get("b2b"):
        for side, sign in (("home", 1), ("away", -1)):
            r = profs[side]["rest"]
            if r is not None and r < 1.6:
                adj -= sign * L["b2b"]; why.append(f"{g[side]['abbr']} on a back-to-back (-{L['b2b']} pts)")
    # injuries (small; the market already knows)
    for side, sign in (("home", 1), ("away", -1)):
        outs = [i for i in inj[side]["key"] if (i["status"] or "").lower() in ("out", "doubtful")]
        if outs:
            per = 4.0 if lk in ("nfl", "cfb") and any(i.get("pos") == "QB" for i in outs) else 2.0
            hit = min(5.0, per * len(outs))
            adj -= sign * hit
            why.append(f"{g[side]['abbr']} key player(s) out: {', '.join(i['name'] for i in outs)} (-{hit:.1f})")
    own = rh - ra + hfa + adj
    margin = own
    src = "own"
    if pred:
        espn_margin = L["sd"] * inv_phi(pred["home"])
        margin = 0.5 * own + 0.5 * espn_margin
        src = "own+espn"
        res["notes"].append(f"ESPN matchup predictor: {g['home']['abbr']} {pred['home']*100:.1f}% (implied margin {espn_margin:+.1f}); blended 50/50 with own rating.")
    p_home = phi(margin / L["sd"])
    # totals
    exp_total = None
    if h["n"] and a["n"]:
        exp_total = (h["pf"] + a["pa"]) / 2 + (a["pf"] + h["pa"]) / 2
        if h["n"] >= 5 and a["n"] >= 5:
            rec = (h["pf5"] + a["pa5"]) / 2 + (a["pf5"] + h["pa5"]) / 2
            exp_total = 0.75 * exp_total + 0.25 * rec
    res["model"] = {"type": "margin-normal", "home_rating": round(rh, 2), "away_rating": round(ra, 2), "hfa": hfa,
                    "adjust": round(adj, 2), "own_margin": round(own, 2), "exp_margin_home": round(margin, 2), "source": src,
                    "p_home": round(p_home, 4), "exp_total": round(exp_total, 1) if exp_total else None, "adj_notes": why,
                    "sd": L["sd"], "tsd": L["tsd"]}


_AVG = {}


def _goals_model(lk, L, g, res, profs, inj):
    h, a = profs["home"], profs["away"]
    if lk not in _AVG:
        _AVG[lk] = espn.league_scoring_avg(lk)
    if _AVG[lk]:
        L = dict(L, avg=_AVG[lk])  # this season's actual league scoring rate
        res["notes"].append(f"League scoring average this season (ESPN standings): {_AVG[lk]:.2f} per team-game.")
    hgf, hga = goals_rates(h, L); agf, aga = goals_rates(a, L)
    hf = 1.0 if g.get("neutral") else L["hfa"]
    lam_h = hgf * aga / L["avg"] * math.sqrt(hf)
    lam_a = agf * hga / L["avg"] / math.sqrt(hf)
    why = []
    if L.get("b2b"):
        for side in ("home", "away"):
            r = profs[side]["rest"]
            if r is not None and r < 1.6:
                why.append(f"{g[side]['abbr']} on a back-to-back")
                if side == "home": lam_h *= (1 - L["b2b"]); lam_a *= (1 + L["b2b"])
                else: lam_a *= (1 - L["b2b"]); lam_h *= (1 + L["b2b"])
    mx = L.get("maxgoals", 12)
    grid = [[poisson_pmf(i, lam_h) * poisson_pmf(j, lam_a) for j in range(mx)] for i in range(mx)]
    ph = sum(grid[i][j] for i in range(mx) for j in range(mx) if i > j)
    pd = sum(grid[i][i] for i in range(mx))
    pa = 1 - ph - pd
    res["model"] = {"type": "poisson", "lam_home": round(lam_h, 3), "lam_away": round(lam_a, 3),
                    "p_home_reg": round(ph, 4), "p_draw": round(pd, 4), "p_away_reg": round(pa, 4),
                    "exp_total": round(lam_h + lam_a, 2), "adj_notes": why, "grid": grid, "mx": mx}
    if L.get("ot") or lk == "mlb":  # no draws in final result: split ties ~52/48 home
        res["model"]["p_home"] = round(ph + pd * 0.52, 4)
    else:
        res["model"]["p_home"] = round(ph, 4)


def _cover_prob(res, L, side_home_line, home=True):
    """P(selected side covers given its line). Returns (p_win, p_push)."""
    m = res["model"]
    if m["type"] == "margin-normal":
        mu = m["exp_margin_home"] if home else -m["exp_margin_home"]
        return normal_over(mu, L["sd"], -side_home_line)
    grid, mx = m["grid"], m["mx"]
    pw = pp = 0.0
    for i in range(mx):
        for j in range(mx):
            d = (i - j) if home else (j - i)
            v = d + side_home_line
            if abs(v) < 1e-9: pp += grid[i][j]
            elif v > 0: pw += grid[i][j]
    return pw, pp


def _total_prob(res, L, line, over=True):
    m = res["model"]
    if m["type"] == "margin-normal":
        if not m["exp_total"]:
            return None, None
        po, pp = normal_over(m["exp_total"], L["tsd"], line)
        return (po, pp) if over else (1 - po - pp, pp)
    grid, mx = m["grid"], m["mx"]
    po = pu = pp = 0.0
    for i in range(mx):
        for j in range(mx):
            t = i + j
            if abs(t - line) < 1e-9: pp += grid[i][j]
            elif t > line: po += grid[i][j]
            else: pu += grid[i][j]
    return (po, pp) if over else (pu, pp)


def _inj_caution(m, inj, side):
    """v2 ratings don't include injuries: a model lean ON a side missing a key player is suspect -> one-tier downgrade."""
    if m.get("type") != "ratings-v2" or side not in ("home", "away"):
        return []
    outs = [i for i in inj[side]["key"] if (i["status"] or "").lower() in ("out", "doubtful")]
    return [f"injury: {', '.join(i['name'] for i in outs)} out for this side and the rating doesn't know it"] if outs else []


def _norm_pushless(p, push):
    return p / (1 - push) if push < 1 else p


def _picks(lk, L, g, res, inj):
    o, m = g["odds"], res["model"]
    hA, aA = g["home"]["abbr"], g["away"]["abbr"]
    base_flags = list(res["flags"])
    dq = quality(base_flags)
    weight = {"High": 0.5, "Medium": 0.4, "Low": 0.25}[dq]
    pr = res["profiles"]
    form = f"{aA} L5 {pr['away']['last5'] or '-'} (MOV {pr['away']['mov'] if pr['away']['mov'] is None else round(pr['away']['mov'],1)}), {hA} L5 {pr['home']['last5'] or '-'} (MOV {pr['home']['mov'] if pr['home']['mov'] is None else round(pr['home']['mov'],1)})"
    q_inj = {s: [i for i in inj[s]["list"] if (i["status"] or "").lower() in ("questionable", "day-to-day", "doubtful", "game-time decision")] for s in ("home", "away")}
    key_any = {s: [i for i in inj[s]["key"]] for s in ("home", "away")}

    def cautions(side_key, kind, cur_line=None, open_line=None, cur_price=None, open_price=None):
        c = []
        if any(f.startswith("thin") or f.startswith("!") for f in base_flags):
            c.append("thin data: " + "; ".join(f.lstrip('!') for f in base_flags))
        opp = {"home": "away", "away": "home"}.get(side_key)
        if side_key in ("home", "away"):
            unsure = [i for i in key_any[side_key] if (i["status"] or "").lower() not in ("out",)]
            if unsure:
                c.append("injury news: key player status uncertain - " + ", ".join(f"{i['name']} ({i['status']})" for i in unsure))
        # line move against the pick (market moved away from us since open)
        if open_price is not None and cur_price is not None and implied(cur_price) - implied(open_price) < -0.03:
            c.append(f"line move: price drifted against this side ({fmt_am(open_price)} -> {fmt_am(cur_price)})")
        if open_line is not None and cur_line is not None and cur_line - open_line <= -1.0 and kind == "spread":
            c.append(f"line move: spread moved against this side ({open_line:+g} -> {cur_line:+g})")
        return c

    picks = []
    # ---- moneyline ----
    if o.get("ml_home") is not None and o.get("ml_away") is not None:
        three = L.get("draw") and o.get("ml_draw") is not None
        if three:
            nv, over = no_vig([o["ml_home"], o["ml_draw"], o["ml_away"]])
            mp = [m["p_home_reg"], m["p_draw"], m["p_away_reg"]]
            sides = [("home", hA, o["ml_home"], o.get("ml_home_open")), ("draw", "Draw", o["ml_draw"], None), ("away", aA, o["ml_away"], o.get("ml_away_open"))]
        else:
            nv, over = no_vig([o["ml_home"], o["ml_away"]])
            mp = [m["p_home"], 1 - m["p_home"]]
            sides = [("home", hA, o["ml_home"], o.get("ml_home_open")), ("away", aA, o["ml_away"], o.get("ml_away_open"))]
        res["market"] = {"ml_novig": [round(x, 4) for x in nv], "ml_overround": round(over, 4)}
        v2 = m["type"] == "ratings-v2" and not three
        for (sk, lab, price, op), p_model, p_mkt in zip(sides, mp, nv):
            why = [f"Model {lab} win {p_model*100:.1f}% vs market no-vig {p_mkt*100:.1f}%.", form] + m.get("adj_notes", [])
            if m["type"] == "ratings-v2":
                why.insert(1, f"v2 projected margin {hA} {m['exp_margin_home']:+.1f} (ratings {hA} {m['home_rating']:+.1f}, {aA} {m['away_rating']:+.1f}, home edge {m['hfa']}); raw model {p_model*100:.1f}%.")
            elif m["type"] == "margin-normal":
                why.insert(1, f"Projected margin {hA} {m['exp_margin_home']:+.1f} (ratings {hA} {m['home_rating']:+.1f}, {aA} {m['away_rating']:+.1f}, HFA {m['hfa']}).")
            else:
                why.insert(1, f"Expected goals {hA} {m['lam_home']:.2f} - {aA} {m['lam_away']:.2f} (Poisson).")
            against = (f"Market makes {lab} {p_mkt*100:.0f}%; books see lineup/goalie/motivation info this model doesn't, and " +
                       ("heavy favorites risk a lot to win a little; one upset erases several wins" if price <= -200 else
                        "favorites in this range still lose often, and public money tends to inflate them" if price < 0 else
                        "an underdog price means it loses more often than not") + ".")
            kw = {}
            if v2:
                fin = RT.blend(lk, "ml", p_mkt, p_model)
                kw = {"blended": fin if fin is not None else p_mkt, "tier_fn": _v2_tier(lk, "ml"), "far_downgrade": False}
                why.append(RT.blend_note(lk, "ml"))
            pk = make_pick("ML" if not three else "1X2", f"{lab} ML" if sk != "draw" else "Draw", sk, None, price, p_model, p_mkt, weight, dq,
                           why, base_flags, caution=cautions(sk, "ml", cur_price=price, open_price=op) + _inj_caution(m, inj, sk), against=against, **kw)
            if pk: picks.append(pk)
    # ---- spread ----
    if o.get("spread_home") is not None and o.get("spread_home_odds") is not None and o.get("spread_away_odds") is not None:
        sh = o["spread_home"]
        nv, _ = no_vig([o["spread_home_odds"], o["spread_away_odds"]])
        for sk, lab, line, price, p_mkt in (("home", hA, sh, o["spread_home_odds"], nv[0]), ("away", aA, -sh, o["spread_away_odds"], nv[1])):
            if m["type"] == "ratings-v2":
                ph = _v2_side_probs(lk, m, "sp", sh)
                p_model, pp = (ph if sk == "home" else 1 - ph), 0.0
            else:
                pw, pp = _cover_prob(res, L, line, home=(sk == "home"))
                p_model = _norm_pushless(pw, pp)
            opn = o.get("spread_home_open")
            opn = (opn if sk == "home" else -opn) if opn is not None else None
            why = [f"Model {lab} {line:+g} covers {p_model*100:.1f}% vs market {p_mkt*100:.1f}%.",
                   (f"Projected margin {hA} {m['exp_margin_home']:+.1f} vs line {hA} {sh:+g}." if m["type"] in ("margin-normal", "ratings-v2")
                    else f"Poisson xG {hA} {m['lam_home']:.2f}-{m['lam_away']:.2f} {aA}."), form] + m.get("adj_notes", [])
            against = (f"Margin s.d. is ~{L['sd']} pts; one garbage-time/late score flips it, and the closing number is usually sharper than this model."
                       if L["kind"] == "pts" else "One-goal games (and empty-net/late goals) decide most of these; goalie/lineup news isn't in the model.")
            kw = {}
            if m["type"] == "ratings-v2":
                fin = RT.blend(lk, "sp", p_mkt, p_model)
                kw = {"blended": fin if fin is not None else p_mkt, "tier_fn": _v2_tier(lk, "sp"), "far_downgrade": False}
                why.append(RT.blend_note(lk, "sp"))
            pk = make_pick("Spread", f"{lab} {line:+g}", sk, line, price, p_model, p_mkt, weight, dq, why, base_flags, push=pp,
                           caution=cautions(sk, "spread", cur_line=line, open_line=opn) + _inj_caution(m, inj, sk), against=against, **kw)
            if pk: picks.append(pk)
    # ---- total ----
    if o.get("total") is not None and o.get("over_odds") is not None and o.get("under_odds") is not None and m.get("exp_total"):
        t = o["total"]
        nv, _ = no_vig([o["over_odds"], o["under_odds"]])
        for sk, p_mkt, price in (("over", nv[0], o["over_odds"]), ("under", nv[1], o["under_odds"])):
            if m["type"] == "ratings-v2":
                po = _v2_side_probs(lk, m, "tot", t)
                p_model, pp = (po if sk == "over" else 1 - po), 0.0
            else:
                pw, pp = _total_prob(res, L, t, over=(sk == "over"))
                if pw is None: continue
                p_model = _norm_pushless(pw, pp)
            mv = ""
            if o.get("total_open") is not None and o["total_open"] != t:
                mv = f" Line moved {o['total_open']:g} -> {t:g}."
            why = [f"Model {sk} {t:g}: {p_model*100:.1f}% vs market {p_mkt*100:.1f}%.",
                   (f"Projected total {m['exp_total']:.1f} from v2 team-total ratings (carry-over + this season; no weather/lineup inputs).{mv}" if m["type"] == "ratings-v2" else
                    f"Projected total {m['exp_total']:.1f} from season/recent scoring & allowing averages (no pace/weather/lineup inputs).{mv}"), form]
            c = cautions(None, "total")
            if o.get("total_open") is not None and ((sk == "over" and t - o["total_open"] >= 1.0 and L["kind"] == "pts") or (sk == "under" and o["total_open"] - t >= 1.0 and L["kind"] == "pts")):
                c.append(f"line move: total already moved toward {sk} ({o['total_open']:g} -> {t:g}); value may be gone")
            if o.get("total_open") is not None and L["kind"] == "pts" and ((sk == "over" and t - o["total_open"] <= -1.0) or (sk == "under" and t - o["total_open"] >= 1.0)):
                c.append(f"line move: market moved against the {sk} ({o['total_open']:g} -> {t:g})")
            against = "Averages ignore pace changes, weather, rest-day lineups and opponent-adjusted defense; totals markets are among the sharpest."
            kw = {}
            if m["type"] == "ratings-v2":
                fin = RT.blend(lk, "tot", p_mkt, p_model)
                kw = {"blended": fin if fin is not None else p_mkt, "tier_fn": _v2_tier(lk, "tot"), "far_downgrade": False}
                why.append(RT.blend_note(lk, "tot"))
            pk = make_pick("Total", f"{sk.title()} {t:g}", sk, t, price, p_model, p_mkt, weight * 0.8, dq, why, base_flags, push=pp, caution=c, against=against, **kw)
            if pk: picks.append(pk)
    for p in picks:
        p["next_step"] = _next_step(p)
    res["picks"] = sorted(picks, key=lambda p: -p["ev"])


def _next_step(p):
    mp = min_price(p["model_prob"])
    if p["ev"] <= 0:
        return f"Pass. Only interesting at {fmt_am(mp)} or better." if mp else "Pass."
    if p["tier"] == "Low":
        return f"Monitor only; if anything, wait for {fmt_am(mp)} or better and re-check injuries near start."
    return f"Playable at {fmt_am(mp)} or better (current {fmt_am(p['odds'])}); re-check injuries/line 60 min before start."


def reprice_pick(lk, res, market, side, line, odds, market_p, label):
    """Price one side at another book's real line and American odds. Uses the v2 blend when the game model is v2."""
    if odds is None or market_p is None or not res.get("model"):
        return None
    m = res["model"]
    flags = list(res.get("flags") or [])
    dq = quality(flags)
    hA, aA = res["home"]["abbr"], res["away"]["abbr"]
    reasons = []
    push = 0.0
    weight = {"High": 0.5, "Medium": 0.4, "Low": 0.25}[dq]
    kw = {}
    if m.get("type") == "ratings-v2":
        mkey = {"ML": "ml", "1X2": "ml", "Spread": "sp", "Total": "tot"}.get(market)
        if mkey == "ml":
            raw = m.get("p_home") if side == "home" else (None if m.get("p_home") is None else 1 - m["p_home"])
        elif mkey == "sp" and line is not None:
            home_line = line if side == "home" else -line
            ph = _v2_side_probs(lk, m, "sp", home_line)
            raw = None if ph is None else (ph if side == "home" else 1 - ph)
        elif mkey == "tot" and line is not None:
            po = _v2_side_probs(lk, m, "tot", line)
            raw = None if po is None else (po if side == "over" else 1 - po)
        else:
            raw = None
        if raw is None:
            return None
        fin = RT.blend(lk, mkey, market_p, raw)
        reasons = [f"Raw model {label}: {raw*100:.1f}%.", RT.blend_note(lk, mkey)]
        if m.get("exp_margin_home") is not None:
            reasons.append(f"v2 margin {hA} {m['exp_margin_home']:+.1f}, total {m.get('exp_total')}.")
        kw = {"blended": fin if fin is not None else market_p, "tier_fn": _v2_tier(lk, mkey), "far_downgrade": False}
    else:
        if market in ("ML", "1X2"):
            if market == "1X2":
                raw = {"home": m.get("p_home_reg"), "draw": m.get("p_draw"), "away": m.get("p_away_reg")}.get(side)
            elif side == "home":
                raw = m.get("p_home")
            else:
                raw = None if m.get("p_home") is None else 1 - m["p_home"]
        elif market == "Spread" and line is not None:
            pw, push = _cover_prob(res, LEAGUES[lk], line, home=(side == "home"))
            raw = _norm_pushless(pw, push)
        elif market == "Total" and line is not None:
            pw, push = _total_prob(res, LEAGUES[lk], line, over=(side == "over"))
            raw = None if pw is None else _norm_pushless(pw, push)
            weight *= 0.8
        else:
            raw = None
        if raw is None:
            return None
        reasons = [f"Model {label}: {raw*100:.1f}% before shrink, this book's no-vig {market_p*100:.1f}%."]
    caution = []
    if any(f.startswith("thin") or f.startswith("!") for f in flags):
        caution.append("thin data: " + "; ".join(f.lstrip("!") for f in flags))
    pk = make_pick(market, label, side, line, odds, raw, market_p, weight, dq, reasons, flags,
                   push=push or 0.0, caution=caution,
                   against="Where the backtest did not earn the model any weight, the final number is the market's.",
                   **kw)
    if not pk:
        return None
    pk["next_step"] = _next_step(pk)
    return pk


# ---------------- props ----------------
STAT_ALIASES = {
    "pts": ["points"], "points": ["points"], "reb": ["totalRebounds", "rebounds"], "rebounds": ["totalRebounds", "rebounds"],
    "ast": ["assists"], "assists": ["assists", "goalAssists"], "stl": ["steals"], "blk": ["blocks"], "to": ["turnovers"], "tov": ["turnovers"],
    "3pm": ["threePointFieldGoalsMade-threePointFieldGoalsAttempted", "threePointFieldGoalsMade"],
    "threes": ["threePointFieldGoalsMade-threePointFieldGoalsAttempted", "threePointFieldGoalsMade"],
    "min": ["minutes"],
    "pass_yds": ["passingYards"], "pass_td": ["passingTouchdowns"], "pass_att": ["passingAttempts"], "completions": ["completions"],
    "int": ["interceptions"], "rush_yds": ["rushingYards"], "rush_att": ["rushingAttempts"], "rush_td": ["rushingTouchdowns"],
    "rec": ["receptions"], "receptions": ["receptions"], "rec_yds": ["receivingYards"], "rec_td": ["receivingTouchdowns"], "targets": ["receivingTargets"],
    "goals": ["goals", "totalGoals"], "g": ["goals", "totalGoals"], "a": ["assists", "goalAssists"], "sog": ["shotsTotal", "shots"], "shots": ["shotsTotal", "shots", "totalShots"],
    "saves": ["saves"], "hits": ["hits"], "hr": ["homeRuns"], "rbi": ["RBIs", "runsBattedIn"], "k": ["strikeouts"], "so": ["strikeouts"],
    "tb": ["totalBases"], "runs": ["runs"], "sot": ["shotsOnTarget"],
}
COMBOS = {"pra": ["pts", "reb", "ast"], "pr": ["pts", "reb"], "pa": ["pts", "ast"], "ra": ["reb", "ast"], "sb": ["stl", "blk"],
          "pass_rush_yds": ["pass_yds", "rush_yds"], "rush_rec_yds": ["rush_yds", "rec_yds"]}


def _num(v):
    try:
        if isinstance(v, str) and "-" in v and not v.startswith("-"):
            v = v.split("-")[0]
        if isinstance(v, str) and ":" in v:
            mm, ss = v.split(":"); return float(mm) + float(ss) / 60
        return float(v)
    except Exception:
        return None


def player_values(lk, athlete_id, stat, season=None):
    """Return (rows newest-first [{event, date, opp, value}], labels) for stat or combo from ESPN gamelog."""
    d = espn.gamelog(lk, athlete_id, season)
    if not d:
        return None, None
    names = d.get("names") or []
    parts = COMBOS.get(stat.lower(), [stat])
    idxs = []
    for ptk in parts:
        cands = STAT_ALIASES.get(ptk.lower(), [ptk])
        idx = next((names.index(c) for c in cands if c in names), None)
        if idx is None:
            idx = next((i for i, n in enumerate(names) if n.lower() == ptk.lower()), None)
        if idx is None:
            lbl = [x.lower() for x in d.get("labels") or []]
            idx = lbl.index(ptk.lower()) if ptk.lower() in lbl else None
        if idx is None:
            return [], names
        idxs.append(idx)
    evmeta = d.get("events") or {}
    rows, seen = [], set()
    for st in d.get("seasonTypes") or []:
        if "preseason" in (st.get("displayName") or "").lower():
            continue
        for cat in st.get("categories") or []:
            for ev in cat.get("events") or []:
                eid = ev.get("eventId")
                if eid in seen: continue
                vals = [_num(ev["stats"][i]) if i < len(ev.get("stats", [])) else None for i in idxs]
                if any(v is None for v in vals): continue
                seen.add(eid)
                meta = evmeta.get(eid, {})
                rows.append({"event": eid, "date": meta.get("gameDate"), "opp": (meta.get("opponent") or {}).get("abbreviation"),
                             "atvs": meta.get("atVs"), "value": sum(vals), "result": meta.get("gameResult")})
    rows.sort(key=lambda r: r["date"] or "", reverse=True)
    return rows, names


def prop_prob(vals, line, recent_n=10):
    """Blend of distribution estimate (Poisson for low counts, else normal) and smoothed hit rate."""
    n = len(vals)
    last = vals[:recent_n]
    m_recent = statistics.mean(last)
    m_season = statistics.mean(vals)
    mu = 0.6 * m_recent + 0.4 * m_season
    integerish = all(float(v).is_integer() for v in vals)
    if integerish and mu <= 8:
        po, pp = poisson_over(mu, line); dist = "Poisson"
    else:
        sd = statistics.pstdev(last) if len(last) > 1 else max(1.0, 0.3 * mu)
        sd = max(sd, 0.15 * mu, 1.0)
        po, pp = normal_over(mu, sd, line); dist = f"Normal(sd {sd:.1f})"
    hits = sum(1 for v in last if v > line); pushes = sum(1 for v in last if v == line)
    emp = (hits + 1) / (len(last) - pushes + 2)
    p_dist = _norm_pushless(po, pp)
    p = 0.65 * p_dist + 0.35 * emp
    return {"p_over": p, "p_push": pp, "mu": mu, "dist": dist, "p_dist": p_dist, "emp": emp}


def hit_rates(vals, line):
    out = {}
    for n in (5, 10, 20):
        s = vals[:n]
        if s:
            out[f"L{n}"] = f"{sum(1 for v in s if v > line)}/{len(s)}"
    out["all"] = f"{sum(1 for v in vals if v > line)}/{len(vals)}"
    return out


def evaluate_prop(lk, player, stat, line, over_odds=None, under_odds=None, side=None, season=None):
    cands = espn.search_player(player, lk)
    if not cands:
        return {"error": f"No ESPN player match for '{player}' in {lk}."}
    pl = cands[0]
    rows, names = player_values(lk, pl["id"], stat, season)
    flags = []
    if rows is None:
        return {"error": f"ESPN gamelog unavailable for {pl['name']} ({lk})."}
    if not rows:
        return {"error": f"Stat '{stat}' not found in {pl['name']}'s ESPN gamelog. Available fields: {', '.join(names)}"}
    if len(rows) < 15 and not season:
        # augment with previous season (ESPN gamelog 'filters' lists the current season value)
        try:
            gl = espn.gamelog(lk, pl["id"]) or {}
            cur_season = next((int(f["value"]) for f in gl.get("filters", []) if f.get("name") == "season"), None)
            if cur_season:
                prev, _ = player_values(lk, pl["id"], stat, season=str(cur_season - 1))
                have = {x["event"] for x in rows}
                prev = [r for r in (prev or []) if r["event"] not in have]
                if prev:
                    flags.append(f"current season only {len(rows)} games; added {min(len(prev), 15)} from prior season (role/team may differ)")
                    rows = rows + prev[:15]
        except Exception:
            pass
    vals = [r["value"] for r in rows][:40]
    if len(vals) < 5:
        flags.append("!fewer than 5 games of data")
    elif len(vals) < 10:
        flags.append(f"thin sample ({len(vals)} games)")
    line = float(line)
    pr = prop_prob(vals, line)
    # player injury status
    status = None
    if lk in ("nfl", "nba", "nhl", "wnba", "mlb"):
        for tid, lst in espn.injuries_from_league(lk).items():
            for i in lst:
                if (i["id"] == pl["id"] or (i["name"] or "").lower() == (pl["name"] or "").lower()) and (i["status"] or "").lower() != "active":
                    status = f"{i['status']}: {i.get('comment') or ''}".strip()
    caution = []
    if status:
        caution.append(f"injury news: listed {status}")
    if any(f.startswith("!") or f.startswith("thin") or f.startswith("current season only") for f in flags):
        caution.append("thin data: " + "; ".join(f.lstrip('!') for f in flags))
    if under_odds is None and over_odds is not None:
        flags.append("only one side's price given; market no-vig assumes a standard ~4.5% hold")
    if over_odds is None and under_odds is None:
        over_odds = under_odds = -110.0
        flags.append("no price given; assumed -110/-110 (pass --odds/--under-odds for real prices)")
    if over_odds is not None and under_odds is not None:
        nv, _ = no_vig([over_odds, under_odds]); m_over = nv[0]
    elif over_odds is not None:
        m_over = implied(over_odds) / 1.045 * 1.0 + 0.0; m_over = min(max(m_over, 0.02), 0.98)
    else:
        m_over = 1 - min(max(implied(under_odds) / 1.045, 0.02), 0.98)
    dq = quality(flags)
    weight = {"High": 0.6, "Medium": 0.5, "Low": 0.3}[dq]
    hr = hit_rates(vals, line)
    picks = []
    for sk, p_model, p_mkt, price in (("over", pr["p_over"], m_over, over_odds), ("under", 1 - pr["p_over"], 1 - m_over, under_odds)):
        if side and side != sk:
            continue
        if price is None:
            continue
        why = [f"Model {sk} {line:g}: {p_model*100:.1f}% vs market {p_mkt*100:.1f}%.",
               f"Projection {pr['mu']:.1f} ({pr['dist']}; 60% last-10 avg {statistics.mean(vals[:10]):.1f}, 40% sample avg {statistics.mean(vals):.1f}).",
               "Hit rate over " + ", ".join(f"{k} {v}" for k, v in hr.items()) + "."]
        against = ("Game logs ignore tonight's minutes, role, matchup and blowout risk; small samples overstate streaks."
                   if sk == "over" else "Unders lose to one hot night or overtime; a role/minutes bump isn't in the logs.")
        pk = make_pick("Prop", f"{pl['name']} {sk.title()} {line:g} {stat}", sk, line, price, p_model, p_mkt, weight, dq, why, flags,
                       push=pr["p_push"], caution=caution, against=against)
        if pk:
            pk["next_step"] = _next_step(pk)
            picks.append(pk)
    # alternate-line ladder
    ladder = []
    step = 0.5 if pr["mu"] < 15 else 1.0
    base = math.floor(line) + 0.5 if not line.is_integer() else line
    for k in range(-4, 5):
        ln = base + k * step * (2 if pr["mu"] >= 40 else 1)
        if ln < 0: continue
        q = prop_prob(vals, ln)
        ladder.append({"line": ln, "p_over": round(q["p_over"], 3), "fair_over": prob_to_am(q["p_over"]),
                       "fair_under": prob_to_am(1 - q["p_over"]), "L10": hit_rates(vals, ln).get("L10")})
    return {"league": lk, "player": pl, "stat": stat, "line": line, "games_used": len(vals), "recent": rows[:10],
            "projection": round(pr["mu"], 2), "dist": pr["dist"], "hit_rates": hr, "status": status,
            "picks": picks, "ladder": ladder, "flags": flags, "other_matches": [c["name"] + " (" + (c.get("team") or "") + ")" for c in cands[1:4]]}
