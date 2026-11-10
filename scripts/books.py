"""Ohio sportsbooks EdgeLab will show. Home URLs are public sites, not bet-slip APIs.

Text marks in the UI are names, not official logos. A book with no feed note still
appears when a game was priced by The Odds API, so a missing price is visible.
"""

BOOKS = [
    {
        "key": "draftkings",
        "name": "DraftKings",
        "short": "DK",
        "home": "https://sportsbook.draftkings.com/",
        "region": "us",
    },
    {
        "key": "fanduel",
        "name": "FanDuel",
        "short": "FD",
        "home": "https://sportsbook.fanduel.com/",
        "region": "us",
    },
    {
        "key": "betmgm",
        "name": "BetMGM",
        "short": "MGM",
        "home": "https://www.oh.betmgm.com/en/sports",
        "region": "us",
    },
    {
        "key": "williamhill_us",
        "also": ["caesars"],
        "name": "Caesars",
        "short": "CZR",
        "home": "https://sportsbook.caesars.com/us/oh/bet/",
        "region": "us",
        "feed_note": "Caesars is on The Odds API paid plan only, so the free key does not return it.",
    },
    {
        "key": "bet365",
        "name": "bet365",
        "short": "365",
        "home": "https://www.oh.bet365.com/",
        "region": None,
        "feed_note": "The Odds API has no US bet365 book, so Ohio bet365 lines are not in this feed.",
    },
    {
        "key": "fanatics",
        "name": "Fanatics",
        "short": "FAN",
        "home": "https://sportsbook.fanatics.com/",
        "region": "us",
        "feed_note": "Fanatics is on The Odds API paid plan only, so the free key does not return it.",
    },
    {
        "key": "espnbet",
        "name": "theScore",
        "short": "SCR",
        "home": "https://sportsbook.thescore.bet/",
        "region": "us2",
        "feed_note": "Formerly ESPN BET. The Odds API lists it as espnbet in region us2, not us.",
    },
    {
        "key": "hardrockbet_oh",
        "also": ["hardrockbet"],
        "name": "Hard Rock",
        "short": "HR",
        "home": "https://www.hardrock.bet/sportsbook/",
        "region": "us2",
        "feed_note": "Ohio Hard Rock is hardrockbet_oh in region us2, not the us region.",
    },
    {
        "key": "betrivers",
        "name": "BetRivers",
        "short": "BR",
        "home": "https://oh.betrivers.com/",
        "region": "us",
    },
    {
        "key": "ballybet",
        "name": "Bally Bet",
        "short": "BAL",
        "home": "https://play.ballybet.com/",
        "region": "us2",
        "feed_note": "Bally Bet is in region us2. Shown when that region is in the snapshot.",
    },
]


def keys_of(book):
    return [book["key"]] + list(book.get("also") or [])


def find_book(api_key):
    for book in BOOKS:
        if api_key in keys_of(book):
            return book
    return None


def catalog(seen_keys):
    seen = set(seen_keys or [])
    rows = []
    for book in BOOKS:
        present = any(k in seen for k in keys_of(book))
        row = {
            "key": book["key"],
            "also": list(book.get("also") or []),
            "name": book["name"],
            "short": book["short"],
            "home": book["home"],
            "region": book.get("region"),
            "in_feed": present,
        }
        if book.get("feed_note") and not present:
            row["feed_note"] = book["feed_note"]
        rows.append(row)
    return rows
