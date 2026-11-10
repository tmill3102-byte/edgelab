"""Extra pre-game features for the backtest, each computed only from information dated before the game.
NHL starting goalies, MLB probable pitchers, NFL starting-QB changes. Each returns (adj_margin, adj_total, notes)."""
import datetime as dt, json, os
from collections import defaultdict, deque
HERE = os.path.dirname(os.path.abspath(__file__)); DATA = os.path.join(HERE, "data")


def _parse(s):
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))


class NHLGoalies:
    """mode='actual': the goalie who actually started (normally confirmed ~1h before puck drop; small look-ahead risk on
    late scratches). mode='projected': what the live app can know in the morning: the team's previous starter, or on the
    second night of a back-to-back the team's other most-used goalie."""
    def __init__(self, w=1.0, K=800, mode="actual", shots=28.0):
        self.w, self.K, self.mode, self.shots = w, K, mode, shots
        self.by_key = {}
        for l in open(os.path.join(DATA, "nhl_goalies.jsonl")):
            r = json.loads(l)
            if r.get("hs") is None: continue
            self.by_key.setdefault((r["hs"], r["as"]), []).append(r)
        self.gs = defaultdict(lambda: [0.0, 0.0])      # goalie -> [shots, saves]
        self.lg = [0.0, 0.0]
        self.team_starts = defaultdict(lambda: deque(maxlen=10))   # espn team id -> recent starter ids
        self.last_date = {}
        self.season = None

    def match(self, g):
        cands = self.by_key.get((int(g["home"]["score"]), int(g["away"]["score"])), [])
        t = g["when"]
        best = [c for c in cands if c.get("start") and abs((_parse(c["start"]) - t).total_seconds()) < 4 * 3600]
        return best[0] if len(best) == 1 else None

    def q(self, gid):
        sh, sv = self.gs[gid]
        lg = self.lg[1] / self.lg[0] if self.lg[0] > 1000 else 0.900
        return (sv + lg * self.K) / (sh + self.K) - lg

    def starter(self, r, side):
        for x in r.get(side + "_goalies") or []:
            if x["starter"]: return x["id"]
        return None

    def projected(self, tid, when):
        hist = list(self.team_starts[tid])
        if not hist: return None
        last = hist[-1]
        ld = self.last_date.get(tid)
        if ld and (when - ld).total_seconds() < 1.6 * 86400:
            others = [x for x in hist if x != last]
            if others: return max(set(others), key=others.count)
        return last

    def pre(self, g):
        if self.season != g["season"]:
            if self.season is not None:
                for k in self.gs: self.gs[k] = [self.gs[k][0] * 0.5, self.gs[k][1] * 0.5]
            self.season = g["season"]
        r = self.match(g); g["_nhl"] = r
        if not r or not self.w: return 0.0, 0.0, []
        adj, notes = {}, []
        for side in ("home", "away"):
            tid = g[side]["id"]
            st = self.starter(r, side) if self.mode == "actual" else self.projected(tid, g["when"])
            hist = list(self.team_starts[tid])
            if st is None or not hist: adj[side] = 0.0; continue
            base = sum(self.q(x) for x in hist) / len(hist)
            adj[side] = self.w * self.shots * (self.q(st) - base)
        return adj["home"] - adj["away"], -(adj["home"] + adj["away"]), notes

    def post(self, g):
        r = g.get("_nhl")
        if not r: return
        for side in ("home", "away"):
            for x in r.get(side + "_goalies") or []:
                self.gs[x["id"]][0] += x["shots"]; self.gs[x["id"]][1] += x["saves"]
                self.lg[0] += x["shots"]; self.lg[1] += x["saves"]
            st = self.starter(r, side)
            if st: self.team_starts[g[side]["id"]].append(st)
            self.last_date[g[side]["id"]] = g["when"]


class MLBPitchers:
    """Probable starters from statsapi schedule (announced before the game). Pitcher quality = FIP-style rate per batter
    faced from game logs dated strictly before the game (this + last season, last season half weight), shrunk to league."""
    def __init__(self, w=1.0, K=300, adj_in_update=True):
        self.w, self.K, self.adj_in_update = w, K, adj_in_update
        self.sched = {}
        for l in open(os.path.join(DATA, "mlb_sched.jsonl")):
            r = json.loads(l)
            self.sched.setdefault((r["home"]["team"], r["away"]["team"], r["home"]["score"], r["away"]["score"]), []).append(r)
        logs = json.load(open(os.path.join(DATA, "mlb_pitchlogs.json")))
        self.logs = {}
        tot = [0.0, 0.0]
        for pid, rows in logs.items():
            seen, lst = set(), []
            for x in rows:
                if not x.get("bf") or not x.get("date") or (x["pk"], x["date"]) in seen: continue
                seen.add((x["pk"], x["date"]))
                v = 13 * (x["hr"] or 0) + 3 * ((x["bb"] or 0) + (x["hbp"] or 0)) - 2 * (x["k"] or 0)
                lst.append((x["date"], v, x["bf"])); tot[0] += v; tot[1] += x["bf"]
            self.logs[pid] = sorted(lst)
        self.lg = tot[0] / tot[1]

    def match(self, g):
        k = (g["home"]["name"], g["away"]["name"], int(g["home"]["score"]), int(g["away"]["score"]))
        c = [r for r in self.sched.get(k, []) if abs((_parse(r["date"]) - g["when"]).total_seconds()) < 36 * 3600]
        return c[0] if len(c) == 1 else None

    def rating(self, pid, date, season):
        """Runs above average per start (positive = worse pitcher); same formula as the live engine."""
        from betlib.mlb_pitchers import runs_above_avg
        return runs_above_avg(self.logs.get(str(pid), []), date, season, self.lg, self.K)

    def pre(self, g):
        r = self.match(g); g["_mlb"] = r
        if not r or not self.w: return 0.0, 0.0, []
        date = g["date"][:10]
        R = {}
        for side in ("home", "away"):
            pid = r[side].get("pp")
            R[side] = self.rating(pid, date, g["season"]) if pid else 0.0
        return self.w * (R["away"] - R["home"]), self.w * (R["home"] + R["away"]), []

    def post(self, g):
        pass


class NFLQB:
    """Starting-QB change: if a team's starter (most pass attempts) differs from the QB who started its previous game
    this season, that team's margin is reduced by `q` points. Starters are known pre-game in practice (injury reports /
    depth charts), which is what the live engine's QB-out adjustment uses."""
    def __init__(self, q=0.0):
        self.q = q
        self.qb = {}
        for l in open(os.path.join(DATA, "nfl_qb.jsonl")):
            r = json.loads(l); self.qb[r["id"]] = r
        self.last = {}

    def pre(self, g):
        r = self.qb.get(g["id"]) or {}
        adj = 0.0; notes = []
        for side, sgn in (("home", 1), ("away", -1)):
            tid = g[side]["id"]; cur = (r.get(tid) or {}).get("id")
            prev = self.last.get((tid, g["season"]))
            if cur and prev and cur != prev:
                adj -= sgn * self.q; notes.append(f"{side} QB change")
        return adj, 0.0, notes

    def post(self, g):
        r = self.qb.get(g["id"]) or {}
        for side in ("home", "away"):
            tid = g[side]["id"]; cur = (r.get(tid) or {}).get("id")
            if cur: self.last[(tid, g["season"])] = cur


from betlib.ratings import NBAPace  # shared with the live engine
