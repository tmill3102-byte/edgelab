"""Each NFL team's primary passer per game (most pass attempts) from ESPN summary box scores. Output data/nfl_qb.jsonl"""
import json, os
from concurrent.futures import ThreadPoolExecutor
from backtest import fetch as F


def main():
    ids = []
    for fn in ("nfl_warm.jsonl", "nfl.jsonl"):
        ids += [json.loads(l)["id"] for l in open(os.path.join(F.DATA, fn))]
    def one(i):
        s = F.get(F.SITE + "football/nfl/summary", {"event": i})
        out = {"id": i}
        for tb in ((s or {}).get("boxscore") or {}).get("players") or []:
            tid = str((tb.get("team") or {}).get("id"))
            for st in tb.get("statistics") or []:
                if st.get("name") != "passing": continue
                keys = st.get("keys") or []
                best = None
                for a in st.get("athletes") or []:
                    try:
                        ca = a["stats"][keys.index("completions/passingAttempts")]; att = int(ca.split("/")[1])
                    except Exception:
                        att = 0
                    if best is None or att > best["att"]:
                        best = {"id": str(a["athlete"]["id"]), "name": a["athlete"].get("displayName"), "att": att}
                out[tid] = best
        return out
    with ThreadPoolExecutor(6) as ex:
        res = list(ex.map(one, ids))
    with open(os.path.join(F.DATA, "nfl_qb.jsonl"), "w") as f:
        for r in res: f.write(json.dumps(r) + "\n")
    print("wrote", len(res), flush=True)


if __name__ == "__main__":
    main()
