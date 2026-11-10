"""League registry. kind: pts (margin/normal model), goals (Poisson model), field (tennis/golf/mma/racing: listing only)."""

# key: dict(path, name, kind, params...)
#  hfa = home advantage in points (pts) or multiplicative lambda factor (goals)
#  sd = st.dev. of final margin; tsd = st.dev. of game total; k = shrink games; avg = league avg goals/runs per team
LEAGUES = {
    "nfl":   dict(path="football/nfl", name="NFL", kind="pts", hfa=1.7, sd=13.5, tsd=13.0, k=4, inj="nfl"),
    "cfb":   dict(path="football/college-football", name="College Football (FBS)", kind="pts", hfa=2.5, sd=16.0, tsd=16.0, k=4, groups="80"),
    "nba":   dict(path="basketball/nba", name="NBA", kind="pts", hfa=2.3, sd=12.5, tsd=18.0, k=10, b2b=1.5),
    "wnba":  dict(path="basketball/wnba", name="WNBA", kind="pts", hfa=2.0, sd=11.5, tsd=16.0, k=8, b2b=1.0),
    "ncaab": dict(path="basketball/mens-college-basketball", name="Men's College Basketball", kind="pts", hfa=3.0, sd=11.0, tsd=15.0, k=6, groups="50"),
    "ncaaw": dict(path="basketball/womens-college-basketball", name="Women's College Basketball", kind="pts", hfa=3.0, sd=12.0, tsd=15.0, k=6, groups="50"),
    "mlb":   dict(path="baseball/mlb", name="MLB", kind="goals", hfa=1.03, avg=4.4, k=20, maxgoals=20),
    "nhl":   dict(path="hockey/nhl", name="NHL", kind="goals", hfa=1.04, avg=3.05, k=10, ot=True, b2b=0.06),
    # soccer
    "epl":   dict(path="soccer/eng.1", name="Premier League", kind="goals", hfa=1.15, avg=1.40, k=6, draw=True),
    "efl":   dict(path="soccer/eng.2", name="EFL Championship", kind="goals", hfa=1.15, avg=1.30, k=6, draw=True),
    "laliga":dict(path="soccer/esp.1", name="La Liga", kind="goals", hfa=1.15, avg=1.30, k=6, draw=True),
    "seriea":dict(path="soccer/ita.1", name="Serie A", kind="goals", hfa=1.15, avg=1.35, k=6, draw=True),
    "bundesliga":dict(path="soccer/ger.1", name="Bundesliga", kind="goals", hfa=1.15, avg=1.55, k=6, draw=True),
    "ligue1":dict(path="soccer/fra.1", name="Ligue 1", kind="goals", hfa=1.15, avg=1.35, k=6, draw=True),
    "eredivisie":dict(path="soccer/ned.1", name="Eredivisie", kind="goals", hfa=1.15, avg=1.55, k=6, draw=True),
    "primeira":dict(path="soccer/por.1", name="Primeira Liga", kind="goals", hfa=1.15, avg=1.30, k=6, draw=True),
    "mls":   dict(path="soccer/usa.1", name="MLS", kind="goals", hfa=1.2, avg=1.50, k=6, draw=True),
    "ligamx":dict(path="soccer/mex.1", name="Liga MX", kind="goals", hfa=1.2, avg=1.40, k=6, draw=True),
    "brasileirao":dict(path="soccer/bra.1", name="Brasileirao", kind="goals", hfa=1.2, avg=1.25, k=6, draw=True),
    "argentina":dict(path="soccer/arg.1", name="Liga Profesional (ARG)", kind="goals", hfa=1.2, avg=1.15, k=6, draw=True),
    "scotland":dict(path="soccer/sco.1", name="Scottish Premiership", kind="goals", hfa=1.15, avg=1.40, k=6, draw=True),
    "ucl":   dict(path="soccer/uefa.champions", name="UEFA Champions League", kind="goals", hfa=1.12, avg=1.50, k=4, draw=True),
    "uel":   dict(path="soccer/uefa.europa", name="UEFA Europa League", kind="goals", hfa=1.12, avg=1.40, k=4, draw=True),
    "uecl":  dict(path="soccer/uefa.europa.conf", name="UEFA Conference League", kind="goals", hfa=1.12, avg=1.40, k=4, draw=True),
    "nations":dict(path="soccer/uefa.nations", name="UEFA Nations League", kind="goals", hfa=1.10, avg=1.30, k=4, draw=True),
    "friendly":dict(path="soccer/fifa.friendly", name="International Friendlies", kind="goals", hfa=1.08, avg=1.30, k=4, draw=True),
    "concacaf":dict(path="soccer/concacaf.nations.league", name="CONCACAF Nations League", kind="goals", hfa=1.12, avg=1.30, k=4, draw=True),
    "nwsl":  dict(path="soccer/usa.nwsl", name="NWSL", kind="goals", hfa=1.15, avg=1.35, k=6, draw=True),
    # field / individual sports: schedule listing only (ESPN exposes no odds for these)
    "atp":   dict(path="tennis/atp", name="ATP Tennis", kind="field"),
    "wta":   dict(path="tennis/wta", name="WTA Tennis", kind="field"),
    "pga":   dict(path="golf/pga", name="PGA Tour", kind="field"),
    "lpga":  dict(path="golf/lpga", name="LPGA", kind="field"),
    "ufc":   dict(path="mma/ufc", name="UFC", kind="field"),
    "f1":    dict(path="racing/f1", name="Formula 1", kind="field"),
}

ALIASES = {"ncaaf": "cfb", "cbb": "ncaab", "ncaam": "ncaab", "premier": "epl", "pl": "epl", "soccer": "soccer",
           "championsleague": "ucl", "tennis": "tennis", "golf": "pga", "mma": "ufc", "nationsleague": "nations"}
GROUPS = {
    "soccer": [k for k, v in LEAGUES.items() if v["path"].startswith("soccer/")],
    "tennis": ["atp", "wta"],
    "golf": ["pga", "lpga"],
    "college": ["cfb", "ncaab", "ncaaw"],
    "us": ["nfl", "nba", "mlb", "nhl", "wnba", "cfb", "ncaab"],
}


def resolve(name):
    """Return list of league keys for a user string (league, group, or 'all')."""
    n = (name or "all").lower().replace(" ", "").replace("-", "")
    n = ALIASES.get(n, n)
    if n == "all":
        return list(LEAGUES)
    if n in GROUPS:
        return GROUPS[n]
    if n in LEAGUES:
        return [n]
    for k, v in LEAGUES.items():
        if n in v["path"].replace("-", "") or n in v["name"].lower().replace(" ", ""):
            return [k]
    raise SystemExit(f"Unknown sport/league '{name}'. Options: all, {', '.join(list(GROUPS) + list(LEAGUES))}")
