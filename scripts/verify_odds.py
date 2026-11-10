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

DATA = ROOT / "site" / "data"
API = "https://api.the-odds-api.com/v4"
PREFERRED = (
    "basketball_nba",
    "icehockey_nhl",
    "americanfootball_nfl",
    "basketball_ncaab",
    "americanfootball_ncaaf",
)
OHIO_KEYS = []
for book in BOOKS:
    OHIO_KEYS.append(book["key"])
    OHIO_KEYS.extend(book.get("also") or [])
TTL_HOURS = float(os.environ.get("ODDS_SNAPSHOT_TTL_HOURS", "12"))
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
            outcomes = []
            for outcome in market.get("outcomes") or []:
                # Outcome links are bet-slip deep links. Keep the price only.
                outcomes.append({
                    "name": outcome.get("name"),
                    "price": outcome.get("price"),
                    "point": outcome.get("point"),
                    "description": outcome.get("description"),
                })
            markets.append({"key": market.get("key"), "outcomes": outcomes})
        row = {"key": book.get("key"), "title": book.get("title"), "markets": markets}
        url = public_event_url(book["link"]) if isinstance(book.get("link"), str) else None
        if url:
            row["link"] = url
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

    snapshot_path = DATA / "odds-snapshot.json"
    force = os.environ.get("ODDS_API_FORCE") == "1"
    fresh = False
    if snapshot_path.exists() and not force:
        age_h = (dt.datetime.now(dt.timezone.utc).timestamp() - snapshot_path.stat().st_mtime) / 3600
        fresh = age_h < TTL_HOURS
        if fresh:
            report["odds"] = {
                "skipped": True,
                "reason": f"snapshot is {age_h:.1f}h old (ttl {TTL_HOURS:g}h); skipped the paid call",
                **sports_headers,
            }
            _write(report)
            print(json.dumps(report, indent=2))
            print("key_valid: true")
            return 0

    remaining = sports_headers.get("x_requests_remaining")
    try:
        remaining_n = int(remaining) if remaining is not None else None
    except ValueError:
        remaining_n = None
    if remaining_n is not None and remaining_n < 40:
        report["odds"] = {
            "skipped": True,
            "reason": f"only {remaining_n} credits remaining; refused the paid call (reserve 40)",
            **sports_headers,
        }
        _write(report)
        print(json.dumps(report, indent=2))
        return 0

    if not chosen:
        report["odds"] = {"skipped": True, "reason": "no active sport returned by /sports", **sports_headers}
        _write(report)
        print(json.dumps(report, indent=2))
        return 1

    try:
        odds_response = get(
            session,
            f"/sports/{chosen}/odds",
            key,
            regions="us",
            markets=MARKETS,
            oddsFormat="american",
            includeLinks="true",
        )
    except RuntimeError as exc:
        report["odds"] = {"status": 0, "error": str(exc), "sport_key": chosen, "regions": "us", "markets": MARKETS}
        _write(report)
        print(json.dumps(report, indent=2))
        return 1

    odds_headers = headers_of(odds_response)
    print("odds status", odds_response.status_code, "sport", chosen, "quota", json.dumps(odds_headers))
    if odds_response.status_code != 200:
        report["odds"] = {
            "status": odds_response.status_code,
            "sport_key": chosen,
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
    seen = {}
    for event in events:
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
    report["odds"] = {
        "skipped": False,
        "status": 200,
        "sport_key": chosen,
        "regions": "us",
        "markets": MARKETS,
        "events": len(events),
        "bookmakers": [{"key": key_name, "title": title} for key_name, title in sorted(seen.items())],
        "ohio_present": present,
        "ohio_absent": absent,
        "other_bookmakers": others,
        **odds_headers,
    }
    snapshot = {
        "fetched_at": now,
        "sport_key": chosen,
        "regions": "us",
        "markets": MARKETS.split(","),
        "headers": odds_headers,
        "events": [slim_event(event) for event in events],
    }
    snapshot_path.write_text(json.dumps(snapshot))
    _write(report)
    print(json.dumps(report, indent=2))
    print("key_valid: true")
    print("ohio_present:", ", ".join(present) or "(none)")
    print("ohio_absent:", ", ".join(absent) or "(none)")
    return 0


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
