# EdgeLab

Personal sports-betting **research** app. It reads public odds and stats, explains a side, and helps build a parlay. It never takes a bet and it never suggests a stake.

NBA, NHL, NFL, college football, and MLB use engine v2. An edge is shown only where the backtest earned weight: NBA moneyline, NBA total, and NHL puck line. Other markets still show the model number and sit on the market price. Details are in `betting/BACKTEST.md`.

The phone app is a static PWA. A scheduled GitHub Action runs the Python engine, writes JSON into `site/data/`, and (once you turn Pages on) serves that folder. There is no subscription and no paid API except the optional free tier of [The Odds API](https://the-odds-api.com/), which you can skip.

## Install on an iPhone

This works only after GitHub Pages is serving the site (see the owner steps below).

1. Open the Pages URL in Safari. It will look like `https://tmill3102-byte.github.io/edgelab/`.
2. Tap the Share button.
3. Tap **Add to Home Screen**.
4. Open EdgeLab from the icon. It runs full screen and keeps the last slate if you are offline.

The data timestamp in the header is the last successful refresh, Eastern time. If the phone cannot reach the site, it shows the copy it saved last time.

## What you can do

- **Today** — slate by sport and day, with a team filter. A card with no price says so.
- **Edges** — High only, or High and Medium. Tap a row for the full note: numbers, why, the case against, the next step, and caution flags.
- **Game** — moneyline, spread, and total. Each side shows the price and the model edge. Tap a side for the explanation, then add it to the slip. Player props appear when a real prop price was fetched. If this game was not in the budget, the screen says "Props not loaded for this game yet."
- **SGP** — same-game parlays for each game: Safer (about 35% or better), Balanced (about 15–30%), Longshot (under 10%), and Lotto (under 3%). The hit chance is adjusted for correlation instead of multiplying the legs. Each card shows the legs, that hit chance, the best book's multiplied price when every leg is listed, the edge versus that price, and the weakest leg. A missing tier means no card landed in the band. **SGPx** stacks 2–3 of those cards from different games. One tap puts the legs on the slip. Books price SGPs with their own correlation, so a real SGP price can differ from the multiplied leg prices.
- **Builder** — type something like `safe 4 leg parlay browns sunday +400`, or use the controls. Safe, Balanced, and Aggressive are priced differently: Safe keeps the highest hit chance and short prices, and it may finish under the target. Balanced aims at the target with middling prices. Aggressive uses plus-money legs. The three hit chances are shown side by side, and each leg shows its own hit chance. Once you tap the risk control, that choice wins over the sentence. Same-game cards stay on the SGP tab.
- **Slip** — one card per Ohio book that the feed can speak for. A card shows how many legs that book actually priced (`4/4 bets`) and the combined price estimated by multiplying leg prices. Books that do not offer a leg are dimmed. The best estimated price is selected. **Open in** copies the slip and opens that book's public event page when every leg is the same game and the feed included a link. Otherwise it opens the book's public home. Pre-filled bet slips are not supported.
- **Tracker** — record (W-L-P), hit rate, model accuracy, CLV, and ROI as a percent at the listed odds. There is no unit size and no dollar figure. Under 50 graded plays it warns you. **My plays** stay on the phone and are not graded.

## Owner setup

Do these in the GitHub repo settings. The app cannot turn them on for you.

1. **Pages** — Settings → Pages → Build and deployment → Source: **GitHub Actions**.
2. **Actions write** — Settings → Actions → General → Workflow permissions → **Read and write permissions**. The refresh job commits `site/data/` and `betting/tracker.db`. The workflow file also sets `contents: write`, which only works if this repo setting allows it.
3. **Secret** — Settings → Secrets and variables → Actions → New repository secret. Name: `ODDS_API_KEY`. Value: a free key from https://the-odds-api.com/. Do not put the key in the repo. The workflow reads `${{ secrets.ODDS_API_KEY }}`. If the secret is missing, the refresh still publishes ESPN/DraftKings lines and the app shows only DraftKings.

The scheduled workflow is on the default branch only. It runs at 8am, 11am, 2pm, 5pm, 8pm, and 11pm Eastern Standard Time. In summer those runs shift an hour later because GitHub schedules in UTC. You can also run it with **Actions → refresh → Run workflow**.

The deploy job runs only on `main`, after a refresh. Until Pages source is GitHub Actions, that job has nothing to publish to.

## How the refresh spends credits

The free Odds API plan is 500 credits a month. A live odds call costs **markets × regions**. `/sports` and `/events` are free. This repo keeps a 40-credit reserve so a run cannot drain the account to zero. The planner is `scripts/odds_budget.py`.

**Featured lines.** One snapshot per in-season major sport per day: `h2h`, `spreads`, `totals`, `regions=us`. That is 3 credits per sport. NBA, NFL, and NHL together are 9 credits a day, **270 a month**. MLB adds another 3 a day when it is in season. A snapshot newer than 24 hours is reused. Other sports stay on ESPN DraftKings lines.

**Props.** What is left after featured odds and the reserve is the prop budget. With three majors in season that is 500 − 270 − 40 = **190 credits a month**.

| Sport | Markets | Credits per game |
|---|---|---|
| NBA | points, rebounds, assists, threes, PRA | 5 |
| NFL | passing, rushing, and receiving yards, anytime TD | 4 |
| NHL | points, shots, assists | 3 |
| MLB | hits, pitcher strikeouts, total bases | 3 |

190 ÷ 5 = 38 NBA-sized games a month, about **1 to 2 games a day**. The planner buys today's share (`prop credits left ÷ days left in the month`) and skips a game it cannot afford. A cached board is reused for 12 hours, so the same game is not bought on every refresh, and it stays on the slate for 36 hours. A push does not buy props. The schedule and a manual run do.

That is not a full slate. A busy day of 15 NBA games, 8 NFL games, and 10 NHL games is 15×5 + 8×4 + 10×3 = **137 credits**, about **4,110 a month** before featured odds, or about **4,380** with them. The free tier cannot cover that.

The Odds API **$30 / month plan is 20,000 credits**. That pays for the full NBA, NFL, and NHL prop slate twice a day (about 8,500 credits) and the featured snapshots, with room left.

**What was not used.** ESPN's public DraftKings `propBets` feed does return American prices, but it does not label Over versus Under, so those rows are dropped rather than guessed. DraftKings' own website JSON is not a documented public API and is not called. No prop price is invented.

The log prints `key_present`, `key_valid`, `x-requests-remaining`, `x-requests-used`, the sport, and the event id. It never prints the key.

## Project layout

| Path | Role |
|---|---|
| `betting/` | Research engine (`bet.py`, `betlib/`). Behavior is unchanged aside from a public event URL on parsed odds, repricing a fitted model at another book's real line, and an optional `EDGE_TRACKER_DB` path. |
| `betting/tracker.db` | SQLite history the engine grades. Committed so it survives between runs. |
| `site/` | The PWA. |
| `site/data/` | JSON the phone reads. Schema: [SCHEMA.md](SCHEMA.md). |
| `scripts/verify_odds.py` | The cheap key check and the single US odds call. |
| `scripts/publish.py` | Builds the JSON. `--quick` is a shorter local run. |
| `.github/workflows/refresh.yml` | Schedule, manual run, and branch push. |

Local check, from the repo root, with Python 3.11+ and `pip install -r requirements.txt`:

```bash
python3 scripts/publish.py --quick
cd site && python3 -m http.server 8765
```

## Limitations

- The model is a public box-score model shrunk toward the market. A "High" tier is still mostly model error until CLV over a large sample says otherwise. The tracker says this while the sample is under 50 graded plays.
- One free odds snapshot covers one sport at a time. Other sports stay on ESPN's DraftKings prices. The slip does not pretend FanDuel priced a game the snapshot never asked about.
- Caesars and Fanatics are on The Odds API's paid plan. bet365 has no US book in that API. theScore (formerly ESPN BET) and Hard Rock Ohio are in region `us2`, not `us`. Until a run spends a call on `us2`, those cards are absent rather than filled with guessed numbers. The combined price on a card is the product of leg prices, not the book's parlay quote, and same-game parlays are correlated.
- There is no line shopping history beyond the open/current numbers ESPN already sends. No weather, no confirmed goalies or pitchers, no lineup. College injury reports are not in the free feed.
- Props show up only after a budgeted Odds API call, with hit rates from ESPN game logs. The free tier covers about 1–2 games a day. ESPN's public prop feed is not used because it does not label over versus under. The alternate-line ladder is the model's fair price, not a book price.
- Tennis, golf, UFC, and F1 are schedules only. ESPN does not put odds on them here, so there is no model.
- "Open in" uses a public event URL when the feed included one (query strings that would pre-fill a bet slip are stripped) or else the book's public home. It does not call a private sportsbook API.
- Research only. No guarantees. If gambling is a problem, call 1-800-GAMBLER.
