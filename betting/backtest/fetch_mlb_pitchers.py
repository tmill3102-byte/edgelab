"""MLB probable/starting pitchers (statsapi.mlb.com schedule hydrate=probablePitcher) + each pitcher's game logs.
Output: data/mlb_sched.jsonl (one row per game) and data/mlb_pitchlogs.json {pitcher_id: [game rows]}"""
import datetime as dt, json, os
from concurrent.futures import ThreadPoolExecutor
from backtest import fetch as F

B = "https://statsapi.mlb.com/api/v1/"
SEAS = {2024: ("2024-03-20", "2024-10-31"), 2025: ("2025-03-18", "2025-11-02"), 2026: ("2026-03-25", "2026-11-05")}


def months(a, b):
    d = dt.date.fromisoformat(a); e = dt.date.fromisoformat(b)
    while d <= e:
        nxt = min(e, (d.replace(day=28) + dt.timedelta(days=4)).replace(day=1) - dt.timedelta(days=1))
        yield d.isoformat(), nxt.isoformat(); d = nxt + dt.timedelta(days=1)


def main():
    rows, pids = [], set()
    for yr, (a, b) in SEAS.items():
        for s, e in months(a, b):
            js = F.get(B + "schedule", {"sportId": 1, "startDate": s, "endDate": e, "hydrate": "probablePitcher", "gameType": "R,F,D,L,W"})
            for d in (js or {}).get("dates") or []:
                for g in d.get("games") or []:
                    if (g.get("status") or {}).get("abstractGameState") != "Final": continue
                    r = {"pk": g["gamePk"], "season": yr, "date": g.get("gameDate"), "official": g.get("officialDate"), "type": g.get("gameType"),
                         "dh": g.get("doubleHeader"), "gn": g.get("gameNumber")}
                    for side in ("home", "away"):
                        t = g["teams"][side]
                        pp = t.get("probablePitcher") or {}
                        r[side] = {"team": t["team"]["name"], "tid": t["team"]["id"], "score": t.get("score"), "pp": pp.get("id"), "pp_name": pp.get("fullName")}
                        if pp.get("id"): pids.add((pp["id"], yr))
                    rows.append(r)
    print("mlb games", len(rows), "pitcher-seasons", len(pids), flush=True)
    logs = {}
    def gl(k):
        return k, F.get(B + f"people/{k[0]}/stats", {"stats": "gameLog", "group": "pitching", "season": k[1]})
    with ThreadPoolExecutor(6) as ex:
        for (pid, yr), js in ex.map(gl, sorted(pids)):
            for st in (js or {}).get("stats") or []:
                for sp in st.get("splits") or []:
                    s = sp.get("stat") or {}
                    logs.setdefault(str(pid), []).append({"date": sp.get("date"), "pk": (sp.get("game") or {}).get("gamePk"), "gs": s.get("gamesStarted"),
                                                          "bf": s.get("battersFaced"), "k": s.get("strikeOuts"), "bb": s.get("baseOnBalls"), "hbp": s.get("hitByPitch"),
                                                          "hr": s.get("homeRuns"), "ip": s.get("inningsPitched"), "er": s.get("earnedRuns")})
    with open(os.path.join(F.DATA, "mlb_sched.jsonl"), "w") as f:
        for r in rows: f.write(json.dumps(r) + "\n")
    json.dump(logs, open(os.path.join(F.DATA, "mlb_pitchlogs.json"), "w"))
    print("wrote", len(rows), "games;", len(logs), "pitchers", flush=True)


if __name__ == "__main__":
    main()
