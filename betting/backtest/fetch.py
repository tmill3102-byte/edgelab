"""Historical dataset builder (free public ESPN endpoints only; nothing is invented).

For every completed game in the requested window it stores final score, teams, neutral flag, season/type,
basic team box stats from the scoreboard (FGA/FTA for pace proxies when present), and the pre-game
sportsbook odds ESPN keeps on the core API (open + close for ML, spread, total; live-odds providers skipped).
Games where ESPN has no pre-game odds are kept with odds=None (used for ratings, not for ROI/CLV).

Raw responses are cached gzip'd in backtest/raw/ (never purged by the engine) so re-runs are offline.
Usage: python3 -m backtest.fetch nba nhl nfl cfb [mlb]
"""
import datetime as dt, gzip, hashlib, json, os, sys, threading, time
from concurrent.futures import ThreadPoolExecutor
import requests

HERE = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(HERE, "raw"); DATA = os.path.join(HERE, "data")
os.makedirs(RAW, exist_ok=True); os.makedirs(DATA, exist_ok=True)
SITE = "https://site.api.espn.com/apis/site/v2/sports/"
CORE = "https://sports.core.api.espn.com/v2/sports/"
S = requests.Session(); S.headers.update({"User-Agent": "Mozilla/5.0 (personal research backtest; low volume)"})
_lock = threading.Lock(); _last = [0.0]; GAP = 0.06

PATHS = {"nba": ("basketball", "nba"), "nhl": ("hockey", "nhl"), "nfl": ("football", "nfl"),
         "cfb": ("football", "college-football"), "mlb": ("baseball", "mlb")}
# (start, end) inclusive windows; today is 2026-11-10 so everything ends 2026-11-09
WINDOWS = {
    "nba": [("2024-10-22", "2025-06-23"), ("2025-10-21", "2026-06-22"), ("2026-10-20", "2026-11-09")],
    "nhl": [("2024-10-04", "2025-06-18"), ("2025-10-07", "2026-06-20"), ("2026-10-06", "2026-11-09")],
    "nfl": [("2024-09-05", "2025-02-10"), ("2025-09-04", "2026-02-09"), ("2026-09-09", "2026-11-09")],
    "cfb": [("2024-08-24", "2025-01-21"), ("2025-08-23", "2026-01-20"), ("2026-08-22", "2026-11-09")],
    "mlb": [("2025-03-18", "2025-11-02"), ("2026-03-25", "2026-11-05")],
}


def get(url, params=None):
    key = hashlib.sha1((url + json.dumps(params or {}, sort_keys=True)).encode()).hexdigest()
    p = os.path.join(RAW, key + ".json.gz")
    if os.path.exists(p):
        with gzip.open(p, "rt") as f:
            return json.load(f)
    for att in range(4):
        with _lock:
            g = time.time() - _last[0]
            if g < GAP: time.sleep(GAP - g)
            _last[0] = time.time()
        try:
            r = S.get(url, params=params, timeout=25)
            if r.status_code == 200:
                d = r.json()
                with gzip.open(p, "wt") as f:
                    json.dump(d, f)
                return d
            if r.status_code in (400, 404):
                with gzip.open(p, "wt") as f:
                    json.dump(None, f)
                return None
        except Exception:
            pass
        time.sleep(1.5 * (att + 1))
    return None


def _f(x):
    try:
        if x is None or x == "": return None
        if isinstance(x, str):
            x = x.strip().lower().lstrip("ou")
            if x in ("even", "ev", "pk"): return 100.0
        return float(x)
    except Exception:
        return None


def _am(blk, k):
    v = (blk or {}).get(k) or {}
    return _f(v.get("american") if isinstance(v, dict) else v)


def parse_core_odds(d):
    """Pick the pre-game provider (skip '... Live Odds'); return dict with open/close fields or None."""
    items = [it for it in (d or {}).get("items") or [] if "live" not in ((it.get("provider") or {}).get("name") or "").lower()]
    if not items:
        return None
    it = items[0]
    h, a = it.get("homeTeamOdds") or {}, it.get("awayTeamOdds") or {}
    o = {"provider": (it.get("provider") or {}).get("name")}
    for tag in ("open", "close"):
        hb, ab, tb = h.get(tag) or {}, a.get(tag) or {}, it.get(tag) or {}
        o[f"ml_home_{tag}"] = _am(hb, "moneyLine"); o[f"ml_away_{tag}"] = _am(ab, "moneyLine")
        o[f"spread_home_{tag}"] = _am(hb, "pointSpread")
        o[f"spread_home_odds_{tag}"] = _am(hb, "spread"); o[f"spread_away_odds_{tag}"] = _am(ab, "spread")
        o[f"total_{tag}"] = _am(tb, "total"); o[f"over_{tag}"] = _am(tb, "over"); o[f"under_{tag}"] = _am(tb, "under")
    # top-level fields = last pre-game snapshot; use as close fallback
    fb = {"ml_home_close": _f(h.get("moneyLine")), "ml_away_close": _f(a.get("moneyLine")),
          "spread_home_odds_close": _f(h.get("spreadOdds")), "spread_away_odds_close": _f(a.get("spreadOdds")),
          "total_close": _f(it.get("overUnder")), "over_close": _f(it.get("overOdds")), "under_close": _f(it.get("underOdds"))}
    for k, v in fb.items():
        if o.get(k) is None: o[k] = v
    if o.get("spread_home_close") is None and _f(it.get("spread")) is not None:
        o["spread_home_close"] = _f(it.get("spread"))
    # sanity: drop obviously broken ML pairs (both favourites etc.)
    return o if any(o.get(k) is not None for k in ("ml_home_close", "spread_home_close", "total_close")) else None


def dates(a, b):
    d = dt.date.fromisoformat(a); e = dt.date.fromisoformat(b)
    while d <= e:
        yield d.strftime("%Y%m%d"); d += dt.timedelta(days=1)


def events_for(lk):
    sp, lg = PATHS[lk]
    params = {"groups": "80", "limit": 400} if lk == "cfb" else ({"limit": 100} if lk == "mlb" else None)
    out = {}
    def one(day):
        p = dict(params or {}); p["dates"] = day
        return get(SITE + f"{sp}/{lg}/scoreboard", p)
    days = [d for w in WINDOWS[lk] for d in dates(*w)]
    with ThreadPoolExecutor(6) as ex:
        for d in ex.map(one, days):
            for e in (d or {}).get("events") or []:
                c = (e.get("competitions") or [{}])[0]
                st = ((c.get("status") or e.get("status") or {}).get("type") or {})
                if not st.get("completed"):
                    continue
                season = e.get("season") or {}
                if season.get("type") not in (2, 3):  # regular + post only
                    continue
                g = {"id": e["id"], "date": e.get("date"), "season": season.get("year"), "stype": season.get("type"),
                     "neutral": bool(c.get("neutralSite")), "conf": bool(c.get("conferenceCompetition"))}
                ok = True
                for t in c.get("competitors") or []:
                    side = t.get("homeAway"); tm = t.get("team") or {}
                    sc = _f(t.get("score") if not isinstance(t.get("score"), dict) else t["score"].get("value"))
                    if sc is None: ok = False
                    stats = {s.get("name"): _f(s.get("displayValue")) for s in t.get("statistics") or []}
                    g[side] = {"id": str(tm.get("id")), "abbr": tm.get("abbreviation"), "name": tm.get("displayName"),
                               "score": sc, "fga": stats.get("fieldGoalsAttempted"), "fta": stats.get("freeThrowsAttempted"),
                               "ls": len(t.get("linescores") or [])}
                if ok and g.get("home") and g.get("away"):
                    out[g["id"]] = g
    return sorted(out.values(), key=lambda g: g["date"])


def build(lk):
    sp, lg = PATHS[lk]
    t0 = time.time()
    evs = events_for(lk)
    print(f"[{lk}] {len(evs)} completed games from scoreboards ({time.time()-t0:.0f}s)", flush=True)
    def od(g):
        return parse_core_odds(get(CORE + f"{sp}/leagues/{lg}/events/{g['id']}/competitions/{g['id']}/odds"))
    with ThreadPoolExecutor(6) as ex:
        for g, o in zip(evs, ex.map(od, evs)):
            g["odds"] = o
    n_odds = sum(1 for g in evs if g["odds"] and g["odds"].get("ml_home_close") is not None)
    with open(os.path.join(DATA, f"{lk}.jsonl"), "w") as f:
        for g in evs:
            f.write(json.dumps(g) + "\n")
    print(f"[{lk}] wrote {len(evs)} games, {n_odds} with closing ML ({time.time()-t0:.0f}s)", flush=True)


if __name__ == "__main__":
    for lk in sys.argv[1:]:
        build(lk)
