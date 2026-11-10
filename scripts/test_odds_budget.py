"""Credit planner stays inside the free tier and rejects unlabeled ESPN props."""

import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from odds_budget import call_cost, days_left, espn_labeled_props, plan_credits, prop_cost


def test_cost_is_markets_times_regions():
    assert call_cost(3, 1) == 3
    assert call_cost(5, 1) == 5
    assert call_cost(4, 2) == 8
    assert prop_cost("basketball_nba") == 5
    assert prop_cost("americanfootball_nfl") == 4


def test_full_month_stays_inside_500():
    active = ["basketball_nba", "americanfootball_nfl", "icehockey_nhl"]
    candidates = [{"sport": "basketball_nba", "event_id": str(i)} for i in range(12)]
    candidates += [{"sport": "americanfootball_nfl", "event_id": "n" + str(i)} for i in range(8)]
    remaining = 500
    featured = props = games = 0
    for day in range(1, 31):
        when = dt.date(2026, 11, day)
        plan = plan_credits(remaining, active, days_left(when), active, candidates)
        spend = len(plan["featured"]) * 3 + plan["prop_spent"]
        featured += len(plan["featured"]) * 3
        props += plan["prop_spent"]
        games += plan["games_today"]
        remaining -= spend
        assert remaining >= 40
    assert featured == 270
    assert props == 190
    assert remaining == 40
    assert 30 <= games <= 50


def test_espn_unlabeled_pair_is_dropped():
    rows = espn_labeled_props([
        {"type": {"name": "Total Points"}, "odds": {"american": {"value": "-108"}, "total": {"value": "4.5"}}, "current": {"target": {"value": 4.5}}},
        {"type": {"name": "Total Points"}, "odds": {"american": {"value": "-118"}, "total": {"value": "4.5"}}, "current": {"target": {"value": 4.5}}},
    ])
    assert rows == []
    kept = espn_labeled_props([
        {"side": "over", "player": "A", "type": {"name": "Total Points"}, "odds": {"american": {"value": "-110"}}, "current": {"target": {"value": 24.5}}},
    ])
    assert kept[0]["side"] == "over" and kept[0]["price"] == -110 and kept[0]["line"] == 24.5


if __name__ == "__main__":
    test_cost_is_markets_times_regions()
    test_full_month_stays_inside_500()
    test_espn_unlabeled_pair_is_dropped()
    print("ok")
