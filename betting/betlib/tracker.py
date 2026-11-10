"""SQLite tracker: log suggested plays, auto-grade from ESPN finals, report record/units/ROI/CLV."""
import os, sqlite3, json, datetime as dt
from . import espn
from .models import am_to_dec, no_vig, implied
from .leagues import LEAGUES

DB = os.environ.get("EDGE_TRACKER_DB") or os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tracker.db")
SCHEMA = """
CREATE TABLE IF NOT EXISTS plays (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at TEXT, date TEXT, sport TEXT, event_id TEXT, event_name TEXT, start_time TEXT,
  market TEXT, selection TEXT, side TEXT, line REAL, odds REAL,
  model_prob REAL, market_prob REAL, edge REAL, ev REAL, tier TEXT, stake_units REAL,
  rationale TEXT, source TEXT, recommended INTEGER DEFAULT 1,
  player_id TEXT, player_name TEXT, stat TEXT,
  status TEXT DEFAULT 'pending', result_detail TEXT, profit_units REAL,
  closing_odds REAL, closing_line REAL, clv REAL, graded_at TEXT, notes TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_play ON plays(date, sport, event_id, market, selection, source);
"""


def conn():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    c.executescript(SCHEMA)
    return c


def add(p, source="manual", recommended=None):
    """p: dict with keys sport, event_id, event_name, start_time, market, selection, side, line, odds, model_prob,
    market_prob, edge, ev, tier, stake_units, rationale, player_id, player_name, stat."""
    rec = recommended if recommended is not None else (1 if p.get("tier") in ("High", "Medium") else 0)
    c = conn()
    now = dt.datetime.now(espn.ET)
    date = p.get("date") or now.strftime("%Y-%m-%d")
    stake = p.get("stake_units")
    if not stake:
        stake = 1.0 if source == "manual" else 0.5  # flat fallback for tracking
    try:
        cur = c.execute("""INSERT INTO plays(created_at,date,sport,event_id,event_name,start_time,market,selection,side,line,odds,
            model_prob,market_prob,edge,ev,tier,stake_units,rationale,source,recommended,player_id,player_name,stat)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (now.isoformat(timespec="seconds"), date, p.get("sport"), str(p.get("event_id") or ""), p.get("event_name"), p.get("start_time"),
                         p.get("market"), p.get("selection"), p.get("side"), p.get("line"), p.get("odds"), p.get("model_prob"),
                         p.get("market_prob"), p.get("edge"), p.get("ev"), p.get("tier"), stake, p.get("rationale"), source, rec,
                         p.get("player_id"), p.get("player_name"), p.get("stat")))
        c.commit()
        return cur.lastrowid
    except sqlite3.IntegrityError:
        return None
    finally:
        c.close()


def rows(where="1=1", args=()):
    c = conn()
    r = [dict(x) for x in c.execute(f"SELECT * FROM plays WHERE {where} ORDER BY date, id", args)]
    c.close()
    return r


def _profit(status, odds, stake):
    if status == "won":
        return round(stake * (am_to_dec(odds) - 1), 3)
    if status == "lost":
        return -stake
    return 0.0


def _closing(p, s):
    """Closing price on our side from summary pickcenter (ESPN keeps the last line after the game)."""
    o = espn.odds_from_summary(s)
    if not o:
        return None, None, None
    m, side = p["market"], p["side"]
    try:
        if m in ("ML", "1X2"):
            if m == "1X2" and o.get("ml_draw") is not None:
                prices = [o["ml_home"], o["ml_draw"], o["ml_away"]]; idx = {"home": 0, "draw": 1, "away": 2}[side]
            else:
                prices = [o["ml_home"], o["ml_away"]]; idx = {"home": 0, "away": 1}[side]
            nv, _ = no_vig(prices)
            return prices[idx], None, nv[idx]
        if m == "Spread":
            prices = [o["spread_home_odds"], o["spread_away_odds"]]
            line = o["spread_home"] if side == "home" else -o["spread_home"]
            nv, _ = no_vig(prices); idx = 0 if side == "home" else 1
            return prices[idx], line, nv[idx]
        if m == "Total":
            prices = [o["over_odds"], o["under_odds"]]
            nv, _ = no_vig(prices); idx = 0 if side == "over" else 1
            return prices[idx], o["total"], nv[idx]
    except Exception:
        pass
    return None, None, None


def _prop_value(s, player_id, stat):
    from .analysis import STAT_ALIASES, COMBOS, _num
    parts = COMBOS.get((stat or "").lower(), [stat])
    total = 0.0
    for ptk in parts:
        cands = STAT_ALIASES.get((ptk or "").lower(), [ptk])
        found = None
        for team in ((s or {}).get("boxscore") or {}).get("players") or []:
            for grp in team.get("statistics") or []:
                names = grp.get("names") or grp.get("keys") or []
                keys = grp.get("keys") or []
                for a in grp.get("athletes") or []:
                    if str((a.get("athlete") or {}).get("id")) != str(player_id):
                        continue
                    for cand in cands:
                        for arr in (names, keys):
                            if cand in arr and arr.index(cand) < len(a.get("stats") or []):
                                found = _num(a["stats"][arr.index(cand)])
                                break
                        if found is not None: break
                    if found is None and a.get("didNotPlay"):
                        return "DNP"
        if found is None:
            return None
        total += found
    return total


def grade(verbose=True):
    """Settle all pending plays whose events are final."""
    out = []
    c = conn()
    pend = [dict(x) for x in c.execute("SELECT * FROM plays WHERE status='pending'")]
    for p in pend:
        if p["sport"] not in LEAGUES or not p["event_id"]:
            continue
        s = espn.summary(p["sport"], p["event_id"], ttl=120)
        if not s:
            continue
        g = espn.event_from_summary(p["sport"], s)
        st = g["status"]
        if not st.get("completed"):
            if (st.get("name") or "") in ("STATUS_POSTPONED", "STATUS_CANCELED"):
                c.execute("UPDATE plays SET status='void', result_detail=?, profit_units=0, graded_at=? WHERE id=?",
                          (st.get("name"), dt.datetime.now(espn.ET).isoformat(timespec="seconds"), p["id"]))
                out.append((p, "void"))
            continue
        hs, as_ = g["home"]["score"], g["away"]["score"]
        status, detail = None, f"{g['away']['abbr']} {as_:g} @ {g['home']['abbr']} {hs:g}"
        m, side, line = p["market"], p["side"], p["line"]
        if m in ("ML", "1X2"):
            if side == "draw":
                status = "won" if hs == as_ else "lost"
            elif hs == as_:
                status = "push" if m == "ML" and p["sport"] not in ("nhl", "mlb") else "lost"
            else:
                status = "won" if ((hs > as_) == (side == "home")) else "lost"
        elif m == "Spread":
            d = (hs - as_) if side == "home" else (as_ - hs)
            v = d + line
            status = "push" if abs(v) < 1e-9 else ("won" if v > 0 else "lost")
        elif m == "Total":
            t = hs + as_
            status = "push" if abs(t - line) < 1e-9 else ("won" if (t > line) == (side == "over") else "lost")
        elif m == "Prop":
            val = _prop_value(s, p["player_id"], p["stat"])
            if val == "DNP":
                status, detail = "void", "player did not play"
            elif val is None:
                continue  # leave pending for manual grading
            else:
                detail = f"{p['player_name']} {p['stat']} = {val:g}"
                status = "push" if abs(val - line) < 1e-9 else ("won" if (val > line) == (side == "over") else "lost")
        if not status:
            continue
        co, cl, cp = _closing(p, s) if m != "Prop" else (None, None, None)
        clv = None
        if cp is not None and p["odds"] is not None and (cl is None or p["line"] is None or abs(cl - p["line"]) < 1e-9):
            clv = round(am_to_dec(p["odds"]) * cp - 1, 4)  # >0 = beat the close
        prof = _profit(status, p["odds"], p["stake_units"] or 0)
        c.execute("""UPDATE plays SET status=?, result_detail=?, profit_units=?, closing_odds=?, closing_line=?, clv=?, graded_at=? WHERE id=?""",
                  (status, detail, prof, co, cl, clv, dt.datetime.now(espn.ET).isoformat(timespec="seconds"), p["id"]))
        out.append((p, status))
    c.commit(); c.close()
    return out


def manual_grade(pid, status):
    c = conn()
    p = c.execute("SELECT * FROM plays WHERE id=?", (pid,)).fetchone()
    if not p:
        c.close(); return False
    prof = _profit(status, p["odds"], p["stake_units"] or 0)
    c.execute("UPDATE plays SET status=?, profit_units=?, result_detail='manual', graded_at=? WHERE id=?",
              (status, prof, dt.datetime.now(espn.ET).isoformat(timespec="seconds"), pid))
    c.commit(); c.close(); return True


def _agg(rs):
    w = sum(1 for r in rs if r["status"] == "won"); l = sum(1 for r in rs if r["status"] == "lost")
    pu = sum(1 for r in rs if r["status"] == "push")
    risk = sum(r["stake_units"] or 0 for r in rs if r["status"] in ("won", "lost", "push"))
    prof = sum(r["profit_units"] or 0 for r in rs)
    clvs = [r["clv"] for r in rs if r["clv"] is not None]
    return {"n": w + l + pu, "W": w, "L": l, "P": pu, "units": round(prof, 2), "risked": round(risk, 2),
            "roi": round(prof / risk * 100, 1) if risk else None,
            "clv_avg": round(sum(clvs) / len(clvs) * 100, 2) if clvs else None, "clv_n": len(clvs),
            "beat_close": f"{sum(1 for x in clvs if x > 0)}/{len(clvs)}" if clvs else None}


def report(since=None, all_plays=False):
    where, args = "status IN ('won','lost','push')", []
    if not all_plays:
        where += " AND recommended=1"
    if since:
        where += " AND date>=?"; args.append(since)
    rs = rows(where, tuple(args))
    pend = rows("status='pending'" + ("" if all_plays else " AND recommended=1"))
    rep = {"scope": "all logged plays" if all_plays else "recommended plays only (tier High/Medium or manual adds)",
           "overall": _agg(rs), "pending": len(pend), "by": {}}
    for key in ("sport", "market", "tier", "source"):
        groups = {}
        for r in rs:
            groups.setdefault(r[key] or "?", []).append(r)
        rep["by"][key] = {k: _agg(v) for k, v in sorted(groups.items())}
    n = rep["overall"]["n"]
    rep["warning"] = (f"Small sample: {n} graded plays (<50). Record/ROI are mostly noise at this size; CLV is the faster signal."
                      if n < 50 else None)
    return rep


def _bucket(v, edges, fmt):
    for lo, hi in zip(edges[:-1], edges[1:]):
        if v is not None and lo <= v < hi:
            return fmt(lo, hi)
    return "n/a"


def signals(min_n=50, all_plays=False):
    rs = rows("status IN ('won','lost','push')" + ("" if all_plays else " AND recommended=1"))
    def side_bucket(r):
        if r["market"] == "Prop": return "prop " + (r["side"] or "")
        if r["side"] in ("home", "away", "draw"): return r["side"]
        return r["side"] or "?"
    dims = {
        "model win prob": lambda r: _bucket(r["model_prob"], [0, .35, .45, .5, .55, .65, .8, 1.01], lambda a, b: f"{a*100:.0f}-{min(b,1)*100:.0f}%"),
        "edge (no-vig)": lambda r: _bucket(r["edge"], [-1, 0, .02, .04, .06, .1, 1], lambda a, b: f"{a*100:+.0f} to {b*100:+.0f} pp"),
        "market": lambda r: r["market"],
        "side": side_bucket,
    }
    out = {"min_n": min_n, "total_graded": len(rs), "dims": {}}
    for name, fn in dims.items():
        g = {}
        for r in rs:
            g.setdefault(fn(r), []).append(r)
        out["dims"][name] = {}
        for k, v in sorted(g.items()):
            a = _agg(v)
            if a["n"] < min_n:
                out["dims"][name][k] = {"n": a["n"], "hidden": f"sample {a['n']} < {min_n}; not shown (noise)"}
            else:
                out["dims"][name][k] = a
    return out
