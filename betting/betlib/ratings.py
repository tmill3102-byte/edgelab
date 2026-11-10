"""v2 team ratings: margin (Elo-style, opponent-adjusted by construction) + team-total ratings,
with season carry-over, capped margin of victory, early-season learning boost, home edge and rest.

The same RatingBook is used by the backtest (backtest/harness.py) and the live engine (analysis.py), so
the numbers reported in BACKTEST.md are produced by exactly this code. Parameters per league were tuned
on the first backtest season only (see BACKTEST.md) and are stored in PARAMS.
"""
import math, datetime as dt
from .models import phi, poisson_pmf

# m_k: margin learning rate, early: extra learning for a team's first games of a season (K*(1+early/(n+1)))
# carry: fraction of last season's rating kept, cap: MOV cap, hfa: home edge (points/goals), sd: margin s.d.
# t_k: team-total learning rate, t_carry, tsd: total s.d., b2b: back-to-back penalty, rest: pts per rest-day diff (football)
# new: starting margin rating for a team never seen before (FCS teams in CFB), a_lr: league scoring EWMA rate
PARAMS = {
    "nba": dict(m_k=0.045, early=2.0, carry=0.6, cap=25, hfa=1.5, sd=12.5, t_k=0.1, t_carry=0.3, tsd=19.32, b2b=3.5, rest=0.0, new=0.0, a_lr=0.001),
    "nhl": dict(m_k=0.0133, early=0.5, carry=0.9, cap=10.64, hfa=0.4, sd=2.4, t_k=0.0037, t_carry=0.0, tsd=2.31, b2b=0.35, rest=0.0, new=0.0, a_lr=0.0013, ot_home=0.5),
    "nfl": dict(m_k=0.1, early=0.5, carry=0.9, cap=21, hfa=1.5, sd=13.5, t_k=0.12, t_carry=0.9, tsd=13.82, b2b=0.0, rest=0.0, new=0.0, a_lr=0.0075),
    "cfb": dict(m_k=0.18, early=1.0, carry=0.9, cap=49.5, hfa=3.325, sd=15.5, t_k=0.0798, t_carry=0.6, tsd=16.12, b2b=0.0, rest=0.0, new=-35.0, a_lr=0.0025),
    "mlb": dict(m_k=0.0075, early=0.0, carry=0.9, cap=5, hfa=0.3, sd=4.3, t_k=0.015, t_carry=0.6, tsd=4.56, b2b=0.0, rest=0.0, new=0.0, a_lr=0.0025, ot_home=0.52),
}
GOALS = {"nhl", "mlb"}
INIT_AVG = {"nba": 228.0, "nhl": 6.1, "nfl": 45.0, "cfb": 52.0, "mlb": 8.8}


def _season_of(g):
    return g.get("season")


class RatingBook:
    def __init__(self, lk, params=None):
        self.lk = lk
        self.p = dict(PARAMS[lk], **(params or {}))
        self.r, self.t, self.n, self.season, self.last = {}, {}, {}, {}, {}
        self.avg = INIT_AVG[lk]

    def _roll(self, tid, season):
        if tid not in self.r:
            self.r[tid] = self.p["new"]; self.t[tid] = 0.0; self.n[tid] = 0; self.season[tid] = season
            return
        if self.season.get(tid) != season:
            self.r[tid] *= self.p["carry"]; self.t[tid] *= self.p["t_carry"]; self.n[tid] = 0; self.season[tid] = season

    def rest_days(self, tid, when):
        lst = self.last.get(tid)
        if not lst or not when:
            return None
        return (when - lst).total_seconds() / 86400.0

    def predict(self, home, away, when=None, neutral=False, season=None, adj_m=0.0, adj_t=0.0, why=None):
        """Expected home margin and game total using only games already passed to update()."""
        p = self.p
        for tid in (home, away):
            if season is not None:
                self._roll(tid, season)
            elif tid not in self.r:
                self._roll(tid, None)
        rh, ra = self.r[home], self.r[away]
        hfa = 0.0 if neutral else p["hfa"]
        adj, notes = 0.0, []
        rest_h, rest_a = self.rest_days(home, when), self.rest_days(away, when)
        if p["b2b"]:
            if rest_h is not None and rest_h < 1.6: adj -= p["b2b"]; notes.append("home b2b")
            if rest_a is not None and rest_a < 1.6: adj += p["b2b"]; notes.append("away b2b")
        if p["rest"] and rest_h is not None and rest_a is not None:
            d = max(-7.0, min(7.0, rest_h - rest_a))
            adj += p["rest"] * d
        if adj_m or adj_t:
            notes += list(why or [])
        adj += adj_m
        margin = rh - ra + hfa + adj
        total = self.avg + self.t[home] + self.t[away] + adj_t
        return {"margin": margin, "total": total, "r_home": rh, "r_away": ra, "hfa": hfa, "adj": adj, "notes": notes,
                "n_home": self.n[home], "n_away": self.n[away], "rest_home": rest_h, "rest_away": rest_a}

    def update(self, home, away, hs, as_, when=None, neutral=False, season=None, adj_m=0.0, adj_t=0.0):
        pr = self.predict(home, away, when, neutral, season, adj_m, adj_t)
        p = self.p
        m = max(-p["cap"], min(p["cap"], hs - as_))
        err = m - pr["margin"]
        for tid, sgn in ((home, 1), (away, -1)):
            k = p["m_k"] * (1 + p["early"] / (self.n[tid] + 1))
            self.r[tid] += sgn * k * err
        et = (hs + as_) - pr["total"]
        for tid in (home, away):
            k = p["t_k"] * (1 + p["early"] / (self.n[tid] + 1))
            self.t[tid] += k * et / 2
        self.avg += p["a_lr"] * ((hs + as_) - self.avg)
        for tid in (home, away):
            self.n[tid] += 1
            if when: self.last[tid] = when
        return pr


class NBAPace:
    """Pace proxy for totals: EWMA of each team's shot volume (FGA + 0.44*FTA, own + opponent) from the scoreboard box.
    (True possessions need turnovers/offensive rebounds, which the free scoreboard doesn't carry.)"""
    def __init__(self, w=0.0, alpha=0.1):
        self.w, self.alpha = w, alpha
        self.p = {}; self.lg = None

    def _vol(self, g):
        try:
            return (g["home"]["fga"] + 0.44 * g["home"]["fta"]) + (g["away"]["fga"] + 0.44 * g["away"]["fta"])
        except TypeError:
            return None

    def pre(self, g):
        if not self.w or self.lg is None: return 0.0, 0.0, []
        ph = self.p.get(g["home"]["id"], self.lg); pa = self.p.get(g["away"]["id"], self.lg)
        # expected extra shots vs league average game, ~1.1 points per shot attempt-equivalent
        return 0.0, self.w * 1.1 * ((ph + pa) / 2 - self.lg), []

    def post(self, g):
        v = self._vol(g)
        if v is None: return
        self.lg = v if self.lg is None else self.lg + 0.01 * (v - self.lg)
        for s in ("home", "away"):
            t = g[s]["id"]; self.p[t] = self.p.get(t, v) + self.alpha * (v - self.p.get(t, v))

    def state(self):
        return {"p": self.p, "lg": self.lg}

    def load(self, st):
        self.p = dict(st.get("p") or {}); self.lg = st.get("lg")


# Extra features adopted after the backtest (chosen on the train season, kept only if out-of-sample better)
FEATURES = {"nba": ("NBAPace", {"w": 0.5})}


def make_feature(lk):
    cfg = FEATURES.get(lk)
    if not cfg: return None
    return globals()[cfg[0]](**cfg[1])


# ---------------- probabilities from a prediction ----------------
def _grid(margin, total, mx):
    lh = max(0.2, (total + margin) / 2); la = max(0.2, (total - margin) / 2)
    ph = [poisson_pmf(i, lh) for i in range(mx)]; pa = [poisson_pmf(j, la) for j in range(mx)]
    return [[ph[i] * pa[j] for j in range(mx)] for i in range(mx)], lh, la


def probs(lk, pred, spread_home=None, total_line=None):
    """Return dict p_home (win incl. OT), p_home_cover (no-push), p_over (no-push) and push probs."""
    p = PARAMS[lk]
    out = {}
    if lk in GOALS:
        mx = 25 if lk == "mlb" else 14
        g, lh, la = _grid(pred["margin"], pred["total"], mx)
        out.update(lam_home=lh, lam_away=la)
        ph = sum(g[i][j] for i in range(mx) for j in range(mx) if i > j)
        pd = sum(g[i][i] for i in range(mx))
        out["p_home"] = ph + pd * p.get("ot_home", 0.5)
        out["p_draw_reg"] = pd
        if spread_home is not None:
            w = ps = 0.0
            for i in range(mx):
                for j in range(mx):
                    v = i - j + spread_home
                    if abs(v) < 1e-9: ps += g[i][j]
                    elif v > 0: w += g[i][j]
            out["p_home_cover"] = w / (1 - ps) if ps < 1 else None; out["push_spread"] = ps
        if total_line is not None:
            o = ps = 0.0
            for i in range(mx):
                for j in range(mx):
                    if abs(i + j - total_line) < 1e-9: ps += g[i][j]
                    elif i + j > total_line: o += g[i][j]
            out["p_over"] = o / (1 - ps) if ps < 1 else None; out["push_total"] = ps
        return out
    sd, tsd = p["sd"], p["tsd"]
    out["p_home"] = phi(pred["margin"] / sd)
    if spread_home is not None:
        out["p_home_cover"] = phi((pred["margin"] + spread_home) / sd)
    if total_line is not None:
        out["p_over"] = phi((pred["total"] - total_line) / tsd)
    return out


# ---------------- market blend / calibration ----------------
# Final probability = sigmoid((1-b)*logit(market_novig) + b*logit(model)). b per league/market comes from the
# walk-forward backtest (backtest/report.py writes betlib/data/blend.json). Markets where the model did not earn
# weight out of sample get b = 0 (final = market), and can never be tiered above Low ("enabled": false).
import json as _json, os as _os
_BLEND_PATH = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "data", "blend.json")
try:
    BLEND = _json.load(open(_BLEND_PATH))
except Exception:
    BLEND = {}
TIERS = {"high_ev": 0.03, "med_ev": 0.01}   # backtest-retuned: EV at the offered price using the blended probability
MNAMES = {"ml": "moneyline", "sp": "spread", "tot": "total"}


def logit(p):
    p = min(max(p, 1e-6), 1 - 1e-6)
    return math.log(p / (1 - p))


def sigmoid(x):
    return 1 / (1 + math.exp(-x))


def enabled(lk, market):
    return bool(BLEND.get(lk, {}).get(market, {}).get("enabled"))


def blend(lk, market, p_market, p_model):
    c = BLEND.get(lk, {}).get(market)
    if p_market is None or p_model is None:
        return None
    b = c.get("b", 0.0) if c and c.get("enabled") else 0.0
    return sigmoid((1 - b) * logit(p_market) + b * logit(p_model))


def blend_note(lk, market):
    c = BLEND.get(lk, {}).get(market) or {}
    if c.get("enabled"):
        return (f"Backtest ({c.get('basis')}): model gets {c['b']*100:.0f}% weight vs the market in log-odds for {lk.upper()} {MNAMES[market]}s; "
                f"{c.get('why', '')}".strip())
    return (f"Backtest: the model showed no out-of-sample edge over the market for {lk.upper()} {MNAMES[market]}s, so the final % = market "
            f"no-vig and this can't rate above Low. Raw model lean shown for context only.")
