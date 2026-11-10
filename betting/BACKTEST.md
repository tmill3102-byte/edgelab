# EdgeLab engine v2: backtest and calibration report

Generated 2026-11-10 15:44 ET by `backtest/write_md.py` from `backtest/out/summary.json`. Every number below comes from free public data (ESPN scoreboards and its core odds API, api-web.nhle.com, statsapi.mlb.com). Nothing was estimated or filled in. Games with no stored odds count toward the ratings, but not toward the market metrics.

## Bottom line

- **No league's model beats the closing line.** Over every test season, the best result (v2 blended with the market) only matches the closing no-vig line's log loss, within noise. A simple model built on free box scores can't out-predict the closing number. That's expected, and it's why the engine stays anchored to the market.
- **v1 was worse than doing nothing.** In 14 of the 15 league×market cells, its blended probabilities had a higher log loss than the market. The exception was NHL puck lines (dLL -0.0012). Its High+Medium picks lost money at closing prices in NBA (-6.8%, n=1160), NHL (-3.6%, n=1000), college football (-7.8%, n=270) and MLB (-5.0%, n=3177). NFL was up +3.2%, but on only n=240. v1's tiers weren't reliable either. High had the best closing ROI in the NBA and NFL, but the worst CLV in the NBA (-5.4%) and the worst ROI in the NHL (-13.3%) and MLB (-7.3%).
- **v2 is market-anchored and earns weight only where the data supports it.** The model gets weight in a market only when walk-forward tests show it improves log loss against the opening line, or when its picks beat the closing line. That leaves 3 of 15 league×market cells enabled: NBA moneylines, NBA totals and NHL puck lines. Every other market shows the market's own no-vig probability with the raw model lean as context. Those markets can't be rated above Low.
- **Raw models improved a lot.** Elo-style margin ratings with season carry-over and a capped margin of victory, opponent-adjusted by construction, cut raw log loss sharply against v1, especially in college football. The raw models are still well short of the market.

## Data

| League | Warm-up (scores only) | Tuning season | Test seasons (out of sample) | Games (tuning + test) | With closing ML / spread / total | Odds provider stored by ESPN |
|---|---|---|---|---|---|---|
| NBA | 2023-24 | 2024-25 | 2025-26, 2026-27 to Nov 9 | 2792 | 2781 / 2785 / 2786 | ESPN BET 1568, Draft Kings 1219 |
| NHL | 2023-24 | 2024-25 | 2025-26, 2026-27 to Nov 9 | 3041 | 3041 / 3037 / 3037 | ESPN BET 1781, Draft Kings 1260 |
| NFL | 2023 | 2024 | 2025, 2026 to Nov 9 | 708 | 665 / 676 / 677 | ESPN BET 435, Draft Kings 244 |
| College football (FBS) | 2023 | 2024 | 2025, 2026 to Nov 9 | 2608 | 2262 / 2546 / 2547 | ESPN BET 1766, Draft Kings 788, Caesars Sportsbook (Colorado) 7 |
| MLB | 2024 | 2025 | 2026 | 4948 | 4948 / 4946 / 4945 | ESPN BET 2478, DraftKings 2470 |

The odds come from ESPN's pre-game sportsbook record for each finished game: ESPN BET through mid-2025 and DraftKings after that, with open and close prices. Live in-game odds providers were skipped. Quotes with an impossible overround (below -0.5% or above 15%) were dropped rather than repaired. College football is limited to games with an FBS team, and FCS teams enter with a rating of -35. MLB was backtested for 2026 too, even though the season is over, so the model is ready for spring.

## Method (walk-forward, no look-ahead)

1. **Replay in date order.** Every game is replayed in order. Each game's prediction is stored *before* that game's result updates any rating, and ratings only ever see earlier games.
2. **Tune on one season, judge on the rest.** Parameters are tuned on the tuning season only: learning rate, carry-over, MOV cap, home edge, rest and back-to-back, team-total rates, and so on. Coordinate descent minimizes home-win log loss, with mean squared error for totals. Test seasons are never used for tuning.
3. **Fit the market blend walk-forward.** For each test season, the blend weight is fitted on earlier seasons only, using `logit p = (1-b)·logit(market) + b·logit(model)`. A free 3-parameter fit was tried first. On these sample sizes it mostly re-scaled the market (noise), so it was replaced.
4. **Metrics.** Log loss, Brier score and calibration buckets against the closing no-vig line and the opening no-vig line. dLL is the model's log loss minus the market's (negative means the model is better), shown ± its standard error. ROI is flat-stake, graded at the pick's price. CLV is the bet's decimal price times the closing no-vig probability of the same selection, minus 1. Spreads and totals only count CLV when the closing line equals the bet line.
5. **v1 is replayed with the old engine code** (`analysis._picks` and its tiers), fed the same season-to-date results. Two v1 inputs can't be rebuilt from history: ESPN's matchup predictor, which is empty for finished games, and live injury reports. The v1 numbers here therefore leave those inputs out.

## NBA: test seasons 2025-26, 2026-27 to Nov 9

**Probability quality against the closing line** (lower is better; dLL = model minus market):

| Market | n | Market close LL | v1 engine LL (dLL) | v1 raw LL | v2 raw LL | v2 final LL (dLL ± se) | Brier market / v1 / v2 final |
|---|---|---|---|---|---|---|---|
| Moneyline | 1464 | 0.5717 | 0.5799 (+0.0082) | 0.6046 | 0.5965 | 0.5722 (+0.0006 ± 0.0007) | 0.1952 / 0.1978 / 0.1954 |
| Spread / puck line / run line | 1469 | 0.6927 | 0.7013 (+0.0086) | 0.7328 | 0.7217 | 0.6931 (+0.0004 ± 0.0007) | 0.2498 / 0.2540 / 0.2500 |
| Total | 1437 | 0.6927 | 0.7011 (+0.0084) | 0.7386 | 0.7148 | 0.6927 (+0.0000 ± 0.0000) | 0.2498 / 0.2539 / 0.2498 |

**Against the opening line** (the walk-forward blend is fitted against openers):

| Market | n | Market open LL | v2 raw LL | v2 final LL (dLL ± se) | Model-vs-opener correlation with the line move (same line) |
|---|---|---|---|---|---|
| Moneyline | 1463 | 0.5829 | 0.5967 | 0.5831 (+0.0002 ± 0.0020) | 0.207 (n=1463) |
| Spread / puck line / run line | 1468 | 0.6933 | 0.7108 | 0.6931 (-0.0002 ± 0.0016) | -0.074 (n=361) |
| Total | 1469 | 0.6930 | 0.7017 | 0.6921 (-0.0009 ± 0.0006) | 0.049 (n=185) |

**Calibration, moneyline (home win), test seasons.** Each cell shows the predicted rate, then the actual rate in brackets, then n:

| Bucket | Market close | v1 engine | v2 final |
|---|---|---|---|
| 0.00-0.20 | 14% [10%] n=92 | 15% [8%] n=51 | 15% [6%] n=84 |
| 0.20-0.35 | 28% [25%] n=200 | 28% [22%] n=186 | 28% [27%] n=198 |
| 0.35-0.45 | 40% [41%] n=200 | 40% [34%] n=193 | 40% [40%] n=203 |
| 0.45-0.55 | 50% [50%] n=187 | 50% [51%] n=254 | 50% [49%] n=213 |
| 0.55-0.65 | 60% [60%] n=247 | 60% [59%] n=264 | 60% [60%] n=237 |
| 0.65-0.80 | 72% [75%] n=332 | 72% [77%] n=345 | 72% [75%] n=328 |
| 0.80-1.00 | 86% [86%] n=206 | 85% [85%] n=171 | 86% [86%] n=201 |

**v1 picks (EV > 0), graded at the closing price, with CLV for bets placed at the opener:**

| Tier | n (close) | Hit | ROI at close | n (open) | ROI at open | Avg CLV (n) | Share with CLV > 0 |
|---|---|---|---|---|---|---|---|
| High | 164 | 50.0% | +9.7% | 241 | -0.0% | -5.4% (158) | 27.8% |
| Medium | 996 | 43.6% | -9.5% | 1667 | -2.5% | -2.9% (743) | 27.6% |
| Low | 1875 | 44.0% | -10.0% | 991 | -9.3% | -2.8% (485) | 24.7% |
| High+Medium | 1160 | 44.5% | -6.8% | 1908 | -2.2% | -3.4% (901) | 27.6% |

**v2 decision per market** (rule settled before the final run, after the revisions listed under Caveats: enable if the walk-forward blend beats the opener's log loss by more than one standard error and its picks don't lose to the close; *or* if the walk-forward CLV-fitted picks average positive CLV with n ≥ 30):

| Market | Enabled | Weight b | Evidence |
|---|---|---|---|
| Moneyline | yes | 0.14 | walk-forward High+Medium picks beat the closing line by +1.9% on average (n=145) |
| Spread / puck line / run line | no | 0.00 | walk-forward dLL vs opener -0.0002, CLV picks n=0 mean CLV None |
| Total | yes | 0.17 | walk-forward blend beat the opening line's log loss over 1469 test games (dLL -0.0009 ± 0.0006) |

**v2 picks in the enabled markets, walk-forward** (b for each test season fitted on earlier seasons; tiers High EV ≥ 3%, Medium EV ≥ 1%, prices -400 to +400; picks at the opener, so ROI is at the opening price and CLV is against the close; closing-price ROI shown for comparison):

| Market | Tier | n | Hit | ROI at open | Avg CLV (n) | n at close | ROI at close |
|---|---|---|---|---|---|---|---|
| Moneyline | High | 59 | 37.3% | +25.0% | +5.4% (59) | 82 | -2.1% |
| Moneyline | Medium | 86 | 37.2% | +7.6% | -0.5% (86) | 96 | +14.5% |
| Moneyline | Low | 204 | 24.5% | -11.0% | +0.4% (204) | 216 | -31.3% |
| Total | High | 12 | 66.7% | +26.9% | -4.5% (1) | 7 | +36.3% |
| Total | Medium | 26 | 50.0% | -4.2% | -4.0% (3) | 30 | -17.1% |
| Total | Low | 34 | 47.1% | -9.7% | -3.2% (3) | 38 | -19.3% |

## NHL: test seasons 2025-26, 2026-27 to Nov 9

**Probability quality against the closing line** (lower is better; dLL = model minus market):

| Market | n | Market close LL | v1 engine LL (dLL) | v1 raw LL | v2 raw LL | v2 final LL (dLL ± se) | Brier market / v1 / v2 final |
|---|---|---|---|---|---|---|---|
| Moneyline | 1636 | 0.6747 | 0.6767 (+0.0020) | 0.6848 | 0.6854 | 0.6751 (+0.0003 ± 0.0002) | 0.2411 / 0.2420 / 0.2412 |
| Spread / puck line / run line | 1632 | 0.6272 | 0.6260 (-0.0012) | 0.6324 | 0.6325 | 0.6272 (+0.0000 ± 0.0001) | 0.2178 / 0.2173 / 0.2178 |
| Total | 1632 | 0.6899 | 0.6937 (+0.0039) | 0.7049 | 0.7029 | 0.6924 (+0.0025 ± 0.0011) | 0.2484 / 0.2503 / 0.2496 |

**Against the opening line** (the walk-forward blend is fitted against openers):

| Market | n | Market open LL | v2 raw LL | v2 final LL (dLL ± se) | Model-vs-opener correlation with the line move (same line) |
|---|---|---|---|---|---|
| Moneyline | 1636 | 0.6774 | 0.6854 | 0.6786 (+0.0012 ± 0.0006) | 0.187 (n=1636) |
| Spread / puck line / run line | 1632 | 0.6302 | 0.6298 | 0.6296 (-0.0006 ± 0.0003) | 0.154 (n=1482) |
| Total | 1631 | 0.6875 | 0.6927 | 0.6894 (+0.0019 ± 0.0015) | -0.136 (n=1222) |

**Calibration, moneyline (home win), test seasons.** Each cell shows the predicted rate, then the actual rate in brackets, then n:

| Bucket | Market close | v1 engine | v2 final |
|---|---|---|---|
| 0.20-0.35 | 32% [31%] n=35 | 32% [33%] n=24 | 32% [30%] n=30 |
| 0.35-0.45 | 41% [43%] n=285 | 41% [41%] n=239 | 41% [44%] n=257 |
| 0.45-0.55 | 50% [49%] n=580 | 50% [50%] n=704 | 50% [48%] n=613 |
| 0.55-0.65 | 59% [57%] n=573 | 59% [57%] n=545 | 59% [57%] n=572 |
| 0.65-0.80 | 70% [72%] n=163 | 69% [76%] n=123 | 70% [72%] n=164 |
| 0.80-1.00 | — | 80% [0%] n=1 | — |

**v1 picks (EV > 0), graded at the closing price, with CLV for bets placed at the opener:**

| Tier | n (close) | Hit | ROI at close | n (open) | ROI at open | Avg CLV (n) | Share with CLV > 0 |
|---|---|---|---|---|---|---|---|
| High | 133 | 38.3% | -13.3% | 163 | -9.0% | -0.1% (162) | 49.4% |
| Medium | 867 | 51.8% | -2.1% | 961 | -0.0% | -1.5% (859) | 36.0% |
| Low | 1163 | 50.1% | -7.0% | 1122 | +1.1% | -2.5% (984) | 27.0% |
| High+Medium | 1000 | 50.0% | -3.6% | 1124 | -1.3% | -1.2% (1021) | 38.1% |

**v2 decision per market** (rule settled before the final run, after the revisions listed under Caveats: enable if the walk-forward blend beats the opener's log loss by more than one standard error and its picks don't lose to the close; *or* if the walk-forward CLV-fitted picks average positive CLV with n ≥ 30):

| Market | Enabled | Weight b | Evidence |
|---|---|---|---|
| Moneyline | no | 0.00 | walk-forward dLL vs opener 0.0012, CLV picks n=0 mean CLV None |
| Spread / puck line / run line | yes | 0.27 | walk-forward blend beat the opening line's log loss over 1632 test games (dLL -0.0006 ± 0.0003) |
| Total | no | 0.00 | walk-forward dLL vs opener 0.0019, CLV picks n=0 mean CLV None |

**v2 picks in the enabled markets, walk-forward** (b for each test season fitted on earlier seasons; tiers High EV ≥ 3%, Medium EV ≥ 1%, prices -400 to +400; picks at the opener, so ROI is at the opening price and CLV is against the close; closing-price ROI shown for comparison):

| Market | Tier | n | Hit | ROI at open | Avg CLV (n) | n at close | ROI at close |
|---|---|---|---|---|---|---|---|
| Spread / puck line / run line | High | 0 | — | — | — (0) | 1 | -100.0% |
| Spread / puck line / run line | Medium | 8 | 62.5% | +32.9% | +0.5% (6) | 12 | +16.3% |
| Spread / puck line / run line | Low | 8 | 62.5% | -7.7% | -6.2% (6) | 11 | +8.0% |

## NFL: test seasons 2025, 2026 to Nov 9

**Probability quality against the closing line** (lower is better; dLL = model minus market):

| Market | n | Market close LL | v1 engine LL (dLL) | v1 raw LL | v2 raw LL | v2 final LL (dLL ± se) | Brier market / v1 / v2 final |
|---|---|---|---|---|---|---|---|
| Moneyline | 405 | 0.6119 | 0.6145 (+0.0026) | 0.6383 | 0.6289 | 0.6119 (-0.0000 ± 0.0000) | 0.2121 / 0.2135 / 0.2121 |
| Spread / puck line / run line | 414 | 0.6933 | 0.6963 (+0.0029) | 0.7163 | 0.7246 | 0.6939 (+0.0006 ± 0.0005) | 0.2501 / 0.2515 / 0.2504 |
| Total | 387 | 0.6920 | 0.7047 (+0.0128) | 0.7756 | 0.7055 | 0.6912 (-0.0007 ± 0.0020) | 0.2494 / 0.2557 / 0.2490 |

**Against the opening line** (the walk-forward blend is fitted against openers):

| Market | n | Market open LL | v2 raw LL | v2 final LL (dLL ± se) | Model-vs-opener correlation with the line move (same line) |
|---|---|---|---|---|---|
| Moneyline | 405 | 0.6253 | 0.6289 | 0.6253 (-0.0000 ± 0.0000) | 0.413 (n=405) |
| Spread / puck line / run line | 415 | 0.6950 | 0.7119 | 0.6954 (+0.0003 ± 0.0003) | 0.079 (n=109) |
| Total | 419 | 0.6927 | 0.7048 | 0.6927 (-0.0000 ± 0.0000) | -0.041 (n=88) |

**Calibration, moneyline (home win), test seasons.** Each cell shows the predicted rate, then the actual rate in brackets, then n:

| Bucket | Market close | v1 engine | v2 final |
|---|---|---|---|
| 0.00-0.20 | 17% [10%] n=10 | 17% [25%] n=4 | 17% [10%] n=10 |
| 0.20-0.35 | 29% [22%] n=58 | 28% [26%] n=42 | 29% [22%] n=58 |
| 0.35-0.45 | 40% [35%] n=71 | 41% [25%] n=77 | 40% [35%] n=71 |
| 0.45-0.55 | 50% [54%] n=52 | 51% [54%] n=87 | 50% [54%] n=52 |
| 0.55-0.65 | 60% [59%] n=83 | 60% [60%] n=88 | 60% [59%] n=83 |
| 0.65-0.80 | 72% [68%] n=97 | 72% [70%] n=84 | 72% [68%] n=95 |
| 0.80-1.00 | 86% [88%] n=34 | 84% [96%] n=23 | 85% [86%] n=36 |

**v1 picks (EV > 0), graded at the closing price, with CLV for bets placed at the opener:**

| Tier | n (close) | Hit | ROI at close | n (open) | ROI at open | Avg CLV (n) | Share with CLV > 0 |
|---|---|---|---|---|---|---|---|
| High | 41 | 58.5% | +33.7% | 69 | +37.2% | -1.4% (44) | 34.1% |
| Medium | 199 | 44.7% | -3.1% | 356 | +4.8% | +3.1% (166) | 42.2% |
| Low | 559 | 44.8% | -3.6% | 381 | -5.7% | -1.6% (193) | 29.5% |
| High+Medium | 240 | 47.1% | +3.2% | 425 | +10.1% | +2.1% (210) | 40.5% |

**v2 decision per market** (rule settled before the final run, after the revisions listed under Caveats: enable if the walk-forward blend beats the opener's log loss by more than one standard error and its picks don't lose to the close; *or* if the walk-forward CLV-fitted picks average positive CLV with n ≥ 30):

| Market | Enabled | Weight b | Evidence |
|---|---|---|---|
| Moneyline | no | 0.00 | walk-forward dLL vs opener -0.0, CLV picks n=1 mean CLV 1.2029 |
| Spread / puck line / run line | no | 0.00 | walk-forward dLL vs opener 0.0003, CLV picks n=0 mean CLV None |
| Total | no | 0.00 | walk-forward dLL vs opener -0.0, CLV picks n=0 mean CLV None |

## College football (FBS): test seasons 2025, 2026 to Nov 9

**Probability quality against the closing line** (lower is better; dLL = model minus market):

| Market | n | Market close LL | v1 engine LL (dLL) | v1 raw LL | v2 raw LL | v2 final LL (dLL ± se) | Brier market / v1 / v2 final |
|---|---|---|---|---|---|---|---|
| Moneyline | 1423 | 0.5034 | 0.5272 (+0.0237) | 0.6181 | 0.5549 | 0.5046 (+0.0011 ± 0.0007) | 0.1683 / 0.1753 / 0.1686 |
| Spread / puck line / run line | 1614 | 0.6934 | 0.7122 (+0.0188) | 0.9926 | 0.7795 | 0.6934 (+0.0000 ± 0.0000) | 0.2501 / 0.2592 / 0.2501 |
| Total | 1343 | 0.6932 | 0.6981 (+0.0049) | 0.7362 | 0.7092 | 0.6960 (+0.0028 ± 0.0024) | 0.2500 / 0.2524 / 0.2514 |

**Against the opening line** (the walk-forward blend is fitted against openers):

| Market | n | Market open LL | v2 raw LL | v2 final LL (dLL ± se) | Model-vs-opener correlation with the line move (same line) |
|---|---|---|---|---|---|
| Moneyline | 1426 | 0.5082 | 0.5539 | 0.5090 (+0.0007 ± 0.0009) | 0.223 (n=1420) |
| Spread / puck line / run line | 1618 | 0.6934 | 0.7653 | 0.6934 (+0.0000 ± 0.0000) | 0.025 (n=325) |
| Total | 1632 | 0.6922 | 0.7033 | 0.6950 (+0.0028 ± 0.0026) | 0.145 (n=295) |

**Calibration, moneyline (home win), test seasons.** Each cell shows the predicted rate, then the actual rate in brackets, then n:

| Bucket | Market close | v1 engine | v2 final |
|---|---|---|---|
| 0.00-0.20 | 13% [13%] n=102 | 15% [6%] n=64 | 13% [13%] n=102 |
| 0.20-0.35 | 28% [34%] n=179 | 28% [33%] n=168 | 28% [35%] n=175 |
| 0.35-0.45 | 41% [32%] n=138 | 40% [36%] n=157 | 40% [30%] n=135 |
| 0.45-0.55 | 50% [54%] n=123 | 50% [47%] n=191 | 50% [53%] n=131 |
| 0.55-0.65 | 60% [63%] n=203 | 60% [69%] n=226 | 60% [64%] n=198 |
| 0.65-0.80 | 72% [74%] n=272 | 73% [79%] n=331 | 72% [74%] n=276 |
| 0.80-1.00 | 89% [93%] n=406 | 85% [94%] n=286 | 89% [93%] n=406 |

**v1 picks (EV > 0), graded at the closing price, with CLV for bets placed at the opener:**

| Tier | n (close) | Hit | ROI at close | n (open) | ROI at open | Avg CLV (n) | Share with CLV > 0 |
|---|---|---|---|---|---|---|---|
| High | 0 | — | — | 0 | — | — (0) | — |
| Medium | 270 | 34.8% | -7.8% | 401 | -11.4% | -1.5% (245) | 34.3% |
| Low | 2695 | 40.4% | -11.5% | 2505 | -6.5% | -0.5% (1161) | 34.7% |
| High+Medium | 270 | 34.8% | -7.8% | 401 | -11.4% | -1.5% (245) | 34.3% |

**v2 decision per market** (rule settled before the final run, after the revisions listed under Caveats: enable if the walk-forward blend beats the opener's log loss by more than one standard error and its picks don't lose to the close; *or* if the walk-forward CLV-fitted picks average positive CLV with n ≥ 30):

| Market | Enabled | Weight b | Evidence |
|---|---|---|---|
| Moneyline | no | 0.00 | walk-forward dLL vs opener 0.0007, CLV picks n=26 mean CLV 0.041 |
| Spread / puck line / run line | no | 0.00 | walk-forward dLL vs opener 0.0, CLV picks n=0 mean CLV None |
| Total | no | 0.00 | walk-forward dLL vs opener 0.0028, CLV picks n=0 mean CLV None |

## MLB: test seasons 2026

**Probability quality against the closing line** (lower is better; dLL = model minus market):

| Market | n | Market close LL | v1 engine LL (dLL) | v1 raw LL | v2 raw LL | v2 final LL (dLL ± se) | Brier market / v1 / v2 final |
|---|---|---|---|---|---|---|---|
| Moneyline | 2470 | 0.6791 | 0.6822 (+0.0031) | 0.6922 | 0.6817 | 0.6793 (+0.0002 ± 0.0008) | 0.2431 / 0.2446 / 0.2432 |
| Spread / puck line / run line | 2470 | 0.6770 | 0.6827 (+0.0057) | 0.7002 | 0.6910 | 0.6778 (+0.0008 ± 0.0008) | 0.2420 / 0.2446 / 0.2424 |
| Total | 2358 | 0.6926 | 0.6992 (+0.0066) | 0.7380 | 0.7255 | 0.6926 (+0.0000 ± 0.0000) | 0.2497 / 0.2530 / 0.2497 |

**Against the opening line** (the walk-forward blend is fitted against openers):

| Market | n | Market open LL | v2 raw LL | v2 final LL (dLL ± se) | Model-vs-opener correlation with the line move (same line) |
|---|---|---|---|---|---|
| Moneyline | 2470 | 0.6809 | 0.6817 | 0.6808 (-0.0000 ± 0.0013) | 0.252 (n=2470) |
| Spread / puck line / run line | 2469 | 0.6757 | 0.6862 | 0.6758 (+0.0001 ± 0.0010) | 0.123 (n=2226) |
| Total | 2349 | 0.6924 | 0.7248 | 0.6943 (+0.0019 ± 0.0012) | 0.048 (n=1023) |

**Calibration, moneyline (home win), test seasons.** Each cell shows the predicted rate, then the actual rate in brackets, then n:

| Bucket | Market close | v1 engine | v2 final |
|---|---|---|---|
| 0.20-0.35 | 32% [28%] n=29 | 33% [32%] n=41 | 32% [23%] n=22 |
| 0.35-0.45 | 42% [43%] n=364 | 41% [43%] n=388 | 41% [42%] n=305 |
| 0.45-0.55 | 51% [51%] n=1035 | 50% [51%] n=1096 | 51% [50%] n=1075 |
| 0.55-0.65 | 59% [57%] n=892 | 59% [59%] n=803 | 59% [57%] n=907 |
| 0.65-0.80 | 69% [70%] n=150 | 69% [65%] n=141 | 68% [71%] n=160 |
| 0.80-1.00 | — | 80% [100%] n=1 | 80% [100%] n=1 |

**v1 picks (EV > 0), graded at the closing price, with CLV for bets placed at the opener:**

| Tier | n (close) | Hit | ROI at close | n (open) | ROI at open | Avg CLV (n) | Share with CLV > 0 |
|---|---|---|---|---|---|---|---|
| High | 281 | 44.1% | -7.3% | 324 | +2.6% | -3.0% (317) | 27.1% |
| Medium | 2896 | 51.5% | -4.8% | 2886 | -5.0% | -3.7% (2081) | 16.3% |
| Low | 1583 | 52.2% | -0.7% | 1334 | -5.6% | -4.1% (1038) | 13.9% |
| High+Medium | 3177 | 50.8% | -5.0% | 3210 | -4.2% | -3.6% (2398) | 17.8% |

**v2 decision per market** (rule settled before the final run, after the revisions listed under Caveats: enable if the walk-forward blend beats the opener's log loss by more than one standard error and its picks don't lose to the close; *or* if the walk-forward CLV-fitted picks average positive CLV with n ≥ 30):

| Market | Enabled | Weight b | Evidence |
|---|---|---|---|
| Moneyline | no | 0.00 | walk-forward dLL vs opener -0.0, CLV picks n=487 mean CLV -0.0184 |
| Spread / puck line / run line | no | 0.00 | walk-forward dLL vs opener 0.0001, CLV picks n=6 mean CLV 0.0708 |
| Total | no | 0.00 | walk-forward dLL vs opener 0.0019, CLV picks n=2 mean CLV None |

## What was tried, and what was kept

Each candidate was tuned on the tuning season, then judged on the test seasons. It was kept only if out-of-sample log loss or CLV improved. Raw output of these runs is in `backtest/out/features.log`.

| Change | Result | Kept? |
|---|---|---|
| Elo-style margin ratings: season carry-over, capped margin of victory, early-season learning boost, opponent-adjusted by construction | Raw moneyline log loss, v1 to v2, test seasons: NBA 0.6046 to 0.5965; NHL 0.6848 to 0.6854; NFL 0.6383 to 0.6289; College football (FBS) 0.6181 to 0.5549; MLB 0.6922 to 0.6817. College football improved most; NHL was no better. | Yes, as the v2 base model |
| Home edge, rest and back-to-back tuned by league | Tuned values: NBA home +1.5 pts, back-to-back -3.5 pts. NHL home +0.4 goals, back-to-back -0.35. NFL home +1.5, extra rest days worth 0 (no gain). CFB home +3.3, rest 0. MLB home +0.3 runs. | Yes |
| Team-total ratings (opponent-adjusted scoring tendency) for totals | Replace the v1 season averages; the raw totals model beats v1 in every league | Yes |
| NBA pace proxy (shot volume, FGA + 0.44·FTA) | Totals MSE, tuning season 383.1 to 373.2; test season 397.1 to 383.8 | Yes (w = 0.5) |
| MLB probable pitchers (statsapi, FIP-style per batter faced, shrunk) | Test moneyline log loss 0.6840 to 0.6817 (applied at prediction only, which the live engine can reproduce); totals MSE 20.01 to 19.90 | Yes (w = 0.5) |
| NHL starting goalies (api-web.nhle.com save % above the team's recent goalies) | Actual starters: tuning-season pick w = 1.0, test log loss unchanged (0.6854 to 0.6854), blended log loss worse. Projected starters: worse on the tuning season | No |
| NFL starting-QB change (box-score starter differs from last week's) | Tuning season picked -3 pts, but test log loss got worse (0.6297 to 0.6309) | No. The QB-out status is shown as a caution instead |
| Market-blend weight tuning | Against closing lines, walk-forward b was 0–0.14 for moneylines and spreads. Totals fits were unstable (up to 0.56 in CFB) and didn't hold up out of sample. Against openers, b reached about 0.4 (NBA moneyline) | Yes, b is set per league and market (above) |
| Calibration of the raw model: Platt and isotonic, fitted walk-forward | Platt sometimes helps a raw model (for example NFL spreads), isotonic overfits. Neither beats the market blend (see each league's table) | Superseded by the market blend |
| Tier retune | v1 tiers (edge ≥ 4 pp, EV ≥ 5%) did not order results. v2 tiers use EV at the offered price from the blended probability (High ≥ 3%, Medium ≥ 1%, -400 to +400, High needs High data quality) and apply only in enabled markets. In NBA moneylines at opening prices, High beat Medium beat Low on ROI (+25% / +8% / -11%), and High had the best CLV (+5.4%). Graded at closing prices, that order did not hold (High -2.1%, Medium +14.5%, Low -31.3%), so the tiers aren't proven | Yes, with that caveat |
| v1's 'model > 12 pp from market' tier downgrade | Across leagues, these picks had equal or better CLV than picks near the market (for example NBA ML at the opener: +0.4% vs -2.9%) | No. It's now a note with no downgrade |
| ESPN matchup predictor (v1 blended it 50/50) | Can't be backtested, because ESPN removes it from finished games | Shown as a note, not used |

## Live engine (v2) changes

- `betlib/ratings.py` holds the rating model, tuned parameters, the pace feature, market-blend weights (`betlib/data/blend.json`) and tier thresholds. `betlib/ratings_live.py` starts from `betlib/data/ratings_seed.json`, the state at the end of the last completed season, and replays every completed game since. Those games come from ESPN football week scoreboards, NBA day scoreboards, or NHL and MLB team schedules. For the NBA and NFL, the replayed ratings were checked against the backtest replay and are identical (max difference 0.0).
- `betlib/mlb_pitchers.py` reads today's probable pitchers and their game logs from statsapi.mlb.com. If they aren't announced yet, the pick gets a data-quality flag.
- `analysis.evaluate_game` uses v2 for NBA, NHL, NFL, CFB and MLB. Soccer, WNBA and NCAA basketball keep v1 because they weren't backtested here. If the ratings can't be built, for example because of a network error, it falls back to v1 and says so.
- The output JSON keeps every v1 key, with `model_raw` as the raw v2 number and `model_prob` as the blended one. It adds `engine: "2.0"` and `model.type = "ratings-v2"`. The CLI commands and `betlib/api.py` are unchanged.

## Caveats (please read)

- **Small samples.** One to two test seasons per league. NFL has about 400 test games, and the current seasons only run to Nov 9. A ±1–3% ROI difference over a few hundred bets is noise. The CLV evidence for NBA moneylines rests on 145 picks. Treat 'enabled' as 'promising', not 'proven'.
- **Odds coverage.** Spreads and totals count CLV only when the line didn't move, which is a minority of games in some leagues. Some games have no stored odds, mostly early-season college football and some 2024 NFL. There is a single sportsbook record per game. ESPN BET and DraftKings closing lines may differ from a sharp consensus close.
- **When the opening line is posted.** ESPN's 'open' can be a look-ahead line posted well before the week, especially DraftKings NFL 2026. The model's correlation with the open-to-close move was 0.63 in NFL 2026 but only 0.03–0.13 in earlier seasons, so CLV measured from the opener overstates what you can get at the time the app refreshes.
- **Selection and in-sample effects.** The 'enabled' decision and the High/Medium thresholds were set after looking at test-season aggregates. The tuning season also fed the first blend fit. The later price-range limit and the removal of the far-from-market downgrade were also chosen after seeing results. Both are conservative or neutral, but they aren't pre-registered. The NHL goalie mapping matched about 80% of games.
- **What v1 had that this replay doesn't.** v1 used ESPN's predictor and injuries, which can't be replayed. Live v1 may have been somewhat better than its replay here.
- **Track it live.** The tracker's CLV over the next 100+ plays is the real test. Research only, never a guarantee.

## Reproduce

```
cd /workspace/betting
python3 -m backtest.fetch nfl nba nhl cfb mlb      # ESPN scoreboards + core odds (cached in backtest/raw, gzip)
python3 -m backtest.fetch_warm nfl nba nhl cfb mlb # warm-up season scores
python3 -m backtest.fetch_nhl_goalies; python3 -m backtest.fetch_mlb_pitchers; python3 -m backtest.fetch_nfl_qb
python3 -m backtest.tune <league>                   # tuning season only -> betlib/ratings.PARAMS (backtest/setparams.py)
for l in nba nhl nfl cfb mlb; do python3 -m backtest.harness $l; done
python3 -m backtest.report nba nhl nfl cfb mlb      # walk-forward metrics + betlib/data/blend.json
python3 -m backtest.make_seed && python3 -m backtest.write_md
```
