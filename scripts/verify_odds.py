#!/usr/bin/env python3
"""Confirm ODDS_API_KEY with one free call and at most one paid US odds call.

Never prints the key. Writes site/data/odds-check.json and, on a paid call,
site/data/odds-snapshot.json for the publisher to reuse.
"""
import json
import os
import re
import sys
import datetime as dt
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from books import BOOKS, find_book  # noqa: E402
from odds_budget import FEATURED_TTL_HOURS, PRIORITY, RESERVE, featured_cost, plan_credits, days_left  # noqa: E402

DATA = ROOT / "site" / "data"
API = "https://api.the-odds-api.com/v4"
PREFERRED = PRIORITY + (
    "basketball_ncaab",
    "americanfootball_ncaaf",
)
OHIO_KEYS = []
for book in BOOKS:
    OHIO_KEYS.append(book["key"])
    OHIO_KEYS.extend(book.get("also") or [])
TTL_HOURS = float(os.environ.get("ODDS_SNAPSHOT_TTL_HOURS", str(FEATURED_TTL_HOURS)))
MARKETS = "h2h,spreads,totals"


def clean(text, key):
    text = "" if text is None else str(text)
    if key:
        text = text.replace(key, "[redacted]")
    return re.sub(r"apiKey=[^&\s\"']+", "apiKey=[redacted]", text)


def headers_of(response):
    return {
        "x_requests_remaining": response.headers.get("x-requests-remaining"),
        "x_requests_used": response.headers.get("x-requests-used"),
        "x_requests_last": response.headers.get("x-requests-last"),
    }


def get(session, path, key, **params):
    params = dict(params)
    params["apiKey"] = key
    try:
        response = session.get(API + path, params=params, timeout=30)
    except requests.RequestException as exc:
        raise RuntimeError(clean(str(exc), key)) from None
    return response


def slim_event(event):
    # Imported lazily so this script still runs before the package path is needed.
    sys.path.insert(0, str(ROOT / "betting"))
    from betlib.espn import public_event_url
    books = []
    for book in event.get("bookmakers") or []:
        markets = []
        for market in book.get("markets") or []:
            row = {"key": market.get("key"), "outcomes": []}
            if market.get("sid"):
                row["sid"] = market.get("sid")
            for outcome in market.get("outcomes") or []:
                item = {
                    "name": outcome.get("name"),
                    "price": outcome.get("price"),
                    "point": outcome.get("point"),
                    "description": outcome.get("description"),
                }
                if outcome.get("sid"):
                    item["sid"] = outcome.get("sid")
                link = outcome.get("link") if isinstance(outcome.get("link"), str) else None
                if link:
                    item["link"] = public_event_url(link) or link
                row["outcomes"].append(item)
            markets.append(row)
        book_row = {"key": book.get("key"), "title": book.get("title"), "markets": markets}
        if book.get("sid"):
            book_row["sid"] = book.get("sid")
        url = public_event_url(book["link"]) if isinstance(book.get("link"), str) else None
        if url:
            book_row["link"] = url
        row = book_row
        books.append(row)
    return {
        "id": event.get("id"),
        "sport_key": event.get("sport_key"),
        "commence_time": event.get("commence_time"),
        "home_team": event.get("home_team"),
        "away_team": event.get("away_team"),
        "bookmakers": books,
    }


def main():
    DATA.mkdir(parents=True, exist_ok=True)
    key = os.environ.get("ODDS_API_KEY") or ""
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    report = {
        "checked_at": now,
        "key_present": bool(key),
        "key_valid": False,
        "sports": None,
        "odds": None,
    }
    print(f"ODDS_API_KEY present: {bool(key)}")
    if not key:
        report["error"] = "ODDS_API_KEY is not set"
        _write(report)
        print(json.dumps(report, indent=2))
        return 1

    session = requests.Session()
    session.headers["User-Agent"] = "EdgeLab research (low volume)"
    try:
        sports_response = get(session, "/sports", key)
    except RuntimeError as exc:
        report["error"] = str(exc)
        _write(report)
        print(json.dumps(report, indent=2))
        return 1

    sports_headers = headers_of(sports_response)
    print("sports status", sports_response.status_code, "quota", json.dumps(sports_headers))
    if sports_response.status_code != 200:
        report["sports"] = {"status": sports_response.status_code, "body": clean(sports_response.text[:400], key), **sports_headers}
        report["error"] = "sports endpoint rejected the key" if sports_response.status_code in (401, 403) else "sports endpoint failed"
        _write(report)
        print(json.dumps(report, indent=2))
        return 1

    sports = sports_response.json()
    active = {row.get("key") for row in sports if row.get("active")}
    chosen = next((key_name for key_name in PREFERRED if key_name in active), None)
    if chosen is None:
        chosen = next((row.get("key") for row in sports if row.get("active") and not row.get("has_outrights")), None)
    report["key_valid"] = True
    report["sports"] = {
        "status": 200,
        "count": len(sports),
        "active_preferred": chosen,
        **sports_headers,
    }

    bundle = _load_bundle()
    force = os.environ.get("ODDS_API_FORCE") == "1"
    active = [sport for sport in PRIORITY if sport in active]
    due = []
    for sport in active:
        snap = bundle.get(sport) or {}
        age_h = _age_hours(snap.get("fetched_at"))
        if force or age_h is None or age_h >= TTL_HOURS:
            due.append(sport)
    remaining = sports_headers.get("x_requests_remaining")
    try:
        remaining_n = int(remaining) if remaining is not None else 0
    except ValueError:
        remaining_n = 0
    today = dt.datetime.now(dt.timezone.utc).date()
    plan = plan_credits(remaining_n, active, days_left(today), due, [])
    report["budget"] = {
        "active": plan["active"],
        "featured_due": due,
        "featured_buying": plan["featured"],
        "featured_cost_each": featured_cost(),
        "reserve": RESERVE,
        "days_left": plan["days_left"],
        "prop_today": plan["prop_today"],
    }
    print("featured budget", json.dumps(report["budget"]))
    bought = []
    odds_headers = sports_headers
    for sport in plan["featured"]:
        if remaining_n < RESERVE + featured_cost():
            print("featured: stopping, reserve", remaining_n)
            break
        try:
            odds_response = get(
                session,
                f"/sports/{sport}/odds",
                key,
                regions="us",
                markets=MARKETS,
            oddsFormat="american",
            includeLinks="true",
            includeSids="true",
            )
        except RuntimeError as exc:
            report["odds"] = {"status": 0, "error": str(exc), "sport_key": sport, "regions": "us", "markets": MARKETS}
            _write(report)
            print(json.dumps(report, indent=2))
            return 1
        odds_headers = headers_of(odds_response)
        print("odds status", odds_response.status_code, "sport", sport, "quota", json.dumps(odds_headers))
        try:
            remaining_n = int(odds_headers.get("x_requests_remaining") or remaining_n)
        except ValueError:
            pass
        if odds_response.status_code != 200:
            report["odds"] = {
                "status": odds_response.status_code,
                "sport_key": sport,
                "regions": "us",
                "markets": MARKETS,
                "body": clean(odds_response.text[:400], key),
                **odds_headers,
            }
            _write(report)
            print(json.dumps(report, indent=2))
            return 1
        events = odds_response.json()
        if not isinstance(events, list):
            events = []
        bundle[sport] = {
            "fetched_at": now,
            "sport_key": sport,
            "regions": "us",
            "markets": MARKETS.split(","),
            "headers": odds_headers,
            "events": [slim_event(event) for event in events],
        }
        bought.append(sport)

    _write_bundle(bundle)
    primary = _primary_snapshot(bundle, chosen)
    seen = {}
    for snap in bundle.values():
        for event in snap.get("events") or []:
            for book in event.get("bookmakers") or []:
                if book.get("key"):
                    seen[book["key"]] = book.get("title") or book["key"]
    present, absent = [], []
    for book in BOOKS:
        names = [book["key"]] + list(book.get("also") or [])
        title = book["name"]
        if any(name in seen for name in names):
            present.append(title)
        else:
            absent.append(title)
    others = sorted(title for key_name, title in seen.items() if find_book(key_name) is None)
    if not bought and not due:
        reason = f"featured snapshots are under {TTL_HOURS:g}h old; skipped the paid calls"
    elif not bought:
        reason = f"only {remaining_n} credits remaining; refused featured calls (reserve {RESERVE})"
    else:
        reason = None
    report["odds"] = {
        "skipped": not bought,
        "reason": reason,
        "status": 200 if primary else None,
        "sport_key": (primary or {}).get("sport_key") or chosen,
        "sports": sorted(bundle),
        "bought": bought,
        "regions": "us",
        "markets": MARKETS,
        "events": sum(len(snap.get("events") or []) for snap in bundle.values()),
        "bookmakers": [{"key": key_name, "title": title} for key_name, title in sorted(seen.items())],
        "ohio_present": present,
        "ohio_absent": absent,
        "other_bookmakers": others,
        **odds_headers,
    }
    _write(report)
    print(json.dumps(report, indent=2))
    print("key_valid: true")
    print("ohio_present:", ", ".join(present) or "(none)")
    print("ohio_absent:", ", ".join(absent) or "(none)")
    return 0


def _age_hours(stamp):
    if not stamp:
        return None
    try:
        parsed = dt.datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except ValueError:
        return None
    return (dt.datetime.now(dt.timezone.utc) - parsed).total_seconds() / 3600


def _load_bundle():
    path = DATA / "odds-snapshots.json"
    sports = {}
    if path.exists():
        try:
            sports = json.loads(path.read_text()).get("sports") or {}
        except json.JSONDecodeError:
            sports = {}
    single = DATA / "odds-snapshot.json"
    if single.exists():
        try:
            one = json.loads(single.read_text())
        except json.JSONDecodeError:
            one = None
        if one and one.get("sport_key") and one["sport_key"] not in sports:
            sports[one["sport_key"]] = one
    return sports


def _primary_snapshot(bundle, chosen):
    if chosen and bundle.get(chosen):
        return bundle[chosen]
    for sport in PRIORITY:
        if bundle.get(sport):
            return bundle[sport]
    return next(iter(bundle.values()), None)


def _write_bundle(bundle):
    path = DATA / "odds-snapshots.json"
    path.write_text(json.dumps({"sports": bundle}))
    primary = _primary_snapshot(bundle, "basketball_nba")
    if primary:
        (DATA / "odds-snapshot.json").write_text(json.dumps(primary))


def _write(report):
    (DATA / "odds-check.json").write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        # Last-resort guard. The message is scrubbed of anything that looks like a key.
        key = os.environ.get("ODDS_API_KEY") or ""
        print("verify_odds failed:", clean(str(exc), key))
        sys.exit(1)
