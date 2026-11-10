"""Locks ESPN odds parsing, including the total-line prefix and public event URL."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from betlib.espn import parse_odds, public_event_url


class PublicUrlTests(unittest.TestCase):
    def test_strips_betslip_query(self):
        href = (
            "https://sportsbook.draftkings.com/gateway?s=__s__&wpcid=__wpcid__"
            "&preurl=https%3A%2F%2Fsportsbook.draftkings.com%2Fevent%2F34983855%3Foutcomes%3D0HC87151635N1550_1"
        )
        self.assertEqual(public_event_url(href), "https://sportsbook.draftkings.com/event/34983855")

    def test_rejects_unknown_host(self):
        self.assertIsNone(public_event_url("https://example.com/event/1"))

    def test_ohio_state_placeholder_and_betslip_params(self):
        self.assertEqual(
            public_event_url("https://{state}.betrivers.com/?page=sportsbook#event/1028754081"),
            "https://oh.betrivers.com/?page=sportsbook#event/1028754081",
        )
        self.assertEqual(
            public_event_url("https://sports.{state}.betmgm.com/en/sports/events/bucks-at-knicks-20050890"),
            "https://sports.oh.betmgm.com/en/sports/events/bucks-at-knicks-20050890",
        )
        self.assertIsNone(public_event_url("https://sportsbook.fanduel.com/addToBetslip?marketId=1&selectionId=2"))
        self.assertEqual(
            public_event_url("https://sportsbook.draftkings.com/?outcomes=0ML87151635_3"),
            "https://sportsbook.draftkings.com/",
        )

    def test_parse_prefixed_total_and_spread(self):
        parsed = parse_odds({
            "provider": {"name": "DraftKings"},
            "details": "NY -15.5",
            "link": {"href": "https://sportsbook.draftkings.com/gateway?preurl=https%3A%2F%2Fsportsbook.draftkings.com%2Fevent%2F34983855%3Foutcomes%3Dabc"},
            "moneyline": {
                "home": {"close": {"odds": "-1040"}},
                "away": {"close": {"odds": "+670"}},
            },
            "pointSpread": {
                "home": {"close": {"line": "-15.5", "odds": "-111"}},
                "away": {"close": {"line": "+15.5", "odds": "-109"}},
            },
            "total": {
                "over": {"close": {"line": "o220.5", "odds": "-115"}},
                "under": {"close": {"line": "u220.5", "odds": "-105"}},
            },
        })
        self.assertEqual(parsed["total"], 220.5)
        self.assertEqual(parsed["over_odds"], -115)
        self.assertEqual(parsed["under_odds"], -105)
        self.assertEqual(parsed["spread_home"], -15.5)
        self.assertEqual(parsed["ml_away"], 670)
        self.assertEqual(parsed["event_url"], "https://sportsbook.draftkings.com/event/34983855")


if __name__ == "__main__":
    unittest.main()
