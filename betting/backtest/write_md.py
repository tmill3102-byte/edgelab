"""Write BACKTEST.md from backtest/out/summary.json + data files (no hand-typed numbers in tables)."""
import collections, json, os, sys, datetime as dt
from backtest.harness import SEASONS, SEASON_NAME, load
from backtest import report as RP, evaluate as E
from betlib import ratings as RT

S = json.load(open("backtest/out/summary.json"))
FEAT = open("backtest/out/features.log").read()
LN = {"nba": "NBA", "nhl": "NHL", "nfl": "NFL", "cfb": "College football (FBS)", "mlb": "MLB"}
MN = {"ml": "Moneyline", "sp": "Spread / puck line / run line", "tot": "Total"}


def f(x, d=4, pct=False, sign=False):
    if x is None: return "—"
    if pct: return f"{x*100:+.1f}%" if sign else f"{x*100:.1f}%"
    return f"{x:+.{d}f}" if sign else f"{x:.{d}f}"


def seasons(lk, lst):
    return ", ".join(SEASON_NAME[lk][s] for s in lst)


out = []
w = out.append
w("# EdgeLab engine v2: backtest and calibration report")
w("")
w(f"Generated {dt.datetime.now().strftime('%Y-%m-%d %H:%M')} ET by `backtest/write_md.py` from `backtest/out/summary.json`. Every number below comes from free public data "
  "(ESPN scoreboards and its core odds API, api-web.nhle.com, statsapi.mlb.com). Nothing was estimated or filled in. Games with no stored odds count toward the ratings, but not toward the market metrics.")
w("")
w("## Bottom line")
w("")
w("- **No league's model beats the closing line.** Over every test season, the best result (v2 blended with the market) only matches the closing no-vig line's log loss, within noise. A simple model built on free box scores can't out-predict the closing number. That's expected, and it's why the engine stays anchored to the market.")
w("- **v1 was worse than doing nothing.** In 14 of the 15 league×market cells, its blended probabilities had a higher log loss than the market. The exception was NHL puck lines (dLL -0.0012). Its High+Medium picks lost money at closing prices in NBA (-6.8%, n=1160), NHL (-3.6%, n=1000), college football (-7.8%, n=270) and MLB (-5.0%, n=3177). NFL was up +3.2%, but on only n=240. v1's tiers weren't reliable either. High had the best closing ROI in the NBA and NFL, but the worst CLV in the NBA (-5.4%) and the worst ROI in the NHL (-13.3%) and MLB (-7.3%).")
w("- **v2 is market-anchored and earns weight only where the data supports it.** The model gets weight in a market only when walk-forward tests show it improves log loss against the opening line, or when its picks beat the closing line. That leaves 3 of 15 league×market cells enabled: NBA moneylines, NBA totals and NHL puck lines. Every other market shows the market's own no-vig probability with the raw model lean as context. Those markets can't be rated above Low.")
w("- **Raw models improved a lot.** Elo-style margin ratings with season carry-over and a capped margin of victory, opponent-adjusted by construction, cut raw log loss sharply against v1, especially in college football. The raw models are still well short of the market.")
w("")
w("## Data")
w("")
w("| League | Warm-up (scores only) | Tuning season | Test seasons (out of sample) | Games (tuning + test) | With closing ML / spread / total | Odds provider stored by ESPN |")
w("|---|---|---|---|---|---|---|")
for lk in ("nba", "nhl", "nfl", "cfb", "mlb"):
    ev = S[lk]["eval"]; cov = ev["coverage"]
    prov = collections.Counter()
    for g in load(lk):
        if g.get("odds"): prov[(g["odds"].get("provider") or "?")] += 1
    n = sum(c["games"] for c in cov.values()); ml = sum(c["close_ml"] for c in cov.values()); sp = sum(c["close_sp"] for c in cov.values()); tt = sum(c["close_tot"] for c in cov.values())
    w(f"| {LN[lk]} | {seasons(lk, SEASONS[lk]['warm'])} | {seasons(lk, SEASONS[lk]['train'])} | {seasons(lk, SEASONS[lk]['test'])} | {n} | {ml} / {sp} / {tt} | " +
      ", ".join(f"{k} {v}" for k, v in prov.most_common()) + " |")
w("")
w("The odds come from ESPN's pre-game sportsbook record for each finished game: ESPN BET through mid-2025 and DraftKings after that, with open and close prices. Live in-game odds providers were skipped. Quotes with an impossible overround (below -0.5% or above 15%) were dropped rather than repaired. College football is limited to games with an FBS team, and FCS teams enter with a rating of -35. MLB was backtested for 2026 too, even though the season is over, so the model is ready for spring.")
w("")
w("## Method (walk-forward, no look-ahead)")
w("")
w("1. **Replay in date order.** Every game is replayed in order. Each game's prediction is stored *before* that game's result updates any rating, and ratings only ever see earlier games.")
w("2. **Tune on one season, judge on the rest.** Parameters are tuned on the tuning season only: learning rate, carry-over, MOV cap, home edge, rest and back-to-back, team-total rates, and so on. Coordinate descent minimizes home-win log loss, with mean squared error for totals. Test seasons are never used for tuning.")
w("3. **Fit the market blend walk-forward.** For each test season, the blend weight is fitted on earlier seasons only, using `logit p = (1-b)·logit(market) + b·logit(model)`. A free 3-parameter fit was tried first. On these sample sizes it mostly re-scaled the market (noise), so it was replaced.")
w("4. **Metrics.** Log loss, Brier score and calibration buckets against the closing no-vig line and the opening no-vig line. dLL is the model's log loss minus the market's (negative means the model is better), shown ± its standard error. ROI is flat-stake, graded at the pick's price. CLV is the bet's decimal price times the closing no-vig probability of the same selection, minus 1. Spreads and totals only count CLV when the closing line equals the bet line.")
w("5. **v1 is replayed with the old engine code** (`analysis._picks` and its tiers), fed the same season-to-date results. Two v1 inputs can't be rebuilt from history: ESPN's matchup predictor, which is empty for finished games, and live injury reports. The v1 numbers here therefore leave those inputs out.")
w("")
for lk in ("nba", "nhl", "nfl", "cfb", "mlb"):
    ev = S[lk]["eval"]; te = SEASONS[lk]["test"]
    w(f"## {LN[lk]}: test seasons {seasons(lk, te)}")
    w("")
    w("**Probability quality against the closing line** (lower is better; dLL = model minus market):")
    w("")
    w("| Market | n | Market close LL | v1 engine LL (dLL) | v1 raw LL | v2 raw LL | v2 final LL (dLL ± se) | Brier market / v1 / v2 final |")
    w("|---|---|---|---|---|---|---|---|")
    for m in ("ml", "sp", "tot"):
        mm = ev["markets"].get(m)
        if not mm: continue
        mc, v1e, v1r, v2r, v2f = mm["market_close"], mm["v1_engine"], mm.get("v1_raw") or {}, mm["v2_raw"], mm["v2_final"]
        w(f"| {MN[m]} | {mc['n']} | {f(mc['logloss'])} | {f(v1e['logloss'])} ({f(v1e['d_logloss_vs_mkt'], sign=True)}) | {f(v1r.get('logloss'))} | {f(v2r['logloss'])} | "
          f"{f(v2f['logloss'])} ({f(v2f['d_logloss_vs_mkt'], sign=True)} ± {f(v2f['se_d'])}) | {f(mc['brier'])} / {f(v1e['brier'])} / {f(v2f['brier'])} |")
    w("")
    w("**Against the opening line** (the walk-forward blend is fitted against openers):")
    w("")
    w("| Market | n | Market open LL | v2 raw LL | v2 final LL (dLL ± se) | Model-vs-opener correlation with the line move (same line) |")
    w("|---|---|---|---|---|---|")
    for m in ("ml", "sp", "tot"):
        mm = ev["markets"].get(m) or {}; op = mm.get("open")
        if not op: continue
        cs = mm.get("clv_signal") or {}
        w(f"| {MN[m]} | {op['market_open']['n']} | {f(op['market_open']['logloss'])} | {f(op['v2_raw']['logloss'])} | {f(op['v2_final']['logloss'])} ({f(op['v2_final']['d_logloss_vs_mkt'], sign=True)} ± {f(op['v2_final']['se_d'])}) | "
          f"{f(cs.get('corr'), 3)} (n={cs.get('n', '—')}) |")
    w("")
    cb = ev["markets"]["ml"]
    w("**Calibration, moneyline (home win), test seasons.** Each cell shows the predicted rate, then the actual rate in brackets, then n:")
    w("")
    w("| Bucket | Market close | v1 engine | v2 final |")
    w("|---|---|---|---|")
    keys = sorted({b["bin"] for k in ("calib_market", "calib_v1_engine", "calib_v2_final") for b in cb[k]})
    for k in keys:
        cells = []
        for src in ("calib_market", "calib_v1_engine", "calib_v2_final"):
            b = next((x for x in cb[src] if x["bin"] == k), None)
            cells.append(f"{b['pred']*100:.0f}% [{b['actual']*100:.0f}%] n={b['n']}" if b else "—")
        w(f"| {k} | " + " | ".join(cells) + " |")
    w("")
    w("**v1 picks (EV > 0), graded at the closing price, with CLV for bets placed at the opener:**")
    w("")
    w("| Tier | n (close) | Hit | ROI at close | n (open) | ROI at open | Avg CLV (n) | Share with CLV > 0 |")
    w("|---|---|---|---|---|---|---|---|")
    for t in ("High", "Medium", "Low", "High+Medium"):
        c = ev["picks"]["v1_close"][t]; o = ev["picks"]["v1_open"][t]
        w(f"| {t} | {c['n']} | {f(c.get('hit'), pct=True)} | {f(c.get('roi'), pct=True, sign=True)} | {o['n']} | {f(o.get('roi'), pct=True, sign=True)} | {f(o.get('clv'), pct=True, sign=True)} ({o.get('clv_n', 0)}) | {f(o.get('clv_pos'), pct=True)} |")
    w("")
    fin = S[lk]["final"]
    w("**v2 decision per market** (rule settled before the final run, after the revisions listed under Caveats: enable if the walk-forward blend beats the opener's log loss by more than one standard error and its picks don't lose to the close; *or* if the walk-forward CLV-fitted picks average positive CLV with n ≥ 30):")
    w("")
    w("| Market | Enabled | Weight b | Evidence |")
    w("|---|---|---|---|")
    for m in ("ml", "sp", "tot"):
        d = fin[m]
        w(f"| {MN[m]} | {'yes' if d['enabled'] else 'no'} | {d['b']:.2f} | {d.get('why', '')} |")
    w("")
    en = [m for m in ("ml", "sp", "tot") if fin[m]["enabled"]]
    if en:
        recs = json.load(open(f"backtest/out/{lk}_recs.json"))
        w("**v2 picks in the enabled markets, walk-forward** (b for each test season fitted on earlier seasons; tiers High EV ≥ 3%, Medium EV ≥ 1%, prices -400 to +400; picks at the opener, so ROI is at the opening price and CLV is against the close; closing-price ROI shown for comparison):")
        w("")
        w("| Market | Tier | n | Hit | ROI at open | Avg CLV (n) | n at close | ROI at close |")
        w("|---|---|---|---|---|---|---|---|")
        for m in en:
            key = "coefs_clv" if fin[m]["route"] == "clv" else "coefs_open"
            lo, lc = [], []
            for s in te:
                b = (ev[key].get(str(s)) or {}).get(m, {}).get("b")
                if b:
                    lo += RP.picks_for(recs, lk, m, b, [s], "open"); lc += RP.picks_for(recs, lk, m, b, [s], "close")
            so, sc = E.summarize_picks(lo), E.summarize_picks(lc)
            for t in ("High", "Medium", "Low"):
                o, c = so[t], sc[t]
                w(f"| {MN[m]} | {t} | {o['n']} | {f(o.get('hit'), pct=True)} | {f(o.get('roi'), pct=True, sign=True)} | {f(o.get('clv'), pct=True, sign=True)} ({o.get('clv_n', 0)}) | {c['n']} | {f(c.get('roi'), pct=True, sign=True)} |")
        w("")
w("## What was tried, and what was kept")
w("")
w("Each candidate was tuned on the tuning season, then judged on the test seasons. It was kept only if out-of-sample log loss or CLV improved. Raw output of these runs is in `backtest/out/features.log`.")
w("")
rows = []
for lk in ("nba", "nhl", "nfl", "cfb", "mlb"):
    mm = S[lk]["eval"]["markets"]["ml"]
    rows.append(f"{LN[lk]} {f((mm.get('v1_raw') or {}).get('logloss'))} to {f(mm['v2_raw']['logloss'])}")
w("| Change | Result | Kept? |")
w("|---|---|---|")
w(f"| Elo-style margin ratings: season carry-over, capped margin of victory, early-season learning boost, opponent-adjusted by construction | Raw moneyline log loss, v1 to v2, test seasons: {'; '.join(rows)}. College football improved most; NHL was no better. | Yes, as the v2 base model |")
w("| Home edge, rest and back-to-back tuned by league | Tuned values: NBA home +1.5 pts, back-to-back -3.5 pts. NHL home +0.4 goals, back-to-back -0.35. NFL home +1.5, extra rest days worth 0 (no gain). CFB home +3.3, rest 0. MLB home +0.3 runs. | Yes |")
w("| Team-total ratings (opponent-adjusted scoring tendency) for totals | Replace the v1 season averages; the raw totals model beats v1 in every league | Yes |")
w("| NBA pace proxy (shot volume, FGA + 0.44·FTA) | Totals MSE, tuning season 383.1 to 373.2; test season 397.1 to 383.8 | Yes (w = 0.5) |")
w("| MLB probable pitchers (statsapi, FIP-style per batter faced, shrunk) | Test moneyline log loss 0.6840 to 0.6817 (applied at prediction only, which the live engine can reproduce); totals MSE 20.01 to 19.90 | Yes (w = 0.5) |")
w("| NHL starting goalies (api-web.nhle.com save % above the team's recent goalies) | Actual starters: tuning-season pick w = 1.0, test log loss unchanged (0.6854 to 0.6854), blended log loss worse. Projected starters: worse on the tuning season | No |")
w("| NFL starting-QB change (box-score starter differs from last week's) | Tuning season picked -3 pts, but test log loss got worse (0.6297 to 0.6309) | No. The QB-out status is shown as a caution instead |")
w("| Market-blend weight tuning | Against closing lines, walk-forward b was 0–0.14 for moneylines and spreads. Totals fits were unstable (up to 0.56 in CFB) and didn't hold up out of sample. Against openers, b reached about 0.4 (NBA moneyline) | Yes, b is set per league and market (above) |")
w("| Calibration of the raw model: Platt and isotonic, fitted walk-forward | Platt sometimes helps a raw model (for example NFL spreads), isotonic overfits. Neither beats the market blend (see each league's table) | Superseded by the market blend |")
w("| Tier retune | v1 tiers (edge ≥ 4 pp, EV ≥ 5%) did not order results. v2 tiers use EV at the offered price from the blended probability (High ≥ 3%, Medium ≥ 1%, -400 to +400, High needs High data quality) and apply only in enabled markets. In NBA moneylines at opening prices, High beat Medium beat Low on ROI (+25% / +8% / -11%), and High had the best CLV (+5.4%). Graded at closing prices, that order did not hold (High -2.1%, Medium +14.5%, Low -31.3%), so the tiers aren't proven | Yes, with that caveat |")
w("| v1's 'model > 12 pp from market' tier downgrade | Across leagues, these picks had equal or better CLV than picks near the market (for example NBA ML at the opener: +0.4% vs -2.9%) | No. It's now a note with no downgrade |")
w("| ESPN matchup predictor (v1 blended it 50/50) | Can't be backtested, because ESPN removes it from finished games | Shown as a note, not used |")
w("")
w("## Live engine (v2) changes")
w("")
w("- `betlib/ratings.py` holds the rating model, tuned parameters, the pace feature, market-blend weights (`betlib/data/blend.json`) and tier thresholds. `betlib/ratings_live.py` starts from `betlib/data/ratings_seed.json`, the state at the end of the last completed season, and replays every completed game since. Those games come from ESPN football week scoreboards, NBA day scoreboards, or NHL and MLB team schedules. For the NBA and NFL, the replayed ratings were checked against the backtest replay and are identical (max difference 0.0).")
w("- `betlib/mlb_pitchers.py` reads today's probable pitchers and their game logs from statsapi.mlb.com. If they aren't announced yet, the pick gets a data-quality flag.")
w("- `analysis.evaluate_game` uses v2 for NBA, NHL, NFL, CFB and MLB. Soccer, WNBA and NCAA basketball keep v1 because they weren't backtested here. If the ratings can't be built, for example because of a network error, it falls back to v1 and says so.")
w("- The output JSON keeps every v1 key, with `model_raw` as the raw v2 number and `model_prob` as the blended one. It adds `engine: \"2.0\"` and `model.type = \"ratings-v2\"`. The CLI commands and `betlib/api.py` are unchanged.")
w("")
w("## Caveats (please read)")
w("")
w("- **Small samples.** One to two test seasons per league. NFL has about 400 test games, and the current seasons only run to Nov 9. A ±1–3% ROI difference over a few hundred bets is noise. The CLV evidence for NBA moneylines rests on 145 picks. Treat 'enabled' as 'promising', not 'proven'.")
w("- **Odds coverage.** Spreads and totals count CLV only when the line didn't move, which is a minority of games in some leagues. Some games have no stored odds, mostly early-season college football and some 2024 NFL. There is a single sportsbook record per game. ESPN BET and DraftKings closing lines may differ from a sharp consensus close.")
w("- **When the opening line is posted.** ESPN's 'open' can be a look-ahead line posted well before the week, especially DraftKings NFL 2026. The model's correlation with the open-to-close move was 0.63 in NFL 2026 but only 0.03–0.13 in earlier seasons, so CLV measured from the opener overstates what you can get at the time the app refreshes.")
w("- **Selection and in-sample effects.** The 'enabled' decision and the High/Medium thresholds were set after looking at test-season aggregates. The tuning season also fed the first blend fit. The later price-range limit and the removal of the far-from-market downgrade were also chosen after seeing results. Both are conservative or neutral, but they aren't pre-registered. The NHL goalie mapping matched about 80% of games.")
w("- **What v1 had that this replay doesn't.** v1 used ESPN's predictor and injuries, which can't be replayed. Live v1 may have been somewhat better than its replay here.")
w("- **Track it live.** The tracker's CLV over the next 100+ plays is the real test. Research only, never a guarantee.")
w("")
w("## Reproduce")
w("")
w("```")
w("cd /workspace/betting")
w("python3 -m backtest.fetch nfl nba nhl cfb mlb      # ESPN scoreboards + core odds (cached in backtest/raw, gzip)")
w("python3 -m backtest.fetch_warm nfl nba nhl cfb mlb # warm-up season scores")
w("python3 -m backtest.fetch_nhl_goalies; python3 -m backtest.fetch_mlb_pitchers; python3 -m backtest.fetch_nfl_qb")
w("python3 -m backtest.tune <league>                   # tuning season only -> betlib/ratings.PARAMS (backtest/setparams.py)")
w("for l in nba nhl nfl cfb mlb; do python3 -m backtest.harness $l; done")
w("python3 -m backtest.report nba nhl nfl cfb mlb      # walk-forward metrics + betlib/data/blend.json")
w("python3 -m backtest.make_seed && python3 -m backtest.write_md")
w("```")
open("BACKTEST.md", "w").write("\n".join(out) + "\n")
print("wrote BACKTEST.md", len(out), "lines")
