"""Credit planner for The Odds API free tier.

A live odds call costs ``markets × regions``. ``/sports`` and ``/events`` are free.
Historical odds are not used. The free plan is 500 credits a month.
"""

from __future__ import annotations

import calendar
import datetime as dt

FREE_MONTHLY = 500
RESERVE = 40
FEATURED_MARKETS = ("h2h", "spreads", "totals")
FEATURED_TTL_HOURS = 24
PROP_TTL_HOURS = 12
# Show a cached prop board until the next day even if we do not pay to refresh it.
PROP_KEEP_HOURS = 36

# (api market, engine stat, label). Order is the priority inside a sport.
# Cost of one event = len(markets) × regions. regions is 1 (us).
PROP_MARKETS = {
    "basketball_nba": (
        ("player_points", "pts", "Points"),
        ("player_rebounds", "reb", "Rebounds"),
        ("player_assists", "ast", "Assists"),
        ("player_threes", "threes", "Threes"),
        ("player_points_rebounds_assists", "pra", "PRA"),
    ),
    "americanfootball_nfl": (
        ("player_pass_yds", "pass_yds", "Pass yds"),
        ("player_rush_yds", "rush_yds", "Rush yds"),
        ("player_reception_yds", "rec_yds", "Rec yds"),
        ("player_anytime_td", "anytime_td", "Anytime TD"),
    ),
    "icehockey_nhl": (
        ("player_points", "pts", "Points"),
        ("player_shots_on_goal", "sog", "Shots"),
        ("player_assists", "ast", "Assists"),
    ),
    "baseball_mlb": (
        ("batter_hits", "hits", "Hits"),
        ("pitcher_strikeouts", "k", "Strikeouts"),
        ("batter_total_bases", "tb", "Total bases"),
    ),
}
PRIORITY = (
    "basketball_nba",
    "americanfootball_nfl",
    "icehockey_nhl",
    "baseball_mlb",
)


def call_cost(n_markets, regions=1):
    """The Odds API live-odds cost. Empty responses are not charged; budget for the ask."""
    return max(0, int(n_markets)) * max(1, int(regions))


def days_left(day):
    """Days left in the calendar month, including ``day``."""
    if isinstance(day, dt.datetime):
        day = day.date()
    return max(1, calendar.monthrange(day.year, day.month)[1] - day.day + 1)


def featured_cost():
    return call_cost(len(FEATURED_MARKETS), 1)


def prop_cost(sport):
    markets = PROP_MARKETS.get(sport) or ()
    return call_cost(len(markets), 1)


def plan_credits(remaining, active, days_left, featured_due, candidates):
    """Decide which featured snapshots and which prop events to buy.

    ``remaining`` is ``x-requests-remaining`` before this run.
    ``active`` is sport keys ``/sports`` currently marks active.
    ``featured_due`` is active priority sports whose snapshot is older than a day.
    ``candidates`` is upcoming events that are not already in the prop cache,
    dicts with ``sport`` and ``event_id``, best sport first.

    Featured games for other sports stay on ESPN DraftKings lines.
    """
    ordered = [sport for sport in PRIORITY if sport in set(active or [])]
    due = [sport for sport in ordered if sport in set(featured_due or [])]
    left = int(remaining or 0)
    featured = []
    for sport in due:
        cost = featured_cost()
        if left - cost < RESERVE:
            break
        featured.append(sport)
        left -= cost

    future_days = max(0, int(days_left) - 1)
    future_featured = len(ordered) * featured_cost() * future_days
    prop_pool = left - RESERVE - future_featured
    prop_today = max(0, prop_pool // max(1, int(days_left)))

    props = []
    spent = 0
    for cand in candidates or []:
        sport = cand.get("sport")
        cost = prop_cost(sport)
        if cost <= 0:
            continue
        if spent + cost > prop_today:
            continue
        if left - spent - cost < RESERVE:
            break
        markets = PROP_MARKETS[sport]
        props.append({
            "sport": sport,
            "event_id": cand.get("event_id"),
            "home_team": cand.get("home_team"),
            "away_team": cand.get("away_team"),
            "commence_time": cand.get("commence_time"),
            "markets": markets,
            "cost": cost,
        })
        spent += cost

    per_game = {sport: prop_cost(sport) for sport in ordered}
    if ordered:
        busiest = max(per_game.values())
        games_a_day = prop_today // busiest if busiest else 0
    else:
        games_a_day = 0
    return {
        "featured": featured,
        "props": props,
        "remaining_before": int(remaining or 0),
        "reserve": RESERVE,
        "future_featured": future_featured,
        "prop_pool": prop_pool,
        "prop_today": prop_today,
        "prop_spent": spent,
        "games_today": len(props),
        "cost_per_game": per_game,
        "active": ordered,
        "days_left": int(days_left),
        "free_monthly": FREE_MONTHLY,
        "games_a_day_if_dearest": games_a_day,
    }


def espn_labeled_props(items):
    """Keep a prop row only when the feed names the side.

    ESPN's public DraftKings ``propBets`` feed returns two American prices for a
    line and does not say which is Over and which is Under. Those rows are
    dropped. A labeled ``side`` of over/under/yes/no with a real American price
    is kept. Nothing is filled in.
    """
    kept = []
    for item in items or []:
        side = str(item.get("side") or "").strip().lower()
        if side not in ("over", "under", "yes", "no"):
            continue
        odds = item.get("odds") or {}
        american = odds.get("american")
        price = american.get("value") if isinstance(american, dict) else american
        try:
            price_n = float(str(price).replace("+", ""))
        except (TypeError, ValueError):
            continue
        target = ((item.get("current") or {}).get("target") or {}).get("value")
        if target is None:
            target = (odds.get("total") or {}).get("value") if isinstance(odds.get("total"), dict) else None
        if side in ("over", "under") and target is None:
            continue
        kept.append({
            "side": side,
            "price": price_n,
            "line": float(target) if target is not None else 0.5,
            "type": (item.get("type") or {}).get("name"),
            "player": item.get("player"),
        })
    return kept
