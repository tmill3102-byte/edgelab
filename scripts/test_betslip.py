"""Betslip URL shape. A live DraftKings GET is optional."""

import json
import os
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from dk_props import lines_from_catalog


def draftkings_link(event_id, sids):
    parts = [str(sid).replace("#", "%23") for sid in sids if sid]
    if not event_id or not parts:
        return None
    return f"https://sportsbook.draftkings.com/event/{event_id}?outcomes={'+'.join(parts)}"


def test_hash_is_encoded_and_plus_is_the_separator():
    url = draftkings_link("34983855", ["0ML1_1", "0OU#2"])
    assert url == "https://sportsbook.draftkings.com/event/34983855?outcomes=0ML1_1+0OU%232"


def test_lines_from_a_small_board():
    catalog = {
        "events": [{"id": "34983855", "name": "MIL Bucks @ NY Knicks", "participants": [
            {"name": "NY Knicks", "type": "Team", "venueRole": "Home"},
            {"name": "MIL Bucks", "type": "Team", "venueRole": "Away"},
        ]}],
        "markets": [
            {"id": "ml", "eventId": "34983855", "name": "Moneyline"},
            {"id": "ou", "eventId": "34983855", "name": "Total"},
        ],
        "selections": [
            {"id": "0ML87151635_1", "marketId": "ml", "label": "NY Knicks", "outcomeType": "Home", "displayOdds": {"american": "−1040"}},
            {"id": "0OU87151635O22150_1", "marketId": "ou", "label": "Over", "outcomeType": "Over", "points": 221.5, "displayOdds": {"american": "−115"}},
        ],
    }
    lines = lines_from_catalog(catalog)["34983855"]
    assert lines["ml"]["home"]["sid"] == "0ML87151635_1"
    assert lines["total"]["over"]["sid"] == "0OU87151635O22150_1"
    url = draftkings_link("34983855", [lines["ml"]["home"]["sid"], lines["total"]["over"]["sid"]])
    assert "outcomes=0ML87151635_1+0OU87151635O22150_1" in url


def live_get():
    """Fetch the real Knicks link. Not part of the default unit run."""
    url = draftkings_link("34983855", ["0ML87151635_1", "0OU87151635O22150_1"])
    request = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1",
        "Accept": "text/html",
    })
    with urllib.request.urlopen(request, timeout=25) as response:
        body = response.read(800).decode("utf-8", "replace")
        print(json.dumps({"url": url, "status": response.status, "final": response.geturl(), "snippet": body[:180]}))


if __name__ == "__main__":
    test_hash_is_encoded_and_plus_is_the_separator()
    test_lines_from_a_small_board()
    print("ok")
    if os.environ.get("BETSLIP_LIVE") == "1":
        live_get()
