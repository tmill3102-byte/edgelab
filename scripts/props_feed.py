"""Fetch player props from The Odds API and reuse them across refreshes.

``/events`` is free. Each event-odds call costs markets × regions. A game that
was priced in the last 12 hours is not bought again. Cached prices stay on the
slate for 36 hours so a later refresh still shows them.

ESPN's public DraftKings prop feed is not used: the prices are real, but the
payload does not say which number is Over and which is Under. Guessing the
side would invent a bet. DraftKings' own website JSON is not a documented
public API and is not called.
"""

import datetime as dt
import json
import re
from pathlib import Path

import requests

from odds_budget import (
    PRIORITY,
    PROP_KEEP_HOURS,
    PROP_TTL_HOURS,
    days_left,
    plan_credits,
    prop_cost,
)

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "site" / "data"
CACHE_PATH = DATA / "props-cache.json"
API = "https://api.the-odds-api.com/v4"


def redact(text, key):
    text = "" if text is None else str(text)
    if key:
        text = text.replace(key, "[redacted]")
    return re.sub(r"apiKey=[^&\s\"']+", "apiKey=[redacted]", text)


def _parse(value):
    if not value:
        return None
    try:
        return dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _age_hours(stamp, now):
    parsed = _parse(stamp)
    if not parsed:
        return None
    return (now - parsed).total_seconds() / 3600


def load_cache():
    if not CACHE_PATH.exists():
        return {"events": {}}
    try:
        data = json.loads(CACHE_PATH.read_text())
    except json.JSONDecodeError:
        return {"events": {}}
    data.setdefault("events", {})
    return data


def save_cache(cache):
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(cache))


def usable_payloads(cache, now=None):
    """Cached prop boards still fresh enough to show."""
    now = now or dt.datetime.now(dt.timezone.utc)
    out = []
    for payload in (cache.get("events") or {}).values():
        age = _age_hours(payload.get("fetched_at"), now)
        if age is None or age > PROP_KEEP_HOURS:
            continue
        out.append(payload)
    return out


def _headers(response):
    return {
        "x_requests_remaining": response.headers.get("x-requests-remaining"),
        "x_requests_used": response.headers.get("x-requests-used"),
        "x_requests_last": response.headers.get("x-requests-last"),
    }


def _get(session, path, key, **params):
    params = dict(params)
    params["apiKey"] = key
    try:
        response = session.get(API + path, params=params, timeout=30)
    except requests.RequestException as exc:
        raise RuntimeError(redact(str(exc), key)) from None
    return response


def _remaining(headers, fallback):
    raw = (headers or {}).get("x_requests_remaining")
    try:
        return int(raw)
    except (TypeError, ValueError):
        return fallback


def active_priority(session, key):
    response = _get(session, "/sports", key)
    print("props sports status", response.status_code, "quota", json.dumps(_headers(response)))
    if response.status_code != 200:
        print("props sports body:", redact(response.text[:200], key))
        return [], _remaining(_headers(response), None)
    active = {row.get("key") for row in response.json() if row.get("active")}
    ordered = [sport for sport in PRIORITY if sport in active]
    return ordered, _remaining(_headers(response), None)


def _events(session, key, sport):
    response = _get(session, f"/sports/{sport}/events", key)
    if response.status_code != 200:
        print("props events", sport, response.status_code, redact(response.text[:160], key))
        return []
    rows = response.json()
    return rows if isinstance(rows, list) else []


def _upcoming(events, now):
    window = []
    for event in events:
        commence = _parse(event.get("commence_time"))
        if not commence or not event.get("id"):
            continue
        if now <= commence <= now + dt.timedelta(hours=30):
            window.append(event)
    window.sort(key=lambda event: event.get("commence_time") or "")
    return window


def refresh_props(api_key, enabled=True):
    """Return prop payloads to attach, and a budget dict for the meta file.

    When ``enabled`` is false the network is not used. Cached prices are still
    returned so a push refresh does not wipe the board.
    """
    now = dt.datetime.now(dt.timezone.utc)
    cache = load_cache()
    showing = usable_payloads(cache, now)
    budget = {
        "enabled": bool(enabled),
        "cached": len(showing),
        "fetched": 0,
        "note": None,
    }
    if not enabled:
        budget["note"] = "Props were not bought on this run. Showing the cache."
        print(f"props: off, showing {len(showing)} cached")
        return showing, budget
    if not api_key:
        budget["note"] = "No Odds API key. Props stay on the cache."
        print("props: no key, showing cache", len(showing))
        return showing, budget

    session = requests.Session()
    session.headers["User-Agent"] = "EdgeLab research (low volume)"
    try:
        active, remaining = active_priority(session, api_key)
    except RuntimeError as exc:
        print("props sports failed:", exc)
        budget["note"] = "Could not read /sports. Showing the cache."
        return showing, budget
    if remaining is None:
        remaining = 0
    candidates = []
    for sport in active:
        try:
            listed = _events(session, api_key, sport)
        except RuntimeError as exc:
            print("props events failed:", exc)
            continue
        for event in _upcoming(listed, now):
            cached = cache["events"].get(event["id"])
            age = _age_hours((cached or {}).get("fetched_at"), now)
            if age is not None and age <= PROP_TTL_HOURS:
                continue
            candidates.append({
                "sport": sport,
                "event_id": event["id"],
                "home_team": event.get("home_team"),
                "away_team": event.get("away_team"),
                "commence_time": event.get("commence_time"),
            })
    plan = plan_credits(
        remaining=remaining,
        active=active,
        days_left=days_left(now.date()),
        featured_due=[],
        candidates=candidates,
    )
    budget.update({
        "remaining_before": plan["remaining_before"],
        "prop_today": plan["prop_today"],
        "prop_pool": plan["prop_pool"],
        "days_left": plan["days_left"],
        "active": plan["active"],
        "planned": [
            {"sport": row["sport"], "event_id": row["event_id"], "cost": row["cost"]}
            for row in plan["props"]
        ],
    })
    print(
        "props budget",
        json.dumps({
            "remaining": plan["remaining_before"],
            "days_left": plan["days_left"],
            "prop_today": plan["prop_today"],
            "prop_pool": plan["prop_pool"],
            "candidates": len(candidates),
            "buying": len(plan["props"]),
            "cost": plan["prop_spent"],
        }),
    )
    from verify_odds import slim_event
    fetched = 0
    for row in plan["props"]:
        markets = ",".join(key for key, _stat, _label in row["markets"])
        try:
            response = _get(
                session,
                f"/sports/{row['sport']}/events/{row['event_id']}/odds",
                api_key,
                regions="us",
                markets=markets,
                oddsFormat="american",
                includeLinks="true",
            )
        except RuntimeError as exc:
            print("props request failed:", exc)
            continue
        quota = _headers(response)
        print(
            "props status", response.status_code,
            "sport", row["sport"],
            "event", row["event_id"],
            "markets", prop_cost(row["sport"]),
            "quota", json.dumps(quota),
        )
        if response.status_code != 200:
            print("props body:", redact(response.text[:240], api_key))
            continue
        body = response.json()
        if not isinstance(body, dict):
            continue
        payload = slim_event(body)
        payload["fetched_at"] = now.isoformat(timespec="seconds")
        payload["_markets"] = [list(item) for item in row["markets"]]
        payload["_quota"] = quota
        cache["events"][row["event_id"]] = payload
        fetched += 1
        try:
            remaining = int(quota.get("x_requests_remaining"))
        except (TypeError, ValueError):
            remaining = None
        if remaining is not None and remaining < 40:
            print("props: stopping, reserve reached", remaining)
            break
    # Drop boards that are too old to show.
    kept = {}
    for event_id, payload in cache["events"].items():
        age = _age_hours(payload.get("fetched_at"), now)
        if age is not None and age <= PROP_KEEP_HOURS:
            kept[event_id] = payload
    cache["events"] = kept
    cache["updated_at"] = now.isoformat(timespec="seconds")
    cache["budget"] = {key: budget[key] for key in budget if key != "note"}
    save_cache(cache)
    showing = usable_payloads(cache, now)
    budget["fetched"] = fetched
    budget["cached"] = len(showing)
    budget["note"] = (
        f"Bought {fetched} prop board(s) this run. "
        f"{len(showing)} cached. Free tier covers about 1–2 games a day once featured odds are paid for."
    )
    print(f"props cached {len(showing)} fetched {fetched}")
    return showing, budget
