"""ESPN public JSON API wrappers + parsers (free, no key)."""
import datetime as dt
from urllib.parse import parse_qs, unquote, urlparse
from zoneinfo import ZoneInfo
ET = ZoneInfo("America/New_York")
from concurrent.futures import ThreadPoolExecutor
from .net import get_json
from .leagues import LEAGUES

SITE = "https://site.api.espn.com/apis/site/v2/sports/"
WEB = "https://site.web.api.espn.com/apis/"


def _f(x):
    try:
        if x is None or x == "":
            return None
        if isinstance(x, str):
            x = x.strip().lower().lstrip("ou")
            if x in ("even", "ev"):
                return 100.0
        return float(x)
    except Exception:
        return None


def today_str():
    return dt.datetime.now(ET).strftime("%Y%m%d")


def norm_date(s):
    if not s or s == "today":
        return today_str()
    if s == "yesterday":
        return (dt.datetime.now(ET) - dt.timedelta(days=1)).strftime("%Y%m%d")
    if s == "tomorrow":
        return (dt.datetime.now(ET) + dt.timedelta(days=1)).strftime("%Y%m%d")
    days = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    sl = s.lower()
    for i, d in enumerate(days):
        if sl in (d, d[:3]):
            now = dt.datetime.now(ET)
            return (now + dt.timedelta(days=(i - now.weekday()) % 7)).strftime("%Y%m%d")
    return s.replace("-", "")


def parse_iso(s):
    if not s:
        return None
    s = s.replace("Z", "+00:00")
    try:
        return dt.datetime.fromisoformat(s)
    except ValueError:
        try:
            return dt.datetime.strptime(s[:16], "%Y-%m-%dT%H:%M").replace(tzinfo=dt.timezone.utc)
        except Exception:
            return None


def local_time(s):
    d = parse_iso(s)
    if not d:
        return "?"
    return d.astimezone(ET).strftime("%a %b %d %I:%M %p ET").replace(" 0", " ")


# ---------------- scoreboard ----------------
def scoreboard(lk, date=None, ttl=300):
    L = LEAGUES[lk]
    p = {"dates": norm_date(date)}
    if L.get("groups"):
        p["groups"] = L["groups"]
        p["limit"] = 400
    return get_json(SITE + L["path"] + "/scoreboard", p, ttl=ttl)


_BOOK_HOSTS = (
    "draftkings.com", "fanduel.com", "betmgm.com", "caesars.com", "bet365.com",
    "fanatics.com", "hardrock.bet", "betrivers.com", "espnbet.com", "thescore.bet",
    "ballybet.com",
)


_DROP_QUERY = {
    "outcomes", "coupon", "wageramount", "options", "type", "marketid", "selectionid",
    "s", "wpcid", "wpscid", "wpcn", "wpscn", "wpcrn", "wpcrid", "preurl",
}


def public_event_url(href):
    """Public sportsbook event or home URL from an ESPN/Odds API link.

    Affiliate gateways are reduced to their preurl. `{state}` is filled as Ohio.
    Bet-slip query params (outcomes, coupons, add-to-slip) are removed. A link
    that still contains an unresolved template is dropped.
    """
    if not href or not isinstance(href, str):
        return None
    raw = href.strip().replace("{state}", "oh")
    if not raw.startswith("http"):
        return None
    parsed = urlparse(raw)
    pre = (parse_qs(parsed.query).get("preurl") or [None])[0]
    if pre:
        raw = unquote(pre).replace("{state}", "oh")
        parsed = urlparse(raw)
    if "{" in raw or "}" in raw:
        return None
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in ("http", "https"):
        return None
    if not any(host == h or host.endswith("." + h) for h in _BOOK_HOSTS):
        return None
    if "addtobetslip" in (parsed.path or "").lower():
        return None
    kept = []
    for key, values in parse_qs(parsed.query, keep_blank_values=False).items():
        if key.lower() in _DROP_QUERY:
            continue
        for value in values:
            if "{" in value or "}" in value:
                continue
            kept.append(f"{key}={value}")
    frag = parsed.fragment or ""
    if "{" in frag or "}" in frag:
        frag = ""
    url = f"{parsed.scheme}://{host}{parsed.path or '/'}"
    if kept:
        url += "?" + "&".join(kept)
    if frag:
        url += "#" + frag
    return url


def parse_odds(o):
    """Normalize one ESPN odds object (scoreboard competitions[].odds[] or summary pickcenter[])."""
    if not o:
        return None
    link = o.get("link") if isinstance(o.get("link"), dict) else {}
    out = {"provider": (o.get("provider") or {}).get("name"), "details": o.get("details"),
           "event_url": public_event_url(link.get("href"))}
    ml = o.get("moneyline") or {}
    ps = o.get("pointSpread") or {}
    tt = o.get("total") or {}

    def cur(side_obj, field="odds"):
        if not side_obj:
            return None, None
        c = side_obj.get("close") or side_obj.get("current") or {}
        op = side_obj.get("open") or {}
        return _f(c.get(field)), _f(op.get(field))

    out["ml_home"], out["ml_home_open"] = cur(ml.get("home"))
    out["ml_away"], out["ml_away_open"] = cur(ml.get("away"))
    out["ml_draw"], _ = cur(ml.get("draw"))
    h, a = o.get("homeTeamOdds") or {}, o.get("awayTeamOdds") or {}
    if out["ml_home"] is None: out["ml_home"] = _f(h.get("moneyLine"))
    if out["ml_away"] is None: out["ml_away"] = _f(a.get("moneyLine"))
    if out["ml_draw"] is None: out["ml_draw"] = _f((o.get("drawOdds") or {}).get("moneyLine"))
    # spread (home perspective)
    hl, hlo = cur(ps.get("home"), "line")
    out["spread_home"] = hl if hl is not None else _f(o.get("spread"))
    out["spread_home_open"] = hlo
    out["spread_home_odds"], _ = cur(ps.get("home"))
    out["spread_away_odds"], _ = cur(ps.get("away"))
    if out["spread_home_odds"] is None: out["spread_home_odds"] = _f(h.get("spreadOdds"))
    if out["spread_away_odds"] is None: out["spread_away_odds"] = _f(a.get("spreadOdds"))
    tl, tlo = cur(tt.get("over"), "line")
    out["total"] = tl if tl is not None else _f(o.get("overUnder"))
    out["total_open"] = tlo
    out["over_odds"], _ = cur(tt.get("over"))
    out["under_odds"], _ = cur(tt.get("under"))
    if out["over_odds"] is None: out["over_odds"] = _f(o.get("overOdds"))
    if out["under_odds"] is None: out["under_odds"] = _f(o.get("underOdds"))
    has = any(out.get(k) is not None for k in ("ml_home", "spread_home", "total"))
    return out if has else None


def parse_event(lk, e):
    c = (e.get("competitions") or [{}])[0]
    comps = c.get("competitors") or []
    g = {"league": lk, "id": e.get("id"), "name": e.get("name"), "short": e.get("shortName"),
         "date": e.get("date"), "status": (e.get("status") or c.get("status") or {}).get("type", {}),
         "neutral": c.get("neutralSite", False), "home": None, "away": None, "odds": None}
    for t in comps:
        tm = t.get("team") or {}
        rec = None
        for r in t.get("records") or []:
            if r.get("type") in ("total", None) or r.get("name") == "overall":
                rec = r.get("summary"); break
        side = {"id": tm.get("id"), "abbr": tm.get("abbreviation"), "name": tm.get("displayName"),
                "short": tm.get("shortDisplayName"), "record": rec, "score": _f(t.get("score") if not isinstance(t.get("score"), dict) else t["score"].get("value")),
                "winner": t.get("winner")}
        g[t.get("homeAway", "home")] = side
    for o in c.get("odds") or []:
        po = parse_odds(o)
        if po:
            g["odds"] = po; break
    return g


def games(lk, date=None):
    d = scoreboard(lk, date)
    if not d:
        return None
    if LEAGUES[lk]["kind"] == "field":
        return field_events(lk, d, date)
    return [parse_event(lk, e) for e in d.get("events", [])]


def field_events(lk, d, date=None):
    """Tennis/golf/MMA/racing: list tournaments/cards active on the date and the matches/fights scheduled that day."""
    out = []
    day = norm_date(date)
    for e in d.get("events", []):
        comps = []
        for gp in e.get("groupings") or []:
            for c in gp.get("competitions") or []:
                c["_group"] = (gp.get("grouping") or {}).get("displayName")
                comps.append(c)
        if not e.get("groupings"):
            comps = e.get("competitions") or []
        today = []
        for c in comps:
            cd = parse_iso(c.get("date") or c.get("startDate"))
            if cd and cd.astimezone(ET).strftime("%Y%m%d") == day:
                names = [((x.get("athlete") or {}).get("displayName") or (x.get("team") or {}).get("displayName") or "TBD") for x in c.get("competitors") or []]
                today.append({"group": c.get("_group"), "round": (c.get("round") or {}).get("displayName"),
                              "state": ((c.get("status") or {}).get("type") or {}).get("state"), "players": names})
        st, en = parse_iso(e.get("date")), parse_iso(e.get("endDate"))
        nowd = dt.datetime.strptime(day, "%Y%m%d").replace(tzinfo=ET) + dt.timedelta(hours=12)
        active = bool(st and en and st <= nowd <= en) or bool(today)
        hasodds = any(c.get("odds") for c in comps)
        out.append({"league": lk, "id": e.get("id"), "name": e.get("name"), "date": e.get("date"), "end": e.get("endDate"),
                    "status": (e.get("status") or {}).get("type", {}), "matches": len(comps), "today": today,
                    "active": active, "odds": hasodds, "field": True})
    return out


# ---------------- per-game / team / player ----------------
def summary(lk, event_id, ttl=300):
    return get_json(SITE + LEAGUES[lk]["path"] + "/summary", {"event": event_id}, ttl=ttl)


def team_schedule(lk, team_id, ttl=6 * 3600):
    return get_json(SITE + LEAGUES[lk]["path"] + f"/teams/{team_id}/schedule", None, ttl=ttl)


def league_injuries(lk, ttl=1800):
    return get_json(SITE + LEAGUES[lk]["path"] + "/injuries", None, ttl=ttl)


def standings(lk, ttl=3 * 3600):
    return get_json(WEB + "v2/sports/" + LEAGUES[lk]["path"] + "/standings", None, ttl=ttl)


def team_results(lk, team_id, before=None):
    """Completed games for a team this season: list of dicts (date, home, pf, pa, opp)."""
    d = team_schedule(lk, team_id)
    res = []
    if not d:
        return res, None
    nxt = None
    for e in d.get("events", []):
        c = (e.get("competitions") or [{}])[0]
        st = (c.get("status") or {}).get("type", {})
        when = parse_iso(e.get("date"))
        me = op = None
        for t in c.get("competitors") or []:
            if str((t.get("team") or {}).get("id")) == str(team_id):
                me = t
            else:
                op = t
        if not me or not op:
            continue
        if before and when and when >= before:
            continue
        if not st.get("completed"):
            continue
        sc = lambda t: _f(t["score"].get("value") if isinstance(t.get("score"), dict) else t.get("score"))
        pf, pa = sc(me), sc(op)
        if pf is None or pa is None:
            continue
        res.append({"date": when, "home": me.get("homeAway") == "home", "pf": pf, "pa": pa,
                    "opp": (op.get("team") or {}).get("abbreviation")})
    res.sort(key=lambda r: r["date"] or dt.datetime.min.replace(tzinfo=dt.timezone.utc))
    return res, nxt


def injuries_from_summary(s):
    """{team_id: [ {name, id, status, pos, comment} ]}"""
    out = {}
    for blk in (s or {}).get("injuries") or []:
        tid = str((blk.get("team") or {}).get("id"))
        lst = []
        for i in blk.get("injuries") or []:
            a = i.get("athlete") or {}
            lst.append({"name": a.get("displayName"), "id": str(a.get("id") or ""), "status": i.get("status"),
                        "pos": (a.get("position") or {}).get("abbreviation"),
                        "comment": i.get("shortComment") or ((i.get("details") or {}).get("type"))})
        out[tid] = lst
    return out


def injuries_from_league(lk):
    d = league_injuries(lk)
    out = {}
    for blk in (d or {}).get("injuries") or []:
        tid = str(blk.get("id"))
        lst = []
        for i in blk.get("injuries") or []:
            a = i.get("athlete") or {}
            aid = ""
            for l in a.get("links") or []:
                h = l.get("href", "")
                if "/id/" in h:
                    aid = h.split("/id/")[1].split("/")[0]; break
            lst.append({"name": a.get("displayName"), "id": aid, "status": i.get("status"),
                        "pos": (a.get("position") or {}).get("abbreviation"), "comment": i.get("shortComment")})
        out[tid] = lst
    return out


def leaders_from_summary(s):
    """{team_id: set(athlete_ids)} of season team leaders shown in summary."""
    out = {}
    for blk in (s or {}).get("leaders") or []:
        tid = str((blk.get("team") or {}).get("id"))
        ids = set()
        for cat in blk.get("leaders") or []:
            for x in (cat.get("leaders") or [])[:1]:
                ids.add(str((x.get("athlete") or {}).get("id")))
        out[tid] = ids
    return out


def predictor_from_summary(s):
    p = (s or {}).get("predictor")
    if not p:
        return None
    try:
        h = _f((p.get("homeTeam") or {}).get("gameProjection"))
        a = _f((p.get("awayTeam") or {}).get("gameProjection"))
        if h is None:
            return None
        return {"home": h / 100.0, "away": (a / 100.0) if a is not None else 1 - h / 100.0,
                "home_id": str((p.get("homeTeam") or {}).get("id"))}
    except Exception:
        return None


def odds_from_summary(s):
    for o in (s or {}).get("pickcenter") or []:
        po = parse_odds(o)
        if po:
            return po
    return None


def event_from_summary(lk, s):
    """Build a game dict (same shape as parse_event) from a summary payload."""
    h = (s or {}).get("header") or {}
    c = (h.get("competitions") or [{}])[0]
    fake = {"id": h.get("id"), "name": None, "date": c.get("date"), "status": c.get("status"),
            "competitions": [{"competitors": c.get("competitors"), "neutralSite": c.get("neutralSite"), "status": c.get("status")}]}
    g = parse_event(lk, fake)
    if g.get("home") and g.get("away"):
        g["name"] = f"{g['away']['name']} at {g['home']['name']}"
    g["odds"] = odds_from_summary(s)
    return g


def find_game(lk, query, date=None, days=4):
    """Find event by id or team text on date (default: today .. +days)."""
    q = str(query).strip()
    if q.isdigit() and len(q) >= 6:
        s = summary(lk, q)
        return (event_from_summary(lk, s), s) if s else (None, None)
    ql = q.lower()
    start = dt.datetime.strptime(norm_date(date), "%Y%m%d")
    for i in range(0 if date else -1, (1 if date else days + 1)):
        dstr = (start + dt.timedelta(days=i)).strftime("%Y%m%d")
        gs = games(lk, dstr) or []
        for g in gs:
            if g.get("field"):
                continue
            hay = " ".join(str(x).lower() for side in ("home", "away") if g.get(side)
                           for x in (g[side]["abbr"], g[side]["name"], g[side]["short"]))
            if ql in hay or ql in (g.get("name") or "").lower():
                if i == -1 and g["status"].get("state") == "post" and not date:
                    continue
                s = summary(lk, g["id"])
                if s and not g.get("odds"):
                    g["odds"] = odds_from_summary(s)
                return g, s
    return None, None


def search_player(name, lk=None):
    d = get_json(WEB + "search/v2", {"query": name, "limit": 10, "type": "player"}, ttl=86400)
    out = []
    for blk in (d or {}).get("results") or []:
        if blk.get("type") != "player":
            continue
        for c in blk.get("contents") or []:
            uid = c.get("uid", "")
            web = (c.get("link") or {}).get("web", "")
            aid = uid.split("a:")[-1] if "a:" in uid else None
            out.append({"id": aid, "name": c.get("displayName"), "team": c.get("subtitle"), "league_desc": c.get("description"), "web": web})
    if lk:
        slug = LEAGUES[lk]["path"].split("/")[1]
        if LEAGUES[lk]["path"].startswith("soccer/"):
            slug = "soccer"
        pref = [p for p in out if f"/{slug}/player" in p["web"]]
        if pref:
            return pref
    return out


def gamelog(lk, athlete_id, season=None):
    p = {"season": season} if season else None
    return get_json(WEB + "common/v3/sports/" + LEAGUES[lk]["path"] + f"/athletes/{athlete_id}/gamelog", p, ttl=3 * 3600)


def parallel(fn, items, workers=6):
    with ThreadPoolExecutor(max_workers=workers) as ex:
        return list(ex.map(fn, items))


def league_scoring_avg(lk):
    """Average points/goals per team per game this season from ESPN standings (None if unavailable/thin)."""
    d = standings(lk)
    if not d:
        return None
    def ents(n):
        out = list((n.get("standings") or {}).get("entries") or [])
        for c in n.get("children") or []:
            out += ents(c)
        return out
    pf = gp = 0.0
    for e in ents(d):
        st = {x.get("name"): x.get("value") for x in e.get("stats") or []}
        g = st.get("gamesPlayed") or sum(st.get(k) or 0 for k in ("wins", "losses", "ties", "otLosses"))
        if g and st.get("pointsFor") is not None:
            pf += st["pointsFor"]; gp += g
    return pf / gp if gp >= 30 else None
