"""MLB probable starting pitchers (statsapi.mlb.com, free & official) -> run adjustment per start.

Pitcher quality = FIP-style rate per batter faced, (13*HR + 3*(BB+HBP) - 2*K) / BF, from game logs dated strictly
before the game (this season + last season at half weight), shrunk toward league average with K=300 BF, converted to
runs above average over a ~5.5-inning start. Backtest (BACKTEST.md): improves out-of-sample win log loss; weight 0.5
chosen on the 2025 season. Shared by the backtest (file provider) and the live engine (HTTP provider)."""
import datetime as dt
from .net import get_json

B = "https://statsapi.mlb.com/api/v1/"
LG = 0.2424      # league average of the rate above over 2024-2026 logs (backtest/data)
W = 0.5
K = 300


def runs_above_avg(logs, date, season, lg=LG, k=K):
    """logs: list of (YYYY-MM-DD, numerator, BF) sorted by date. Positive = worse than average pitcher."""
    v = bf = 0.0
    for d, vv, b in logs:
        if d >= date: break
        wt = 1.0 if int(d[:4]) == season else (0.5 if int(d[:4]) == season - 1 else 0.0)
        v += wt * vv; bf += wt * b
    x = (v + lg * k) / (bf + k)
    return (x - lg) * 4.3 * 5.5 / 9   # FIP numerator is runs per 9 IP; ~4.3 BF per IP; ~5.5 IP per start


def adjustment(r_home, r_away, w=W):
    """(margin adj for home, total adj)."""
    return w * (r_away - r_home), w * (r_home + r_away)


# ---------------- live provider ----------------
def _logs(pid, season):
    out = []
    for yr in (season - 1, season):
        js = get_json(B + f"people/{pid}/stats", {"stats": "gameLog", "group": "pitching", "season": yr}, ttl=6 * 3600)
        for st in (js or {}).get("stats") or []:
            for sp in st.get("splits") or []:
                s = sp.get("stat") or {}
                if not s.get("battersFaced") or not sp.get("date"): continue
                out.append((sp["date"], 13 * (s.get("homeRuns") or 0) + 3 * ((s.get("baseOnBalls") or 0) + (s.get("hitByPitch") or 0)) - 2 * (s.get("strikeOuts") or 0),
                            s["battersFaced"]))
    return sorted(set(out))


def probables(date_iso, home_name, away_name, start=None):
    """Return {'home': (id, name) or None, 'away': ...} for the scheduled game (closest start time if a doubleheader)."""
    js = get_json(B + "schedule", {"sportId": 1, "date": date_iso, "hydrate": "probablePitcher"}, ttl=1800)
    best = None
    for d in (js or {}).get("dates") or []:
        for g in d.get("games") or []:
            t = g["teams"]
            if t["home"]["team"]["name"] != home_name or t["away"]["team"]["name"] != away_name: continue
            gt = g.get("gameDate")
            gap = abs((dt.datetime.fromisoformat(gt.replace("Z", "+00:00")) - start).total_seconds()) if (start and gt) else 0
            if best is None or gap < best[0]: best = (gap, g)
    if not best: return None
    g = best[1]["teams"]
    return {s: ((g[s].get("probablePitcher") or {}).get("id"), (g[s].get("probablePitcher") or {}).get("fullName")) if g[s].get("probablePitcher") else None
            for s in ("home", "away")}


def live_adjustment(when, season, home_name, away_name):
    """(adj_margin, adj_total, notes) for a live MLB game; zeros + a note when pitchers aren't announced."""
    if not when: return 0.0, 0.0, []
    local = when.astimezone(dt.timezone(dt.timedelta(hours=-5)))
    pp = probables(local.strftime("%Y-%m-%d"), home_name, away_name, when)
    if not pp or not pp.get("home") or not pp.get("away"):
        return 0.0, 0.0, ["probable pitchers not announced yet (statsapi.mlb.com): no starter adjustment"]
    date = local.strftime("%Y-%m-%d")
    r = {s: runs_above_avg(_logs(pp[s][0], season), date, season) for s in ("home", "away")}
    am, at = adjustment(r["home"], r["away"])
    notes = [f"starters: {pp['away'][1]} ({r['away']:+.2f} runs vs avg) at {pp['home'][1]} ({r['home']:+.2f}); margin {am:+.2f}, total {at:+.2f}"]
    return am, at, notes
