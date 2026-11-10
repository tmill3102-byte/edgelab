# EdgeLab data schema `edgelab.data/v1`

The GitHub Actions refresh writes these files under `site/data/`. The phone app only reads them. It never invents a price or a stat that is not in a file.

Times are US Eastern. American odds are numbers (`-110`, `140`). Probabilities are 0–1. `edge` is model probability minus the book's no-vig probability, in probability points (`0.021` = +2.1 pp).

Money, stakes, Kelly fractions and bankroll are not in these files.

## `meta.json`

| Field | Meaning |
|---|---|
| `generated_at` | ISO timestamp of the refresh (Eastern offset). |
| `generated_at_et` | Same moment, for the header. |
| `games_listed`, `games_analyzed`, `edges`, `legs` | Counts from that refresh. |
| `books` | Ohio books the app can show. `in_feed` is true only if this snapshot actually returned that book. `feed_note` explains a book the free Odds API plan does not carry. `home` is a public site, not a bet-slip API. |
| `odds_api` | Whether a snapshot was used, the sport and region of the one featured-odds call, quota headers (`x_requests_remaining`, `x_requests_used`, `x_requests_last`), and a plain-language `note`. |
| `disclaimer` | Research-only line. |

## `slate.json`

```json
{ "days": [ { "date": "2026-11-10", "key": "20261110", "label": "Today", "weekday": "tuesday", "sports": [] } ], "offseason": [] }
```

Each sport has `games` and, for tennis/golf/UFC/F1, `fields`.

A game on the slate is a short card: teams, records, `start_local`, `state`, `analyzed`, `odds_feed` (`espn`, `oddsapi`, or `none`), `lines` keyed by book, `badge` if a High/Medium edge exists at the modeled line, and `event_urls`. `empty_reason` is set when the free feed posted the game without a price. Field rows say schedule-only and carry no bet buttons.

## `games/{league}-{event_id}.json`

The game page. Includes `model_summary`, `flags`, `notes`, `injuries`, `form`, `markets`, and `props`.

`markets[]` is `{ market, sides: [{ side, offers }] }`. `offers` is keyed by bookmaker. An offer has:

`selection`, `line`, `odds`, `model_raw`, `model_prob`, `market_prob`, `fair_odds`, `edge`, `edge_at_price`, `ev`, `tier`, `data_quality`, `reasons`, `case_against`, `next_step`, `caution`, `flags`.

`model_prob` is the engine's market-shrunk probability. `ev` is expected return at that American price as a fraction of a 1-stake mathematical unit. The UI shows it only as a percent. If `model_prob` is null, the row is a posted line with no model. That happens when the refresh listed the game but did not run the model.

`props[]` exists only when The Odds API returned a real prop price. Each prop has the player, stat, line, projection, `hit_rates` (`L5`, `L10`, `L20`, `all`), recent game-log values, a `ladder` of model fair prices (explicitly not book prices), and per-side `offers`.

## `legs.json`

Builder candidates. One leg per modeled side at the primary book's line. Other books are included only when their line matches. Important fields: `id`, `event_id`, `weekday`, `date_et`, `matchup`, team names, `market`, `side`, `selection`, `primary_book`, `offers`, `odds_feed`, `event_urls`, and for props `player`, `prop_key`, `hit_rate`.

## `edges.json`

High and Medium sides with positive edge and positive expected return at the primary book, best first. Each row embeds the `leg` so the explanation can open without another file. Low-tier leans are not listed.

## `report.json` and `tracker.json`

`report.json` is the recommended-play record graded from ESPN finals:

- `overall.record` is `W-L-P`.
- `hit_rate` is wins / (wins + losses).
- `roi_pct` is the return if every graded play risked the same stake at the listed American odds. It is not dollars.
- `clv_avg_pct` is the average closing-line value, only when the close is the same number that was logged.
- `model` compares average model probability with the actual win rate, plus a Brier score and a direction hit rate.
- `by.sport`, `by.market`, `by.tier` repeat those fields.
- `warning` is set while graded plays are under 50.

`tracker.json` lists `pending` and `graded` plays (selection, odds, tier, status, CLV). The SQLite file `betting/tracker.db` is the store the engine grades. The JSON is the export the phone reads. Re-running the refresh does not duplicate a play with the same date, sport, event, market, selection and source.

## `odds-check.json` and `odds-snapshot.json`

Written by `scripts/verify_odds.py`. The check file is the safe log: key present or not, HTTP status, quota headers, which Ohio books came back. It never contains the key. The snapshot is the one `regions=us` featured-odds response (h2h, spreads, totals for a single sport) with affiliate query strings removed from stored links where the publisher can parse them. `publish.py` reads the snapshot and does not call that endpoint again.

## Same-game correlation

The phone does this. It is not a second model on the server.

For legs in one game, the hit chance is not the product of the leg probabilities. Each added leg is joined to the running parlay with the strongest documented correlation:

`P(A and B) = P(A)P(B) + ρ √[P(A)(1−P(A))P(B)(1−P(B))]`

clamped to the range that is mathematically possible. ρ is fixed and small:

| Pair | ρ |
|---|---|
| Same-team moneyline and spread | +0.75 |
| Opposite-team moneyline and spread | −0.55 |
| Favorite and over | +0.25 |
| Underdog and under | +0.22 |
| Favorite and under | −0.12 |
| Quarterback passing and a teammate's receiving | +0.55 |
| Two props on the same player | +0.28 |
| Player points and that team's side | +0.30 |
| Points or passing yards and the over | +0.35 |
| Teammate props | +0.15 |

Different games are then multiplied. That treats SGPx games as independent. The number is a research adjustment, not the correlation a book uses when it prices an SGP. The card says so. If no combo falls in a tier, the tier is left empty.

## What a missing number means

Empty odds, a null edge, or an absent book are data. The app is not supposed to fill them in.
