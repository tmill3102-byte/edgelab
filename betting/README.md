# Betting Research Engine (personal, research-only)

Free, no-API-key sports betting **research** tool. It never places bets. Every number comes from a
free public feed fetched live, or from a price you type in. If a source has no data, the output says so.

Location: `/workspace/betting/` (shared box). Entry point: `python3 /workspace/betting/bet.py`. Add `--json` to any command.

## Commands
```
bet.py sources [--date YYYYMMDD]               # live status of every feed/league: events, odds, injuries, standings
bet.py slate <sport|group|all> [--date D] [--analyze]
bet.py game <sport> <team text|event id> [--date D] [--log best|<selection prefix>]
bet.py prop <sport> "<player>" <stat> <line> [--odds -115 --under-odds -105] [--side over|under] [--event ID --log over|under|best]
bet.py parlay --leg nba:Suns:total:over --leg nhl:Kings:ml:NSH [--leg prop:nba:Jalen Brunson:pts:26.5:over:-115] [--leg manual:0.55:-110:label] [--leg track:12] [--price +260]
bet.py build <sport> <team> [--date sunday] [--legs 3] [--target +400] [--risk safe|balanced|aggressive] [--prop "Player:stat:line:over:-115"] [--game <2nd team>] [--price <book SGP price>]
bet.py edges [sport] [--tier High|Medium|Low] [--min-edge 0.02] [--date D]
bet.py digest [--top 5] [--no-log] [--date D]   # grades pending, today's slate counts, top High/Medium edges, logs them (source=digest)
bet.py track add|list|grade|report|signals|void [...]
bet.py odds -110 -110 [--prob 0.55]            # implied / no-vig / fair / EV / Kelly calculator
./run_digest.sh                                # routine entry point: digest + report saved to digests/YYYY-MM-DD.*
```
Dates: `YYYYMMDD`, `today`, `tomorrow`, `yesterday`, or a weekday (`sunday` = next Sunday, today included). Times print in ET.

Sports / leagues (`bet.py slate all`): nfl, cfb (FBS), nba, wnba, ncaab, ncaaw, mlb, nhl, soccer
(epl, efl, laliga, seriea, bundesliga, ligue1, eredivisie, primeira, mls, ligamx, brasileirao, argentina, scotland,
ucl, uel, uecl, nations, friendly, concacaf, nwsl), tennis (atp, wta), golf (pga, lpga), ufc, f1.
Groups: `all`, `soccer`, `tennis`, `golf`, `college`, `us`.

Prop stats: pts reb ast stl blk to 3pm min pra pr pa ra sb | pass_yds pass_td pass_att completions int rush_yds rush_att rush_td
rec rec_yds rec_td targets pass_rush_yds rush_rec_yds | goals a sog shots saves | hits hr rbi k tb runs | soccer goals/shots/sot/assists.
Or any raw ESPN gamelog field name (an unknown stat prints the list of available ones).

## Data sources (all free, no key; cached in `cache/` with TTLs 2 min–24 h, ~0.12 s between live calls)
| Source | Used for |
|---|---|
| `site.api.espn.com/apis/site/v2/sports/{sport}/{league}/scoreboard?dates=` | slates, scores, **DraftKings odds** (ML/spread/total, open + current) |
| `.../summary?event=` | pickcenter odds (kept after the game = closing line for CLV), injuries, team leaders, ESPN matchup predictor (BPI/FPI), box scores (grading props) |
| `.../teams/{id}/schedule` | completed results → scoring averages, margin, last-5 form, rest/back-to-back |
| `.../injuries` | league injury reports (NFL, NBA, NHL, WNBA, MLB) |
| `site.web.api.espn.com/apis/v2/sports/.../standings` | league scoring average (Poisson baseline) |
| `site.web.api.espn.com/apis/common/v3/sports/.../athletes/{id}/gamelog` | player game logs for props (current + prior season) |
| `site.web.api.espn.com/apis/search/v2` | player name lookup |
| `statsapi.mlb.com`, `api-web.nhle.com` | probed by `sources` (reachable; reserved for MLB probable pitchers / NHL extras, not yet in models) |

Not available free: player-prop prices (no free feed; you supply them), tennis/golf/UFC odds (ESPN has none), multiple sportsbooks.

## Model method (simple, documented, conservative)
1. **Market**: American → implied prob; vig removed proportionally (2-way, or 3-way for soccer 1X2); fair odds = 1/no-vig prob.
2. **Points sports** (NFL, CFB, NBA, WNBA, NCAAB/W): team rating = points margin per game (70% season / 30% last 5),
   shrunk toward 0 by k pseudo-games (NFL/CFB 4, NCAA 6, WNBA 8, NBA 10). Projected margin = rating diff + home edge
   (NFL 1.7, CFB 2.5, NBA 2.3, NCAA 3.0; 0 at neutral sites) − back-to-back (NBA 1.5) − key injuries (team stat leader or QB out:
   2–4 pts, capped 5). If ESPN's matchup predictor exists, its win% is converted to a margin and blended 50/50.
   Win/cover prob = Normal(margin, sd) (sd: NFL 13.5, CFB 16, NBA 12.5, NCAAB 11). Totals = average of each offense vs the
   other's defense (75% season / 25% last 5), Normal with total sd.
3. **Goals sports** (NHL, soccer, MLB): Poisson attack/defence rates shrunk to this season's league average (from standings),
   home factor, NHL back-to-back. Score grid → 1X2 / ML (NHL/MLB ties split 52/48 as OT), puck line / handicap, totals, with pushes.
4. **Props**: ESPN game log (adds prior season if < 15 games). Projection = 60% last-10 mean + 40% sample mean.
   Poisson for low-count integer stats (mean ≤ 8), else Normal (sd ≥ 15% of mean). Final = 65% distribution + 35% smoothed L10 hit rate.
   Shows L5/L10/L20/all hit rates and an alt-line ladder of model fair prices.
5. **Shrink to market**: final prob = w·model + (1−w)·market no-vig. w = 0.5 / 0.4 / 0.25 for High/Medium/Low data quality
   (totals ×0.8; props 0.6/0.5/0.3). This deliberately keeps "edges" small: a box-score model is weaker than the market.
6. **Outputs per market**: model % (and raw), market no-vig %, edge (no-vig) **and edge at the actual price (vig included)**,
   EV per unit, fair odds, ¼-Kelly stake capped at 2% of bankroll (1u = 1%), tier, reasons, **case against**, **next step**
   (price at which it's still playable: EV ≥ +2%), and **CAUTION** list.
7. **Tiers**: High = edge ≥ 4 pp, EV ≥ 5%, high data quality, price ≤ +400. Medium = edge ≥ 2 pp, EV ≥ 2%, not low data quality.
   Each caution (thin data, uncertain key-player injury, line move against the pick, model > 12 pp from market) drops one tier and says so.

## Tracker (`tracker.db`, SQLite)
Each play: date, sport, event id, market, selection, side, line, odds, model/market prob, edge, EV, tier, stake units,
rationale (incl. case against + cautions), source (digest/manual), recommended flag, player/stat for props.
`track grade` settles from ESPN finals: ML/1X2, spreads, totals, props (box score), void if postponed/DNP; leaves unknowns pending
(`track grade --id N --result won|lost|push|void` for manual). Closing price from ESPN pickcenter → **CLV** = bet decimal × closing no-vig − 1
(only when the closing line equals your line). `track report` counts **recommended plays only** (use `--all` for everything),
by sport/market/tier/source, and warns when < 50 graded. `track signals` buckets by model win prob, edge, market and side,
hiding any bucket with n < 50 (`--min-n` to change).

## Using it from a front end (planned iPhone "prop builder" UI — same app)
All logic lives in the importable package `betlib/`; `betlib/api.py` returns plain JSON dicts for every feature:
```python
from betlib import api
api.slate("nba"); api.game("nba", "Knicks"); api.prop("nba", "Jalen Brunson", "pts", 26.5, -115, -105)
api.parlay(["nba:Suns:total:over", "nhl:Kings:ml:NSH"]); api.build("nfl", "chiefs", "sunday", legs=3, target=400, risk="balanced")
api.edges("all"); api.digest(log=False); api.track_list(); api.track_report(); api.track_signals(); api.track_grade()
```
A web UI would wrap these in a thin HTTP layer (e.g. FastAPI: `GET /slate/{sport}`, `GET /game/{sport}/{q}`, `POST /build`,
`POST /parlay`, `GET /track/report`) or shell out to `bet.py --json <cmd>`. Keep the engine server-side (box/cloud); the phone only renders JSON.

## Limitations (read these)
- Public box-score models are **much weaker than betting markets**. Most "edges" are model error; that's why results shrink toward the
  market and tiers are strict. Track CLV: if you don't beat the closing line over 100+ plays, the edges are not real.
- One odds source (DraftKings via ESPN); no line shopping. Lines refresh every few minutes; re-check before acting.
- No lineups, starting goalies/pitchers, weather, pace, travel, motivation or opponent-strength (SOS) adjustment beyond ESPN's predictor.
- Early season (college basketball in November) = thin data → mostly Low tier.
- Injuries: only flagged/adjusted when ESPN lists them; "key" = team statistical leader (or QB). College injuries are not available.
- Props: no free prop prices → you supply them, otherwise -110/-110 is assumed and labelled. Game logs ignore minutes/role changes.
- Tennis, golf, UFC, F1: schedules only (ESPN exposes no odds) → no model; use `odds` with your own probability.
- MLB is in the registry but off-season (Nov); its model ignores starting pitchers, so treat it as Low quality when the season starts.
- Same-game parlays: independence math is only an approximation; books' SGP prices differ.
- Research only. Not financial advice. Gambling problem? 1-800-GAMBLER.
