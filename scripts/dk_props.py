"""DraftKings player props from the anonymous sportsbook JSON.

These are the same GET requests a logged-out browser makes for
sportsbook.draftkings.com in the Ohio region (site ``dkusoh``). No cookies,
no tokens, no proxy. If the feed answers with a block or a challenge page,
fetching stops.

A league board is one request. Each prop market is one more. Results are
cached for 12 hours, so a refresh usually makes no requests.
"""

from __future__ import annotations

import datetime as dt
import json
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "site" / "data"
CACHE_PATH = DATA / "dk-props-cache.json"
BASE = "https://sportsbook-nash.draftkings.com/api/sportscontent/dkusoh/v1/leagues"
TTL_HOURS = 12
MAX_REQUESTS = 16
PAUSE_SECONDS = 0.4
UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1"
)

# (subcategory name, engine stat, label, odds-api market key, mode)
MARKETS = {
    "nba": (
        ("Points O/U", "pts", "Points", "player_points", "ou"),
        ("Rebounds O/U", "reb", "Rebounds", "player_rebounds", "ou"),
        ("Assists O/U", "ast", "Assists", "player_assists", "ou"),
        ("Threes O/U", "threes", "Threes", "player_threes", "ou"),
        ("Pts + Reb + Ast O/U", "pra", "PRA", "player_points_rebounds_assists", "ou"),
    ),
    "nfl": (
        ("Pass Yards O/U", "pass_yds", "Pass yds", "player_pass_yds", "ou"),
        ("Rush Yards O/U", "rush_yds", "Rush yds", "player_rush_yds", "ou"),
        ("Rec Yards O/U", "rec_yds", "Rec yds", "player_reception_yds", "ou"),
        ("TD Scorer", "anytime_td", "Anytime TD", "player_anytime_td", "anytime"),
    ),
    "nhl": (
        ("Points O/U", "pts", "Points", "player_points", "ou"),
        ("Shots on Goal O/U", "sog", "Shots", "player_shots_on_goal", "ou"),
        ("Assists O/U", "ast", "Assists", "player_assists", "ou"),
    ),
    "mlb": (
        ("Hits O/U", "hits", "Hits", "batter_hits", "ou"),
        ("Strikeouts O/U", "k", "Strikeouts", "pitcher_strikeouts", "ou"),
        ("Total Bases O/U", "tb", "Total bases", "batter_total_bases", "ou"),
    ),
}
LEAGUE_IDS = {"nba": "42648", "nfl": "88808", "nhl": "42133", "mlb": "84240"}
SPORT_KEYS = {
    "nba": "basketball_nba",
    "nfl": "americanfootball_nfl",
    "nhl": "icehockey_nhl",
    "mlb": "baseball_mlb",
}
ORDER = ("nba", "nfl", "nhl", "mlb")


class FeedBlocked(RuntimeError):
    """The public feed refused the request or returned a challenge page."""


def american(value):
    if value is None:
        return None
    text = str(value).strip().replace("−", "-").replace("–", "-").replace("—", "-").replace("+", "")
    if not text or text in ("-", "even", "EV"):
        return None
    try:
        return int(round(float(text)))
    except ValueError:
        return None


def implied(price):
    price = american(price)
    if price is None or price == 0:
        return None
    if price > 0:
        return 100 / (price + 100)
    return (-price) / (-price + 100)


def juice_ok(over, under):
    """Raw implied probabilities of a two-sided price should sum a little over 1."""
    left, right = implied(over), implied(under)
    if left is None or right is None:
        return False
    total = left + right
    return 1.01 <= total <= 1.25


def _parse_time(value):
    if not value:
        return None
    text = str(value).strip().replace("Z", "+00:00")
    if "." in text:
        head, tail = text.split(".", 1)
        frac = tail
        tz = ""
        for mark in ("+", "-"):
            if mark in tail[1:]:
                frac, rest = tail.split(mark, 1)
                tz = mark + rest
                break
        text = f"{head}.{frac[:6]}{tz}"
    try:
        return dt.datetime.fromisoformat(text)
    except ValueError:
        return None


def _blocked_body(raw, content_type):
    ctype = (content_type or "").lower()
    sample = raw[:400].decode("utf-8", "replace").lower()
    if "json" not in ctype:
        return True
    markers = ("just a moment", "cf-browser-verification", "attention required", "access denied", "akamai", "<html")
    return any(marker in sample for marker in markers)


def _get(url, counter):
    if counter["n"] >= MAX_REQUESTS:
        counter["capped"] = True
        return None
    if counter["n"]:
        time.sleep(PAUSE_SECONDS)
    counter["n"] += 1
    request = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=25) as response:
            raw = response.read()
            if response.status != 200 or _blocked_body(raw, response.headers.get("content-type")):
                raise FeedBlocked(f"status {response.status}")
            return json.loads(raw)
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403, 429, 503):
            raise FeedBlocked(f"http {exc.code}") from None
        raise


def _player(selection):
    people = selection.get("participants") or []
    for person in people:
        if (person.get("type") or "").lower() == "player" and person.get("name"):
            return person.get("name")
    for person in people:
        if (person.get("type") or "").lower() != "team" and person.get("name"):
            return person.get("name")
    return None


def _sides(event):
    home = away = None
    for person in event.get("participants") or []:
        role = (person.get("venueRole") or "").lower()
        if role == "home":
            home = person.get("name")
        elif role == "away":
            away = person.get("name")
    if home and away:
        return home, away
    name = event.get("name") or ""
    if " @ " in name:
        away, home = name.split(" @ ", 1)
        return home.strip(), away.strip()
    return None, None


def _upcoming(events, now):
    horizon = now + dt.timedelta(days=8)
    ready = []
    for event in events or []:
        start = _parse_time(event.get("startEventDate"))
        if start and now <= start <= horizon:
            ready.append(event)
    return ready


def parse_board(data, spec):
    """Pull labelled prices out of one subcategory payload. Unlabelled rows are dropped."""
    _name, stat, label, _key, mode = spec
    events = {event.get("id"): event for event in data.get("events") or []}
    markets = {market.get("id"): market for market in data.get("markets") or []}
    grouped = {}
    for selection in data.get("selections") or []:
        market = markets.get(selection.get("marketId")) or {}
        event = events.get(market.get("eventId"))
        if not event:
            continue
        outcome = selection.get("outcomeType") or ""
        if mode == "anytime":
            if (market.get("name") or "") != "Anytime TD Scorer" or outcome != "Anytime Scorer":
                continue
            side, line = "yes", 0.5
        else:
            side = outcome.lower()
            if side not in ("over", "under") or selection.get("points") is None:
                continue
            line = float(selection["points"])
        player = _player(selection)
        price = american((selection.get("displayOdds") or {}).get("american"))
        if not player or price is None:
            continue
        slot = grouped.setdefault((event["id"], player, line), {"event": event, "player": player, "line": line, "stat": stat, "label": label})
        slot[side] = price
        if selection.get("id"):
            slot[f"{side}_sid"] = selection.get("id")
    kept = []
    dropped = 0
    for slot in grouped.values():
        if mode == "ou":
            if "over" not in slot or "under" not in slot or not juice_ok(slot["over"], slot["under"]):
                dropped += 1
                continue
        elif "yes" not in slot:
            dropped += 1
            continue
        kept.append(slot)
    return kept, dropped


def _event_shell(event, league):
    home, away = _sides(event)
    start = _parse_time(event.get("startEventDate"))
    return {
        "id": f"dk:{event.get('id')}",
        "dk_event_id": event.get("id"),
        "sport_key": SPORT_KEYS[league],
        "home_team": home,
        "away_team": away,
        "commence_time": start.isoformat().replace("+00:00", "Z") if start else event.get("startEventDate"),
        "bookmakers": [{"key": "draftkings", "title": "DraftKings", "markets": []}],
        "_markets": [],
        "source": "draftkings",
    }


def _add_outcomes(shell, rows, spec):
    _name, stat, label, market_key, mode = spec
    outcomes = []
    for row in rows:
        if mode == "anytime":
            outcomes.append({"name": "Yes", "description": row["player"], "price": row["yes"], "point": 0.5, "sid": row.get("yes_sid")})
        else:
            outcomes.append({"name": "Over", "description": row["player"], "price": row["over"], "point": row["line"], "sid": row.get("over_sid")})
            outcomes.append({"name": "Under", "description": row["player"], "price": row["under"], "point": row["line"], "sid": row.get("under_sid")})
    if not outcomes:
        return
    book = shell["bookmakers"][0]
    market = next((item for item in book["markets"] if item.get("key") == market_key), None)
    if market is None:
        market = {"key": market_key, "outcomes": []}
        book["markets"].append(market)
    market["outcomes"].extend(outcomes)
    marker = [market_key, stat, label]
    if marker not in shell["_markets"]:
        shell["_markets"].append(marker)


def lines_from_catalog(catalog):
    """Moneyline, spread, and total selection ids from the league board."""
    events = {event.get("id"): event for event in catalog.get("events") or []}
    markets = {market.get("id"): market for market in catalog.get("markets") or []}
    found = {}
    for selection in catalog.get("selections") or []:
        market = markets.get(selection.get("marketId")) or {}
        event = events.get(market.get("eventId"))
        if not event or not selection.get("id"):
            continue
        kind = (market.get("name") or "").lower()
        role = (selection.get("outcomeType") or "").lower()
        bucket = found.setdefault(event["id"], {"event": event, "ml": {}, "spread": {}, "total": {}})
        row = {
            "sid": selection["id"],
            "price": american((selection.get("displayOdds") or {}).get("american")),
            "point": selection.get("points"),
        }
        if kind == "moneyline" and role in ("home", "away"):
            bucket["ml"][role] = row
        elif kind == "spread" and role in ("home", "away"):
            bucket["spread"][role] = row
        elif kind == "total" and role in ("over", "under"):
            bucket["total"][role] = row
    return found


def fetch(now=None):
    """Download today's labelled props. Raises FeedBlocked and stops on a challenge."""
    now = now or dt.datetime.now(dt.timezone.utc)
    counter = {"n": 0, "capped": False}
    boards = {}
    dropped = 0
    for league in ORDER:
        catalog = _get(f"{BASE}/{LEAGUE_IDS[league]}", counter)
        if catalog is None:
            break
        if not _upcoming(catalog.get("events"), now):
            continue
        for event_id, info in lines_from_catalog(catalog).items():
            if not _upcoming([info["event"]], now):
                continue
            shell = boards.get(event_id)
            if shell is None:
                shell = _event_shell(info["event"], league)
                boards[event_id] = shell
            shell["lines"] = {"ml": info["ml"], "spread": info["spread"], "total": info["total"]}
            shell["dk_event_id"] = str(info["event"].get("id"))
        by_name = {(sub.get("name") or "").strip().lower(): sub for sub in catalog.get("subcategories") or []}
        for spec in MARKETS[league]:
            sub = by_name.get(spec[0].lower())
            if not sub:
                continue
            url = f"{BASE}/{LEAGUE_IDS[league]}/categories/{sub['categoryId']}/subcategories/{sub['id']}"
            payload = _get(url, counter)
            if payload is None:
                break
            rows, missed = parse_board(payload, spec)
            dropped += missed
            for row in rows:
                event = row["event"]
                shell = boards.get(event["id"])
                if shell is None:
                    shell = _event_shell(event, league)
                    boards[event["id"]] = shell
                _add_outcomes(shell, [row], spec)
        if counter["capped"]:
            break
    return {
        "fetched_at": now.isoformat(timespec="seconds"),
        "requests": counter["n"],
        "capped": counter["capped"],
        "dropped_unpriced": dropped,
        "events": list(boards.values()),
        "blocked": False,
    }


def _age_hours(stamp, now):
    parsed = _parse_time(stamp)
    if not parsed:
        return None
    return (now - parsed).total_seconds() / 3600


def load_cache():
    if not CACHE_PATH.exists():
        return None
    try:
        return json.loads(CACHE_PATH.read_text())
    except json.JSONDecodeError:
        return None


def save_cache(payload):
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(payload))


def refresh(force=False, now=None):
    """Return (events, info). A block keeps the previous cache and does not raise."""
    now = now or dt.datetime.now(dt.timezone.utc)
    cached = load_cache()
    age = _age_hours((cached or {}).get("fetched_at"), now)
    if cached and not force and age is not None and age <= TTL_HOURS and not cached.get("blocked"):
        print(f"dk props: cache {age:.1f}h old, {len(cached.get('events') or [])} events, no request")
        return cached.get("events") or [], {"from_cache": True, "blocked": False, "events": len(cached.get("events") or [])}
    try:
        fresh = fetch(now)
    except FeedBlocked as exc:
        print("dk props: blocked, stopped:", exc)
        events = (cached or {}).get("events") or []
        return events, {"from_cache": bool(events), "blocked": True, "reason": str(exc), "events": len(events)}
    save_cache(fresh)
    print(
        "dk props: fetched",
        fresh["requests"],
        "requests,",
        len(fresh["events"]),
        "events, dropped",
        fresh["dropped_unpriced"],
    )
    return fresh["events"], {
        "from_cache": False,
        "blocked": False,
        "requests": fresh["requests"],
        "events": len(fresh["events"]),
        "dropped_unpriced": fresh["dropped_unpriced"],
        "capped": fresh["capped"],
    }


def merge_prop_payload(api_payload, dk_payload):
    """Prefer DraftKings' own price on DraftKings. Keep other books from the Odds API."""
    if not dk_payload:
        return api_payload
    if not api_payload:
        return dk_payload
    dk_books = dk_payload.get("bookmakers") or []
    dk_markets = {}
    for market in (dk_books[0].get("markets") if dk_books else []) or []:
        if market.get("key"):
            dk_markets[market["key"]] = market
    books = []
    replaced = False
    for book in api_payload.get("bookmakers") or []:
        if book.get("key") != "draftkings":
            books.append(book)
            continue
        replaced = True
        kept = [market for market in book.get("markets") or [] if market.get("key") not in dk_markets]
        kept.extend(dk_markets.values())
        books.append({**book, "markets": kept})
    if not replaced and dk_books:
        books.append(dk_books[0])
    markets = [list(row) for row in (api_payload.get("_markets") or [])]
    have = {row[0] for row in markets if row}
    for row in dk_payload.get("_markets") or []:
        if row and row[0] not in have:
            markets.append(list(row))
            have.add(row[0])
    merged = dict(api_payload)
    merged["bookmakers"] = books
    merged["_markets"] = markets
    merged["source"] = "draftkings+oddsapi"
    if dk_payload.get("dk_event_id"):
        merged["dk_event_id"] = dk_payload.get("dk_event_id")
    return merged


def compare_prices(dk_events, odds_events):
    """Spot-check DraftKings prices against Odds API DraftKings props on the same line."""
    index = {}
    for event in odds_events or []:
        for book in event.get("bookmakers") or []:
            if book.get("key") != "draftkings":
                continue
            stat_of = {row[0]: row[1] for row in event.get("_markets") or [] if isinstance(row, (list, tuple)) and len(row) >= 2}
            for market in book.get("markets") or []:
                stat = stat_of.get(market.get("key"))
                for outcome in market.get("outcomes") or []:
                    side = (outcome.get("name") or "").lower()
                    if side not in ("over", "under") or outcome.get("point") is None:
                        continue
                    key = (outcome.get("description"), stat, float(outcome["point"]), side)
                    index[key] = american(outcome.get("price"))
    exact = close = mismatch = 0
    examples = []
    for event in dk_events or []:
        stat_of = {row[0]: row[1] for row in event.get("_markets") or []}
        for book in event.get("bookmakers") or []:
            for market in book.get("markets") or []:
                stat = stat_of.get(market.get("key"))
                for outcome in market.get("outcomes") or []:
                    side = (outcome.get("name") or "").lower()
                    if side not in ("over", "under"):
                        continue
                    key = (outcome.get("description"), stat, float(outcome.get("point")), side)
                    other = index.get(key)
                    if other is None:
                        continue
                    price = american(outcome.get("price"))
                    if price == other:
                        exact += 1
                    elif abs(price - other) <= 15:
                        close += 1
                    else:
                        mismatch += 1
                    if len(examples) < 8:
                        examples.append({"player": key[0], "stat": stat, "line": key[2], "side": side, "dk": price, "odds_api": other})
    return {"exact": exact, "close": close, "mismatch": mismatch, "examples": examples}
