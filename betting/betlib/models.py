"""Models. Deliberately simple, transparent and conservative.

Pipeline per market:  raw model prob  ->  blended with market no-vig prob (shrinkage)  ->  edge / EV / tier.
Shrinkage exists because a box-score model with no lineup/market info is far weaker than a betting market;
it prevents the tool from shouting about 'edges' that are really just model error.
"""
import math, statistics, datetime as dt

# ---------------- odds math ----------------
def am_to_dec(a):
    a = float(a)
    return 1 + (a / 100.0 if a > 0 else 100.0 / -a)


def dec_to_am(d):
    if d is None or d <= 1:
        return None
    return round((d - 1) * 100) if d >= 2 else round(-100 / (d - 1))


def implied(a):
    return 1.0 / am_to_dec(a)


def prob_to_am(p):
    if not p or p <= 0 or p >= 1:
        return None
    return dec_to_am(1.0 / p)


def no_vig(odds_list):
    """Multiplicative (proportional) vig removal for 2- or 3-way markets. Returns (probs, overround)."""
    if any(o is None for o in odds_list):
        return None, None
    imp = [implied(o) for o in odds_list]
    s = sum(imp)
    return [x / s for x in imp], s - 1


def fmt_am(a):
    if a is None:
        return "n/a"
    a = int(round(a))
    return f"+{a}" if a > 0 else str(a)


def ev_per_unit(p, am):
    d = am_to_dec(am)
    return p * (d - 1) - (1 - p)


def kelly(p, am, frac=0.25, cap=0.02):
    b = am_to_dec(am) - 1
    f = (b * p - (1 - p)) / b if b > 0 else 0
    return max(0.0, min(cap, f * frac))


# ---------------- distributions ----------------
def phi(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def inv_phi(p):
    # Acklam approximation
    p = min(max(p, 1e-6), 1 - 1e-6)
    a = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02, 1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00]
    b = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02, 6.680131188771972e+01, -1.328068155288572e+01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00, -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00, 3.754408661907416e+00]
    pl = 0.02425
    if p < pl:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    if p > 1 - pl:
        q = math.sqrt(-2 * math.log(1 - p))
        return -(((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    q = p - 0.5; r = q * q
    return (((((a[0]*r+a[1])*r+a[2])*r+a[3])*r+a[4])*r+a[5])*q / (((((b[0]*r+b[1])*r+b[2])*r+b[3])*r+b[4])*r+1)


def poisson_pmf(k, lam):
    return math.exp(-lam) * lam ** k / math.factorial(k)


def normal_over(mean, sd, line):
    """P(X > line), P(push) for a continuous approx of a discrete stat (continuity-corrected)."""
    if float(line).is_integer():
        p_over = 1 - phi((line + 0.5 - mean) / sd)
        p_under = phi((line - 0.5 - mean) / sd)
        return p_over, 1 - p_over - p_under
    return 1 - phi((line - mean) / sd), 0.0


def poisson_over(lam, line):
    lam = max(lam, 0.01)
    k = math.floor(line)
    cdf = sum(poisson_pmf(i, lam) for i in range(0, k + 1))
    if float(line).is_integer():
        push = poisson_pmf(int(line), lam)
        return 1 - cdf, push
    return 1 - cdf, 0.0


# ---------------- team strength ----------------
def team_profile(results, L, game_time=None):
    """Summarize completed games -> rating inputs."""
    n = len(results)
    prof = {"n": n, "pf": None, "pa": None, "mov": None, "mov5": None, "last5": "", "rest": None}
    if n == 0:
        return prof
    pf = [r["pf"] for r in results]; pa = [r["pa"] for r in results]
    prof["pf"] = sum(pf) / n; prof["pa"] = sum(pa) / n
    prof["mov"] = prof["pf"] - prof["pa"]
    l5 = results[-5:]
    prof["mov5"] = sum(r["pf"] - r["pa"] for r in l5) / len(l5)
    prof["last5"] = "".join("W" if r["pf"] > r["pa"] else ("L" if r["pf"] < r["pa"] else "D") for r in l5)
    prof["pf5"] = sum(r["pf"] for r in l5) / len(l5); prof["pa5"] = sum(r["pa"] for r in l5) / len(l5)
    if game_time and results[-1]["date"]:
        prof["rest"] = (game_time - results[-1]["date"]).total_seconds() / 86400.0
    return prof


def pts_rating(prof, L):
    """Points-per-game margin rating, recent-form blended and shrunk to 0 by k pseudo-games."""
    if not prof["n"]:
        return 0.0
    base = prof["mov"] if prof["n"] < 5 else 0.7 * prof["mov"] + 0.3 * prof["mov5"]
    return base * prof["n"] / (prof["n"] + L["k"])


def goals_rates(prof, L):
    """Attack & defence rates (goals per game) shrunk to league average."""
    avg, k, n = L["avg"], L["k"], prof["n"]
    if not n:
        return avg, avg
    gf = (prof["pf"] * n + avg * k) / (n + k)
    ga = (prof["pa"] * n + avg * k) / (n + k)
    return gf, ga


# ---------------- tiers ----------------
def quality(flags):
    """flags: list of strings describing data gaps. Map to High/Medium/Low data quality."""
    hard = [f for f in flags if f.startswith("!")]
    if hard or len(flags) >= 3:
        return "Low"
    if flags:
        return "Medium"
    return "High"


def tier(edge, ev, dq, dec):
    if edge is None or ev is None:
        return "Low"
    t = "Low"
    if edge >= 0.04 and ev >= 0.05 and dq == "High":
        t = "High"
    elif edge >= 0.02 and ev >= 0.02 and dq in ("High", "Medium"):
        t = "Medium"
    if t == "High" and dec > 5.0:  # long shots: variance + model error dominate
        t = "Medium"
    return t


DOWN = {"High": "Medium", "Medium": "Low", "Low": "Low"}


def make_pick(market, selection, side, line, odds, model_raw, market_p, weight, dq, reasons, flags, push=0.0,
              caution=None, against=None, blended=None, tier_fn=None, far_downgrade=True):
    """Blend model with market, compute edge/EV/Kelly/tier.
    v2 callers pass `blended` (backtest-fitted market blend, betlib/ratings.py) and `tier_fn` (backtest-retuned tiers)."""
    if odds is None or market_p is None:
        return None
    if blended is None:
        blended = weight * model_raw + (1 - weight) * market_p
    # EV accounting for pushes (push returns stake)
    d = am_to_dec(odds)
    p_win = blended * (1 - push)
    p_loss = (1 - blended) * (1 - push)
    ev = p_win * (d - 1) - p_loss
    edge = blended - market_p
    k = kelly(blended, odds) if ev > 0 else 0.0
    t0 = tier_fn(edge, ev, dq, d) if tier_fn else tier(edge, ev, dq, d)
    t = t0
    caution = list(caution or [])
    far_note = None
    if abs(model_raw - market_p) > 0.12:
        msg = f"model far from market ({model_raw*100:.0f}% vs {market_p*100:.0f}%): usually means the model is missing info (lineups, motivation, SOS)"
        if far_downgrade:
            caution.append(msg)
        else:   # v2: backtest showed these picks were not worse vs the closing line, so note it without a downgrade
            far_note = "Note: " + msg + " (no tier downgrade in v2: backtested picks like this did not do worse against the closing line)."
    for c in caution:            # each caution downgrades one tier
        t = DOWN[t]
    if t != t0:
        caution.append(f"downgraded {t0} -> {t}")
    if far_note:
        reasons = list(reasons) + [far_note]
    edge_price = blended - implied(odds)   # vs the actual price you'd pay (vig included)
    return {"market": market, "selection": selection, "side": side, "line": line, "odds": odds,
            "model_raw": round(model_raw, 4), "model_prob": round(blended, 4), "market_prob": round(market_p, 4),
            "fair_odds": prob_to_am(blended), "edge": round(edge, 4), "edge_at_price": round(edge_price, 4), "ev": round(ev, 4), "kelly_pct": round(k * 100, 2),
            "stake_units": round(k * 100, 2) if t != "Low" else 0.0, "tier": t, "data_quality": dq,
            "reasons": reasons, "flags": flags, "caution": caution, "case_against": against or "Market consensus prices this differently; a simple public-data model is usually the one that is wrong.",
            "push_prob": round(push, 4)}
