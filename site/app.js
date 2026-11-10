"use strict";

const RISK = {
  safe: { tol: 0.3, wP: 1, wEv: 0.5, lowPen: 0.6, maxLegDec: 2.2 },
  balanced: { tol: 0.25, wP: 0.6, wEv: 1, lowPen: 0.35, maxLegDec: 3.5 },
  aggressive: { tol: 0.2, wP: 0.3, wEv: 1.5, lowPen: 0.15, maxLegDec: 99 },
};

const state = {
  meta: null,
  slate: null,
  edges: [],
  legs: [],
  report: null,
  plays: null,
  games: {},
  tab: "today",
  day: null,
  sport: "all",
  teamQuery: "",
  edgeTier: "Medium",
  book: localStorage.getItem("edgelab.book") || "draftkings",
  bookPinned: localStorage.getItem("edgelab.bookPinned") === "1",
  slip: [],
  myPlays: [],
  builder: { text: "", risk: "balanced", legs: 4, target: 400, team: "", date: "", dirty: false, parsed: null, result: null },
  sheet: null,
  game: null,
  gameError: null,
  offline: false,
  fatal: null,
  copied: null,
  copyText: "",
};

const $ = (html) => html;
const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (ch) => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
}[ch]));

function fmtAm(value) {
  if (value == null || value === "" || Number.isNaN(Number(value))) return "—";
  const n = Math.round(Number(value));
  return n > 0 ? `+${n}` : String(n);
}
function fmtPct(value) {
  if (value == null || Number.isNaN(Number(value))) return "—";
  return `${(Number(value) * 100).toFixed(1)}%`;
}
function fmtSignedPct(value) {
  if (value == null || Number.isNaN(Number(value))) return "—";
  const n = Number(value) * 100;
  return `${n > 0 ? "+" : ""}${n.toFixed(1)}%`;
}
function fmtEdge(value) {
  if (value == null || Number.isNaN(Number(value))) return "no model";
  const n = Number(value) * 100;
  return `${n > 0 ? "+" : ""}${n.toFixed(1)} pp`;
}
function edgeClass(value) {
  if (value == null || Number.isNaN(Number(value))) return "edge-none";
  if (value >= 0.02) return "edge-good";
  if (value > 0) return "edge-flat";
  return "edge-bad";
}
function amToDec(value) {
  const a = Number(value);
  return a > 0 ? 1 + a / 100 : 1 + 100 / -a;
}
function decToAm(d) {
  if (!(d > 1)) return null;
  return d >= 2 ? Math.round((d - 1) * 100) : Math.round(-100 / (d - 1));
}
function sameLine(a, b) {
  if (a == null && b == null) return true;
  if (a == null || b == null) return false;
  return Math.abs(Number(a) - Number(b)) < 0.01;
}

function books() { return state.meta?.books || []; }
function bookByKey(key) {
  return books().find((book) => book.key === key || (book.also || []).includes(key)) || null;
}
function bookKeys(book) { return book ? [book.key, ...(book.also || [])] : []; }
function offerOf(offers, book) {
  if (!offers || !book) return null;
  if (offers[book.key]) return offers[book.key];
  for (const key of book.also || []) if (offers[key]) return offers[key];
  return null;
}
function offerPrimary(leg) {
  if (!leg?.offers) return null;
  return leg.offers[leg.primary_book] || Object.values(leg.offers)[0] || null;
}
function rawKeyOn(offers, book) {
  if (!offers || !book) return null;
  if (offers[book.key]) return book.key;
  return (book.also || []).find((key) => offers[key]) || null;
}

async function fetchJson(path) {
  try {
    const response = await fetch(path, { cache: "no-cache" });
    if (!response.ok) throw new Error(String(response.status));
    const data = await response.json();
    try { localStorage.setItem("edgelab.cache." + path, JSON.stringify(data)); } catch (err) { /* quota */ }
    return data;
  } catch (err) {
    const raw = localStorage.getItem("edgelab.cache." + path);
    if (raw) {
      state.offline = true;
      return JSON.parse(raw);
    }
    throw err;
  }
}

function persistSlip() {
  localStorage.setItem("edgelab.slip", JSON.stringify(state.slip));
}
function persistPlays() {
  localStorage.setItem("edgelab.myplays", JSON.stringify(state.myPlays));
}

function icon(name) {
  const common = 'width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"';
  const paths = {
    today: `<rect x="4" y="5" width="16" height="15" rx="2"/><path d="M8 3v4M16 3v4M4 10h16"/>`,
    edges: `<path d="M4 16l5-6 4 3 7-8"/><path d="M14 5h6v6"/>`,
    builder: `<path d="M12 3l1.6 4.8L18 9.4l-4.4 1.6L12 16l-1.6-5L6 9.4l4.4-1.6L12 3z"/><path d="M18 14l.7 2 2 .7-2 .7-.7 2-.7-2-2-.7 2-.7.7-2z"/>`,
    slip: `<path d="M7 4h8l4 4v12a1 1 0 0 1-1 1H7a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1z"/><path d="M15 4v4h4M8 12h8M8 16h6"/>`,
    tracker: `<path d="M5 19V10M12 19V5M19 19v-7"/>`,
  };
  return `<svg ${common}>${paths[name] || ""}</svg>`;
}

function footer() {
  return `<p class="fine">EdgeLab is not a sportsbook and does not place or accept bets. Research only — no guarantees. Problem gambling help: <a href="tel:18004262537">1-800-GAMBLER</a>.</p>`;
}

function shell(body) {
  const stamp = state.meta?.generated_at_et || "";
  const offline = state.offline ? `<p class="banner offline-banner">Showing the last data saved on this phone. A live refresh didn't load.</p>` : "";
  return `
    <div class="phone">
      <header class="top">
        <div class="brand"><span class="mark" aria-hidden="true"></span> EdgeLab</div>
        <div class="stamp">${esc(stamp)}</div>
      </header>
      ${offline}
      <main id="screen">${body}</main>
      ${tabs()}
      ${state.sheet ? sheetHtml() : ""}
    </div>`;
}

function tabs() {
  const items = [["today", "Today"], ["edges", "Edges"], ["builder", "Builder"], ["slip", "Slip"], ["tracker", "Tracker"]];
  return `<nav class="tabs">${items.map(([id, label]) => {
    const badge = id === "slip" && state.slip.length ? `<span class="dot">${state.slip.length}</span>` : "";
    return `<button type="button" data-act="tab" data-tab="${id}" class="${state.tab === id ? "on" : ""}" ${state.tab === id ? 'aria-current="page"' : ""}>${icon(id)}${badge}${label}</button>`;
  }).join("")}</nav>`;
}

function currentDay() {
  const days = state.slate?.days || [];
  return days.find((day) => day.key === state.day) || days[0] || null;
}

function renderToday() {
  const day = currentDay();
  const days = state.slate?.days || [];
  const sports = day?.sports || [];
    const shortName = { nfl: "NFL", nba: "NBA", nhl: "NHL", cfb: "CFB", ncaab: "NCAAB", ncaaw: "NCAAW", mlb: "MLB", wnba: "WNBA", epl: "EPL", atp: "ATP", wta: "WTA", ucl: "UCL", mls: "MLS" };
    const chips = [`<button type="button" class="chip ${state.sport === "all" ? "on" : ""}" data-act="sport" data-sport="all">All</button>`]
    .concat(sports.map((sport) => `<button type="button" class="chip ${state.sport === sport.key ? "on" : ""}" data-act="sport" data-sport="${esc(sport.key)}">${esc(shortName[sport.key] || sport.name)}</button>`));
  const dayChips = days.map((item) => `<button type="button" class="chip ${item.key === day?.key ? "on" : ""}" data-act="day" data-day="${esc(item.key)}">${esc(item.label)}</button>`);
  const off = (state.slate?.offseason || []).slice(0, 6).map((row) => `<p class="note"><b>${esc(row.name)}.</b> ${esc(row.note)}</p>`).join("");
  return `
    <h1>Today</h1>
    <div class="row">${dayChips.join("")}</div>
    <div class="row">${chips.join("")}</div>
    <input id="team-filter" class="search" placeholder="Filter teams" value="${esc(state.teamQuery)}" autocomplete="off">
    <div id="game-list">${gameListHtml()}</div>
    ${off}
    ${footer()}`;
}

function gameListHtml() {
  const day = currentDay();
  if (!day) return `<div class="empty">No slate in this data file yet.</div>`;
  const query = state.teamQuery.trim().toLowerCase();
  const blocks = [];
  for (const sport of day.sports) {
    if (state.sport !== "all" && state.sport !== sport.key) continue;
    const games = (sport.games || []).filter((game) => {
      if (!query) return true;
      const hay = `${game.home?.name} ${game.away?.name} ${game.home?.abbr} ${game.away?.abbr}`.toLowerCase();
      return hay.includes(query);
    });
    const fields = sport.fields || [];
    if (!games.length && !fields.length) continue;
    blocks.push(`<h3>${esc(sport.name)}</h3>`);
    for (const game of games) blocks.push(gameCard(game));
    for (const field of fields) {
      blocks.push(`<article class="card"><div class="match">${esc(field.name)}</div><p class="note">${esc(field.note)} ${field.today_count ? esc(String(field.today_count)) + " match(es) listed today." : ""}</p></article>`);
    }
  }
  if (!blocks.length) {
    const label = state.sport === "all" ? "this day" : state.sport.toUpperCase();
    return `<div class="empty">No ${esc(label)} games with a posted slate. Try another day, or this sport is off-season in the free feed.</div>`;
  }
  return blocks.join("");
}

function lineBits(game) {
  const lines = game.lines || {};
  const preferred = lines.draftkings || Object.values(lines)[0];
  if (!preferred) return `<p class="note">No odds in the free feed.</p>`;
  const bits = [];
  if (preferred.spread_home != null && game.home) {
    const n = Number(preferred.spread_home);
    bits.push(`<span class="keep">${esc(game.home.abbr)} ${n > 0 ? "+" : ""}${n}</span>`);
  }
  if (preferred.total != null) bits.push(`<span class="keep">O/U ${preferred.total}</span>`);
  if (preferred.ml_home != null && game.home) bits.push(`<span class="keep">${esc(game.home.abbr)} ML ${fmtAm(preferred.ml_home)}</span>`);
  const bookName = (bookByKey(Object.keys(lines)[0]) || {}).name || "DraftKings";
  return `<p class="spread"><span>${bits.join(" · ") || "Odds posted"}</span></p><p class="muted">${esc(bookName)}</p>`;
}

function gameCard(game) {
  const badge = game.badge
    ? `<span class="pill ${game.badge.tier === "High" ? "high" : "medium"}">${esc(game.badge.tier)} ${esc(fmtEdge(game.badge.edge))}</span>`
    : "";
  const score = game.score && game.state !== "pre"
    ? `<span class="muted">${esc(game.away.abbr)} ${esc(game.score.away)} · ${esc(game.home.abbr)} ${esc(game.score.home)}</span>`
    : `<span class="when">${esc(game.start_local || "")}</span>`;
  return `<button type="button" class="card" data-act="game" data-league="${esc(game.league)}" data-id="${esc(game.event_id)}">
    <div class="card-top"><span class="match">${esc(game.away.abbr)} @ ${esc(game.home.abbr)}</span>${score}</div>
    <div class="records">${esc(game.away.record || "—")} at ${esc(game.home.record || "—")}</div>
    ${lineBits(game)}
    <div class="pills">${badge}${game.analyzed ? "" : `<span class="pill">Line only</span>`}</div>
  </button>`;
}

function renderEdges() {
  const rank = { High: 0, Medium: 1, Low: 2 };
  const max = rank[state.edgeTier] ?? 1;
  const rows = state.edges.filter((edge) => (rank[edge.tier] ?? 9) <= max);
  const chips = ["High", "Medium"].map((tier) => `<button type="button" class="chip ${state.edgeTier === tier ? "on" : ""}" data-act="tier" data-tier="${tier}">${tier === "Medium" ? "High + Medium" : "High only"}</button>`);
  const body = rows.length ? rows.map((edge, index) => {
    const caution = (edge.caution || []).slice(0, 2).map((item) => `<span class="pill warn">${esc(item.split(":")[0])}</span>`).join("");
    return `<button type="button" class="card" data-act="edge" data-index="${index}">
      <div class="card-top"><span class="match">${esc(edge.selection)}</span><span class="pill ${edge.tier === "High" ? "high" : "medium"}">${esc(edge.tier)} ${esc(fmtEdge(edge.edge))}</span></div>
      <p class="note">${esc(edge.game)} · ${esc(edge.start_local || "")} · ${fmtAm(edge.odds)} · model ${fmtPct(edge.model_prob)}</p>
      <div class="pills">${caution}</div>
    </button>`;
  }).join("") : `<div class="empty">No ${state.edgeTier === "High" ? "High" : "High or Medium"} edges in this refresh. Most lines are efficient. Passing is a position.</div>`;
  const visible = state.edges.filter((edge) => (rank[edge.tier] ?? 9) <= max);
  state._visibleEdges = visible;
  return `<h1>Edges</h1><div class="row">${chips.join("")}</div>${body}${footer()}`;
}

function activeBook(game) {
  const present = new Set(game?.books || []);
  const current = bookByKey(state.book);
  if (current) {
    for (const key of bookKeys(current)) if (present.has(key)) return key;
  }
  if (present.has("draftkings")) return "draftkings";
  return [...present][0] || "draftkings";
}

function renderGame() {
  if (state.gameError) return `<button class="back" type="button" data-act="tab" data-tab="today">Back</button><div class="empty">${esc(state.gameError)}</div>`;
  if (!state.game) return `<p class="note">Loading game…</p>`;
  const game = state.game;
  const bookKey = activeBook(game);
  const book = bookByKey(bookKey);
  const source = game.odds_feed === "oddsapi"
    ? `Prices from The Odds API where a book posted them. Showing ${book?.name || bookKey}.`
    : `Lines from ${book?.name || "DraftKings"} via ESPN. Other books are not in this game's free feed.`;
  const flags = (game.flags || []).map((flag) => `<span class="pill warn">${esc(String(flag).replace(/^!/, ""))}</span>`).join("");
  const injuries = ["away", "home"].map((side) => {
    const list = (game.injuries?.[side] || []).filter((row) => row.key || /out|doubt/i.test(row.status || ""));
    if (!list.length) return "";
    return `<p class="note"><b>${esc(game[side].abbr)}:</b> ${list.map((row) => `${esc(row.name)} ${esc(row.status)}`).join("; ")}</p>`;
  }).join("");
  const markets = (game.markets || []).map((market) => {
    const buttons = market.sides.map((side) => {
      const offer = side.offers?.[bookKey];
      const label = offer?.selection || side.side;
      if (!offer) {
        return `<button type="button" class="pick" disabled><span class="pick-side">${esc(label)}</span><span class="pick-meta">Not offered</span></button>`;
      }
      return `<button type="button" class="pick" data-act="pick" data-market="${esc(market.market)}" data-side="${esc(side.side)}">
        <span class="pick-side">${esc(offer.selection)}</span>
        <span class="pick-meta"><b class="num">${fmtAm(offer.odds)}</b><span class="${edgeClass(offer.edge)}">${esc(fmtEdge(offer.edge))}</span></span>
      </button>`;
    }).join("");
    return `<section><div class="market-name">${esc(market.market)}</div><div class="pair">${buttons}</div></section>`;
  }).join("");
  const props = (game.props || []).map((prop) => {
    const sides = Object.entries(prop.sides || {}).map(([side, offers]) => {
      const offer = offers[bookKey];
      if (!offer) return "";
      return `<button type="button" class="pick" data-act="prop" data-player="${esc(prop.player_id)}" data-stat="${esc(prop.stat)}" data-line="${esc(prop.line)}" data-side="${esc(side)}">
        <span class="pick-side">${esc(prop.player)} ${esc(side)} ${esc(prop.line)} ${esc(prop.stat_label)}</span>
        <span class="pick-meta"><b class="num">${fmtAm(offer.odds)}</b><span class="${edgeClass(offer.edge)}">${esc(fmtEdge(offer.edge))}</span></span>
      </button>`;
    }).join("");
    const rate = prop.hit_rates ? Object.entries(prop.hit_rates).map(([k, v]) => `${esc(k)} ${esc(v)}`).join(" · ") : "";
    return `<section><div class="market-name">${esc(prop.player)} · ${esc(prop.stat_label)} ${esc(prop.line)}</div>
      <p class="note">Projection ${esc(prop.projection)} · over hit ${rate}</p>
      <div class="pair">${sides || `<p class="note">Not offered at this book.</p>`}</div></section>`;
  }).join("");
  const propEmpty = game.props?.length ? "" : `<p class="note">No player-prop prices in this refresh. ESPN's free feed does not include prop odds, and this run did not spend Odds API credits on props. No prop line is shown rather than invented.</p>`;
  const score = game.score ? `<p class="note">Score ${esc(game.away.abbr)} ${esc(game.score.away)} – ${esc(game.home.abbr)} ${esc(game.score.home)}. Picks are only for games that have not started.</p>` : "";
  return `
    <button class="back" type="button" data-act="tab" data-tab="today">Back</button>
    <h1>${esc(game.away.abbr)} @ ${esc(game.home.abbr)}</h1>
    <p class="note">${esc(game.start_local || "")} · ${esc(game.league_name || game.league)}</p>
    <p class="note">${esc(game.model_summary || "No model number for this game.")}</p>
    ${score}
    <p class="source">${esc(source)}</p>
    <div class="pills">${flags}</div>
    ${injuries}
    <div class="markets">${markets || `<div class="empty">No markets in the free feed for this game.</div>`}</div>
    <h3>Players</h3>
    ${props}${propEmpty}
    ${footer()}`;
}

function parseRequest(text) {
  const raw = text.trim();
  const lower = raw.toLowerCase();
  let risk = "balanced";
  if (/\b(safe|safer|conservative|chalk)\b/.test(lower)) risk = "safe";
  if (/\b(aggressive|lotto|risky|longshot)\b/.test(lower)) risk = "aggressive";
  let legs = 3;
  const legMatch = lower.match(/(\d+)\s*-?\s*leg/);
  if (legMatch) legs = Math.max(2, Math.min(8, parseInt(legMatch[1], 10)));
  let target = 400;
  const price = raw.match(/([+-]\d{3,4})\b/);
  if (price) target = parseInt(price[1], 10);
  let date = "";
  for (const word of ["today", "tomorrow", "yesterday", "sunday", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday"]) {
    if (lower.includes(word)) date = word;
  }
  const ymd = lower.match(/\b(20\d{2}-?\d{2}-?\d{2})\b/);
  if (ymd) date = ymd[1];
  const stop = new Set("safe safer conservative chalk aggressive lotto risky longshot leg legs parlay parlays prop props build builder for the a an on at to of and with me my target odds today tomorrow yesterday sunday monday tuesday wednesday thursday friday saturday".split(" "));
  const team = raw.split(/\s+/).filter((word) => {
    const token = word.toLowerCase().replace(/[^a-z0-9]/g, "");
    if (!token || stop.has(token) || /^[+-]?\d+$/.test(word)) return false;
    return true;
  }).join(" ");
  return { risk, legs, target, date, team, raw };
}

function matchDate(leg, date) {
  const value = String(date || "").toLowerCase();
  if (!value) return true;
  if (value === "today" || value === "tomorrow" || value === "yesterday") {
    const day = (state.slate?.days || []).find((item) => item.label.toLowerCase() === value);
    return day ? leg.date_et === day.date : false;
  }
  if (/^[a-z]+$/.test(value)) return (leg.weekday || "") === value || (leg.weekday || "").startsWith(value.slice(0, 3));
  return (leg.date_et || "").replace(/-/g, "") === value.replace(/-/g, "");
}
function matchTeam(leg, team) {
  const query = team.toLowerCase();
  const hay = [leg.home_name, leg.away_name, leg.home_abbr, leg.away_abbr, leg.team_name, leg.player].filter(Boolean).join(" ").toLowerCase();
  return hay.includes(query);
}
function conflict(a, b) {
  if (a.event_id !== b.event_id) return false;
  if (a.market === b.market && a.market !== "Prop") return true;
  if (a.market === "Prop" && b.market === "Prop") return a.prop_key && a.prop_key === b.prop_key;
  const sides = new Set(["ML", "1X2", "Spread"]);
  if (sides.has(a.market) && sides.has(b.market) && a.side !== b.side) return true;
  return false;
}
function combinations(list, k) {
  const out = [];
  const walk = (start, combo) => {
    if (combo.length === k) { out.push(combo.slice()); return; }
    for (let i = start; i < list.length; i++) {
      combo.push(list[i]);
      walk(i + 1, combo);
      combo.pop();
    }
  };
  if (k > 0) walk(0, []);
  return out;
}
function corrNotes(legs) {
  const notes = [];
  const byEvent = {};
  for (const leg of legs) (byEvent[leg.event_id] ||= []).push(leg);
  for (const group of Object.values(byEvent)) {
    if (group.length < 2) continue;
    notes.push(`Same-game legs (${group.map((leg) => leg.selection).join(", ")}): these outcomes move together, so the independence probability is only an approximation. A same-game parlay price will differ, usually for the worse.`);
    const markets = Object.fromEntries(group.map((leg) => [leg.market, leg]));
    if ((markets.ML || markets["1X2"]) && markets.Spread) {
      notes.push("Moneyline and spread on the same game are strongly correlated. The spread leg adds less than the multiplied probability implies.");
    }
    if (markets.Total && (markets.Spread || markets.ML)) {
      notes.push("A side and a total in the same game are mildly correlated. Favorite-and-over, or underdog-and-under, tend to land together.");
    }
    if (group.some((leg) => leg.market === "Prop")) {
      notes.push("Player props move with the game total and the player's team. Treat the combined probability as a rough ceiling.");
    }
  }
  return notes;
}

function runBuild(spec) {
  const notes = [];
  const profile = RISK[spec.risk] || RISK.balanced;
  let universe = state.legs.slice();
  if (spec.date) {
    const dated = universe.filter((leg) => matchDate(leg, spec.date));
    if (dated.length) universe = dated;
    else notes.push(`No published legs on ${spec.date}. The builder used the full published slate instead.`);
  }
  const teamLegs = spec.team ? universe.filter((leg) => matchTeam(leg, spec.team)) : [];
  if (spec.team && !teamLegs.length) notes.push(`No game matching “${spec.team}” in that window.`);
  const teamEvents = new Set(teamLegs.map((leg) => leg.event_id)).size;
  const teamCapacity = teamEvents * 3 + teamLegs.filter((leg) => leg.market === "Prop").length;
  let expanded = false;
  let pool = universe;
  if (teamLegs.length && teamLegs.length >= spec.legs && teamCapacity >= spec.legs) pool = teamLegs;
  else if (teamLegs.length && (teamLegs.length < spec.legs || teamCapacity < spec.legs)) {
    expanded = true;
    notes.push(`${spec.team} can fill about ${teamCapacity} uncorrelated priced markets from the games found. Other legs are taken from the same published slate. No prop price was invented to fill the card.`);
  }
  const scoreOf = (leg) => offerPrimary(leg)?.model_prob || 0;
  const rankedTeam = [...teamLegs].sort((a, b) => scoreOf(b) - scoreOf(a));
  const rest = pool.filter((leg) => !rankedTeam.includes(leg)).sort((a, b) => scoreOf(b) - scoreOf(a));
  pool = [...rankedTeam, ...rest].slice(0, 12);
  const priced = pool.filter((leg) => {
    const offer = offerPrimary(leg);
    return offer && amToDec(offer.odds) <= profile.maxLegDec;
  });
  const usable = priced.length >= 2 ? priced : pool;
  if (usable.length < 2) return { error: "Not enough priced legs in the published data for that request.", notes, spec };
  const n = Math.min(spec.legs, usable.length);
  if (n < spec.legs) notes.push(`Only ${usable.length} priced candidate legs were available, so this is a ${n}-leg card.`);
  const targetDec = amToDec(spec.target);
  const must = new Set(rankedTeam.map((leg) => leg.id));
  let scored = [];
  for (const combo of combinations(usable, n)) {
    if (combo.some((a, i) => combo.slice(i + 1).some((b) => conflict(a, b)))) continue;
    if (must.size && !combo.some((leg) => must.has(leg.id))) continue;
    const prob = combo.reduce((product, leg) => product * (offerPrimary(leg).model_prob || 0), 1);
    const dec = combo.reduce((product, leg) => product * amToDec(offerPrimary(leg).odds), 1);
    if (!(prob > 0) || !(dec > 1)) continue;
    const dist = Math.abs(Math.log(dec) - Math.log(targetDec));
    const ev = prob * dec - 1;
    const lows = combo.filter((leg) => offerPrimary(leg).tier === "Low").length;
    const score = -2 * dist + profile.wP * Math.log(prob) + profile.wEv * ev - profile.lowPen * lows;
    scored.push({ combo, prob, dec, ev, dist, score, within: dist <= Math.log(1 + profile.tol) });
  }
  if (!scored.length && must.size) {
    notes.push("No combo could keep the named team without a conflict, so the team requirement was dropped.");
    for (const combo of combinations(usable, n)) {
      if (combo.some((a, i) => combo.slice(i + 1).some((b) => conflict(a, b)))) continue;
      const prob = combo.reduce((product, leg) => product * (offerPrimary(leg).model_prob || 0), 1);
      const dec = combo.reduce((product, leg) => product * amToDec(offerPrimary(leg).odds), 1);
      if (!(prob > 0) || !(dec > 1)) continue;
      const dist = Math.abs(Math.log(dec) - Math.log(targetDec));
      const ev = prob * dec - 1;
      const lows = combo.filter((leg) => offerPrimary(leg).tier === "Low").length;
      const score = -2 * dist + profile.wP * Math.log(prob) + profile.wEv * ev - profile.lowPen * lows;
      scored.push({ combo, prob, dec, ev, dist, score, within: dist <= Math.log(1 + profile.tol) });
    }
  }
  if (!scored.length) return { error: "No non-conflicting combination of priced legs matched.", notes, spec };
  const anyWithin = scored.some((row) => row.within);
  scored.sort((a, b) => {
    if (anyWithin && a.within !== b.within) return a.within ? -1 : 1;
    if (!anyWithin && Math.round(a.dist * 100) !== Math.round(b.dist * 100)) return Math.round(a.dist * 100) - Math.round(b.dist * 100);
    return b.score - a.score;
  });
  const best = scored[0];
  const honest = [];
  if (!best.within) honest.push(`No combo lands within ${Math.round(profile.tol * 100)}% of ${fmtAm(spec.target)}. Closest estimated price is ${fmtAm(decToAm(best.dec))}.`);
  const negative = best.combo.filter((leg) => (offerPrimary(leg).edge || 0) < 0);
  if (negative.length) {
    honest.push(`Hitting ${fmtAm(spec.target)} with ${n} legs uses ${negative.length} leg(s) with no model edge (${negative.map((leg) => leg.selection).join(", ")}). The model would not take those as singles. They are filler to reach the price.`);
  }
  if (best.ev < 0) honest.push(`Expected return at the estimated price is ${fmtSignedPct(best.ev)} before same-game pricing. That is not a value bet.`);
  const weak = [];
  for (const leg of [...best.combo].sort((a, b) => (offerPrimary(a).edge || 0) - (offerPrimary(b).edge || 0))) {
    const offer = offerPrimary(leg);
    const why = [];
    if ((offer.edge || 0) < 0) why.push(`negative edge ${fmtEdge(offer.edge)}`);
    if (offer.tier === "Low") why.push("Low tier");
    if ((offer.model_prob || 1) < 0.4) why.push(`low hit probability ${fmtPct(offer.model_prob)}`);
    if ((offer.caution || []).length) why.push("caution: " + offer.caution.join("; "));
    if (why.length) weak.push({ id: leg.id, why });
  }
  return {
    spec, notes, honest, expanded,
    legs: best.combo,
    weak,
    correlation: corrNotes(best.combo),
    prob: best.prob,
    fair: decToAm(1 / best.prob),
    payout: decToAm(best.dec),
    ev: best.ev,
    within: best.within,
    priceBasis: "Product of each leg's listed price at the modeled line. A book's parlay price, especially same-game, will be different.",
    alternatives: scored.slice(1, 3).map((row) => ({
      label: row.combo.map((leg) => leg.selection).join(" + "),
      price: decToAm(row.dec),
      prob: row.prob,
    })),
  };
}

function renderBuilder() {
  const b = state.builder;
  const days = (state.slate?.days || []).map((day) => `<option value="${esc(day.weekday)}" ${b.date === day.weekday ? "selected" : ""}>${esc(day.label)}</option>`).join("");
  let result = "";
  if (b.result?.error) {
    result = `<div class="empty">${esc(b.result.error)}</div>${(b.result.notes || []).map((note) => `<p class="note">${esc(note)}</p>`).join("")}`;
  } else if (b.result?.legs) {
    const res = b.result;
    const weakIds = new Set((res.weak || []).map((row) => row.id));
    const legs = res.legs.map((leg, index) => {
      const offer = offerPrimary(leg);
      const why = (offer.reasons || [])[0] || "";
      return `<article class="leg ${weakIds.has(leg.id) ? "weak" : ""}">
        <div><div class="leg-title">${index + 1}. ${esc(leg.selection)}</div>
        <div class="leg-sub">${esc(leg.matchup)} · ${esc(leg.start_local || "")}</div></div>
        <div class="num">${fmtAm(offer.odds)}<div class="${edgeClass(offer.edge)}">${esc(fmtEdge(offer.edge))}</div></div>
        <div class="leg-sub">Model ${fmtPct(offer.model_prob)} · ${esc(offer.tier || "")}${leg.hit_rate ? ` · L10 over ${esc(leg.hit_rate)}` : ""}${leg.form ? ` · ${esc(leg.form)}` : ""}<br>${esc(why)}</div>
      </article>`;
    }).join("");
    const weak = (res.weak || []).map((row) => `<li>${esc(res.legs.find((leg) => leg.id === row.id)?.selection || "Leg")}: ${esc(row.why.join("; "))}</li>`).join("");
    result = `
      <div id="build-result">
        <div class="statgrid">
          <div class="stat"><span>Model fair</span><b class="num">${fmtPct(res.prob)} · ${fmtAm(res.fair)}</b></div>
          <div class="stat"><span>Estimated payout</span><b class="num">${fmtAm(res.payout)}</b></div>
        </div>
        <p class="note">${esc(res.priceBasis)} Expected return at that estimate: ${fmtSignedPct(res.ev)}.</p>
        ${legs}
        <h3>Weakest leg</h3>
        ${weak ? `<ul>${weak}</ul>` : `<p class="note">No leg was flagged.</p>`}
        ${(res.correlation || []).map((note) => `<p class="note">${esc(note)}</p>`).join("")}
        ${(res.honest || []).map((note) => `<p class="warnbox">${esc(note)}</p>`).join("")}
        ${(res.notes || []).map((note) => `<p class="note">${esc(note)}</p>`).join("")}
        <button type="button" class="cta" data-act="use-build">Put these on the slip</button>
      </div>`;
  }
  const parsed = b.parsed ? `<p class="note">Read as ${esc(b.parsed.risk)} · ${esc(b.parsed.legs)} legs · ${esc(b.parsed.team || "any team")} · ${esc(b.parsed.date || "any date")} · target ${fmtAm(b.parsed.target)}.</p>` : "";
  return `
    <h1>Builder</h1>
    <p class="note">Type a request, or set the controls. Legs come only from published prices.</p>
    <input id="sentence" class="field" placeholder="safe 4 leg parlay browns sunday +400" value="${esc(b.text)}">
    <button type="button" class="cta" data-act="build">Build</button>
    ${parsed}
    <div class="grid-2">
      <div><label class="lbl" for="team">Team</label><input id="team" class="field" value="${esc(b.team)}"></div>
      <div><label class="lbl" for="date">Date</label>
        <select id="date" class="field"><option value="">Any published day</option>${days}</select></div>
    </div>
    <label class="lbl">Legs ${esc(b.legs)}</label>
    <div class="seg">
      ${[2, 3, 4, 5, 6].map((n) => `<button type="button" data-act="legs" data-n="${n}" class="${Number(b.legs) === n ? "on" : ""}">${n}</button>`).join("")}
    </div>
    <div class="grid-2">
      <div><label class="lbl" for="target">Target American odds</label><input id="target" class="field" inputmode="text" value="${esc(b.target)}"></div>
      <div><label class="lbl">Risk</label><div class="seg">${["safe", "balanced", "aggressive"].map((risk) => `<button type="button" data-act="risk" data-risk="${risk}" class="${b.risk === risk ? "on" : ""}">${risk}</button>`).join("")}</div></div>
    </div>
    ${result}
    ${footer()}`;
}

function slipBooks(legs) {
  const covered = legs.some((leg) => leg.odds_feed === "oddsapi");
  if (!covered) return books().filter((book) => legs.some((leg) => offerOf(leg.offers, book)));
  return books();
}
function summaryFor(legs, book) {
  const rows = legs.map((leg) => ({ leg, offer: offerOf(leg.offers, book) }));
  const have = rows.filter((row) => row.offer && row.offer.odds != null).length;
  const complete = legs.length > 0 && have === legs.length;
  let dec = 1;
  let prob = 1;
  if (complete) {
    for (const row of rows) {
      dec *= amToDec(row.offer.odds);
      prob *= Number(row.offer.model_prob);
    }
  }
  return { have, total: legs.length, complete, dec, prob: complete ? prob : null, american: complete ? decToAm(dec) : null };
}
function bestBook(legs) {
  let best = null;
  for (const book of slipBooks(legs)) {
    const summary = summaryFor(legs, book);
    if (!summary.complete) continue;
    if (!best || summary.dec > best.summary.dec) best = { book, summary };
  }
  return best;
}

function renderSlip() {
  if (!state.slip.length) {
    return `<h1>Slip</h1><div class="empty">Nothing here yet. Build a card or add a side from a game. EdgeLab will copy the legs. It cannot pre-fill a sportsbook.</div>${footer()}`;
  }
  const catalog = slipBooks(state.slip);
  const best = bestBook(state.slip);
  const selected = state.bookPinned ? (bookByKey(state.book) || best?.book) : (best?.book || bookByKey(state.book) || catalog[0]);
  const summary = selected ? summaryFor(state.slip, selected) : null;
  const cards = catalog.map((book) => {
    const row = summaryFor(state.slip, book);
    const inFeed = book.in_feed || row.have > 0;
    const disabled = !inFeed || !row.complete;
    const count = !inFeed ? "no feed" : `${row.have}/${row.total} bets`;
    const price = row.complete ? `${fmtAm(row.american)} est.` : "—";
    const isBest = best && book.key === best.book.key;
    const on = selected && book.key === selected.key;
    return `<button type="button" class="book ${on ? "on" : ""} ${isBest ? "best" : ""} ${disabled ? "off" : ""}" data-act="choose-book" data-book="${esc(book.key)}" ${disabled ? "disabled" : ""}>
      <div class="book-name">${esc(book.name)} ${isBest ? `<span class="tag">Best</span>` : ""} ${on ? `<span class="tag">Selected</span>` : ""}</div>
      <div class="book-count">${esc(count)}</div>
      <div class="book-price num">${esc(price)}</div>
    </button>`;
  }).join("");
  const legs = state.slip.map((leg) => {
    const offer = selected ? offerOf(leg.offers, selected) : null;
    const who = leg.player || leg.team_name || leg.selection;
    return `<article class="leg">
      <div>
        <div class="leg-title">${esc(who)}</div>
        <div class="leg-sub">${esc(leg.selection)} · ${esc(leg.matchup || "")} · ${esc(leg.start_local || "")}</div>
        <div class="leg-sub">Model ${offer ? fmtPct(offer.model_prob) : "—"} ${leg.hit_rate ? `· L10 over ${esc(leg.hit_rate)}` : leg.form ? `· ${esc(leg.form)}` : ""}</div>
      </div>
      <div><b class="num">${offer ? fmtAm(offer.odds) : "—"}</b><button type="button" class="x" data-act="remove" data-id="${esc(leg.id)}" aria-label="Remove">×</button></div>
    </article>`;
  }).join("");
  const edge = summary?.complete ? summary.prob - 1 / summary.dec : null;
  const same = corrNotes(state.slip);
  const negative = state.slip.filter((leg) => {
    const offer = selected && offerOf(leg.offers, selected);
    return offer && (offer.edge || 0) < 0;
  });
  const risk = [
    "Estimated price multiplies the leg prices. It is not the sportsbook's parlay price.",
    ...same,
    negative.length ? `${negative.length} leg(s) have no model edge at this book.` : "",
    edge != null && edge < 0 ? "The model probability is below the estimated price. That is a negative edge." : "",
  ].filter(Boolean);
  const absent = catalog.filter((book) => !book.in_feed && book.feed_note).slice(0, 3).map((book) => `<p class="note">${esc(book.name)}: ${esc(book.feed_note)}</p>`).join("");
  const copied = state.copied === true ? `<p class="note">Slip copied. Pre-filled bets are not supported — enter the legs yourself.</p>`
    : state.copied === false ? `<p class="note">Clipboard was blocked. Select the slip text below.</p><textarea class="field copybox" readonly>${esc(state.copyText)}</textarea>` : "";
  return `
    <h1>Slip</h1>
    <div class="books">${cards}</div>
    <p class="note">Best price is the highest estimated payout among books that offer every leg. “est.” means the product of leg prices, not a quoted parlay.</p>
    ${absent}
    ${legs}
    <div class="statgrid">
      <div class="stat"><span>Estimated odds</span><b class="num">${summary?.complete ? fmtAm(summary.american) : "—"}</b></div>
      <div class="stat"><span>Model vs price</span><b class="num">${edge == null ? "—" : fmtEdge(edge)}</b></div>
    </div>
    <p class="note">Model ${summary?.complete ? fmtPct(summary.prob) : "—"} if the legs were independent. Fair ${summary?.complete ? fmtAm(decToAm(1 / summary.prob)) : "—"}.</p>
    ${risk.map((line) => `<p class="note">${esc(line)}</p>`).join("")}
    <button type="button" class="cta" data-act="open-book" ${selected ? "" : "disabled"}>Open in ${esc(selected?.name || "book")}</button>
    <p class="source">Opens that book's event page when every leg is the same game and the feed included a public link. Otherwise it opens the book's home. The slip is copied. EdgeLab cannot fill the bet slip for you.</p>
    ${copied}
    <button type="button" class="btn block" data-act="save-play">Save to my plays</button>
    <button type="button" class="btn block" data-act="clear-slip">Clear slip</button>
    ${footer()}`;
}

function renderTracker() {
  const overall = state.report?.overall || {};
  const model = overall.model || {};
  const warning = state.report?.warning;
  const blocks = ["sport", "market", "tier"].map((key) => {
    const rows = Object.entries(state.report?.by?.[key] || {});
    if (!rows.length) return "";
    const body = rows.map(([name, stats]) => `<p class="note"><b>${esc(name)}</b> ${esc(stats.record)} · hit ${fmtPct(stats.hit_rate)} · ROI ${stats.roi_pct == null ? "—" : esc(String(stats.roi_pct)) + "%"} · CLV ${stats.clv_avg_pct == null ? "—" : esc(String(stats.clv_avg_pct)) + "%"}</p>`).join("");
    return `<h3>By ${esc(key)}</h3>${body}`;
  }).join("");
  const pending = (state.plays?.pending || []).slice(-12).map((play) => `<p class="note">${esc(play.date)} · ${esc(play.sport)} · ${esc(play.selection)} ${fmtAm(play.odds)} · ${esc(play.tier || "")}</p>`).join("");
  const mine = state.myPlays.length ? state.myPlays.map((play) => `<article class="card"><div class="match">${play.legs.length} legs · ${esc(bookByKey(play.book)?.name || play.book || "")}</div><p class="note">${play.legs.map((leg) => esc(leg.selection)).join(" · ")}</p><p class="note">Saved on this phone. Not graded by the refresh.</p><button type="button" class="btn" data-act="drop-play" data-id="${esc(play.id)}">Remove</button></article>`).join("") : `<p class="note">No personal slips saved on this phone.</p>`;
  return `
    <h1>Tracker</h1>
    ${warning ? `<div class="warnbox">${esc(warning)}</div>` : ""}
    <div class="statgrid">
      <div class="stat"><span>Record</span><b class="num">${esc(overall.record || "0-0-0")}</b></div>
      <div class="stat"><span>Hit rate</span><b class="num">${fmtPct(overall.hit_rate)}</b></div>
      <div class="stat"><span>ROI at listed odds</span><b class="num">${overall.roi_pct == null ? "—" : esc(String(overall.roi_pct)) + "%"}</b></div>
      <div class="stat"><span>Average CLV</span><b class="num">${overall.clv_avg_pct == null ? "—" : esc(String(overall.clv_avg_pct)) + "%"}</b></div>
    </div>
    <p class="note">${model.n ? `Model called ${fmtPct(model.avg_model_prob)} on average and those sides won ${fmtPct(model.actual_win_rate)}. Direction ${fmtPct(model.direction_hit)}. Brier ${model.brier == null ? "—" : esc(String(model.brier))} (0.25 is a coin flip, lower is better).` : "Model accuracy appears after plays are graded. There is nothing to compare yet."}</p>
    <p class="note">${esc(state.report?.definitions?.roi_pct || "")}</p>
    ${blocks}
    <h3>Waiting on a final</h3>
    ${pending || `<p class="note">No pending recommended plays. The refresh logs High and Medium edges and grades them from ESPN finals.</p>`}
    <h3>My plays</h3>
    ${mine}
    ${footer()}`;
}

function sheetHtml() {
  const sheet = state.sheet;
  if (!sheet) return "";
  const offer = sheet.offer;
  const leg = sheet.leg;
  if (!offer) {
    return `<div class="sheet"><div class="sheet-card"><div class="grab"></div><p class="note">No priced side to explain.</p><button type="button" class="btn" data-act="close-sheet">Close</button></div></div>`;
  }
  const numbers = offer.model_prob == null
    ? `<p>This is a posted line only. No model was run, so there is no edge, fair price, or recommendation.</p>`
    : `<p>Model ${fmtPct(offer.model_prob)} (raw ${fmtPct(offer.model_raw)}). Market no-vig ${fmtPct(offer.market_prob)}. Edge ${fmtEdge(offer.edge)} versus no-vig, ${fmtEdge(offer.edge_at_price)} at this price. Fair price ${fmtAm(offer.fair_odds)}. Expected return at this price ${fmtSignedPct(offer.ev)}.</p>`;
  const why = (offer.reasons || []).map((row) => `<li>${esc(row)}</li>`).join("");
  const caution = (offer.caution || []).map((row) => `<li>${esc(row)}</li>`).join("");
  const add = offer.model_prob == null ? "" : `<button type="button" class="cta" data-act="add-sheet">Add to slip</button>`;
  return `<div class="sheet" data-act="close-sheet">
    <div class="sheet-card" data-act="stop">
      <div class="grab"></div>
      <p class="kicker note">${esc(leg.market)} · ${esc(offer.tier || "no tier")}</p>
      <h2>${esc(offer.selection || leg.selection)} <span class="num">${fmtAm(offer.odds)}</span></h2>
      <p class="note">${esc(leg.matchup || leg.name || "")} · ${esc(leg.start_local || "")}</p>
      <h3>Numbers</h3>${numbers}
      <h3>Why</h3><ul>${why}</ul>
      <h3>Case against</h3><p>${esc(offer.case_against || "")}</p>
      <h3>Next step</h3><p>${esc(offer.next_step || "")}</p>
      ${caution ? `<h3>Caution</h3><ul>${caution}</ul>` : ""}
      ${leg.hit_rates ? `<p class="note">Over hit rate ${Object.entries(leg.hit_rates).map(([k, v]) => `${esc(k)} ${esc(v)}`).join(" · ")}</p>` : ""}
      ${add}
      <button type="button" class="btn block" data-act="close-sheet">Close</button>
    </div>
  </div>`;
}

function legFromGame(game, marketName, sideName, bookKey) {
  const market = (game.markets || []).find((item) => item.market === marketName);
  const side = market?.sides?.find((item) => item.side === sideName);
  const offer = side?.offers?.[bookKey];
  if (!offer) return null;
  const offers = {};
  for (const [key, row] of Object.entries(side.offers)) {
    if (sameLine(row.line, offer.line)) offers[key] = row;
  }
  const home = sideName === "home";
  return {
    id: `${game.league}:${game.event_id}:${marketName}:${sideName}:${offer.line ?? "na"}`,
    event_id: game.event_id,
    league: game.league,
    name: game.name,
    start: game.start,
    start_local: game.start_local,
    date_et: game.date_et,
    weekday: game.weekday,
    matchup: game.matchup,
    home_abbr: game.home.abbr,
    away_abbr: game.away.abbr,
    home_name: game.home.name,
    away_name: game.away.name,
    market: marketName,
    side: sideName,
    selection: offer.selection,
    line: offer.line,
    primary_book: bookKey,
    team_abbr: sideName === "home" || sideName === "away" ? game[sideName].abbr : null,
    team_name: sideName === "home" || sideName === "away" ? game[sideName].name : null,
    opponent: sideName === "home" ? `vs ${game.away.abbr}` : sideName === "away" ? `@ ${game.home.abbr}` : game.matchup,
    position: null,
    player: null,
    prop_key: null,
    hit_rate: null,
    form: game.form?.[sideName] || null,
    event_urls: game.event_urls || {},
    odds_feed: game.odds_feed,
    offers,
    _home: home,
  };
}

function render() {
  let body;
  if (state.fatal) body = `<div class="empty">${esc(state.fatal)}</div>`;
  else if (state.tab === "today") body = renderToday();
  else if (state.tab === "edges") body = renderEdges();
  else if (state.tab === "game") body = renderGame();
  else if (state.tab === "builder") body = renderBuilder();
  else if (state.tab === "slip") body = renderSlip();
  else body = renderTracker();
  document.getElementById("app").innerHTML = shell(body);
  document.body.dataset.ready = state.fatal ? "error" : "1";
}

function go(hash) {
  if (location.hash === hash) route();
  else location.hash = hash;
}

async function showGame(league, id) {
  state.tab = "game";
  state.game = state.games[`${league}-${id}`] || null;
  state.gameError = null;
  state.sheet = null;
  render();
  if (state.game) return;
  try {
    const response = await fetchJson(`data/games/${league}-${id}.json`);
    state.games[`${league}-${id}`] = response;
    state.game = response;
  } catch (err) {
    state.gameError = "This game is not in the latest data file.";
  }
  render();
}

function route() {
  const raw = (location.hash || "#today").replace(/^#/, "");
  const [head, league, id] = raw.split("/");
  state.sheet = null;
  if (head === "game" && league && id) {
    showGame(league, decodeURIComponent(id));
    return;
  }
  state.tab = ["today", "edges", "builder", "slip", "tracker"].includes(head) ? head : "today";
  if (head !== "game") state.game = null;
  render();
}

function addLeg(leg) {
  if (!leg || state.slip.some((item) => item.id === leg.id)) return;
  state.slip.push(leg);
  state.bookPinned = false;
  persistSlip();
}

function openSheet(leg, bookKey) {
  const book = bookByKey(bookKey) || { key: bookKey, also: [] };
  const offer = offerOf(leg.offers, book) || offerPrimary(leg);
  state.sheet = { leg, offer, bookKey };
  render();
}

async function openBook() {
  const catalog = slipBooks(state.slip);
  const best = bestBook(state.slip);
  const selected = state.bookPinned ? (bookByKey(state.book) || best?.book) : (best?.book || catalog[0]);
  if (!selected) return;
  const summary = summaryFor(state.slip, selected);
  const lines = [
    "EdgeLab research slip — not a bet",
    selected.name,
    ...state.slip.map((leg, index) => {
      const offer = offerOf(leg.offers, selected);
      return `${index + 1}. ${leg.selection} ${offer ? fmtAm(offer.odds) : "not offered"} — ${leg.matchup || ""} — ${leg.start_local || ""}`;
    }),
    summary.complete ? `Estimated from leg prices: ${fmtAm(summary.american)} (the book's parlay price will differ)` : "This book does not offer every leg.",
    summary.complete ? `Model if independent: ${fmtPct(summary.prob)} · fair ${fmtAm(decToAm(1 / summary.prob))}` : "",
    "Pre-filled slips are not supported. Enter the legs yourself.",
    "Research only. No guarantees. 1-800-GAMBLER.",
  ].filter(Boolean);
  const text = lines.join("\n");
  state.copyText = text;
  try {
    await navigator.clipboard.writeText(text);
    state.copied = true;
  } catch (err) {
    state.copied = false;
  }
  let url = selected.home;
  const events = new Set(state.slip.map((leg) => leg.event_id));
  if (events.size === 1) {
    const urls = state.slip[0].event_urls || {};
    for (const key of bookKeys(selected)) if (urls[key]) { url = urls[key]; break; }
  }
  render();
  window.open(url, "_blank", "noopener");
}

function onClick(event) {
  const el = event.target.closest("[data-act]");
  if (!el) return;
  const act = el.dataset.act;
  if (act === "stop") { event.stopPropagation(); return; }
  if (act === "tab") { go("#" + el.dataset.tab); return; }
  if (act === "day") { state.day = el.dataset.day; render(); return; }
  if (act === "sport") { state.sport = el.dataset.sport; render(); return; }
  if (act === "tier") { state.edgeTier = el.dataset.tier; render(); return; }
  if (act === "game") { go(`#game/${el.dataset.league}/${el.dataset.id}`); return; }
  if (act === "edge") {
    const edge = state._visibleEdges?.[Number(el.dataset.index)];
    if (edge?.leg) openSheet(edge.leg, edge.book);
    return;
  }
  if (act === "pick" && state.game) {
    const leg = legFromGame(state.game, el.dataset.market, el.dataset.side, activeBook(state.game));
    if (leg) openSheet(leg, activeBook(state.game));
    return;
  }
  if (act === "prop" && state.game) {
    const prop = (state.game.props || []).find((item) => String(item.player_id) === el.dataset.player && item.stat === el.dataset.stat && String(item.line) === el.dataset.line);
    const offers = prop?.sides?.[el.dataset.side];
    if (!prop || !offers) return;
    const bookKey = activeBook(state.game);
    const leg = {
      id: `prop:${state.game.league}:${state.game.event_id}:${prop.player_id}:${prop.stat}:${el.dataset.side}:${prop.line}`,
      event_id: state.game.event_id,
      league: state.game.league,
      name: state.game.name,
      start_local: state.game.start_local,
      matchup: state.game.matchup,
      market: "Prop",
      side: el.dataset.side,
      selection: offers[bookKey]?.selection || `${prop.player} ${el.dataset.side} ${prop.line}`,
      line: prop.line,
      player: prop.player,
      team_name: prop.player,
      prop_key: `${prop.player_id}:${prop.stat}`,
      hit_rate: prop.hit_rates?.L10 || null,
      hit_rates: prop.hit_rates,
      primary_book: bookKey,
      offers,
      event_urls: state.game.event_urls || {},
      odds_feed: state.game.odds_feed,
    };
    openSheet(leg, bookKey);
    return;
  }
  if (act === "close-sheet") { state.sheet = null; render(); return; }
  if (act === "add-sheet" && state.sheet?.leg) {
    addLeg(state.sheet.leg);
    state.sheet = null;
    go("#slip");
    return;
  }
  if (act === "build") {
    const text = document.getElementById("sentence")?.value ?? state.builder.text;
    state.builder.text = text;
    let spec;
    if (!state.builder.dirty && text.trim()) spec = parseRequest(text);
    else {
      spec = {
        risk: state.builder.risk,
        legs: Number(state.builder.legs) || 3,
        target: Number(state.builder.target) || 400,
        team: document.getElementById("team")?.value || state.builder.team,
        date: document.getElementById("date")?.value || state.builder.date,
      };
    }
    state.builder.team = spec.team || "";
    state.builder.date = spec.date || "";
    state.builder.legs = spec.legs;
    state.builder.target = spec.target;
    state.builder.risk = spec.risk;
    state.builder.parsed = spec;
    state.builder.dirty = false;
    state.builder.result = runBuild(spec);
    render();
    document.getElementById("build-result")?.scrollIntoView({ block: "start" });
    return;
  }
  if (act === "legs") { state.builder.legs = Number(el.dataset.n); state.builder.dirty = true; render(); return; }
  if (act === "risk") { state.builder.risk = el.dataset.risk; state.builder.dirty = true; render(); return; }
  if (act === "use-build" && state.builder.result?.legs) {
    state.slip = state.builder.result.legs.slice();
    state.bookPinned = false;
    state.copied = null;
    persistSlip();
    go("#slip");
    return;
  }
  if (act === "choose-book") {
    state.book = el.dataset.book;
    state.bookPinned = true;
    localStorage.setItem("edgelab.book", state.book);
    localStorage.setItem("edgelab.bookPinned", "1");
    render();
    return;
  }
  if (act === "remove") {
    state.slip = state.slip.filter((leg) => leg.id !== el.dataset.id);
    persistSlip();
    render();
    return;
  }
  if (act === "clear-slip") { state.slip = []; state.copied = null; persistSlip(); render(); return; }
  if (act === "open-book") { openBook(); return; }
  if (act === "save-play" && state.slip.length) {
    state.myPlays.unshift({ id: String(Date.now()), book: state.book, legs: state.slip });
    persistPlays();
    go("#tracker");
    return;
  }
  if (act === "drop-play") {
    state.myPlays = state.myPlays.filter((play) => String(play.id) !== el.dataset.id);
    persistPlays();
    render();
  }
}

function onInput(event) {
  if (event.target.id === "team-filter") {
    state.teamQuery = event.target.value;
    const box = document.getElementById("game-list");
    if (box) box.innerHTML = gameListHtml();
    return;
  }
  if (event.target.id === "sentence") { state.builder.text = event.target.value; state.builder.dirty = false; }
  if (event.target.id === "team") { state.builder.team = event.target.value; state.builder.dirty = true; }
  if (event.target.id === "target") { state.builder.target = event.target.value; state.builder.dirty = true; }
  if (event.target.id === "date") { state.builder.date = event.target.value; state.builder.dirty = true; }
}

async function boot() {
  document.getElementById("app").innerHTML = shell(`<p class="note">Loading the latest research data…</p>`);
  try {
    state.slip = JSON.parse(localStorage.getItem("edgelab.slip") || "[]");
    state.myPlays = JSON.parse(localStorage.getItem("edgelab.myplays") || "[]");
  } catch (err) {
    state.slip = [];
    state.myPlays = [];
  }
  try {
    state.meta = await fetchJson("data/meta.json");
    state.slate = await fetchJson("data/slate.json");
    state.edges = await fetchJson("data/edges.json");
    state.legs = await fetchJson("data/legs.json");
    state.report = await fetchJson("data/report.json");
    state.plays = await fetchJson("data/tracker.json");
  } catch (err) {
    state.fatal = "Couldn't load the research data. Connect once so EdgeLab can save a copy for offline use.";
  }
  const today = state.slate?.days?.find((day) => day.label === "Today");
  state.day = today?.key || state.slate?.days?.[0]?.key || null;
  window.addEventListener("hashchange", route);
  document.body.addEventListener("click", onClick);
  document.body.addEventListener("input", onInput);
  document.body.addEventListener("change", onInput);
  route();
  if ("serviceWorker" in navigator) navigator.serviceWorker.register("sw.js").catch(() => {});
}

boot();
