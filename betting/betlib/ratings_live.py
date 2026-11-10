"""Live v2 ratings: start from the shipped seed (state at the end of the last completed season in the backtest
dataset, betlib/data/ratings_seed.json) and replay every completed game since then from free ESPN endpoints.
Football: weekly scoreboards. NBA/NHL/MLB: each team's schedule. Built once per process; HTTP cached."""
import datetime as dt, json, os, threading
from . import espn
from .net import get_json
from .leagues import LEAGUES
from .ratings import RatingBook, PARAMS, make_feature, FEATURES

SEED_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "ratings_seed.json")
_BOOKS, _LOCK = {}, threading.Lock()
FOOT = {"nfl": [(2, 18), (3, 5)], "cfb": [(2, 16), (3, 1)]}


def season_for(lk, when):
    """ESPN season label for a date (NBA/NHL label = year the season ends)."""
    when = when or dt.datetime.now(dt.timezone.utc)
    if lk in ("nba", "nhl"):
        return when.year + 1 if when.month >= 8 else when.year
    if lk in ("nfl", "cfb"):
        return when.year if when.month >= 3 else when.year - 1
    return when.year


def _stat(t, name):
    for x in t.get("statistics") or []:
        if x.get("name") == name:
            return espn._f(x.get("displayValue"))
    return None


def _row(lk, e, season):
    c = (e.get("competitions") or [{}])[0]
    st = ((c.get("status") or e.get("status") or {}).get("type") or {})
    if not st.get("completed"): return None
    g = {"id": e.get("id"), "when": espn.parse_iso(e.get("date")), "season": season, "neutral": bool(c.get("neutralSite"))}
    for t in c.get("competitors") or []:
        sc = t.get("score")
        sc = espn._f(sc.get("value") if isinstance(sc, dict) else sc)
        if sc is None: return None
        g[t.get("homeAway")] = {"id": str((t.get("team") or {}).get("id")), "score": sc,
                                "fga": _stat(t, "fieldGoalsAttempted"), "fta": _stat(t, "freeThrowsAttempted")}
    return g if g.get("home") and g.get("away") and g["when"] else None


def season_games(lk, season, current=True):
    ttl = 3 * 3600 if current else 30 * 86400
    L = LEAGUES[lk]; out = {}
    if lk in FEATURES and lk == "nba":
        # daily scoreboards: they carry the box-score shot counts the pace feature needs
        start = dt.date(season - 1, 10, 1)
        end = min(dt.datetime.now(espn.ET).date(), dt.date(season, 6, 30))
        days = []
        d = start
        while d <= end:
            days.append(d.strftime("%Y%m%d")); d += dt.timedelta(days=1)
        today = dt.datetime.now(espn.ET).strftime("%Y%m%d")
        def day(ds):
            return get_json(espn.SITE + L["path"] + "/scoreboard", {"dates": ds}, ttl=(600 if ds >= today else 30 * 86400))
        for js in espn.parallel(day, days):
            for e in (js or {}).get("events") or []:
                if ((e.get("season") or {}).get("type")) not in (2, 3): continue
                r = _row(lk, e, season)
                if r: out[r["id"]] = r
    elif lk in FOOT:
        for stype, weeks in FOOT[lk]:
            for w in range(1, weeks + 1):
                p = {"dates": season, "seasontype": stype, "week": w, "limit": 400}
                if L.get("groups"): p["groups"] = L["groups"]
                d = get_json(espn.SITE + L["path"] + "/scoreboard", p, ttl=ttl)
                for e in (d or {}).get("events") or []:
                    r = _row(lk, e, season)
                    if r: out[r["id"]] = r
    else:
        d = get_json(espn.SITE + L["path"] + "/teams", None, ttl=86400)
        teams = [t["team"]["id"] for t in (((d or {}).get("sports") or [{}])[0].get("leagues") or [{}])[0].get("teams", [])]
        def one(tid):
            rows = []
            for stype in ((2,) if current else (2, 3)):
                s = get_json(espn.SITE + L["path"] + f"/teams/{tid}/schedule", {"season": season, "seasontype": stype}, ttl=ttl)
                rows += [r for r in (_row(lk, e, season) for e in (s or {}).get("events") or []) if r]
            return rows
        for rows in espn.parallel(one, teams):
            for r in rows: out[r["id"]] = r
    return sorted(out.values(), key=lambda g: g["when"])


def load_seed(lk):
    try:
        return json.load(open(SEED_PATH)).get(lk)
    except Exception:
        return None


def book(lk, when=None):
    """RatingBook with every completed game up to now applied (None if the league has no v2 model)."""
    if lk not in PARAMS:
        return None
    with _LOCK:
        if lk in _BOOKS:
            return _BOOKS[lk]
        b = RatingBook(lk)
        feat = make_feature(lk)
        seed = load_seed(lk)
        cur = season_for(lk, when)
        start = cur
        if seed:
            for k in ("r", "t", "n", "season"):
                setattr(b, k, dict(seed["state"][k]))
            b.last = {k: espn.parse_iso(v) for k, v in seed["state"]["last"].items()}
            b.avg = seed["state"]["avg"]
            if feat and seed["state"].get("feature"):
                feat.load(seed["state"]["feature"])
            start = seed["season"] + 1
        b.replayed = 0
        for s in range(max(start, cur - 2), cur + 1):
            for g in season_games(lk, s, current=(s == cur)):
                if g["id"] in (seed or {}).get("ids_tail", []): continue
                am, at, _ = feat.pre(g) if feat else (0.0, 0.0, [])
                b.update(g["home"]["id"], g["away"]["id"], g["home"]["score"], g["away"]["score"], g["when"], g["neutral"], g["season"], am, at)
                if feat: feat.post(g)
                b.replayed += 1
        b.seed_season = seed["season"] if seed else None
        b.feature = feat
        _BOOKS[lk] = b
        return b
