"""DraftKings prop parsing. The live feed is checked by scripts/dk_props.py refresh."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from dk_props import american, juice_ok, merge_prop_payload, parse_board


def test_unicode_minus_and_juice():
    assert american("−118") == -118
    assert american("+101") == 101
    assert juice_ok(-118, -108)
    assert juice_ok(-110, -116)
    assert not juice_ok(-500, -500)


def test_unlabelled_ladder_is_dropped():
    data = {
        "events": [{"id": "1", "name": "A @ B", "participants": []}],
        "markets": [{"id": "m", "eventId": "1", "name": "Player Receiving Yards"}],
        "selections": [{
            "marketId": "m",
            "label": "5+",
            "outcomeType": None,
            "points": None,
            "displayOdds": {"american": "−113"},
            "participants": [{"name": "Theo Johnson", "type": "Player"}],
        }],
    }
    rows, dropped = parse_board(data, ("Rec Yards O/U", "rec_yds", "Rec yds", "player_reception_yds", "ou"))
    assert rows == [] and dropped == 0


def test_labelled_pair_kept_and_anytime_yes():
    data = {
        "events": [{"id": "1", "name": "MIL Bucks @ NY Knicks", "participants": [
            {"name": "NY Knicks", "type": "Team", "venueRole": "Home"},
            {"name": "MIL Bucks", "type": "Team", "venueRole": "Away"},
        ]}],
        "markets": [{"id": "m", "eventId": "1", "name": "Jalen Brunson Points O/U"}],
        "selections": [
            {"marketId": "m", "label": "Over", "outcomeType": "Over", "points": 25.5, "displayOdds": {"american": "−118"}, "participants": [{"name": "Jalen Brunson", "type": "Player"}]},
            {"marketId": "m", "label": "Under", "outcomeType": "Under", "points": 25.5, "displayOdds": {"american": "−108"}, "participants": [{"name": "Jalen Brunson", "type": "Player"}]},
        ],
    }
    rows, dropped = parse_board(data, ("Points O/U", "pts", "Points", "player_points", "ou"))
    assert dropped == 0 and rows[0]["over"] == -118 and rows[0]["under"] == -108
    td = {
        "events": data["events"],
        "markets": [{"id": "t", "eventId": "1", "name": "Anytime TD Scorer"}, {"id": "f", "eventId": "1", "name": "First TD Scorer"}],
        "selections": [
            {"marketId": "t", "label": "Jahmyr Gibbs", "outcomeType": "Anytime Scorer", "points": None, "displayOdds": {"american": "+140"}, "participants": [{"name": "Jahmyr Gibbs", "type": "Player"}]},
            {"marketId": "f", "label": "Jahmyr Gibbs", "outcomeType": "First Scorer", "points": None, "displayOdds": {"american": "+600"}, "participants": [{"name": "Jahmyr Gibbs", "type": "Player"}]},
        ],
    }
    yes, _missed = parse_board(td, ("TD Scorer", "anytime_td", "Anytime TD", "player_anytime_td", "anytime"))
    assert len(yes) == 1 and yes[0]["yes"] == 140 and yes[0]["player"] == "Jahmyr Gibbs"


def test_merge_prefers_draftkings_feed():
    api = {"bookmakers": [
        {"key": "draftkings", "markets": [{"key": "player_points", "outcomes": [{"name": "Over", "price": -110}]}]},
        {"key": "fanduel", "markets": [{"key": "player_points", "outcomes": [{"name": "Over", "price": -105}]}]},
    ], "_markets": [["player_points", "pts", "Points"]]}
    dk = {"bookmakers": [{"key": "draftkings", "markets": [{"key": "player_points", "outcomes": [{"name": "Over", "price": -118}]}]}], "_markets": [["player_points", "pts", "Points"]]}
    merged = merge_prop_payload(api, dk)
    dk_book = next(book for book in merged["bookmakers"] if book["key"] == "draftkings")
    fd_book = next(book for book in merged["bookmakers"] if book["key"] == "fanduel")
    assert dk_book["markets"][0]["outcomes"][0]["price"] == -118
    assert fd_book["markets"][0]["outcomes"][0]["price"] == -105
    dk["dk_event_id"] = "34983855"
    assert merge_prop_payload(api, dk)["dk_event_id"] == "34983855"


if __name__ == "__main__":
    test_unicode_minus_and_juice()
    test_unlabelled_ladder_is_dropped()
    test_labelled_pair_kept_and_anytime_yes()
    test_merge_prefers_draftkings_feed()
    print("ok")
