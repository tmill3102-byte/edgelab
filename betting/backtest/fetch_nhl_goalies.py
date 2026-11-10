"""NHL starting goalies + shots/saves per game from api-web.nhle.com (free, official). Output data/nhl_goalies.jsonl"""
import datetime as dt, json, os
from concurrent.futures import ThreadPoolExecutor
from backtest import fetch as F

WIN = [("2023-10-10", "2024-06-25")] + F.WINDOWS["nhl"]
B = "https://api-web.nhle.com/v1/"


def main():
    days = [d for w in WIN for d in F.dates(*w)]
    games = {}
    with ThreadPoolExecutor(6) as ex:
        for d, js in zip(days, ex.map(lambda d: F.get(B + f"score/{d[:4]}-{d[4:6]}-{d[6:]}"), days)):
            for g in (js or {}).get("games") or []:
                if g.get("gameType") not in (2, 3) or g.get("gameState") not in ("OFF", "FINAL"): continue
                games[g["id"]] = {"nhl_id": g["id"], "date": g.get("gameDate"), "start": g.get("startTimeUTC"),
                                  "home": g["homeTeam"]["abbrev"], "away": g["awayTeam"]["abbrev"],
                                  "hs": g["homeTeam"].get("score"), "as": g["awayTeam"].get("score")}
    print("nhl games", len(games), flush=True)
    ids = sorted(games)
    def box(i):
        return F.get(B + f"gamecenter/{i}/boxscore")
    with ThreadPoolExecutor(6) as ex:
        for i, b in zip(ids, ex.map(box, ids)):
            pb = (b or {}).get("playerByGameStats") or {}
            for side, key in (("home", "homeTeam"), ("away", "awayTeam")):
                gl = []
                for x in (pb.get(key) or {}).get("goalies") or []:
                    sa = x.get("saveShotsAgainst") or "0/0"
                    try: sv, sh = [int(v) for v in sa.split("/")]
                    except Exception: sv, sh = 0, 0
                    gl.append({"id": x.get("playerId"), "name": (x.get("name") or {}).get("default"), "starter": bool(x.get("starter")),
                               "saves": sv, "shots": sh, "toi": x.get("toi")})
                games[i][side + "_goalies"] = gl
    with open(os.path.join(F.DATA, "nhl_goalies.jsonl"), "w") as f:
        for i in ids: f.write(json.dumps(games[i]) + "\n")
    print("wrote", len(ids), flush=True)


if __name__ == "__main__":
    main()
