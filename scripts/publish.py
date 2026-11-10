#!/usr/bin/env python3
"""Build the static EdgeLab data files from the research engine.

Odds API credits: featured odds are read from site/data/odds-snapshots.json
(written by verify_odds.py, one sport per day). Player props are bought from the
free-tier budget in scripts/odds_budget.py when ODDS_API_PROPS=1, then cached.
"""
import json
import os
import re
import sys
import datetime as dt
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "betting"))
sys.path.insert(0, str(ROOT / "scripts"))

from betlib import analysis, espn, tracker  # noqa: E402
from betlib.leagues import LEAGUES  # noqa: E402
from betlib.models import am_to_dec, make_pick, no_vig  # noqa: E402
from books import catalog  # noqa: E402
from props_feed import refresh_props  # noqa: E402

DATA = ROOT / "site" / "data"
KEEP = ("market", "selection", "side", "line", "odds", "model_raw", "model_prob", "market_prob",
        "fair_odds", "edge", "edge_at_price", "ev", "tier", "data_quality", "reasons", "flags",
        "caution", "case_against", "next_step")
MARKET_ORDER = ["ML", "1X2", "Spread", "Total", "Prop"]
TORD = {"High": 0, "Medium": 1, "Low": 2}
SPORT_TO_LEAGUE = {
    "basketball_nba": "nba", "basketball_wnba": "wnba", "basketball_ncaab": "ncaab",
    "americanfootball_nfl": "nfl", "americanfootball_ncaaf": "cfb",
    "icehockey_nhl": "nhl", "baseball_mlb": "mlb",
    "soccer_epl": "epl", "soccer_uefa_champs_league": "ucl", "soccer_usa_mls": "mls",
}
LEAGUE_TO_SPORT = {league: sport for sport, league in SPORT_TO_LEAGUE.items()}
QUICK_LIST = ["nba", "nhl", "nfl", "cfb", "ncaab", "mlb", "wnba", "atp", "wta"]
FULL_LIST = ["nfl", "cfb", "nba", "wnba", "ncaab", "ncaaw", "mlb", "nhl", "epl", "ucl", "uel",
             "mls", "laliga", "seriea", "bundesliga", "ligue1", "atp", "wta", "pga", "lpga", "ufc"]
ANALYZE = {"nfl", "nba", "nhl", "cfb", "epl", "ucl", "mls", "ncaab"}
PRIO = {"nfl": 0, "nba": 1, "nhl": 2, "cfb": 3, "epl": 4, "ucl": 5, "mls": 6, "ncaab": 7}
DISCLAIMER = "Research only. No guarantees. EdgeLab does not place bets. If gambling is a problem, call 1-800-GAMBLER."


def write_json(name, obj):
    path = DATA / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, default=str) + "\n")


def add_days(yyyymmdd, n):
    return (dt.datetime.strptime(yyyymmdd, "%Y%m%d") + dt.timedelta(days=n)).strftime("%Y%m%d")


def norm_name(value):
    value = (value or "").lower().replace("&", " and ")
    value = re.sub(r"[^a-z0-9 ]", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def same_team(a, b):
    a, b = norm_name(a), norm_name(b)
    if not a or not b:
        return False
    if a == b or a in b or b in a:
        return True
    return a.split()[-1] == b.split()[-1] and len(a.split()[-1]) >= 4


def same_line(a, b):
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    return abs(float(a) - float(b)) < 0.01


def american(price):
    try:
        price = float(price)
    except (TypeError, ValueError):
        return None
    if abs(price) < 100:
        return None
    return price


def strip_pick(pick, league=None):
    out = {key: pick.get(key) for key in KEEP}
    market = {"ML": "ml", "1X2": "ml", "Spread": "sp", "Total": "tot"}.get(pick.get("market"))
    proven = True
    if league:
        try:
            from betlib import ratings as RT
            if league in RT.PARAMS:
                proven = bool(market and RT.enabled(league, market))
        except Exception:
            proven = True
    out["proven"] = proven
    return out


def et_parts(iso, fallback):
    parsed = espn.parse_iso(iso) if iso else None
    if parsed:
        local = parsed.astimezone(espn.ET)
        return local.strftime("%Y-%m-%d"), local.strftime("%A").lower()
    day = dt.datetime.strptime(fallback, "%Y%m%d")
    return day.strftime("%Y-%m-%d"), day.strftime("%A").lower()


def day_label(yyyymmdd, today):
    if yyyymmdd == today:
        return "Today"
    if yyyymmdd == add_days(today, 1):
        return "Tomorrow"
    day = dt.datetime.strptime(yyyymmdd, "%Y%m%d")
    return day.strftime("%a %b ") + str(day.day)


def dates_for(league, quick, today):
    span = 2 if quick and league not in ("nfl", "cfb") else 7
    return [add_days(today, i) for i in range(span)]


def extract_link(obj):
    if not isinstance(obj, dict):
        return None
    for key in ("link", "url", "href"):
        value = obj.get(key)
        if isinstance(value, str):
            url = espn.public_event_url(value)
            if url:
                return url
        elif isinstance(value, dict):
            url = espn.public_event_url(value.get("href") or value.get("url") or "")
            if url:
                return url
    return None


def outcomes_by_side(outcomes, home, away):
    found = {}
    for outcome in outcomes or []:
        name = outcome.get("name") or ""
        low = name.lower()
        if low == "over":
            found["over"] = outcome
        elif low == "under":
            found["under"] = outcome
        elif low == "draw":
            found["draw"] = outcome
        elif same_team(name, home):
            found["home"] = outcome
        elif same_team(name, away):
            found["away"] = outcome
    return found


def model_summary(res):
    model = res.get("model") or {}
    home = res["home"]["abbr"]
    away = res["away"]["abbr"]
    if model.get("type") in ("margin-normal", "ratings-v2"):
        text = f"Margin {home} {model['exp_margin_home']:+.1f}"
        if model.get("exp_total") is not None:
            text += f" · total {model['exp_total']:.1f}"
        return text
    if model.get("type") == "poisson":
        return f"Expected goals {home} {model['lam_home']:.2f} – {away} {model['lam_away']:.2f} · total {model['exp_total']:.2f}"
    return None


def short_injuries(res):
    out = {}
    for side in ("home", "away"):
        rows = (((res.get("injuries") or {}).get(side) or {}).get("list") or [])[:8]
        out[side] = [{
            "name": row.get("name"), "status": row.get("status"),
            "pos": row.get("pos"), "key": bool(row.get("key")),
        } for row in rows]
    return out


def form_map(res):
    out = {}
    for side in ("home", "away"):
        profile = (res.get("profiles") or {}).get(side) or {}
        if profile.get("last5"):
            out[side] = "L5 " + profile["last5"]
    return out


def preview_lines(markets):
    out = {}
    for market, sides in markets.items():
        for side, books in sides.items():
            for book, pick in books.items():
                row = out.setdefault(book, {})
                if market in ("ML", "1X2") and side in ("home", "away", "draw"):
                    row["ml_" + side] = pick.get("odds")
                elif market == "Spread":
                    row["spread_" + side] = pick.get("line")
                    row["spread_" + side + "_odds"] = pick.get("odds")
                elif market == "Total":
                    row["total"] = pick.get("line")
                    row[side + "_odds"] = pick.get("odds")
    return out


def markets_payload(markets):
    payload = []
    for market in MARKET_ORDER:
        sides = markets.get(market)
        if not sides:
            continue
        payload.append({
            "market": market,
            "sides": [{"side": side, "offers": offers} for side, offers in sides.items()],
        })
    return payload


def line_only_markets(game):
    """Scoreboard prices with no model. Edge stays null on purpose."""
    odds = game.get("odds") or {}
    markets = {}
    home, away = game["home"]["abbr"], game["away"]["abbr"]
    note = ["Line from the ESPN/DraftKings scoreboard. This game was not modeled in the latest refresh."]
    against = "No model was run, so there is no edge to show."
    nxt = "Open a modeled game for a full pick, or wait for the next refresh."

    def bare(market, selection, side, line, price):
        if price is None:
            return None
        return {
            "market": market, "selection": selection, "side": side, "line": line, "odds": price,
            "model_raw": None, "model_prob": None, "market_prob": None, "fair_odds": None,
            "edge": None, "edge_at_price": None, "ev": None, "tier": None, "data_quality": None,
            "reasons": note, "flags": ["!not modeled this refresh"], "caution": ["no model on this refresh"],
            "case_against": against, "next_step": nxt,
        }

    if odds.get("ml_home") is not None and odds.get("ml_away") is not None:
        three = odds.get("ml_draw") is not None
        market = "1X2" if three else "ML"
        for side, label, price in (
            ("home", f"{home} ML", odds.get("ml_home")),
            ("away", f"{away} ML", odds.get("ml_away")),
            ("draw", "Draw", odds.get("ml_draw") if three else None),
        ):
            pick = bare(market, label, side, None, price)
            if pick:
                markets.setdefault(market, {}).setdefault(side, {})["draftkings"] = pick
    spread = odds.get("spread_home")
    if spread is not None and odds.get("spread_home_odds") is not None and odds.get("spread_away_odds") is not None:
        for side, label, line, price in (
            ("home", f"{home} {spread:+g}", spread, odds.get("spread_home_odds")),
            ("away", f"{away} {-spread:+g}", -spread, odds.get("spread_away_odds")),
        ):
            pick = bare("Spread", label, side, line, price)
            if pick:
                markets.setdefault("Spread", {}).setdefault(side, {})["draftkings"] = pick
    total = odds.get("total")
    if total is not None and odds.get("over_odds") is not None and odds.get("under_odds") is not None:
        for side, price in (("over", odds.get("over_odds")), ("under", odds.get("under_odds"))):
            pick = bare("Total", f"{side.title()} {total:g}", side, total, price)
            if pick:
                markets.setdefault("Total", {}).setdefault(side, {})["draftkings"] = pick
    return markets


def apply_engine(markets, res):
    for pick in res.get("picks") or []:
        markets.setdefault(pick["market"], {}).setdefault(pick["side"], {})["draftkings"] = strip_pick(pick, res.get("league"))


def apply_api(markets, league, res, event, event_urls):
    home, away = res["home"]["name"], res["away"]["name"]
    for book in event.get("bookmakers") or []:
        key = book.get("key")
        if not key:
            continue
        url = extract_link(book)
        if url:
            event_urls.setdefault(key, url)
        by_market = {row.get("key"): row for row in book.get("markets") or []}
        if "h2h" in by_market:
            sides = outcomes_by_side(by_market["h2h"].get("outcomes"), home, away)
            if "home" in sides and "away" in sides and "draw" in sides:
                prices = [american(sides[s].get("price")) for s in ("home", "draw", "away")]
                nv, _ = no_vig(prices)
                seq, market = (("home", "draw", "away"), "1X2") if nv else ((), None)
            elif "home" in sides and "away" in sides:
                prices = [american(sides[s].get("price")) for s in ("home", "away")]
                nv, _ = no_vig(prices)
                seq, market = (("home", "away"), "ML") if nv else ((), None)
            else:
                seq, market, nv = (), None, None
            if nv:
                for side, prob in zip(seq, nv):
                    price = american(sides[side].get("price"))
                    label = "Draw" if side == "draw" else f"{res[side]['abbr']} ML"
                    pick = analysis.reprice_pick(league, res, market, side, None, price, prob, label)
                    if pick:
                        link = extract_link(sides[side])
                        if link:
                            event_urls.setdefault(key, link)
                        markets.setdefault(market, {}).setdefault(side, {})[key] = strip_pick(pick, league)
        if "spreads" in by_market:
            sides = outcomes_by_side(by_market["spreads"].get("outcomes"), home, away)
            if "home" in sides and "away" in sides:
                prices = [american(sides[s].get("price")) for s in ("home", "away")]
                nv, _ = no_vig(prices)
                if nv:
                    for side, prob in zip(("home", "away"), nv):
                        line = sides[side].get("point")
                        price = american(sides[side].get("price"))
                        try:
                            line = float(line)
                        except (TypeError, ValueError):
                            continue
                        label = f"{res[side]['abbr']} {line:+g}"
                        pick = analysis.reprice_pick(league, res, "Spread", side, line, price, prob, label)
                        if pick:
                            markets.setdefault("Spread", {}).setdefault(side, {})[key] = strip_pick(pick, league)
        if "totals" in by_market:
            sides = outcomes_by_side(by_market["totals"].get("outcomes"), home, away)
            if "over" in sides and "under" in sides:
                prices = [american(sides[s].get("price")) for s in ("over", "under")]
                nv, _ = no_vig(prices)
                if nv:
                    try:
                        line = float(sides["over"].get("point"))
                    except (TypeError, ValueError):
                        line = None
                    if line is not None:
                        for side, prob in zip(("over", "under"), nv):
                            price = american(sides[side].get("price"))
                            label = f"{side.title()} {line:g}"
                            pick = analysis.reprice_pick(league, res, "Total", side, line, price, prob, label)
                            if pick:
                                markets.setdefault("Total", {}).setdefault(side, {})[key] = strip_pick(pick, league)


def team_bits(game, side):
    if side in ("home", "away"):
        other = "away" if side == "home" else "home"
        return {
            "team_abbr": game[side]["abbr"],
            "team_name": game[side]["name"],
            "opponent": ("vs " if side == "home" else "@ ") + game[other]["abbr"],
            "form": (game.get("form") or {}).get(side),
        }
    return {"team_abbr": None, "team_name": None, "opponent": game["matchup"], "form": None}


def build_leg(game, market, side, offers, extra=None):
    if not offers:
        return None
    primary = "draftkings" if "draftkings" in offers else next(iter(offers))
    base = offers[primary]
    if base.get("model_prob") is None or base.get("odds") is None:
        return None
    matched = {book: pick for book, pick in offers.items() if same_line(pick.get("line"), base.get("line"))}
    line = base.get("line")
    bits = team_bits(game, side)
    leg = {
        "id": f"{game['league']}:{game['event_id']}:{market}:{side}:{line if line is not None else 'na'}",
        "event_id": game["event_id"],
        "league": game["league"],
        "name": game["name"],
        "start": game.get("start"),
        "start_local": game.get("start_local"),
        "date_et": game.get("date_et"),
        "weekday": game.get("weekday"),
        "matchup": game.get("matchup"),
        "home_abbr": game["home"]["abbr"],
        "away_abbr": game["away"]["abbr"],
        "home_name": game["home"]["name"],
        "away_name": game["away"]["name"],
        "market": market,
        "side": side,
        "selection": base.get("selection"),
        "line": line,
        "primary_book": primary,
        "position": None,
        "player": None,
        "prop_key": None,
        "hit_rate": None,
        "hit_rates": None,
        "event_urls": game.get("event_urls") or {},
        "odds_feed": game.get("odds_feed"),
        "offers": matched,
        **bits,
    }
    if extra:
        leg.update(extra)
    return leg


def match_api_event(game, events):
    start = espn.parse_iso(game.get("date"))
    best = None
    for event in events:
        if not (same_team(event.get("home_team"), (game.get("home") or {}).get("name"))
                and same_team(event.get("away_team"), (game.get("away") or {}).get("name"))):
            continue
        commence = espn.parse_iso(event.get("commence_time"))
        if start and commence and abs((start - commence).total_seconds()) > 36 * 3600:
            continue
        best = event
        break
    return best


def flat_metrics(rows):
    wins = losses = pushes = 0
    profit = 0.0
    risked = 0
    clvs = []
    brier = model_sum = 0.0
    decided_model = direction = 0
    for row in rows:
        status = row.get("status")
        if status not in ("won", "lost", "push"):
            continue
        risked += 1
        if status == "won":
            wins += 1
            if row.get("odds") is not None:
                profit += am_to_dec(row["odds"]) - 1
        elif status == "lost":
            losses += 1
            profit -= 1
        else:
            pushes += 1
        if row.get("clv") is not None:
            clvs.append(row["clv"])
        if status in ("won", "lost") and row.get("model_prob") is not None:
            outcome = 1.0 if status == "won" else 0.0
            prob = float(row["model_prob"])
            brier += (prob - outcome) ** 2
            model_sum += prob
            decided_model += 1
            if (prob >= 0.5) == (status == "won"):
                direction += 1
    decided = wins + losses
    graded = wins + losses + pushes
    return {
        "n": graded,
        "w": wins,
        "l": losses,
        "p": pushes,
        "record": f"{wins}-{losses}-{pushes}",
        "hit_rate": round(wins / decided, 4) if decided else None,
        "roi_pct": round(profit / risked * 100, 1) if risked else None,
        "clv_avg_pct": round(sum(clvs) / len(clvs) * 100, 2) if clvs else None,
        "clv_n": len(clvs),
        "model": {
            "n": decided_model,
            "avg_model_prob": round(model_sum / decided_model, 4) if decided_model else None,
            "actual_win_rate": round(wins / decided, 4) if decided else None,
            "brier": round(brier / decided_model, 4) if decided_model else None,
            "direction_hit": round(direction / decided_model, 4) if decided_model else None,
        },
    }


def public_play(row):
    keys = ("id", "date", "sport", "event_id", "event_name", "market", "selection", "side",
            "line", "odds", "model_prob", "market_prob", "edge", "tier", "status", "result_detail", "clv", "source")
    return {key: row.get(key) for key in keys}


def redact(text, key):
    text = "" if text is None else str(text)
    if key:
        text = text.replace(key, "[redacted]")
    return re.sub(r"apiKey=[^&\s\"']+", "apiKey=[redacted]", text)


def load_snapshots():
    """Every fresh featured sport, plus the legacy single-sport file."""
    sports = {}
    bundle = DATA / "odds-snapshots.json"
    if bundle.exists():
        try:
            sports = json.loads(bundle.read_text()).get("sports") or {}
        except json.JSONDecodeError:
            sports = {}
    single = load_snapshot()
    if single and single.get("sport_key") and single["sport_key"] not in sports:
        sports[single["sport_key"]] = single
    return sports


def props_for_game(league, res, payload):
    """Turn one event-odds prop payload into prop groups with real prices only."""
    if not payload:
        return []
    stat_of = {key: (stat, label) for key, stat, label in payload.get("_markets") or []}
    grouped = {}
    for book in payload.get("bookmakers") or []:
        book_key = book.get("key")
        for market in book.get("markets") or []:
            mapped = stat_of.get(market.get("key"))
            if not mapped or not book_key:
                continue
            stat, label = mapped
            for outcome in market.get("outcomes") or []:
                raw_name = (outcome.get("name") or "").strip()
                side_name = raw_name.lower()
                price = american(outcome.get("price"))
                if price is None or not book_key:
                    continue
                if side_name in ("over", "under") and outcome.get("point") is not None:
                    player = outcome.get("description") or raw_name
                    side = side_name
                    line = float(outcome["point"])
                elif side_name in ("yes", "no") and outcome.get("description"):
                    # Anytime TD and other yes/no props. The price is the posted one.
                    player = outcome.get("description")
                    side = "over" if side_name == "yes" else "under"
                    line = 0.5
                else:
                    continue
                if not player:
                    continue
                slot = grouped.setdefault((player, stat, line), {"label": label, "books": {}})
                slot["books"].setdefault(book_key, {})[side] = price
    # One main line per player and stat (closest to -110), then the players who
    # show up in the most markets. Cap the ESPN lookups.
    by_player_stat = {}
    for (player, stat, line), slot in grouped.items():
        both = [key for key, sides in slot["books"].items() if "over" in sides and "under" in sides]
        one = [key for key, sides in slot["books"].items() if sides]
        if not one:
            continue
        book = "draftkings" if "draftkings" in (both or one) else (both or one)[0]
        over = slot["books"][book].get("over")
        juice = abs(am_to_dec(over) - 1.909) if over is not None else 99
        current = by_player_stat.get((player, stat))
        if current is None or juice < current[0]:
            by_player_stat[(player, stat)] = (juice, player, stat, line, slot, book)
    coverage = {}
    for (_player, stat) in by_player_stat:
        coverage.setdefault(_player, set()).add(stat)
    ranked_players = sorted(coverage, key=lambda name: (-len(coverage[name]), name))[:4]
    chosen = []
    for name in ranked_players:
        for stat in coverage[name]:
            _juice, player, stat, line, slot, book = by_player_stat[(name, stat)]
            chosen.append((player, stat, line, slot, book))
    built = []
    for player, stat, line, slot, ref_book in chosen[:16]:
        sides = slot["books"][ref_book]
        try:
            prop = analysis.evaluate_prop(league, player, stat, line, sides.get("over"), sides.get("under"))
        except Exception as exc:
            print("  prop skip", player, stat, exc)
            continue
        if prop.get("error") or not prop.get("picks"):
            print("  prop skip", player, stat, prop.get("error"))
            continue
        ref = {pick["side"]: pick for pick in prop["picks"]}
        group_sides = {}
        for book_key, prices in slot["books"].items():
            have = [side for side in ("over", "under") if side in prices and side in ref]
            if "over" in prices and "under" in prices:
                nv, _ = no_vig([prices["over"], prices["under"]])
                probs = {"over": nv[0], "under": nv[1]} if nv else {}
            else:
                # One posted side only. Use the model's no-vig estimate and the real price.
                # Do not invent the missing side's price.
                probs = {}
                for side in have:
                    source = ref.get(side) or {}
                    if source.get("market_prob") is not None:
                        probs[side] = source["market_prob"]
            for side in have:
                if side not in probs:
                    continue
                source = ref[side]
                weight = {"High": 0.6, "Medium": 0.5, "Low": 0.3}[source.get("data_quality") or "Low"]
                reasons = [
                    f"Model {side} {line:g}: {source['model_raw']*100:.1f}% before shrink, this book's no-vig {probs[side]*100:.1f}%.",
                    f"Projection {prop['projection']} ({prop['dist']}).",
                    "Hit rate over " + ", ".join(f"{k} {v}" for k, v in (prop.get("hit_rates") or {}).items()) + ".",
                ]
                pick = make_pick(
                    "Prop", source["selection"], side, line, prices[side], source["model_raw"], probs[side],
                    weight, source.get("data_quality") or "Low", reasons, prop.get("flags") or [],
                    push=source.get("push_prob") or 0.0, caution=list(source.get("caution") or []),
                    against=source.get("case_against"),
                )
                if not pick:
                    continue
                pick["next_step"] = analysis._next_step(pick)
                group_sides.setdefault(side, {})[book_key] = strip_pick(pick, league)
        if not group_sides:
            continue
        athlete = prop.get("player") or {}
        built.append({
            "player": athlete.get("name") or player,
            "player_id": athlete.get("id"),
            "team": athlete.get("team"),
            "stat": stat,
            "stat_label": slot["label"],
            "line": line,
            "projection": prop.get("projection"),
            "hit_rates": prop.get("hit_rates"),
            "recent": [row.get("value") for row in (prop.get("recent") or [])[:10]],
            "ladder": prop.get("ladder"),
            "ladder_note": "Model fair prices from the game log. Not book prices.",
            "flags": prop.get("flags") or [],
            "status": prop.get("status"),
            "sides": group_sides,
        })
    return built


def prop_legs(game, prop):
    legs = []
    for side, offers in (prop.get("sides") or {}).items():
        extra = {
            "player": prop.get("player"),
            "position": None,
            "prop_key": f"{prop.get('player_id')}:{prop.get('stat')}",
            "hit_rates": prop.get("hit_rates"),
            "hit_rate": (prop.get("hit_rates") or {}).get("L10"),
            "stat": prop.get("stat"),
            "stat_label": prop.get("stat_label"),
            "team_abbr": prop.get("team") or game["home"]["abbr"],
            "team_name": prop.get("player"),
            "opponent": game["matchup"],
            "form": None,
        }
        # build_leg overwrites team bits. Set them after.
        leg = build_leg(game, "Prop", side, offers)
        if not leg:
            continue
        leg.update(extra)
        leg["id"] = f"prop:{game['league']}:{game['event_id']}:{prop.get('player_id')}:{prop.get('stat')}:{side}:{prop.get('line')}"
        legs.append(leg)
    return legs


def load_snapshot():
    path = DATA / "odds-snapshot.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        return None


def main():
    quick = "--quick" in sys.argv
    today = espn.today_str()
    leagues = QUICK_LIST if quick else FULL_LIST
    cap = 30 if quick else 40
    print(f"publish {'quick' if quick else 'full'} today={today} cap={cap}")
    snapshots = load_snapshots()
    snapshot = None
    for sport in ("basketball_nba", "americanfootball_nfl", "icehockey_nhl", "baseball_mlb"):
        if snapshots.get(sport):
            snapshot = snapshots[sport]
            break
    if snapshot is None and snapshots:
        snapshot = next(iter(snapshots.values()))
    api_events = []
    for snap in snapshots.values():
        api_events.extend(snap.get("events") or [])
    prop_payloads, prop_budget = refresh_props(
        os.environ.get("ODDS_API_KEY") or "",
        enabled=os.environ.get("ODDS_API_PROPS") == "1",
    )
    seen_books = set()
    for event in api_events:
        for book in event.get("bookmakers") or []:
            if book.get("key"):
                seen_books.add(book["key"])

    listed = {}  # id -> slim + maybe full later
    order = []
    analyze_jobs = []
    field_rows = []
    seen_ids = set()
    league_events = {league: 0 for league in leagues}

    for league in leagues:
        if league not in LEAGUES:
            continue
        for day in dates_for(league, quick, today):
            try:
                games = espn.games(league, day)
            except Exception as exc:
                print("scoreboard failed", league, day, exc)
                continue
            if not games:
                continue
            for game in games:
                if game.get("field"):
                    if game.get("active") or game.get("today"):
                        field_rows.append({
                            "field": True,
                            "league": league,
                            "name": game.get("name"),
                            "date": day,
                            "date_et": f"{day[:4]}-{day[4:6]}-{day[6:]}",
                            "matches": game.get("matches") or 0,
                            "today_count": len(game.get("today") or []),
                            "sample": [
                                {"players": row.get("players"), "round": row.get("round"), "state": row.get("state")}
                                for row in (game.get("today") or [])[:8]
                            ],
                            "odds": bool(game.get("odds")),
                            "note": "Schedule only. The free feed has no odds for this sport, so there is no model and no bet button.",
                        })
                    continue
                if not game.get("home") or not game.get("away") or not game.get("id"):
                    continue
                if game["id"] in seen_ids:
                    continue
                seen_ids.add(game["id"])
                league_events[league] += 1
                date_et, weekday = et_parts(game.get("date"), day)
                record = {
                    "league": league,
                    "event_id": game["id"],
                    "name": game.get("name"),
                    "start": game.get("date"),
                    "start_local": espn.local_time(game.get("date")),
                    "date_et": date_et,
                    "weekday": weekday,
                    "slate_day": day,
                    "state": (game.get("status") or {}).get("state"),
                    "status": (game.get("status") or {}).get("shortDetail"),
                    "home": {k: game["home"].get(k) for k in ("abbr", "name", "record", "id")},
                    "away": {k: game["away"].get(k) for k in ("abbr", "name", "record", "id")},
                    "neutral": game.get("neutral"),
                    "_game": game,
                }
                listed[game["id"]] = record
                order.append(game["id"])
                state = record["state"]
                if league in ANALYZE and game.get("odds") and state == "pre":
                    analyze_jobs.append(record)

    analyze_jobs.sort(key=lambda row: (PRIO.get(row["league"], 9), row["date_et"] or ""))
    # Keep college basketball from crowding out the majors.
    kept, ncaab = [], 0
    for row in analyze_jobs:
        if row["league"] == "ncaab":
            if ncaab >= 6:
                continue
            ncaab += 1
        if len(kept) >= cap:
            break
        kept.append(row)
    analyze_ids = {row["event_id"] for row in kept}
    print(f"listed {len(order)} events, analyzing {len(kept)}")

    games_dir = DATA / "games"
    games_dir.mkdir(parents=True, exist_ok=True)
    for old in games_dir.glob("*.json"):
        old.unlink()

    legs, edges = [], []
    analyzed_n = 0
    for row in kept:
        league = row["league"]
        game = row["_game"]
        print(f"  analyze {league} {row['away']['abbr']}@{row['home']['abbr']} {row['event_id']}")
        try:
            res = analysis.evaluate_game(league, game)
        except Exception as exc:
            print("    failed", exc)
            continue
        analyzed_n += 1
        sport_key = LEAGUE_TO_SPORT.get(league)
        sport_events = (snapshots.get(sport_key) or {}).get("events") or []
        api_event = match_api_event(game, sport_events) if sport_events else None
        markets = {}
        event_urls = {}
        if (res.get("odds") or {}).get("event_url"):
            event_urls["draftkings"] = res["odds"]["event_url"]
        if res.get("picks"):
            apply_engine(markets, res)
        if api_event:
            apply_api(markets, league, res, api_event, event_urls)
        props = []
        prop_payload = match_api_event(game, [row for row in prop_payloads if SPORT_TO_LEAGUE.get(row.get("sport_key")) == league])
        if prop_payload:
            props = props_for_game(league, res, prop_payload)
        full = _full_game(row, res, markets, event_urls, props, odds_feed="oddsapi" if api_event else "espn")
        write_json(f"games/{league}-{row['event_id']}.json", full)
        row["_full"] = full
        for market in full["markets"]:
            for side in market["sides"]:
                leg = build_leg(full, market["market"], side["side"], side["offers"])
                if leg:
                    legs.append(leg)
        for prop in props:
            new_legs = prop_legs(full, prop)
            legs.extend(new_legs)
            for side, offers in (prop.get("sides") or {}).items():
                primary_key = "draftkings" if "draftkings" in offers else next(iter(offers), None)
                primary = offers.get(primary_key) if primary_key else None
                if not primary or primary.get("model_prob") is None:
                    continue
                edges.append({
                    "league": full["league"],
                    "event_id": full["event_id"],
                    "game": full["name"],
                    "start_local": full["start_local"],
                    "date_et": full["date_et"],
                    "book": primary_key,
                    "selection": primary.get("selection"),
                    "market": "Prop",
                    "side": side,
                    "odds": primary.get("odds"),
                    "line": prop.get("line"),
                    "edge": primary.get("edge"),
                    "edge_at_price": primary.get("edge_at_price"),
                    "tier": "Prop",
                    "proven": False,
                    "caution": primary.get("caution") or [],
                    "model_prob": primary.get("model_prob"),
                    "leg": next((leg for leg in new_legs if leg.get("side") == side), None),
                })

    # Line-only files for games we listed but did not model, when they have a price.
    for event_id in order:
        row = listed[event_id]
        if event_id in analyze_ids and row.get("_full"):
            continue
        if row["_game"].get("odds"):
            markets = line_only_markets(row["_game"])
            event_urls = {}
            if row["_game"]["odds"].get("event_url"):
                event_urls["draftkings"] = row["_game"]["odds"]["event_url"]
            full = _full_game(row, None, markets, event_urls, [], odds_feed="espn" if markets else "none")
            write_json(f"games/{row['league']}-{event_id}.json", full)
            row["_full"] = full

    for leg in legs:
        offer = leg["offers"].get(leg["primary_book"]) or {}
        tier = offer.get("tier")
        if tier in ("High", "Medium") and offer.get("proven") is not False and (offer.get("edge") or 0) >= 0 and (offer.get("ev") or 0) > 0:
            edges.append({
                "league": leg["league"],
                "event_id": leg["event_id"],
                "game": leg["name"],
                "start_local": leg["start_local"],
                "date_et": leg["date_et"],
                "book": leg["primary_book"],
                "selection": leg["selection"],
                "market": leg["market"],
                "side": leg["side"],
                "odds": offer.get("odds"),
                "line": leg.get("line"),
                "edge": offer.get("edge"),
                "edge_at_price": offer.get("edge_at_price"),
                "tier": tier,
                "proven": True,
                "caution": offer.get("caution") or [],
                "model_prob": offer.get("model_prob"),
                "leg": leg,
            })
    rest = [row for row in edges if row.get("tier") != "Prop"]
    kept_props = {}
    for row in edges:
        if row.get("tier") != "Prop":
            continue
        leg = row.get("leg") or {}
        key = (row.get("event_id"), leg.get("prop_key") or row.get("selection"))
        prev = kept_props.get(key)
        if prev is None or (row.get("model_prob") or 0) > (prev.get("model_prob") or 0):
            kept_props[key] = row
    props_only = sorted(kept_props.values(), key=lambda row: -(row.get("model_prob") or 0))[:12]
    edges = rest + props_only
    edges.sort(key=lambda row: (TORD.get(row["tier"], 9), -(row.get("edge") or 0)))

    # Log the best modeled edge per game. Flat 1-stake internally; the UI never shows it.
    logged = []
    seen_games = set()
    for edge in edges:
        if edge.get("tier") not in ("High", "Medium") or edge.get("market") == "Prop":
            continue
        if edge["event_id"] in seen_games:
            continue
        seen_games.add(edge["event_id"])
        offer = edge["leg"]["offers"][edge["book"]]
        play = {
            "sport": edge["league"], "event_id": edge["event_id"], "event_name": edge["game"],
            "start_time": edge["leg"].get("start"), "date": edge["date_et"],
            "market": edge["market"], "selection": edge["selection"], "side": edge["side"],
            "line": edge["line"], "odds": edge["odds"], "model_prob": offer.get("model_prob"),
            "market_prob": offer.get("market_prob"), "edge": edge["edge"], "ev": offer.get("ev"),
            "tier": edge["tier"], "stake_units": 1.0,
            "rationale": " ".join(offer.get("reasons") or [])[:800],
        }
        play_id = tracker.add(play, source="digest", recommended=1)
        if play_id:
            logged.append(play_id)
        if len(seen_games) >= 8:
            break
    graded = tracker.grade()
    print(f"tracker logged {logged or 'none new'}, graded {len(graded)}")

    slate = _slate(listed, order, field_rows, today, league_events)
    report = _report()
    check_path = DATA / "odds-check.json"
    check = json.loads(check_path.read_text()) if check_path.exists() else None
    generated = dt.datetime.now(espn.ET)
    meta = {
        "generated_at": generated.isoformat(timespec="seconds"),
        "generated_at_et": generated.strftime("%a %b ") + str(generated.day) + generated.strftime(" %I:%M %p ET").replace(" 0", " "),
        "disclaimer": DISCLAIMER,
        "research_only": True,
        "games_listed": len(order),
        "games_analyzed": analyzed_n,
        "edges": len(edges),
        "legs": len(legs),
        "books": catalog(seen_books),
        "odds_api": _odds_meta(snapshot, check, prop_payloads, prop_budget, snapshots),
        "schema": "edgelab.data/v1",
    }
    write_json("meta.json", meta)
    write_json("slate.json", slate)
    write_json("edges.json", edges)
    write_json("legs.json", legs)
    write_json("report.json", report["report"])
    write_json("tracker.json", report["plays"])
    print(f"done analyzed={analyzed_n} edges={len(edges)} legs={len(legs)}")


def _full_game(row, res, markets, event_urls, props, odds_feed):
    home, away = row["home"], row["away"]
    score = None
    if row.get("state") != "pre":
        score = {"home": row["_game"]["home"].get("score"), "away": row["_game"]["away"].get("score")}
    books = sorted({book for sides in markets.values() for offers in sides.values() for book in offers})
    badge = None
    best = None
    for market, sides in markets.items():
        for side, offers in sides.items():
            primary = offers.get("draftkings") or next(iter(offers.values()))
            tier = primary.get("tier")
            edge = primary.get("edge")
            if tier in ("High", "Medium") and edge is not None and edge >= 0 and (primary.get("ev") or 0) > 0:
                rank = (TORD[tier], -(edge))
                if best is None or rank < best[0]:
                    best = (rank, {
                        "tier": tier, "edge": edge, "selection": primary.get("selection"),
                        "market": market, "book": "draftkings" if "draftkings" in offers else next(iter(offers)),
                    })
    if best:
        badge = best[1]
    full = {
        "league": row["league"],
        "league_name": LEAGUES[row["league"]]["name"],
        "event_id": row["event_id"],
        "name": row["name"] or f"{away['name']} at {home['name']}",
        "matchup": f"{away['abbr']} @ {home['abbr']}",
        "start": row["start"],
        "start_local": row["start_local"],
        "date_et": row["date_et"],
        "weekday": row["weekday"],
        "state": row["state"],
        "status": row["status"],
        "home": home,
        "away": away,
        "score": score,
        "analyzed": bool(res),
        "odds_feed": odds_feed if markets else "none",
        "books": books,
        "event_urls": event_urls,
        "lines": preview_lines(markets),
        "badge": badge,
        "model_summary": model_summary(res) if res else None,
        "flags": list((res or {}).get("flags") or []),
        "notes": list((res or {}).get("notes") or [])[:6],
        "injuries": short_injuries(res) if res else {"home": [], "away": []},
        "form": form_map(res) if res else {},
        "markets": markets_payload(markets),
        "props": props,
    }
    return full


def _slate(listed, order, field_rows, today, league_events):
    days = {}
    for event_id in order:
        row = listed[event_id]
        full = row.get("_full")
        day = row["slate_day"]
        sport = days.setdefault(day, {})
        bucket = sport.setdefault(row["league"], [])
        if full:
            bucket.append({
                "league": full["league"],
                "event_id": full["event_id"],
                "name": full["name"],
                "matchup": full["matchup"],
                "start_local": full["start_local"],
                "date_et": full["date_et"],
                "weekday": full["weekday"],
                "state": full["state"],
                "status": full["status"],
                "home": full["home"],
                "away": full["away"],
                "score": full["score"],
                "analyzed": full["analyzed"],
                "odds_feed": full["odds_feed"],
                "books": full["books"],
                "lines": full["lines"],
                "badge": full["badge"],
                "event_urls": full["event_urls"],
            })
        else:
            bucket.append({
                "league": row["league"],
                "event_id": row["event_id"],
                "name": row["name"],
                "matchup": f"{row['away']['abbr']} @ {row['home']['abbr']}",
                "start_local": row["start_local"],
                "date_et": row["date_et"],
                "weekday": row["weekday"],
                "state": row["state"],
                "status": row["status"],
                "home": row["home"],
                "away": row["away"],
                "score": None,
                "analyzed": False,
                "odds_feed": "none",
                "books": [],
                "lines": {},
                "badge": None,
                "event_urls": {},
                "empty_reason": "No odds in the free feed for this game.",
            })
    day_rows = []
    for day in sorted(days):
        sports = []
        for league, games in days[day].items():
            sports.append({"key": league, "name": LEAGUES[league]["name"], "games": games})
        sports.sort(key=lambda item: (PRIO.get(item["key"], 50), item["name"]))
        day_rows.append({
            "date": f"{day[:4]}-{day[4:6]}-{day[6:]}",
            "key": day,
            "label": day_label(day, today),
            "weekday": dt.datetime.strptime(day, "%Y%m%d").strftime("%A").lower(),
            "sports": sports,
        })
    # Attach field events to their day.
    for field in field_rows:
        day = field["date"]
        slot = next((row for row in day_rows if row["key"] == day), None)
        if slot is None:
            slot = {
                "date": f"{day[:4]}-{day[4:6]}-{day[6:]}",
                "key": day,
                "label": day_label(day, today),
                "weekday": dt.datetime.strptime(day, "%Y%m%d").strftime("%A").lower(),
                "sports": [],
            }
            day_rows.append(slot)
            day_rows.sort(key=lambda row: row["key"])
        sport = next((item for item in slot["sports"] if item["key"] == field["league"]), None)
        if sport is None:
            sport = {"key": field["league"], "name": LEAGUES[field["league"]]["name"], "games": [], "fields": []}
            slot["sports"].append(sport)
        sport.setdefault("fields", []).append(field)
    offseason = []
    for league, count in league_events.items():
        if count == 0 and LEAGUES[league]["kind"] != "field":
            offseason.append({
                "key": league,
                "name": LEAGUES[league]["name"],
                "note": "No games in this window on the free scoreboard. Off-season, or the slate is not posted yet.",
            })
    return {"days": day_rows, "offseason": offseason}


def _report():
    graded = tracker.rows("status IN ('won','lost','push') AND recommended=1")
    pending = tracker.rows("status='pending' AND recommended=1")
    overall = flat_metrics(graded)
    groups = {"sport": {}, "market": {}, "tier": {}}
    for key in groups:
        buckets = {}
        for row in graded:
            buckets.setdefault(row.get(key) or "?", []).append(row)
        groups[key] = {name: flat_metrics(rows) for name, rows in sorted(buckets.items())}
    warning = None
    if overall["n"] < 50:
        warning = f"Small sample: {overall['n']} graded plays (under 50). Record, hit rate and ROI are mostly noise at this size. CLV is the faster check."
    report = {
        "warning": warning,
        "overall": overall,
        "pending": len(pending),
        "by": groups,
        "definitions": {
            "hit_rate": "Wins divided by wins plus losses. Pushes are left out.",
            "roi_pct": "Return at the listed American odds if every graded play risked the same stake. Not dollars and not a suggested bet.",
            "clv_avg_pct": "Average of (bet decimal odds × closing no-vig probability − 1), only when the closing line matches the logged line. Positive means the price beat the close.",
            "model": "Average model probability on graded sides, versus how often those sides won. Direction hit is how often a model probability of at least 50% won and under 50% lost. Brier score: lower is better, 0.25 is a coin flip.",
        },
    }
    plays = {
        "pending": [public_play(row) for row in pending],
        "graded": [public_play(row) for row in graded],
    }
    return {"report": report, "plays": plays}


def _odds_meta(snapshot, check, prop_payloads, prop_budget=None, snapshots=None):
    odds = (check or {}).get("odds") or {}
    budget = prop_budget or {}
    meta = {
        "snapshot": bool(snapshot),
        "sport_key": (snapshot or {}).get("sport_key"),
        "sports": sorted((snapshots or {}).keys()),
        "regions": (snapshot or {}).get("regions"),
        "markets": (snapshot or {}).get("markets"),
        "fetched_at": (snapshot or {}).get("fetched_at"),
        "events": len((snapshot or {}).get("events") or []),
        "x_requests_remaining": odds.get("x_requests_remaining") or ((snapshot or {}).get("headers") or {}).get("x_requests_remaining"),
        "x_requests_used": odds.get("x_requests_used") or ((snapshot or {}).get("headers") or {}).get("x_requests_used"),
        "x_requests_last": odds.get("x_requests_last") or ((snapshot or {}).get("headers") or {}).get("x_requests_last"),
        "ohio_present": odds.get("ohio_present"),
        "ohio_absent": odds.get("ohio_absent"),
        "props_fetched": budget.get("fetched", 0),
        "props_cached": budget.get("cached", len(prop_payloads)),
        "props_budget": budget,
        "note": None,
    }
    if not snapshot:
        meta["note"] = "No Odds API snapshot. Lines are DraftKings via the free ESPN feed only, and the book list is DraftKings until a snapshot is published."
    elif odds.get("skipped"):
        meta["note"] = odds.get("reason")
    else:
        meta["note"] = "Featured moneylines, spreads and totals for one sport came from The Odds API regions=us. Other sports stay on ESPN/DraftKings. Combined parlay prices in the app are the product of leg prices, not a book's parlay quote."
    return meta


if __name__ == "__main__":
    main()
