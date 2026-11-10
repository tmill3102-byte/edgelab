#!/usr/bin/env python3
"""Personal sports betting RESEARCH CLI (free public data, no keys, never places bets).

  python3 bet.py sources
  python3 bet.py slate <sport|all> [--date YYYYMMDD]
  python3 bet.py game <sport> <team|event_id> [--date]
  python3 bet.py prop <sport> "<player>" <stat> <line> [--odds -115 --under-odds -105 --side over]
  python3 bet.py parlay --leg nba:Knicks:spread:home --leg nhl:401892683:total:under --leg manual:0.55:-110:"My leg" [--price +260]
  python3 bet.py edges [sport] [--min-edge 0.02 --tier Medium]
  python3 bet.py digest [--top 5 --no-log]
  python3 bet.py track add|list|grade|report|signals|void ...
  python3 bet.py odds -110 -110      (vig / no-vig / fair calculator)
Add --json to any command for machine output.
"""
import argparse, json, sys, os, datetime as dt
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from betlib import espn, analysis, tracker, net, api
from betlib.models import *
from betlib.leagues import LEAGUES, resolve

DISCLAIMER = "Research only - estimates, not guarantees. Never bet more than you can afford to lose. Help: 1-800-GAMBLER."
J = False


def out(obj, text):
    if J:
        print(json.dumps(obj, indent=1, default=str))
    else:
        print(text)


def pct(x, sign=False):
    if x is None: return "n/a"
    return f"{x*100:+.1f}%" if sign else f"{x*100:.1f}%"


def fmt_pick(p, game=None, indent="  "):
    hdr = f"{indent}PICK: {p['selection']} {fmt_am(p['odds'])}  [{p['tier']}]" + (f"  ({game})" if game else "")
    lines = [hdr,
             f"{indent}  Numbers: model {pct(p['model_prob'])} (raw {pct(p['model_raw'])}) | market no-vig {pct(p['market_prob'])} | "
             f"edge {pct(p['edge'], True)} no-vig, {pct(p['edge_at_price'], True)} at price | EV {p['ev']:+.3f}/unit | fair {fmt_am(p['fair_odds'])}"
             + (f" | stake {p['stake_units']:.2f}u (1u=1% bankroll, 1/4 Kelly, cap 2u)" if p['stake_units'] else ""),
             f"{indent}  Why: " + " ".join(p["reasons"])]
    lines.append(f"{indent}  Case against: {p['case_against']}")
    lines.append(f"{indent}  Next step: {p.get('next_step', '')}")
    if p.get("caution"):
        lines.append(f"{indent}  CAUTION: " + " | ".join(p["caution"]))
    if p.get("flags"):
        lines.append(f"{indent}  Data flags: " + "; ".join(f.lstrip('!') for f in p["flags"]))
    return "\n".join(lines)


def strip_grid(r):
    r = dict(r)
    if r.get("model"):
        r["model"] = {k: v for k, v in r["model"].items() if k not in ("grid",)}
    return r


# ---------------- sources ----------------
def cmd_sources(a):
    date = espn.norm_date(a.date)
    rows, objs = [], []
    def probe(lk):
        L = LEAGUES[lk]
        d = espn.scoreboard(lk, date, ttl=120)
        r = {"league": lk, "name": L["name"], "scoreboard": d is not None, "events": 0, "with_odds": 0, "injuries": None,
             "props": None, "standings": None}
        if d:
            evs = d.get("events", [])
            if L["kind"] == "field":
                r["events"] = sum(len(e.get("competitions") or []) or sum(len(g.get("competitions") or []) for g in e.get("groupings") or []) for e in evs) or len(evs)
                r["with_odds"] = sum(1 for e in evs for c in (e.get("competitions") or []) if c.get("odds"))
                r["tournaments"] = [e.get("name") for e in evs]
            else:
                r["events"] = len(evs)
                r["with_odds"] = sum(1 for e in evs if any((e.get("competitions") or [{}])[0].get("odds") or []))
        if L["kind"] != "field":
            inj = espn.league_injuries(lk)
            r["injuries"] = bool(inj and inj.get("injuries"))
            st = espn.standings(lk)
            r["standings"] = bool(st and (st.get("children") or st.get("standings")))
            r["props"] = L["kind"] in ("pts", "goals")  # gamelog-based; verified per-sport below
        return r
    rows = espn.parallel(probe, list(LEAGUES), workers=6)
    # extra free sources
    extra = []
    for nm, url in [("MLB StatsAPI schedule", "https://statsapi.mlb.com/api/v1/schedule?sportId=1&date=" + f"{date[:4]}-{date[4:6]}-{date[6:]}"),
                    ("NHL api-web schedule", f"https://api-web.nhle.com/v1/schedule/{date[:4]}-{date[4:6]}-{date[6:]}"),
                    ("NHL api-web standings", "https://api-web.nhle.com/v1/standings/now"),
                    ("ESPN player search", "https://site.web.api.espn.com/apis/search/v2?query=Jalen%20Brunson&limit=3"),
                    ("ESPN NBA gamelog", "https://site.web.api.espn.com/apis/common/v3/sports/basketball/nba/athletes/3934672/gamelog")]:
        d = net.get_json(url, ttl=120)
        extra.append({"source": nm, "ok": d is not None, "url": url})
    obj = {"date": date, "leagues": rows, "extra": extra}
    t = [f"Source status for {date} (live checks; ESPN odds provider = DraftKings when present)",
         f"{'league':12} {'events':>6} {'odds':>5}  injuries standings  note"]
    for r in rows:
        note = ""
        if not r["scoreboard"]: note = "scoreboard FAILED"
        elif r["events"] == 0: note = "no events on this date"
        elif r["with_odds"] == 0: note = "events but NO odds in feed"
        if r.get("tournaments"): note += " " + "; ".join(r["tournaments"][:2])
        yn = lambda v: "-" if v is None else ("yes" if v else "no")
        t.append(f"{r['league']:12} {r['events']:>6} {r['with_odds']:>5}  {yn(r['injuries']):8} {yn(r['standings']):9}  {note}")
    t.append("\nOther free endpoints:")
    for e in extra:
        t.append(f"  {'OK  ' if e['ok'] else 'FAIL'} {e['source']}")
    out(obj, "\n".join(t))


# ---------------- slate ----------------
def cmd_slate(a):
    objs, t = [], []
    date = espn.norm_date(a.date)
    for lk in resolve(a.sport):
        gs = espn.games(lk, date)
        if not gs:
            continue
        L = LEAGUES[lk]
        t.append(f"\n== {L['name']} ({lk}) - {len(gs)} event(s) on {date}")
        for g in gs:
            if g.get("field"):
                t.append(f"  {g['name']}  ({'active' if g['active'] else 'not active'} {g['date'][:10]}..{(g['end'] or '')[:10]})  total listed: {g['matches']}  today: {len(g['today'])}  odds in feed: {'yes' if g['odds'] else 'no'}")
                for m in g["today"][:12]:
                    t.append(f"     {m['group'] or ''} {m['round'] or ''}: {' vs '.join(m['players'])} [{m['state']}]")
                objs.append(g); continue
            o = g.get("odds")
            line = "no odds in feed"
            if o:
                parts = []
                if o.get("ml_away") is not None: parts.append(f"ML {g['away']['abbr']} {fmt_am(o['ml_away'])} / {g['home']['abbr']} {fmt_am(o['ml_home'])}" + (f" / draw {fmt_am(o['ml_draw'])}" if o.get('ml_draw') else ""))
                if o.get("spread_home") is not None: parts.append(f"spread {g['home']['abbr']} {o['spread_home']:+g}")
                if o.get("total") is not None: parts.append(f"total {o['total']:g}")
                line = " | ".join(parts)
            sc = ""
            if g["status"].get("state") != "pre":
                sc = f" [{g['away']['score']:g}-{g['home']['score']:g} {g['status'].get('shortDetail')}]" if g['home']['score'] is not None else f" [{g['status'].get('shortDetail')}]"
            t.append(f"  {g['id']}  {espn.local_time(g['date'])}  {g['away']['abbr']} ({g['away']['record'] or '-'}) @ {g['home']['abbr']} ({g['home']['record'] or '-'}){sc}  {line}")
            objs.append(g)
        if a.analyze and L["kind"] != "field":
            res = espn.parallel(lambda g: analysis.evaluate_game(lk, g), [g for g in gs if g.get("odds") and g["status"].get("state") == "pre"])
            for r in res:
                best = [p for p in r["picks"] if p["tier"] != "Low"]
                if best:
                    t.append(fmt_pick(best[0], r["name"], "    "))
    if not t:
        t = [f"No events found for {a.sport} on {date}."]
    out(objs, "\n".join(t).strip())


# ---------------- game ----------------
def game_text(r):
    m, o = r.get("model", {}), r.get("odds")
    h, aw = r["home"], r["away"]
    t = [f"{r['name']}  ({r['league']}, event {r['event_id']})  {r['start_local']}  status: {r['status']}"]
    if o:
        t.append(f"Market ({o['provider']}): ML {aw['abbr']} {fmt_am(o.get('ml_away'))} / {h['abbr']} {fmt_am(o.get('ml_home'))}"
                 + (f" / draw {fmt_am(o['ml_draw'])}" if o.get('ml_draw') is not None else "")
                 + (f" | spread {h['abbr']} {o['spread_home']:+g} ({fmt_am(o.get('spread_home_odds'))}/{fmt_am(o.get('spread_away_odds'))})" if o.get('spread_home') is not None else "")
                 + (f" | total {o['total']:g} (o {fmt_am(o.get('over_odds'))} / u {fmt_am(o.get('under_odds'))})" if o.get('total') is not None else "")
                 + (f" | open: ML {fmt_am(o.get('ml_away_open'))}/{fmt_am(o.get('ml_home_open'))}, total {o.get('total_open')}" if o.get('ml_home_open') is not None else ""))
        if r.get("market"):
            nv = r["market"]["ml_novig"]
            labs = [h["abbr"], "draw", aw["abbr"]] if len(nv) == 3 else [h["abbr"], aw["abbr"]]
            t.append("Market no-vig ML: " + " / ".join(f"{l} {pct(x)}" for l, x in zip(labs, nv)) + f" (overround {pct(r['market']['ml_overround'])})")
    else:
        t.append("Market: NO odds available from the free feed for this event.")
    for side in ("away", "home"):
        p = r["profiles"][side]
        t.append(f"  {r[side]['abbr']:5} record {r[side]['record'] or '-':7} GP {p['n']:2}  PF {p['pf'] and round(p['pf'],1)}  PA {p['pa'] and round(p['pa'],1)}  "
                 f"MOV {p['mov'] and round(p['mov'],1)}  L5 {p['last5'] or '-'}  rest {round(p['rest'],1) if p['rest'] is not None else '?'}d")
    if m:
        if m["type"] == "margin-normal":
            t.append(f"Model: projected margin {h['abbr']} {m['exp_margin_home']:+.1f} (own {m['own_margin']:+.1f}, source {m['source']}) -> {h['abbr']} win {pct(m['p_home'])}; "
                     f"projected total {m['exp_total']}")
        else:
            t.append(f"Model (Poisson): xG {h['abbr']} {m['lam_home']} - {aw['abbr']} {m['lam_away']} -> regulation H/D/A {pct(m['p_home_reg'])}/{pct(m['p_draw'])}/{pct(m['p_away_reg'])}; projected total {m['exp_total']}")
        for n in m.get("adj_notes", []): t.append("  adj: " + n)
    for n in r["notes"]: t.append("Note: " + n)
    for side in ("away", "home"):
        inj = r["injuries"][side]
        if inj["list"]:
            t.append(f"Injuries {r[side]['abbr']}: " + "; ".join(f"{i['name']} ({i['pos'] or ''}) {i['status']}{' [KEY]' if i.get('key') else ''}" for i in inj["list"][:8]))
        elif inj["checked"]:
            t.append(f"Injuries {r[side]['abbr']}: none listed")
    if r["flags"]:
        t.append("Data flags: " + "; ".join(f.lstrip('!') for f in r["flags"]))
    if r["picks"]:
        t.append("\nMarkets (best EV first):")
        for p in r["picks"]:
            t.append(fmt_pick(p))
    return "\n".join(t)


def cmd_game(a):
    lk = resolve(a.sport)[0]
    g, s = espn.find_game(lk, a.team, a.date)
    if not g:
        raise SystemExit(f"No {lk} game found for '{a.team}'" + (f" on {a.date}" if a.date else " in the next few days"))
    r = analysis.evaluate_game(lk, g, s)
    out(strip_grid(r), game_text(r) + "\n\n" + DISCLAIMER)
    if a.log:
        for p in r["picks"]:
            if p["selection"].lower().startswith(a.log.lower()) or a.log == "best":
                pid = tracker.add(_play_row(lk, r, p), source="manual", recommended=1)
                print(f"Logged play #{pid}: {p['selection']} {fmt_am(p['odds'])}")
                break


def _play_row(lk, r, p, extra=None):
    d = {"sport": lk, "event_id": r["event_id"], "event_name": r["name"], "start_time": r["start"], "market": p["market"],
         "selection": p["selection"], "side": p["side"], "line": p["line"], "odds": p["odds"], "model_prob": p["model_prob"],
         "market_prob": p["market_prob"], "edge": p["edge"], "ev": p["ev"], "tier": p["tier"], "stake_units": p["stake_units"],
         "rationale": " ".join(p["reasons"]) + " | Against: " + p["case_against"] + (" | Caution: " + "; ".join(p["caution"]) if p.get("caution") else "")}
    if extra: d.update(extra)
    if r.get("start"):
        d["date"] = espn.parse_iso(r["start"]).astimezone(espn.ET).strftime("%Y-%m-%d")
    return d


# ---------------- prop ----------------
def cmd_prop(a):
    lk = resolve(a.sport)[0]
    r = analysis.evaluate_prop(lk, a.player, a.stat, a.line, a.odds, a.under_odds, a.side, a.season)
    if r.get("error"):
        out(r, "ERROR: " + r["error"]); return
    pl = r["player"]
    t = [f"{pl['name']} ({pl.get('team')}) - {a.stat} line {r['line']:g}   [{lk}, ESPN athlete {pl['id']}]",
         f"Games used: {r['games_used']}  projection {r['projection']} ({r['dist']})  status: {r['status'] or 'not on injury report'}",
         "Hit rates over line: " + "  ".join(f"{k} {v}" for k, v in r["hit_rates"].items()),
         "Last 10: " + ", ".join(f"{x['value']:g} {x['atvs'] or ''}{x['opp'] or ''}" for x in r["recent"])]
    if r["flags"]:
        t.append("Data flags: " + "; ".join(f.lstrip('!') for f in r["flags"]))
    for p in r["picks"]:
        t.append(fmt_pick(p))
    t.append("\nAlt-line ladder (model fair prices; compare to your book's alt lines):")
    t.append(f"  {'line':>6} {'P(over)':>8} {'fair o':>7} {'fair u':>7}  L10 over")
    for x in r["ladder"]:
        t.append(f"  {x['line']:>6g} {x['p_over']*100:>7.1f}% {fmt_am(x['fair_over']):>7} {fmt_am(x['fair_under']):>7}  {x['L10']}")
    if r["other_matches"]:
        t.append("Other name matches: " + ", ".join(r["other_matches"]))
    out(r, "\n".join(t) + "\n\n" + DISCLAIMER)
    if a.log and r["picks"]:
        p = max(r["picks"], key=lambda x: x["ev"]) if a.log == "best" else next((x for x in r["picks"] if x["side"] == a.log), None)
        if p:
            pid = tracker.add({"sport": lk, "event_id": a.event or "", "event_name": f"{pl['name']} prop", "market": "Prop",
                               "selection": p["selection"], "side": p["side"], "line": p["line"], "odds": p["odds"],
                               "model_prob": p["model_prob"], "market_prob": p["market_prob"], "edge": p["edge"], "ev": p["ev"],
                               "tier": p["tier"], "stake_units": p["stake_units"], "rationale": " ".join(p["reasons"]),
                               "player_id": pl["id"], "player_name": pl["name"], "stat": a.stat}, source="manual", recommended=1)
            print(f"Logged prop #{pid}" + ("" if a.event else " (no --event id given: it will stay pending until graded manually)"))


# ---------------- parlay ----------------
def cmd_parlay(a):
    try:
        obj = api.parlay(a.leg, a.price)
    except ValueError as ex:
        raise SystemExit(str(ex))
    legs, P, M, price_dec, weak, corr = obj["legs"], obj["model_prob"], obj["market_novig_prob"], obj["offered_dec"], obj["weak_legs"], obj["correlation"]
    ev = obj["ev"]
    t = ["Parlay legs:"]
    for l in legs:
        t.append(f"  - {l['label']}  {fmt_am(l['odds'])}  model {pct(l['prob'])}  market {pct(l['market_prob'])}  edge {pct(l['edge'], True)}  [{l['tier']}]")
    t += [f"Combined model prob {pct(P)} (independence) vs market no-vig {pct(M)}",
          f"Fair price {fmt_am(prob_to_am(P))}  | offered {fmt_am(dec_to_am(price_dec))} ({'your --price' if a.price else 'product of leg prices'})",
          f"EV {ev:+.3f} per unit | book's effective hold vs no-vig: {pct(1 - M*price_dec)}",
          "Weakest legs: " + ("; ".join(f"{w['leg']} ({', '.join(w['why'])})" for w in weak) if weak else "none flagged"),
          ]
    t += ["Correlation: " + c for c in corr]
    t.append("Case against: every leg's vig compounds and model errors multiply; parlays are the highest-hold product. Only legs with a real edge belong here.")
    t.append("Next step: drop the weakest leg(s) and re-run; prefer 2-3 legs with positive edge each.")
    out(obj, "\n".join(t) + "\n\n" + DISCLAIMER)


# ---------------- build (AI Prop Builder) ----------------
def cmd_build(a):
    r = api.build(a.sport, a.team, a.date, a.legs, a.target, a.risk, a.game, a.prop)
    if r.get("error"):
        out(r, "ERROR: " + r["error"] + ("\n" + "\n".join(r.get("notes", [])) if r.get("notes") else "")); return
    if a.price:
        r["payout_odds"] = a.price; r["payout_dec"] = am_to_dec(a.price); r["ev"] = r["combined_model_prob"] * r["payout_dec"] - 1
        r["price_basis"] = "your book's price (--price)"
    t = [f"AI PROP BUILDER - {', '.join(g['name'] + ' (' + g['start'] + ')' for g in r['game'])}",
         f"Request: {r['legs_requested']} legs, target {fmt_am(r['target_odds'])}, risk {r['risk']}  |  {r['candidates_considered']} priced candidate legs"]
    for i, l in enumerate(r["legs"], 1):
        t.append(f"\n Leg {i}: {l['label']}  {fmt_am(l['odds'])}  [{l['tier']}]  source: {l['source']}")
        t.append(f"   Numbers: model {pct(l['prob'])} | market no-vig {pct(l['market_prob'])} | edge {pct(l['edge'], True)}")
        t.append("   Why: " + " ".join(l["reasons"]))
        t.append("   Case against: " + l["case_against"])
        if l.get("caution"): t.append("   CAUTION: " + " | ".join(l["caution"]))
    t.append(f"\nCombined: model {pct(r['combined_model_prob'])} (fair {fmt_am(r['fair_odds'])}) vs payout {fmt_am(r['payout_odds'])} [{r['price_basis']}] | market no-vig {pct(r['combined_market_novig_prob'])} | EV {r['ev']:+.3f}/unit")
    t.append("Weakest legs: " + ("; ".join(f"{w['leg']} ({', '.join(w['why'])})" for w in r["weak_legs"]) or "none flagged"))
    for c in r["correlation"]: t.append("Correlation: " + c)
    for h in r["honest_notes"]: t.append("Honest note: " + h)
    for n in r["notes"]: t.append("Note: " + n)
    if r["alternatives"]:
        t.append("Alternatives: " + " || ".join(f"{' + '.join(x['legs'])} @ {fmt_am(x['price'])} (p {pct(x['model_prob'])}, EV {x['ev']:+.3f})" for x in r["alternatives"]))
    t.append("Case against: " + r["case_against"]); t.append("Next step: " + r["next_step"])
    out(r, "\n".join(t) + "\n\n" + DISCLAIMER)


# ---------------- edges / digest ----------------
scan = api.scan


TORD = {"High": 0, "Medium": 1, "Low": 2}


def best_per_game(results, min_edge=0.0, tier_min="Medium"):
    picks = []
    for r in results:
        cand = [p for p in r["picks"] if TORD[p["tier"]] <= TORD[tier_min] and p["edge"] >= min_edge and p["ev"] > 0]
        if cand:
            p = sorted(cand, key=lambda p: (TORD[p["tier"]], -p["ev"]))[0]
            picks.append((r, p))
    picks.sort(key=lambda x: (TORD[x[1]["tier"]], -x[1]["ev"]))
    return picks


def cmd_edges(a):
    res, counts, _ = scan(resolve(a.sport), a.date)
    picks = []
    for r in res:
        for p in r["picks"]:
            if TORD[p["tier"]] <= TORD[a.tier] and p["edge"] >= a.min_edge and p["ev"] > 0:
                picks.append((r, p))
    picks.sort(key=lambda x: (TORD[x[1]["tier"]], -x[1]["ev"]))
    t = [f"Scanned {sum(c['games'] for c in counts.values())} games in {len(counts)} league(s); {len(res)} priced pre-game. "
         f"Filter: tier>={a.tier}, edge>={a.min_edge*100:.1f}pp, EV>0 -> {len(picks)} result(s)."]
    for r, p in picks[:a.limit]:
        t.append(f"\n[{r['league']}] {r['name']} - {r['start_local']}")
        t.append(fmt_pick(p))
    if not picks:
        t.append("No plays pass the filter. That's normal: most lines are efficient. Try --tier Low to see leans.")
    out([{"game": r["name"], "league": r["league"], "event_id": r["event_id"], **p} for r, p in picks], "\n".join(t) + "\n\n" + DISCLAIMER)


def cmd_digest(a):
    now = dt.datetime.now(espn.ET)
    date = espn.norm_date(a.date)
    graded = tracker.grade()
    yday = (dt.datetime.strptime(date, "%Y%m%d") - dt.timedelta(days=1)).strftime("%Y-%m-%d")
    yrows = tracker.rows("date=? AND status IN ('won','lost','push','void') AND recommended=1", (yday,))
    yagg = tracker._agg(yrows)
    res, counts, field = scan(list(LEAGUES), date)
    picks = best_per_game(res, a.min_edge, "Medium")
    top = picks[:a.top]
    logged = []
    if not a.no_log:
        for r, p in top:
            pid = tracker.add(_play_row(r["league"], r, p), source="digest", recommended=1)
            if pid: logged.append(pid)
    t = [f"BETTING RESEARCH DIGEST - {dt.datetime.strptime(date, '%Y%m%d').strftime('%a %b %d, %Y')} (generated {now.strftime('%I:%M %p ET')})"]
    t.append(f"Yesterday ({yday}) recommended: {yagg['W']}-{yagg['L']}-{yagg['P']}, {yagg['units']:+.2f}u"
             + (f", ROI {yagg['roi']:+.1f}%" if yagg['roi'] is not None else "") + f" | graded this run: {len(graded)}"
             + ("" if yagg["n"] else " (no graded plays yesterday)"))
    t.append("\nSlate:")
    for lk, c in counts.items():
        t.append(f"  {LEAGUES[lk]['name']}: {c['games']} games ({c['with_odds']} with odds, {c['pre']} not started)")
    for lk, evs in field.items():
        for e in evs:
            if e.get("active") and e["today"]:
                real = [m for m in e["today"] if "TBD" not in m["players"]]
                t.append(f"  {LEAGUES[lk]['name']}: {e['name']} - {len(e['today'])} match(es) listed today ({len(real)} with known players); no odds in free feed, no model")
    t.append(f"\nTop edges (High/Medium, best per game; {len(picks)} qualified):")
    if not top:
        t.append("  None today. No game cleared the Medium bar (edge >= 2pp, EV >= 2%, decent data). Passing is a position.")
    for r, p in top:
        t.append(f"\n [{r['league']}] {r['name']} - {r['start_local']}")
        t.append(fmt_pick(p, None, "  "))
        inj = [f"{r[s]['abbr']}: " + ", ".join(f"{i['name']} {i['status']}" for i in r["injuries"][s]["list"] if i.get("key") or (i['status'] or '').lower() == 'out')
               for s in ("away", "home") if any(i.get("key") or (i['status'] or '').lower() == 'out' for i in r["injuries"][s]["list"])]
        if inj: t.append("    Injuries (out / key players): " + " | ".join(inj))
    lean = sum(1 for r in res for p in r["picks"] if p["tier"] == "Low" and p["ev"] > 0)
    t.append(f"\n{lean} additional Low-tier leans hidden (run: bet.py edges --tier Low).")
    if logged: t.append(f"Logged to tracker (source=digest): plays #{', #'.join(map(str, logged))}")
    elif not a.no_log and top: t.append("Top plays were already logged earlier today.")
    t.append(DISCLAIMER)
    obj = {"date": date, "yesterday": yagg, "graded_now": len(graded), "counts": counts,
           "field": {k: [e["name"] for e in v] for k, v in field.items()},
           "top": [{"league": r["league"], "game": r["name"], "start": r["start_local"], "event_id": r["event_id"], **p,
                    "injuries": {s: r["injuries"][s]["list"] for s in ("home", "away")}} for r, p in top],
           "logged_ids": logged}
    out(obj, "\n".join(t))


# ---------------- track ----------------
def cmd_track(a):
    if a.action == "grade":
        g = tracker.grade()
        if a.id and a.result:
            tracker.manual_grade(int(a.id), a.result); print(f"#{a.id} -> {a.result}")
        out([{"id": p["id"], "selection": p["selection"], "status": s} for p, s in g],
            "\n".join(f"#{p['id']} {p['selection']} -> {s}" for p, s in g) or "Nothing new to grade (pending games not final yet).")
    elif a.action == "list":
        rs = tracker.rows("status=?" if a.status else "1=1", (a.status,) if a.status else ())
        t = [f"{'id':>4} {'date':10} {'sp':6} {'selection':32} {'odds':>6} {'tier':6} {'stake':>5} {'status':8} {'P/L':>6} {'CLV':>6}"]
        for r in rs[-a.limit:]:
            t.append(f"{r['id']:>4} {r['date']:10} {r['sport']:6} {r['selection'][:32]:32} {fmt_am(r['odds']):>6} {r['tier'] or '':6} {r['stake_units'] or 0:>5.2f} "
                     f"{r['status']:8} {(r['profit_units'] if r['profit_units'] is not None else 0):>+6.2f} {(f'{r[chr(99)+chr(108)+chr(118)]*100:+.1f}%' if r['clv'] is not None else '-'):>6}"
                     + ("" if r["recommended"] else "  (not rec.)"))
        out(rs, "\n".join(t))
    elif a.action == "add":
        if not (a.sport and a.selection and a.odds is not None):
            raise SystemExit("track add needs --sport --selection --odds (and --event --market --side --line for auto-grading)")
        pid = tracker.add({"sport": resolve(a.sport)[0], "event_id": a.event, "event_name": a.name, "market": a.market, "selection": a.selection,
                           "side": a.side, "line": a.line, "odds": a.odds, "model_prob": a.prob, "stake_units": a.stake, "tier": a.tier,
                           "rationale": a.note, "player_id": a.player_id, "player_name": a.player, "stat": a.stat}, source="manual", recommended=1)
        print(f"Added play #{pid}" if pid else "Duplicate play (already logged)")
    elif a.action == "void":
        tracker.manual_grade(int(a.id), "void"); print(f"#{a.id} voided")
    elif a.action == "report":
        r = tracker.report(a.since, a.all)
        o = r["overall"]
        t = [f"Tracker report - {r['scope']}" + (f" since {a.since}" if a.since else ""),
             f"Record {o['W']}-{o['L']}-{o['P']} | units {o['units']:+.2f} on {o['risked']:.2f} risked | ROI {o['roi'] if o['roi'] is not None else 'n/a'}%"
             f" | avg CLV {o['clv_avg'] if o['clv_avg'] is not None else 'n/a'}% (beat close {o['beat_close'] or 'n/a'}) | pending {r['pending']}"]
        if r["warning"]: t.append("WARNING: " + r["warning"])
        for k, groups in r["by"].items():
            if not groups: continue
            t.append(f"By {k}:")
            for name, g in groups.items():
                t.append(f"  {name:10} {g['W']}-{g['L']}-{g['P']}  {g['units']:+.2f}u  ROI {g['roi'] if g['roi'] is not None else 'n/a'}%  CLV {g['clv_avg'] if g['clv_avg'] is not None else 'n/a'}%")
        out(r, "\n".join(t))
    elif a.action == "signals":
        s = tracker.signals(a.min_n, a.all)
        t = [f"Signals (graded {s['total_graded']}; buckets shown only with n >= {s['min_n']})"]
        if s["total_graded"] < s["min_n"]:
            t.append(f"WARNING: only {s['total_graded']} graded plays - every bucket is below the minimum; nothing here is meaningful yet.")
        for dim, b in s["dims"].items():
            t.append(f"{dim}:")
            for k, v in b.items():
                t.append(f"  {k:16} " + (f"n={v['n']} (hidden: small sample)" if v.get("hidden") else f"{v['W']}-{v['L']}-{v['P']} {v['units']:+.2f}u ROI {v['roi']}% CLV {v['clv_avg']}%"))
        out(s, "\n".join(t))


def cmd_odds(a):
    ps = [float(x) for x in a.prices]
    nv, over = no_vig(ps)
    t = [f"Prices {', '.join(fmt_am(p) for p in ps)} | overround {pct(over)}"]
    for p, q in zip(ps, nv):
        t.append(f"  {fmt_am(p):>6}: implied {pct(implied(p))}  no-vig {pct(q)}  fair {fmt_am(prob_to_am(q))}  dec {am_to_dec(p):.3f}")
    if a.prob:
        t.append(f"Your prob {pct(a.prob)} on first side: EV {ev_per_unit(a.prob, ps[0]):+.3f}/unit, 1/4 Kelly {kelly(a.prob, ps[0])*100:.2f}% (cap 2%)")
    out({"prices": ps, "novig": nv, "overround": over}, "\n".join(t))


def main():
    global J
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--json", action="store_true")
    sp = ap.add_subparsers(dest="cmd", required=True)
    s = sp.add_parser("sources"); s.add_argument("--date")
    s = sp.add_parser("slate"); s.add_argument("sport", nargs="?", default="all"); s.add_argument("--date"); s.add_argument("--analyze", action="store_true")
    s = sp.add_parser("game"); s.add_argument("sport"); s.add_argument("team"); s.add_argument("--date"); s.add_argument("--log", help="log a pick: 'best' or selection prefix e.g. 'NY'")
    s = sp.add_parser("prop"); s.add_argument("sport"); s.add_argument("player"); s.add_argument("stat"); s.add_argument("line", type=float)
    s.add_argument("--odds", type=float, help="over price"); s.add_argument("--under-odds", type=float); s.add_argument("--side", choices=["over", "under"])
    s.add_argument("--season"); s.add_argument("--log", help="'over', 'under' or 'best'"); s.add_argument("--event", help="ESPN event id for auto-grading")
    s = sp.add_parser("parlay"); s.add_argument("--leg", action="append", required=True); s.add_argument("--price", type=float, help="book's parlay price (American)")
    s = sp.add_parser("build", help="AI Prop Builder: best combo near target odds for a game")
    s.add_argument("sport"); s.add_argument("team"); s.add_argument("--date", help="YYYYMMDD, today, tomorrow, or weekday e.g. sunday")
    s.add_argument("--legs", type=int, default=3); s.add_argument("--target", type=float, default=400); s.add_argument("--risk", default="balanced", choices=["safe", "balanced", "aggressive"])
    s.add_argument("--game", action="append", help="extra game(s) for a cross-game build"); s.add_argument("--prop", action="append", help="'Player:stat:line:over|under:ODDS' with a REAL price")
    s.add_argument("--price", type=float, help="your book's actual parlay/SGP price")
    s = sp.add_parser("edges"); s.add_argument("sport", nargs="?", default="all"); s.add_argument("--date"); s.add_argument("--min-edge", type=float, default=0.0)
    s.add_argument("--tier", default="Medium", choices=["High", "Medium", "Low"]); s.add_argument("--limit", type=int, default=25)
    s = sp.add_parser("digest"); s.add_argument("--date"); s.add_argument("--top", type=int, default=5); s.add_argument("--min-edge", type=float, default=0.0); s.add_argument("--no-log", action="store_true")
    s = sp.add_parser("track"); s.add_argument("action", choices=["add", "list", "grade", "report", "signals", "void"])
    for f in ("--sport", "--event", "--name", "--market", "--selection", "--side", "--tier", "--note", "--player", "--player-id", "--stat", "--status", "--since", "--id", "--result"):
        s.add_argument(f)
    for f in ("--line", "--odds", "--prob"): s.add_argument(f, type=float)
    s.add_argument("--stake", type=float, default=1.0); s.add_argument("--limit", type=int, default=50); s.add_argument("--all", action="store_true"); s.add_argument("--min-n", type=int, default=50)
    s = sp.add_parser("odds"); s.add_argument("prices", nargs="+"); s.add_argument("--prob", type=float)
    a = ap.parse_args()
    J = a.json
    {"sources": cmd_sources, "slate": cmd_slate, "game": cmd_game, "prop": cmd_prop, "parlay": cmd_parlay, "build": cmd_build, "edges": cmd_edges,
     "digest": cmd_digest, "track": cmd_track, "odds": cmd_odds}[a.cmd](a)


if __name__ == "__main__":
    main()
