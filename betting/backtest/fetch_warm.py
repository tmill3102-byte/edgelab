"""Warm-up season (scores only, no odds) so ratings enter the first backtest season with carried-over history."""
import json, os, sys
from backtest import fetch as F
F.GAP = 0.12
WARM = {"nba": [("2023-10-24", "2024-06-18")], "nhl": [("2023-10-10", "2024-06-25")],
        "nfl": [("2023-09-07", "2024-02-12")], "cfb": [("2023-08-26", "2024-01-09")], "mlb": [("2024-03-20", "2024-10-31")]}
for lk in sys.argv[1:]:
    F.WINDOWS[lk] = WARM[lk]
    evs = F.events_for(lk)
    with open(os.path.join(F.DATA, f"{lk}_warm.jsonl"), "w") as f:
        for g in evs:
            g["odds"] = None; f.write(json.dumps(g) + "\n")
    print(f"[{lk}] warm-up {len(evs)} games", flush=True)
