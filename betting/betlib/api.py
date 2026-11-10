"""Importable, UI-ready API. Every function returns plain JSON-serializable dicts/lists (no printing).

A future web/iPhone front end (e.g. a FastAPI/Flask app or a serverless function) can import these directly:

    from betlib import api
    api.slate("nba")                       -> list of games with odds
    api.game("nba", "Knicks")              -> full analysis + priced picks
    api.prop("nba", "Jalen Brunson", "pts", 26.5, over_odds=-115, under_odds=-105)
    api.parlay(["nba:Suns:total:over", "nhl:Kings:ml:NSH"])
    api.edges("all", tier="Medium")
    api.digest(log=False)
    api.track_list(), api.track_report(), api.track_signals(), api.track_grade(), api.track_add({...})
    api.sources()
"""
import json, sys
from . import espn, analysis, tracker
from .models import am_to_dec, implied, prob_to_am, dec_to_am, no_vig, fmt_am
from .leagues import LEAGUES, resolve

TORD = {"High": 0, "Medium": 1, "Low": 2}


def clean(obj):
    """Drop internal model arrays and make JSON-safe."""
    def strip(o):
        if isinstance(o, dict):
            return {k: strip(v) for k, v in o.items() if k not in ("grid",)}
        if isinstance(o, list):
            return [strip(x) for x in o]
        return o
    return json.loads(json.dumps(strip(obj), default=str))


def slate(sport="all", date=None):
    out = []
    for lk in resolve(sport):
        gs = espn.games(lk, date)
        if gs:
            out += gs
    return clean(out)


def game(sport, query, date=None):
    lk = resolve(sport)[0]
    g, s = espn.find_game(lk, query, date)
    if not g:
        return {"error": f"No {lk} game found for '{query}'"}
    return clean(analysis.evaluate_game(lk, g, s))


def prop(sport, player, stat, line, over_odds=None, under_odds=None, side=None, season=None):
    lk = resolve(sport)[0]
    return clean(analysis.evaluate_prop(lk, player, stat, line, over_odds, under_odds, side, season))


MKT = {"ml": "ML", "moneyline": "ML", "spread": "Spread", "ats": "Spread", "total": "Total", "ou": "Total", "1x2": "1X2", "draw": "1X2"}


def resolve_leg(spec):
    """Leg spec strings:
       LEAGUE:TEAM_OR_EVENTID:MARKET:SIDE      market ml|spread|total|draw ; side home|away|over|under|draw|<team abbr>
       prop:LEAGUE:Player Name:stat:line:over|under[:odds]
       manual:PROB:AMERICAN_ODDS[:label]
       track:ID   (a play already in the tracker)"""
    parts = spec.split(":")
    if parts[0] == "manual":
        p = float(parts[1]); odds = float(parts[2]); lab = parts[3] if len(parts) > 3 else f"manual {p:.2f}@{fmt_am(odds)}"
        return {"label": lab, "prob": p, "market_prob": None, "odds": odds, "edge": None, "tier": "n/a (manual)", "event": None, "market": "manual"}
    if parts[0] == "track":
        r = tracker.rows("id=?", (int(parts[1]),))
        if not r: raise ValueError(f"tracker play {parts[1]} not found")
        r = r[0]
        return {"label": r["selection"], "prob": r["model_prob"], "market_prob": r["market_prob"], "odds": r["odds"], "edge": r["edge"],
                "tier": r["tier"], "event": r["event_id"], "market": r["market"]}
    if parts[0] == "prop":
        lk = resolve(parts[1])[0]; odds = float(parts[6]) if len(parts) > 6 else None
        r = analysis.evaluate_prop(lk, parts[2], parts[3], parts[4], odds if parts[5] == "over" else None, odds if parts[5] == "under" else None, parts[5])
        if r.get("error") or not r["picks"]: raise ValueError(f"prop leg failed: {r.get('error')}")
        p = r["picks"][0]
        return {"label": p["selection"], "prob": p["model_prob"], "market_prob": p["market_prob"], "odds": p["odds"], "edge": p["edge"],
                "tier": p["tier"], "event": "player:" + r["player"]["id"], "market": "Prop", "caution": p.get("caution")}
    lk = resolve(parts[0])[0]
    g, s = espn.find_game(lk, parts[1])
    if not g: raise ValueError(f"leg '{spec}': game not found")
    r = analysis.evaluate_game(lk, g, s)
    mkt = MKT.get(parts[2].lower(), parts[2])
    side = parts[3].lower() if len(parts) > 3 else "home"
    for sd in ("home", "away"):
        if side == (r[sd]["abbr"] or "").lower(): side = sd
    cands = [p for p in r["picks"] if (p["market"] == mkt or (mkt == "ML" and p["market"] == "1X2")) and p["side"] == side]
    if not cands: raise ValueError(f"leg '{spec}': no priced market {mkt}/{side} (picks exist only for pre-game events with odds)")
    p = cands[0]
    return {"label": f"{p['selection']} ({r['away']['abbr']}@{r['home']['abbr']})", "prob": p["model_prob"], "market_prob": p["market_prob"],
            "odds": p["odds"], "edge": p["edge"], "tier": p["tier"], "event": r["event_id"], "market": p["market"], "caution": p.get("caution")}


def parlay(leg_specs, price=None):
    legs = [resolve_leg(x) if isinstance(x, str) else x for x in leg_specs]
    if len(legs) < 2: raise ValueError("need at least 2 legs")
    P = M = D = 1.0
    for l in legs:
        P *= l["prob"]; D *= am_to_dec(l["odds"])
        M *= l["market_prob"] if l["market_prob"] is not None else implied(l["odds"])
    price_dec = am_to_dec(price) if price else D
    events = {}
    for l in legs:
        if l["event"]: events.setdefault(l["event"], []).append(l)
    corr = [f"Same event {e}: legs {', '.join(x['label'] for x in v)} are correlated - independence math is wrong here; books price same-game parlays with extra hold."
            for e, v in events.items() if len(v) > 1]
    weak = []
    for l in sorted(legs, key=lambda l: (l["edge"] if l["edge"] is not None else 0)):
        why = []
        if l["edge"] is not None and l["edge"] < 0: why.append(f"negative edge {l['edge']*100:+.1f}%")
        if l["tier"] == "Low": why.append("Low tier")
        if l["prob"] < 0.4: why.append(f"low hit prob {l['prob']*100:.1f}%")
        if l.get("caution"): why.append("caution: " + "; ".join(l["caution"]))
        if why: weak.append({"leg": l["label"], "why": why})
    return clean({"legs": legs, "model_prob": P, "market_novig_prob": M, "fair_odds": prob_to_am(P), "offered_odds": dec_to_am(price_dec),
                  "price_source": "user price" if price else "product of leg prices", "offered_dec": price_dec, "ev": P * price_dec - 1,
                  "hold_vs_novig": 1 - M * price_dec, "correlation": corr, "weak_legs": weak,
                  "case_against": "Every leg's vig compounds and model errors multiply; parlays are the highest-hold product.",
                  "next_step": "Drop the weakest leg(s) and re-run; prefer 2-3 legs that each have positive edge."})


def _eval(lk, g):
    try:
        return analysis.evaluate_game(lk, g)
    except Exception as e:
        print(f"[warn] {lk} {g.get('id')}: {e}", file=sys.stderr)
        return None


def scan(leagues, date=None):
    found, counts, field = [], {}, {}
    for lk in leagues:
        gs = espn.games(lk, date)
        if not gs: continue
        if LEAGUES[lk]["kind"] == "field":
            field[lk] = gs; continue
        counts[lk] = {"games": len(gs), "with_odds": sum(1 for g in gs if g.get("odds")),
                      "pre": sum(1 for g in gs if g["status"].get("state") == "pre")}
        todo = [g for g in gs if g.get("odds") and g["status"].get("state") == "pre"]
        found += [r for r in espn.parallel(lambda g: _eval(lk, g), todo) if r]
    return found, counts, field


def edges(sport="all", date=None, min_edge=0.0, tier="Medium", results=None):
    res = results if results is not None else scan(resolve(sport), date)[0]
    picks = [(r, p) for r in res for p in r["picks"] if TORD[p["tier"]] <= TORD[tier] and p["edge"] >= min_edge and p["ev"] > 0]
    picks.sort(key=lambda x: (TORD[x[1]["tier"]], -x[1]["ev"]))
    return clean([{"league": r["league"], "game": r["name"], "event_id": r["event_id"], "start": r["start_local"], **p} for r, p in picks])


def sources(date=None):
    import subprocess
    out = subprocess.run([sys.executable, __file__.replace("betlib/api.py", "bet.py"), "--json", "sources"] + (["--date", date] if date else []),
                         capture_output=True, text=True)
    return json.loads(out.stdout)


def digest(date=None, top=5, log=False):
    import subprocess
    args = [sys.executable, __file__.replace("betlib/api.py", "bet.py"), "--json", "digest", "--top", str(top)] + ([] if log else ["--no-log"]) + (["--date", date] if date else [])
    return json.loads(subprocess.run(args, capture_output=True, text=True).stdout)


def track_add(play, source="manual"):
    return {"id": tracker.add(play, source=source)}


def track_list(status=None):
    return clean(tracker.rows("status=?", (status,)) if status else tracker.rows())


def track_grade():
    return clean([{"id": p["id"], "selection": p["selection"], "status": s} for p, s in tracker.grade()])


def track_report(since=None, all_plays=False):
    return clean(tracker.report(since, all_plays))


def track_signals(min_n=50, all_plays=False):
    return clean(tracker.signals(min_n, all_plays))


# ---------------- AI Prop Builder ----------------
import itertools, math

RISK = {  # weights for the combo objective
    "safe":       dict(tol=0.30, w_p=1.0, w_ev=0.5, low_pen=0.6, max_leg_dec=2.2),
    "balanced":   dict(tol=0.25, w_p=0.6, w_ev=1.0, low_pen=0.35, max_leg_dec=3.5),
    "aggressive": dict(tol=0.20, w_p=0.3, w_ev=1.5, low_pen=0.15, max_leg_dec=99),
}


def _conflict(a, b):
    """True if two legs from the same event can't sensibly be combined."""
    if a["event"] != b["event"]:
        return False
    ma, mb = a["market"], b["market"]
    if ma == mb and ma != "Prop":
        return True                      # both sides / two prices of one market
    if ma == "Prop" and mb == "Prop":
        return a.get("prop_key") == b.get("prop_key")
    sides = {"ML", "1X2", "Spread"}
    if ma in sides and mb in sides and a["side"] != b["side"]:
        return True                      # team A to win + team B to cover etc.
    return False


def _corr_notes(legs):
    notes = []
    by_ev = {}
    for l in legs:
        by_ev.setdefault(l["event"], []).append(l)
    for ev, ls in by_ev.items():
        if len(ls) < 2:
            continue
        notes.append(f"Same-game legs ({', '.join(x['label'] for x in ls)}): outcomes are correlated, so the independence probability below is only an approximation and your book's same-game-parlay price will differ (usually worse). Re-run with --price <book SGP price>.")
        mk = {l["market"]: l for l in ls}
        if ("ML" in mk or "1X2" in mk) and "Spread" in mk:
            notes.append("ML + spread on the same team are strongly positively correlated: the spread leg adds little real independent value.")
        if "Total" in mk and ("Spread" in mk or "ML" in mk):
            t = mk["Total"]; s = mk.get("Spread") or mk.get("ML")
            fav = (s.get("odds") or 0) < 0
            if t["side"] == "over" and fav:
                notes.append("Favorite + over tends to be mildly positively correlated (favorites covering often come with scoring).")
            elif t["side"] == "under" and not fav:
                notes.append("Underdog + under is mildly positively correlated (low-scoring games keep dogs close).")
        if any(l["market"] == "Prop" for l in ls):
            notes.append("Player props are correlated with team results/totals (e.g. a QB passing over with the game over).")
    return notes


def build(sport, query, date=None, legs=3, target=400, risk="balanced", extra_games=None, props=None):
    """Pick the leg combo closest to `target` American odds that maximizes model prob/edge for the risk style.
    props: list of 'Player:stat:line:over|under:ODDS' strings with REAL prices the user saw at their book."""
    risk = risk if risk in RISK else "balanced"
    R = RISK[risk]
    lk = resolve(sport)[0]
    notes, cands, games_used = [], [], []
    for q in [query] + list(extra_games or []):
        g, s = espn.find_game(lk, q, date)
        if not g:
            notes.append(f"No {lk} game found for '{q}'" + (f" on {date}" if date else "")); continue
        r = analysis.evaluate_game(lk, g, s)
        games_used.append({"event_id": r["event_id"], "name": r["name"], "start": r["start_local"], "flags": r["flags"]})
        if not r["odds"]:
            notes.append(f"{r['name']}: no odds in the free feed, so no priced legs from this game.")
        if r["state"] != "pre":
            notes.append(f"{r['name']}: game state '{r['state']}', no pre-game legs.")
        for p in r["picks"]:
            cands.append({"label": f"{p['selection']} ({r['away']['abbr']}@{r['home']['abbr']})", "event": r["event_id"], "market": p["market"],
                          "side": p["side"], "line": p["line"], "odds": p["odds"], "prob": p["model_prob"], "market_prob": p["market_prob"],
                          "edge": p["edge"], "ev": p["ev"], "tier": p["tier"], "reasons": p["reasons"], "case_against": p["case_against"],
                          "caution": p.get("caution", []), "source": "ESPN/DraftKings feed"})
    if props:
        for spec in props:
            try:
                pname, stat, line, side, odds = spec.split(":")
                pr = analysis.evaluate_prop(lk, pname, stat, float(line), float(odds) if side == "over" else None,
                                            float(odds) if side == "under" else None, side)
                if pr.get("error") or not pr["picks"]:
                    notes.append(f"Prop '{spec}' skipped: {pr.get('error', 'no pick')}"); continue
                p = pr["picks"][0]
                ev_id = games_used[0]["event_id"] if games_used else "props"
                cands.append({"label": p["selection"], "event": ev_id, "market": "Prop", "side": side, "line": float(line), "odds": p["odds"],
                              "prob": p["model_prob"], "market_prob": p["market_prob"], "edge": p["edge"], "ev": p["ev"], "tier": p["tier"],
                              "reasons": p["reasons"], "case_against": p["case_against"], "caution": p.get("caution", []),
                              "prop_key": f"{pr['player']['id']}:{stat}", "source": "your price (one side only; no-vig assumes ~4.5% hold)",
                              "hit_rates": pr["hit_rates"]})
            except ValueError:
                notes.append(f"Prop '{spec}' ignored: format is 'Player Name:stat:line:over|under:ODDS'.")
    else:
        notes.append("Player props: the free ESPN feed has NO prop prices, so no prop legs were auto-added (never invented). "
                     "To include props, pass the real prices you see: --prop \"Player Name:pts:24.5:over:-115\".")
    pool = [c for c in cands if am_to_dec(c["odds"]) <= R["max_leg_dec"]] or cands
    if len(pool) < legs:
        notes.append(f"Only {len(pool)} priced candidate legs available; building with fewer legs than requested.")
    n = min(legs, len(pool))
    tgt_dec = am_to_dec(target)
    best, scored = None, []
    for combo in itertools.combinations(pool, n) if n >= 1 else []:
        if any(_conflict(a, b) for a, b in itertools.combinations(combo, 2)):
            continue
        P = math.prod(c["prob"] for c in combo)
        D = math.prod(am_to_dec(c["odds"]) for c in combo)
        dist = abs(math.log(D) - math.log(tgt_dec))
        ev = P * D - 1
        lows = sum(1 for c in combo if c["tier"] == "Low")
        score = -2.0 * dist + R["w_p"] * math.log(P) + R["w_ev"] * ev - R["low_pen"] * lows
        scored.append((dist <= math.log(1 + R["tol"]), score, dist, combo, P, D, ev))
    if not scored:
        return clean({"error": "No valid non-conflicting combination of priced legs.", "notes": notes, "games": games_used,
                      "candidates": cands})
    any_within = any(s[0] for s in scored)
    if any_within:
        scored.sort(key=lambda x: (not x[0], -x[1]))
    else:
        scored.sort(key=lambda x: (round(x[2], 2), -x[1]))
    within, score, dist, combo, P, D, ev = scored[0]
    M = math.prod(c["market_prob"] for c in combo)
    weak = []
    for c in sorted(combo, key=lambda c: c["edge"]):
        why = []
        if c["edge"] < 0: why.append(f"negative edge {c['edge']*100:+.1f}% (model below market)")
        if c["tier"] == "Low": why.append("Low tier")
        if c["prob"] < 0.4: why.append(f"low hit prob {c['prob']*100:.0f}%")
        if c["caution"]: why.append("caution: " + "; ".join(c["caution"]))
        if why: weak.append({"leg": c["label"], "why": why})
    honest = []
    if not within:
        honest.append(f"No combo lands within {int(R['tol']*100)}% of {fmt_am(target)}; closest is {fmt_am(dec_to_am(D))}.")
    neg = [c for c in combo if c["edge"] < 0 or c["ev"] < 0]
    if neg:
        honest.append(f"Hitting {fmt_am(target)} with {n} legs forces {len(neg)} leg(s) with no model edge ({', '.join(c['label'] for c in neg)}). "
                      "The model would not bet these as singles; they are filler to reach the price.")
    if ev < 0:
        honest.append(f"Overall EV is negative ({ev:+.3f}/unit) even before same-game pricing: this is entertainment, not a value bet.")
    alts = [{"legs": [c["label"] for c in x[3]], "price": dec_to_am(x[5]), "model_prob": round(x[4], 4), "ev": round(x[6], 4)} for x in scored[1:4]]
    return clean({
        "game": games_used, "risk": risk, "target_odds": target, "legs_requested": legs, "legs": list(combo),
        "combined_model_prob": P, "combined_market_novig_prob": M, "fair_odds": prob_to_am(P),
        "payout_odds": dec_to_am(D), "payout_dec": D, "price_basis": "product of individual leg prices (books' SGP price will differ)",
        "ev": ev, "within_target": within, "weak_legs": weak, "correlation": _corr_notes(combo), "honest_notes": honest,
        "notes": notes, "alternatives": alts, "candidates_considered": len(pool),
        "case_against": "Each leg carries the book's vig and model error; same-game correlation is priced by the book, not by this tool.",
        "next_step": "If you like it, enter your book's actual SGP price via `parlay --price` (or `build --price`) to re-check EV; drop any weak leg first."})
