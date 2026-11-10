"use strict";

const RISK = {
  // Decimal price bands. Safe is the short favorite. Balanced is around -200 to -125.
  // Aggressive is plus money, the other number on the board.
  safe: { minDec: 1.01, maxDec: 1.35, widenMin: 1.01, widenMax: 1.55, rank: "prob" },
  balanced: { minDec: 1.35, maxDec: 1.8, widenMin: 1.2, widenMax: 2.05, rank: "target" },
  aggressive: { minDec: 2, maxDec: 8, widenMin: 1.7, widenMax: 8, rank: "plus" },
};

var state = {
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
  builder: { text: "", risk: "balanced", riskLocked: false, legs: 4, target: 400, team: "", date: "", dirty: false, parsed: null, result: null, alts: null },
  sgpMode: "sgp",
  sgpx: [],
  sheet: null,
  slipOpen: false,
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
function recordHtml(record) {
  const [w, l, p] = String(record || "0-0-0").split("-");
  return `<span class="win">${esc(w || "0")}</span>-<span class="loss">${esc(l || "0")}</span>-<span class="push">${esc(p || "0")}</span>`;
}
function edgeTone(value, tier, proven) {
  if (proven === false || value == null || Number.isNaN(Number(value))) return "none";
  if (value > 0.001 && tier === "High") return "high";
  if (value > 0.001) return "med";
  if (value < -0.001) return "bad";
  return "none";
}
function edgeClass(value, tier, proven) {
  const tone = edgeTone(value, tier, proven);
  if (tone === "high") return "edge-high";
  if (tone === "med") return "edge-med";
  if (tone === "bad") return "edge-bad";
  return "edge-none";
}
function oddTone(value, tier, proven) {
  const tone = edgeTone(value, tier, proven);
  if (tone === "high") return "up-high";
  if (tone === "med") return "up-med";
  if (tone === "bad") return "down";
  return "";
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

const GEAR = `<svg width="21" height="21" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 13a7.6 7.6 0 0 0 .05-2l1.75-1.25-1.8-3.15-2.05.65a7.8 7.8 0 0 0-1.73-1L15.2 3.2h-3.4L11.4 6.2a7.8 7.8 0 0 0-1.73 1l-2.05-.65-1.8 3.15L7.55 11a7.6 7.6 0 0 0 0 2l-1.73 1.25 1.8 3.15 2.05-.65a7.8 7.8 0 0 0 1.73 1l.4 3h3.4l.4-3a7.8 7.8 0 0 0 1.73-1l2.05.65 1.8-3.15L19.4 13z"/></svg>`;

function icon(name) {
  const common = 'width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"';
  const paths = {
    today: `<path d="M7.5 3.2v2.6M16.5 3.2v2.6"/><rect x="3.5" y="5.2" width="17" height="15.2" rx="3"/><path d="M3.5 10h17"/>`,
    edges: `<path d="M3.5 16.8 8.4 11l3.5 3.2L20.5 5.8"/><path d="M14.2 5.8H20.5V12"/>`,
    builder: `<path d="M12 3.1 13.4 7.2 17.6 8.6 13.4 10 12 14.1 10.6 10 6.4 8.6 10.6 7.2 12 3.1z"/><path d="M17.4 14.2l.6 1.7 1.7.6-1.7.6-.6 1.7-.6-1.7-1.7-.6 1.7-.6.6-1.7z"/>`,
    sgp: `<circle cx="6.5" cy="7" r="2.1"/><circle cx="17.5" cy="7" r="2.1"/><circle cx="12" cy="17.2" r="2.1"/><path d="M8.3 8.4 10.5 15.3M15.7 8.4 13.5 15.3"/>`,
    slip: `<path d="M7 3.4h7.1L19.2 8.4V19.2c0 .8-.7 1.4-1.5 1.4H7c-.8 0-1.5-.6-1.5-1.4V4.8c0-.8.7-1.4 1.5-1.4z"/><path d="M14 3.4V8.2h5.2M8 12.4h8M8 16h5.5"/>`,
    tracker: `<path d="M5 19.2V11.2M12 19.2V4.8M19 19.2v-6.2"/>`,
  };
  return `<svg ${common}>${paths[name] || ""}</svg>`;
}

function footer() {
  return `<p class="fine">EdgeLab is not a sportsbook and does not place or accept bets. Research only — no guarantees. Problem gambling help: <a href="tel:18004262537">1-800-GAMBLER</a>.</p>`;
}

function logoUrl(league, team) {
  if (!team) return "";
  if (team.logo) return team.logo;
  const abbr = String(team.abbr || "").toLowerCase();
  if ((league === "cfb" || league === "ncaab" || league === "ncaaw") && team.id) {
    return `https://a.espncdn.com/i/teamlogos/ncaa/500/${team.id}.png`;
  }
  const sport = { nba: "nba", nfl: "nfl", nhl: "nhl", mlb: "mlb", wnba: "wnba", epl: "soccer", mls: "soccer", ucl: "soccer" }[league];
  return sport && abbr ? `https://a.espncdn.com/i/teamlogos/${sport}/500/${abbr}.png` : "";
}

function logoHtml(league, team) {
  const letters = esc((team?.abbr || "?").slice(0, 3));
  const src = logoUrl(league, team);
  return `<span class="logo-wrap"><span class="logo ph">${letters}</span>${src ? `<img class="logo" alt="" src="${esc(src)}" onerror="this.remove()">` : ""}</span>`;
}

function sportGlyph(key) {
  const paths = {
    all: `<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>`,
    nba: `<circle cx="12" cy="12" r="8"/><path d="M12 4c2.2 2.8 2.2 13.2 0 16M4 12h16M7 7c3 1.6 7 1.6 10 0M7 17c3-1.6 7-1.6 10 0"/>`,
    nfl: `<ellipse cx="12" cy="12" rx="9" ry="5.5"/><path d="M12 6.5v11M9.5 12h5"/>`,
    nhl: `<path d="M3 16c2.5-7 15.5-7 18 0"/><path d="M8 16h8"/>`,
    mlb: `<circle cx="12" cy="12" r="8"/><path d="M4.5 12c2.2 2 12.8 2 15 0"/>`,
  };
  const path = paths[key] || paths[key === "cfb" ? "nfl" : key === "ncaab" || key === "ncaaw" ? "nba" : "all"];
  return `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7">${path}</svg>`;
}

function bookMark(book) {
  const colors = {
    draftkings: "#146c43", fanduel: "#0b6bcb", betmgm: "#8a6a32", williamhill_us: "#1e4d38",
    bet365: "#0d6b52", fanatics: "#16308f", espnbet: "#8d2a2a", hardrockbet_oh: "#6d2a2a",
    betrivers: "#14586f", ballybet: "#9a2450",
  };
  return `<span class="marktile" style="background:${colors[book.key] || "#2c3544"}">${esc(book.short || book.name.slice(0, 2))}</span>`;
}

function shortWhen(game) {
  if (game.state && game.state !== "pre" && game.score) return `${game.away.abbr} ${game.score.away}–${game.home.abbr} ${game.score.home}`;
  const match = String(game.start_local || "").match(/(\d{1,2}:\d{2} [AP]M)/);
  return match ? match[1] : (game.start_local || "");
}

function legFor(game, market, side) {
  return state.legs.find((leg) => String(leg.event_id) === String(game.event_id) && leg.market === market && leg.side === side);
}

function onSlip(leg) {
  return !!(leg && state.slip.some((item) => item.id === leg.id));
}

function meter(prob, band) {
  const width = Math.max(6, Math.min(100, Math.round((prob || 0) * 100)));
  return `<div class="meter ${band}"><span style="width:${width}%"></span></div>`;
}

function hitBand(prob) {
  if (prob >= 0.35) return "safer";
  if (prob >= 0.15) return "balanced";
  if (prob >= 0.03) return "longshot";
  return "lotto";
}

function shell(body) {
  const offline = state.offline ? `<p class="banner">Offline. Showing the last saved slate.</p>` : "";
  const game = state.tab === "game";
  const lead = game
    ? `<button type="button" class="back" data-act="tab" data-tab="today" aria-label="Back">‹</button>`
    : `<div class="brand"><img src="icons/icon-192.png" alt=""><span>EdgeLab</span></div>`;
  return `
    <div class="phone${state.slip.length ? " has-slip" : ""}" id="phone">
      <header class="top${game ? " gamehead" : ""}">
        ${lead}
        <div class="navtitle" id="navtitle"></div>
        <button type="button" class="iconbtn" data-act="settings" aria-label="Settings">${GEAR}</button>
      </header>
      ${offline}
      <main id="screen">${body}</main>
      <div class="dock">
        ${state.slip.length ? slipBar() : ""}
        ${tabs()}
      </div>
      ${state.slipOpen ? slipSheet() : ""}
      ${state.sheet ? sheetHtml() : ""}
    </div>`;
}

function slipBar() {
  const best = bestBook(state.slip);
  const price = best ? `${fmtAm(best.summary.american)} est.` : "—";
  const n = state.slip.length;
  return `<button type="button" class="slipbar" data-act="open-slip"><span class="count">${n}</span><span>${n} pick${n === 1 ? "" : "s"}</span><span class="grow num">${price}</span><span>View slip</span></button>`;
}

function tabs() {
  const items = [["today", "Today"], ["edges", "Edges"], ["builder", "Build"], ["sgp", "SGP"], ["slip", "Slip"], ["tracker", "Track"]];
  return `<nav class="tabs">${items.map(([id, label]) => {
    const badge = id === "slip" && state.slip.length ? `<span class="dot">${state.slip.length}</span>` : "";
    const on = state.tab === id || (id === "slip" && state.slipOpen);
    return `<button type="button" data-act="tab" data-tab="${id}" class="${on ? "on" : ""}" ${on ? 'aria-current="page"' : ""}>${icon(id)}${badge}${label}</button>`;
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
    const chips = [`<button type="button" class="chip ${state.sport === "all" ? "on" : ""}" data-act="sport" data-sport="all">${sportGlyph("all")}All</button>`]
    .concat(sports.map((sport) => `<button type="button" class="chip ${state.sport === sport.key ? "on" : ""}" data-act="sport" data-sport="${esc(sport.key)}">${sportGlyph(sport.key)}${esc(shortName[sport.key] || sport.name)}</button>`));
  const dayChips = days.map((item) => `<button type="button" class="chip ${item.key === day?.key ? "on" : ""}" data-act="day" data-day="${esc(item.key)}">${esc(item.label)}</button>`);
  const off = (state.slate?.offseason || []).slice(0, 6).map((row) => `<p class="note"><b>${esc(row.name)}.</b> ${esc(row.note)}</p>`).join("");
  const updated = state.meta?.generated_at_et ? `<p class="subhead">${esc(state.meta.generated_at_et)}</p>` : "";
  return `
    <h1 class="largetitle" id="largetitle">Today</h1>
    ${updated}
    <div class="sticky">
      <div class="row">${dayChips.join("")}</div>
      <div class="row">${chips.join("")}</div>
      <input id="team-filter" class="search" placeholder="Teams" value="${esc(state.teamQuery)}" autocomplete="off">
    </div>
    <div id="game-list">${gameListHtml()}</div>
    ${off}`;
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

function boardLines(game) {
  const lines = game.lines || {};
  return lines.draftkings || Object.values(lines)[0] || null;
}

function oddCell(game, market, side, top, odds) {
  if (odds == null && top == null) return `<span class="odd empty">—</span>`;
  const leg = legFor(game, market, side);
  const offer = leg ? offerPrimary(leg) : null;
  const tone = oddTone(offer?.edge, offer?.tier, offer?.proven);
  return `<button type="button" class="odd ${tone} ${onSlip(leg) ? "on" : ""}" data-act="toggle-board" data-league="${esc(game.league)}" data-id="${esc(game.event_id)}" data-market="${esc(market)}" data-side="${esc(side)}">
    <b>${esc(top || "")}</b><span class="price num">${fmtAm(odds)}</span>
  </button>`;
}

function teamRow(game, side) {
  const team = game[side];
  const lines = boardLines(game);
  const spread = lines ? (side === "home" ? lines.spread_home : lines.spread_away) : null;
  const spreadOdds = lines ? lines["spread_" + side + "_odds"] : null;
  const totalLabel = !lines || lines.total == null ? null : (side === "away" ? `O ${lines.total}` : `U ${lines.total}`);
  const totalOdds = lines ? (side === "away" ? lines.over_odds : lines.under_odds) : null;
  const ml = lines ? lines["ml_" + side] : null;
  const spreadText = spread == null ? "" : `${Number(spread) > 0 ? "+" : ""}${spread}`;
  return `<div class="cols">
    <button type="button" class="teamcell" data-act="game" data-league="${esc(game.league)}" data-id="${esc(game.event_id)}">
      ${logoHtml(game.league, team)}
      <span class="tmeta"><b>${esc(team.abbr)}</b><span class="rec">${esc(team.record || "")}</span></span>
    </button>
    ${oddCell(game, "Spread", side, spreadText, spreadOdds)}
    ${oddCell(game, "Total", side === "away" ? "over" : "under", totalLabel, totalOdds)}
    ${oddCell(game, lines && lines.ml_draw != null ? "1X2" : "ML", side, "ML", ml)}
  </div>`;
}

function gameCard(game) {
  if (game.field) return "";
  const edge = game.badge ? `<span class="pill ${game.badge.tier === "High" ? "high" : "medium"}">${esc(fmtEdge(game.badge.edge))}</span>` : "";
  const live = game.state === "in" ? `<span class="pill live">Live</span>` : game.state === "post" ? `<span class="pill final">Final</span>` : "";
  const empty = boardLines(game) ? "" : `<p class="meta">No odds posted.</p>`;
  return `<article class="board">
    <div class="board-top"><span class="when">${esc(shortWhen(game))}</span><span class="flags">${live}${edge}</span></div>
    <div class="colhead"><span></span><span>Spread</span><span>Total</span><span>ML</span></div>
    ${teamRow(game, "away")}
    ${teamRow(game, "home")}
    ${empty}
  </article>`;
}

function renderEdges() {
  const rank = { High: 0, Medium: 1, Low: 2 };
  const max = rank[state.edgeTier] ?? 1;
  const rows = state.edges.filter((edge) => (rank[edge.tier] ?? 9) <= max);
  const chips = ["High", "Medium"].map((tier) => `<button type="button" class="chip ${state.edgeTier === tier ? "on" : ""}" data-act="tier" data-tier="${tier}">${tier === "Medium" ? "High + Medium" : "High only"}</button>`);
  const propRows = state.edges.filter((edge) => edge.market === "Prop" || edge.tier === "Prop");
  const propBody = propRows.length ? `<h3>Props</h3><p class="meta">Not in the backtest. Hit chance is the game-log model.</p><div class="list">${propRows.map((edge, index) => {
    const when = String(edge.start_local || "").match(/(\d{1,2}:\d{2} [AP]M)/);
    const meta = `${edge.leg?.matchup || edge.game}${when ? " · " + when[1] : ""} · ${fmtPct(edge.model_prob)}`;
    return `<button type="button" class="edge-row" data-act="edge" data-index="${index}" data-prop="1">
      <span class="who"><span><b>${esc(edge.selection)}</b><div class="meta">${esc(meta)}</div></span></span>
      <span class="pill">${esc(fmtAm(edge.odds))}</span>
    </button>`;
  }).join("")}</div>` : `<h3>Props</h3><p class="meta">Props not loaded yet.</p>`;
  const body = rows.length ? `<div class="list">${rows.map((edge, index) => {
    const flag = (edge.caution || []).length ? ` · caution` : "";
    const when = String(edge.start_local || "").match(/(\d{1,2}:\d{2} [AP]M)/);
    const team = edge.side === "home" || edge.side === "away"
      ? { abbr: edge.leg?.[`${edge.side}_abbr`] }
      : null;
    const meta = `${edge.leg?.matchup || edge.game}${when ? " · " + when[1] : ""} · ${fmtAm(edge.odds)}${flag}`;
    return `<button type="button" class="edge-row" data-act="edge" data-index="${index}">
      <span class="who">${team.abbr ? logoHtml(edge.league, team) : ""}<span><b class="${edgeClass(edge.edge, edge.tier, edge.proven)}">${esc(edge.selection)}</b><div class="meta">${esc(meta)}</div></span></span>
      <span class="pill ${edge.tier === "High" ? "high" : "medium"}">${esc(fmtEdge(edge.edge))}</span>
    </button>`;
  }).join("")}</div>` : `<div class="empty">No ${state.edgeTier === "High" ? "High" : "High or Medium"} edges. Only backtested markets can leave the price.</div>`;
  const visible = state.edges.filter((edge) => (rank[edge.tier] ?? 9) <= max && edge.market !== "Prop" && edge.tier !== "Prop");
  state._visibleEdges = visible;
  state._propEdges = propRows;
  return `<h1 class="largetitle" id="largetitle">Edges</h1><p class="subhead">NBA moneyline, NBA total, NHL puck line.</p><div class="row">${chips.join("")}</div>${body}${propBody}`;
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
  if (state.gameError) return `<h1 class="largetitle" id="largetitle">Game</h1><div class="empty">${esc(state.gameError)}</div>`;
  if (!state.game) return `<h1 class="largetitle" id="largetitle">Game</h1><div class="skel"></div><div class="skel"></div><div class="skel"></div>`;
  const game = state.game;
  const bookKey = activeBook(game);
  const book = bookByKey(bookKey);
  const flags = (game.flags || []).map((flag) => `<span class="pill warn">${esc(String(flag).replace(/^!/, ""))}</span>`).join(" ");
  const injuries = ["away", "home"].map((side) => {
    const list = (game.injuries?.[side] || []).filter((row) => row.key || /out|doubt/i.test(row.status || ""));
    if (!list.length) return "";
    return `<p class="meta"><b>${esc(game[side].abbr)}</b> · ${list.map((row) => `${esc(row.name)} ${esc(row.status)}`).join(" · ")}</p>`;
  }).join("");
  const markets = (game.markets || []).map((market) => {
    let best = null;
    const buttons = market.sides.map((side) => {
      const offer = side.offers?.[bookKey];
      const label = offer?.selection || side.side;
      if (!offer) {
        return `<div class="oddwrap"><button type="button" class="odd big" disabled><b>${esc(label)}</b><span class="price">—</span></button></div>`;
      }
      if (offer.proven !== false && offer.edge > 0.001 && (!best || offer.edge > best.edge)) best = offer;
      const tone = oddTone(offer.edge, offer.tier, offer.proven);
      const leg = legFor(game, market.market, side.side);
      return `<div class="oddwrap"><button type="button" class="odd big ${tone} ${onSlip(leg) ? "on" : ""}" data-act="odd-tap" data-market="${esc(market.market)}" data-side="${esc(side.side)}">
        <b>${esc(offer.selection)}</b>
        <span class="price num">${fmtAm(offer.odds)}</span>
      </button><button type="button" class="why" data-act="why-side" data-market="${esc(market.market)}" data-side="${esc(side.side)}">Why</button></div>`;
    }).join("");
    const listed = market.sides.flatMap((side) => Object.values(side.offers || {}));
    const unproven = listed.length > 0 && listed.every((offer) => offer.proven === false);
    const chip = best ? `<span class="pill ${best.tier === "High" ? "high" : "medium"}">${esc(fmtEdge(best.edge))}</span>` : "";
    return `<section class="mkt"><div class="mkt-head"><span>${esc(market.market)}</span>${chip}</div>${unproven ? `<p class="meta">Model not proven for this market yet.</p>` : ""}<div class="pair">${buttons}</div></section>`;
  }).join("");
  const props = (game.props || []).map((prop) => {
    const sides = Object.entries(prop.sides || {}).map(([side, offers]) => {
      const offer = offers[bookKey];
      if (!offer) return "";
      return `<button type="button" class="odd big ${oddTone(offer.edge, offer.tier, offer.proven)}" data-act="prop" data-player="${esc(prop.player_id)}" data-stat="${esc(prop.stat)}" data-line="${esc(prop.line)}" data-side="${esc(side)}">
        <b>${esc(side)} ${esc(prop.line)}</b>
        <span class="price num">${fmtAm(offer.odds)}</span>
      </button>`;
    }).join("");
    const rate = prop.hit_rates ? Object.entries(prop.hit_rates).map(([k, v]) => `${esc(k)} ${esc(v)}`).join(" · ") : "";
    return `<section class="mkt"><div class="mkt-head"><span>${esc(prop.player)} · ${esc(prop.stat_label)} ${esc(prop.line)}</span></div>
      <p class="meta">Projection ${esc(prop.projection)}${rate ? " · " + rate : ""}</p>
      <div class="pair">${sides || `<p class="meta">Not offered at this book.</p>`}</div></section>`;
  }).join("");
  const score = game.score ? `<p class="meta">${esc(game.away.abbr)} ${esc(game.score.away)} – ${esc(game.home.abbr)} ${esc(game.score.home)}</p>` : "";
  const feed = game.odds_feed === "espn" ? "ESPN" : book?.name || "DraftKings";
  return `
    <h1 class="largetitle" id="largetitle" hidden>${esc(game.away.abbr)} at ${esc(game.home.abbr)}</h1>
    <div class="matchup">
      <div class="side">${logoHtml(game.league, game.away)}<span class="tmeta"><b>${esc(game.away.abbr)}</b><span class="rec">${esc(game.away.record || "")}</span></span></div>
      <div class="vs">${game.state === "in" ? "Live" : "@"}</div>
      <div class="side">${logoHtml(game.league, game.home)}<span class="tmeta"><b>${esc(game.home.abbr)}</b><span class="rec">${esc(game.home.record || "")}</span></span></div>
    </div>
    <p class="subhead">${esc(shortWhen(game))} · ${esc(feed)}</p>
    <p class="meta">${esc(game.model_summary || "")}</p>
    ${score}
    ${flags ? `<p>${flags}</p>` : ""}
    ${injuries}
    <div class="markets">${markets || `<div class="empty">No odds posted.</div>`}</div>
    ${props || `<p class="meta">Props not loaded for this game yet.</p>`}`;
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

function legProb(leg, book) {
  const offer = book ? (offerOf(leg.offers, book) || offerPrimary(leg)) : offerPrimary(leg);
  return offer?.model_prob;
}

function pairRho(a, b) {
  if (!a || !b || a.event_id !== b.event_id) return { rho: 0, why: null };
  const team = (leg) => leg.team_abbr || null;
  const sameTeam = team(a) && team(a) === team(b);
  const oppSide = (a.side === "home" && b.side === "away") || (a.side === "away" && b.side === "home");
  const sameSide = a.side && a.side === b.side && (a.side === "home" || a.side === "away");
  const markets = [a.market, b.market];
  const has = (name) => markets.includes(name);
  if ((has("ML") || has("1X2")) && has("Spread")) {
    if (sameSide) return { rho: 0.75, why: "Same-team moneyline and spread move together. The joint chance stays near the harder leg instead of the product." };
    if (oppSide) return { rho: -0.55, why: "A moneyline on one team and the spread on the other point opposite ways." };
  }
  const total = a.market === "Total" ? a : b.market === "Total" ? b : null;
  const sideLeg = total ? (total === a ? b : a) : null;
  if (total && sideLeg && (sideLeg.market === "Spread" || sideLeg.market === "ML" || sideLeg.market === "1X2")) {
    const fav = sideLeg.market === "Spread" ? Number(sideLeg.line) < 0 : (offerPrimary(sideLeg)?.odds || 0) < 0;
    if (total.side === "over" && fav) return { rho: 0.25, why: "Favorite and over are mildly positively correlated. Covers often come with more scoring." };
    if (total.side === "under" && !fav) return { rho: 0.22, why: "Underdog and under are mildly positively correlated. Lower scoring tends to keep the game closer." };
    if (total.side === "under" && fav) return { rho: -0.12, why: "Favorite and under pull apart, so the joint chance is a bit under the product." };
    return { rho: 0.08, why: "This side and total have only a weak link in the adjustment." };
  }
  if (a.market === "Prop" || b.market === "Prop") {
    const prop = a.market === "Prop" ? a : b;
    const other = prop === a ? b : a;
    const stat = (prop.stat || "").toLowerCase();
    const otherStat = (other.stat || "").toLowerCase();
    const pass = ["pass_yds", "pass_td", "completions"].includes(stat) || ["pass_yds", "pass_td", "completions"].includes(otherStat);
    const rec = ["rec_yds", "rec", "receptions"].includes(stat) || ["rec_yds", "rec", "receptions"].includes(otherStat);
    if (a.market === "Prop" && b.market === "Prop" && prop.prop_key && a.prop_key === b.prop_key) return { rho: 0, why: null };
    if (a.market === "Prop" && b.market === "Prop" && a.player && a.player === b.player) {
      return { rho: 0.28, why: "Two props on the same player share minutes and role." };
    }
    if (pass && rec && sameTeam) return { rho: 0.55, why: "A quarterback's passing and his receiver's production are strongly linked. The ball has to arrive." };
    if ((stat === "pts" || otherStat === "pts") && (other.market === "ML" || other.market === "1X2" || other.market === "Spread") && sameTeam) {
      return { rho: 0.30, why: "A player's points and that team's side move together." };
    }
    if ((stat === "pts" || stat === "pass_yds" || otherStat === "pts" || otherStat === "pass_yds") && (other.market === "Total" || a.market === "Total")) {
      const tot = a.market === "Total" ? a : b;
      if (tot.side === "over") return { rho: 0.35, why: "Scoring props and the game over share pace. They hit together more often than independence says." };
    }
    if (a.market === "Prop" && b.market === "Prop" && sameTeam) return { rho: 0.15, why: "Teammate props share pace. Usage competition is not in this adjustment." };
  }
  return { rho: 0, why: null };
}

function jointProb(legs, book) {
  if (!legs.length) return { prob: 0, notes: [], rho: [] };
  let p = legProb(legs[0], book);
  if (!(p > 0)) return { prob: 0, notes: ["A leg has no model probability."], rho: [] };
  const notes = [];
  const seen = new Set();
  for (let i = 1; i < legs.length; i++) {
    let rho = 0;
    let why = null;
    for (let j = 0; j < i; j++) {
      const pair = pairRho(legs[j], legs[i]);
      if (Math.abs(pair.rho) > Math.abs(rho)) {
        rho = pair.rho;
        why = pair.why;
      }
    }
    const q = legProb(legs[i], book);
    if (!(q > 0)) return { prob: 0, notes: ["A leg has no model probability."], rho: [] };
    const indep = p * q;
    const bump = rho * Math.sqrt(Math.max(0, p * (1 - p) * q * (1 - q)));
    const lo = Math.max(0, p + q - 1);
    const hi = Math.min(p, q);
    p = Math.min(hi, Math.max(lo, indep + bump));
    if (why && !seen.has(why)) {
      seen.add(why);
      notes.push(`${why} ρ ${rho > 0 ? "+" : ""}${rho.toFixed(2)}.`);
    }
  }
  if (!notes.length) notes.push("No documented correlation between these legs, so the hit chance is the straight product.");
  return { prob: p, notes };
}

function slipModel(legs, book) {
  const groups = {};
  for (const leg of legs) (groups[leg.event_id] ||= []).push(leg);
  let prob = 1;
  let same = false;
  for (const group of Object.values(groups)) {
    if (group.length > 1) same = true;
    const joint = group.length === 1 ? { prob: legProb(group[0], book) } : jointProb(group, book);
    if (!(joint.prob > 0)) return { prob: null, same };
    prob *= joint.prob;
  }
  return { prob, same };
}

function cardPrice(legs) {
  let best = null;
  for (const book of books()) {
    const summary = summaryFor(legs, book);
    if (!summary.complete) continue;
    if (!best || summary.dec > best.summary.dec) best = { book, summary };
  }
  return best;
}

function sgpPool(legs) {
  const ranked = [...legs].filter((leg) => (offerPrimary(leg)?.model_prob || 0) > 0 && offerPrimary(leg)?.odds != null);
  ranked.sort((a, b) => offerPrimary(b).model_prob - offerPrimary(a).model_prob);
  if (ranked.length <= 8) return ranked;
  return [...ranked.slice(0, 5), ...ranked.slice(-3)];
}

function buildGameSgps(gameLegs) {
  const pool = sgpPool(gameLegs);
  const found = [];
  for (const size of [2, 3, 4]) {
    if (pool.length < size) continue;
    for (const combo of combinations(pool, size)) {
      if (combo.some((leg, index) => combo.slice(index + 1).some((other) => conflict(leg, other)))) continue;
      const joint = jointProb(combo);
      if (!(joint.prob > 0)) continue;
      found.push({ legs: combo, prob: joint.prob, notes: joint.notes, size });
    }
  }
  const used = new Set();
  function take(ok, rank) {
    const rows = found.filter((row) => ok(row) && !used.has(row.legs.map((leg) => leg.id).sort().join("|")));
    if (!rows.length) return null;
    rows.sort(rank);
    const pick = rows[0];
    used.add(pick.legs.map((leg) => leg.id).sort().join("|"));
    return pick;
  }
  return {
    safer: take((row) => row.size <= 3 && row.prob >= 0.35, (a, b) => b.prob - a.prob || a.size - b.size),
    balanced: take((row) => row.size <= 3 && row.prob >= 0.15 && row.prob < 0.35, (a, b) => Math.abs(a.prob - 0.22) - Math.abs(b.prob - 0.22)),
    longshot: take((row) => row.prob < 0.10 && row.prob >= 0.03, (a, b) => Math.abs(a.prob - 0.06) - Math.abs(b.prob - 0.06)),
    lotto: take((row) => row.size >= 3 && row.prob < 0.03, (a, b) => a.prob - b.prob),
  };
}

const SGP_BANDS = [
  ["safer", "Safer", "2–3 legs, about 35% or better"],
  ["balanced", "Balanced", "about 15–30%"],
  ["longshot", "Longshot", "under 10%"],
  ["lotto", "Lotto", "under 3%, usually 3 or more legs"],
];

function sgpCardsFor(legs) {
  const day = currentDay();
  const games = {};
  for (const leg of legs) {
    if (day && leg.date_et !== day.date) continue;
    if (state.sport !== "all" && leg.league !== state.sport) continue;
    (games[leg.event_id] ||= []).push(leg);
  }
  const cards = [];
  const blocks = [];
  for (const [eventId, gameLegs] of Object.entries(games)) {
    const built = buildGameSgps(gameLegs);
    const sample = gameLegs[0];
    const tiers = [];
    for (const [key, label, band] of SGP_BANDS) {
      const row = built[key];
      if (!row) {
        tiers.push({ key, label, band, empty: true });
        continue;
      }
      const price = cardPrice(row.legs);
      const implied = price ? 1 / price.summary.dec : null;
      const edge = implied == null ? null : row.prob - implied;
      const weak = [...row.legs].sort((a, b) => (offerPrimary(a).edge || 0) - (offerPrimary(b).edge || 0))[0];
      const card = {
        id: `${eventId}:${key}`,
        event_id: eventId,
        key, label, band,
        name: sample.name,
        matchup: sample.matchup,
        start_local: sample.start_local,
        league: sample.league,
        legs: row.legs,
        prob: row.prob,
        notes: row.notes,
        price,
        edge,
        fair: decToAm(1 / row.prob),
        weak,
      };
      cards.push(card);
      tiers.push(card);
    }
    blocks.push({ eventId, name: sample.name, matchup: sample.matchup, start: sample.start, start_local: sample.start_local, tiers });
  }
  blocks.sort((a, b) => (a.start || "").localeCompare(b.start || ""));
  return { blocks, cards };
}

function renderSgpCard(card) {
  if (card.empty) return `<article class="parlay"><div class="parlay-top"><b>${esc(card.label)}</b></div><p class="note">No card in this band.</p></article>`;
  const band = card.key === "longshot" ? "longshot" : card.key;
  const price = card.price ? `${esc(card.price.book.short || card.price.book.name)} ${fmtAm(card.price.summary.american)} est.` : "No full price";
  const legs = card.legs.map((leg) => {
    const offer = offerPrimary(leg);
    return `<div class="legline"><span>${esc(leg.selection)}</span><span class="num">${fmtPct(offer?.model_prob)} · ${fmtAm(offer?.odds)}</span></div>`;
  }).join("");
  const on = state.sgpx.includes(card.id);
  const action = state.sgpMode === "sgpx"
    ? `<button type="button" class="btn" data-act="toggle-sgpx" data-id="${esc(card.id)}">${on ? "Remove" : "Use"}</button>`
    : `<button type="button" class="cta" data-act="add-sgp" data-id="${esc(card.id)}">Add</button>`;
  return `<article class="parlay ${on ? "on-card" : ""}">
    <div class="parlay-top"><b>${esc(card.label)}</b><span class="pill ${band}">${fmtPct(card.prob)}</span></div>
    ${meter(card.prob, band)}
    ${legs}
    <p class="note">${price} · edge ${card.edge == null ? "—" : esc(fmtEdge(card.edge))} · weak ${esc(card.weak.selection)}</p>
    <div class="row-actions"><button type="button" class="btn" data-act="why-sgp" data-id="${esc(card.id)}">Why</button>${action}</div>
  </article>`;
}

function renderSgp() {
  const { blocks, cards } = sgpCardsFor(state.legs);
  state.sgpCards = cards;
  const day = currentDay();
  const days = state.slate?.days || [];
  const dayChips = days.map((item) => `<button type="button" class="chip ${item.key === day?.key ? "on" : ""}" data-act="day" data-day="${esc(item.key)}">${esc(item.label)}</button>`).join("");
  const mode = `<div class="seg">
    <button type="button" data-act="sgp-mode" data-mode="sgp" class="${state.sgpMode === "sgp" ? "on" : ""}">SGP</button>
    <button type="button" data-act="sgp-mode" data-mode="sgpx" class="${state.sgpMode === "sgpx" ? "on" : ""}">SGPx</button>
  </div>`;
  let extra = "";
  if (state.sgpMode === "sgpx") {
    const picked = state.sgpx.map((id) => cards.find((card) => card.id === id)).filter(Boolean);
    if (picked.length >= 2) {
      const legs = picked.flatMap((card) => card.legs);
      const prob = picked.reduce((product, card) => product * card.prob, 1);
      const price = cardPrice(legs);
      const implied = price ? 1 / price.summary.dec : null;
      const edge = implied == null ? null : prob - implied;
      extra = `<article class="parlay">
        <div class="parlay-top"><b>SGPx · ${picked.length}</b><span class="pill ${hitBand(prob)}">${fmtPct(prob)}</span></div>
        ${meter(prob, hitBand(prob))}
        <p class="note">${picked.map((card) => esc(card.matchup)).join(" · ")}</p>
        <p class="note">${price ? `${esc(price.book.short || price.book.name)} ${fmtAm(price.summary.american)} est.` : "No full price"} · edge ${edge == null ? "—" : esc(fmtEdge(edge))}</p>
        <div class="row-actions"><button type="button" class="btn" data-act="why-sgpx">Why</button><button type="button" class="cta" data-act="add-sgpx">Add</button></div>
      </article>`;
    } else {
      extra = `<p class="note">Pick 2 or 3 same-game cards from different games. Two cards from one game are not an SGPx.</p>`;
    }
  }
  const body = blocks.length ? blocks.map((block) => `<h3>${esc(block.matchup)} · ${esc(block.start_local || "")}</h3>${block.tiers.map(renderSgpCard).join("")}`).join("") : `<div class="empty">No modeled games on this day. Try another date.</div>`;
  return `<h1 class="largetitle" id="largetitle">SGP</h1>
    <p class="subhead">Correlation-adjusted. Not a book's price.</p>
    ${mode}
    <div class="row">${dayChips}</div>
    ${extra}
    ${body}`;
}

function scopeLegs(spec, notes) {
  let universe = state.legs.slice();
  if (spec.date) {
    const dated = universe.filter((leg) => matchDate(leg, spec.date));
    if (dated.length) universe = dated;
    else notes.push(`No published legs on ${spec.date}. The builder used the full published slate instead.`);
  }
  const teamLegs = spec.team ? universe.filter((leg) => matchTeam(leg, spec.team)) : [];
  if (spec.team && !teamLegs.length) notes.push(`No game matching “${spec.team}” in that window.`);
  const teamEvents = new Set(teamLegs.map((leg) => leg.event_id)).size;
  let expanded = false;
  let pool = universe;
  // One leg per game, so a card needs that many different games.
  if (teamLegs.length && teamEvents >= spec.legs) pool = teamLegs;
  else if (teamLegs.length) {
    expanded = true;
    const league = teamLegs[0].league;
    const sameLeague = universe.filter((leg) => leg.league === league);
    if (sameLeague.length >= spec.legs) {
      pool = sameLeague;
      notes.push(`${spec.team} is in ${teamEvents} game(s). This card takes one leg per game, so the other legs are from the same sport. Same-game cards are on the SGP tab.`);
    } else {
      notes.push(`${spec.team} does not have enough games for ${spec.legs} legs, so the rest of that date is included.`);
    }
  }
  return { pool, teamIds: new Set(teamLegs.map((leg) => leg.id)), expanded };
}

function inBand(leg, minDec, maxDec) {
  const offer = offerPrimary(leg);
  if (!offer || offer.odds == null || !(offer.model_prob > 0)) return false;
  const dec = amToDec(offer.odds);
  return dec >= minDec && dec <= maxDec;
}

function takePool(rows, rank, targetDec) {
  const scored = rows.slice();
  const legScore = (leg) => {
    const offer = offerPrimary(leg);
    const dec = amToDec(offer.odds);
    if (rank === "prob") return offer.model_prob;
    if (rank === "plus") return offer.model_prob;
    const want = Math.pow(targetDec, 1 / 4);
    return -Math.abs(Math.log(dec) - Math.log(want)) + 0.05 * offer.model_prob;
  };
  scored.sort((a, b) => legScore(b) - legScore(a));
  const out = [];
  const seen = new Set();
  for (const leg of scored) {
    if (seen.has(leg.event_id)) continue;
    seen.add(leg.event_id);
    out.push(leg);
    if (out.length >= 8) break;
  }
  return out;
}

function priceCombo(combo, profile, targetDec) {
  const prob = combo.reduce((product, leg) => product * (offerPrimary(leg).model_prob || 0), 1);
  const dec = combo.reduce((product, leg) => product * amToDec(offerPrimary(leg).odds), 1);
  if (!(prob > 0) || !(dec > 1)) return null;
  const dist = Math.log(dec) - Math.log(targetDec);
  let score;
  if (profile.rank === "prob") score = Math.log(prob) - 2 * Math.max(0, dist);
  else if (profile.rank === "plus") score = -Math.abs(dist) + 0.05 * Math.log(prob);
  else score = -Math.abs(dist) + 0.15 * Math.log(prob);
  return { combo, prob, dec, dist, score, ev: prob * dec - 1 };
}

function runBuild(spec) {
  const notes = [];
  const profile = RISK[spec.risk] || RISK.balanced;
  const scoped = scopeLegs(spec, notes);
  let band = scoped.pool.filter((leg) => inBand(leg, profile.minDec, profile.maxDec));
  if (band.length < spec.legs) {
    const wider = scoped.pool.filter((leg) => inBand(leg, profile.widenMin, profile.widenMax));
    if (wider.length > band.length) {
      band = wider;
      notes.push(`${spec.risk} widened the price band so the card could fill ${spec.legs} legs.`);
    }
  }
  const targetDec = amToDec(spec.target);
  let usable = takePool(band, profile.rank, targetDec);
  if (usable.length < 2) return { error: "Not enough priced legs in that risk band.", notes, spec };
  const n = Math.min(spec.legs, usable.length);
  if (n < spec.legs) notes.push(`Only ${usable.length} legs fit ${spec.risk}, so this is a ${n}-leg card.`);
  const must = scoped.teamIds;
  let scored = [];
  const consider = (requireTeam) => {
    const found = [];
    for (const combo of combinations(usable, n)) {
      if (new Set(combo.map((leg) => leg.event_id)).size !== combo.length) continue;
      if (combo.some((a, i) => combo.slice(i + 1).some((b) => conflict(a, b)))) continue;
      if (requireTeam && must.size && !combo.some((leg) => must.has(leg.id))) continue;
      const row = priceCombo(combo, profile, targetDec);
      if (row) found.push(row);
    }
    return found;
  };
  scored = consider(true);
  if (!scored.length && must.size) {
    notes.push("No combo in this risk band could keep the named team, so that requirement was dropped.");
    scored = consider(false);
  }
  if (!scored.length) return { error: "No non-conflicting combination of priced legs matched.", notes, spec };
  scored.sort((a, b) => b.score - a.score);
  const best = scored[0];
  const honest = [];
  if (profile.rank === "prob" && best.dec < targetDec) {
    honest.push(`Safe keeps the highest hit chance. Estimated price ${fmtAm(decToAm(best.dec))} is under the ${fmtAm(spec.target)} target instead of adding longshots.`);
  } else if (profile.rank === "plus") {
    honest.push("Aggressive uses plus-money prices, including the other side of a favorite. It can land well past the target.");
  } else if (Math.abs(best.dist) > Math.log(1.35)) {
    honest.push(`Balanced aims at ${fmtAm(spec.target)}. Closest estimated price in this band is ${fmtAm(decToAm(best.dec))}.`);
  }
  const negative = best.combo.filter((leg) => (offerPrimary(leg).edge || 0) < 0);
  if (negative.length) {
    honest.push(`${negative.length} leg(s) have no model edge (${negative.map((leg) => leg.selection).join(", ")}).`);
  }
  const weak = [];
  for (const leg of [...best.combo].sort((a, b) => (offerPrimary(a).model_prob || 0) - (offerPrimary(b).model_prob || 0))) {
    const offer = offerPrimary(leg);
    const why = [];
    if ((offer.edge || 0) < 0) why.push(`negative edge ${fmtEdge(offer.edge)}`);
    if ((offer.model_prob || 1) < 0.4) why.push(`hit chance ${fmtPct(offer.model_prob)}`);
    if ((offer.caution || []).length) why.push("caution: " + offer.caution.join("; "));
    if (why.length) weak.push({ id: leg.id, why });
  }
  return {
    spec, notes, honest, expanded: scoped.expanded,
    legs: best.combo,
    weak,
    correlation: ["One leg per game. Same-game cards are on the SGP tab.", ...corrNotes(best.combo)],
    prob: best.prob,
    fair: decToAm(1 / best.prob),
    payout: decToAm(best.dec),
    ev: best.ev,
    within: Math.abs(best.dist) <= Math.log(1.35),
    priceBasis: "Product of each leg's listed price. A book's parlay price will be different.",
    alternatives: scored.slice(1, 3).map((row) => ({
      label: row.combo.map((leg) => leg.selection).join(" + "),
      price: decToAm(row.dec),
      prob: row.prob,
    })),
  };
}

function buildTrio(spec) {
  const alts = {};
  for (const risk of ["safe", "balanced", "aggressive"]) {
    alts[risk] = runBuild({ ...spec, risk });
  }
  return alts;
}

function renderBuilder() {
  const b = state.builder;
  const days = (state.slate?.days || []).map((day) => `<option value="${esc(day.weekday)}" ${b.date === day.weekday ? "selected" : ""}>${esc(day.label)}</option>`).join("");
  let result = "";
  if (b.alts) {
    const cards = ["safe", "balanced", "aggressive"].map((risk) => {
      const res = b.alts[risk];
      const on = risk === b.risk;
      const hit = res?.legs ? fmtPct(res.prob) : "—";
      const names = res?.legs ? res.legs.map((leg) => esc(leg.selection)).join(" · ") : esc(res?.error || "");
      return `<button type="button" class="triocard ${on ? "on" : ""}" data-act="risk" data-risk="${risk}"><b>${risk}</b><span class="hit num">${hit}</span><span class="meta">${names}</span></button>`;
    }).join("");
    const res = b.result;
    let detail = "";
    if (res?.error) {
      detail = `<div class="empty">${esc(res.error)}</div>`;
    } else if (res?.legs) {
      const weakIds = new Set((res.weak || []).map((row) => row.id));
      const band = hitBand(res.prob);
      const legs = res.legs.map((leg) => {
        const offer = offerPrimary(leg);
        const weak = weakIds.has(leg.id) ? " · weak" : "";
        return `<div class="legline"><span>${esc(leg.selection)}${weak}</span><span class="num">${fmtPct(offer.model_prob)} · ${fmtAm(offer.odds)}</span></div>`;
      }).join("");
      detail = `
        <div class="parlay">
          <div class="parlay-top"><b>${esc(res.spec.risk)} · ${esc(res.spec.legs)} legs</b><span class="pill ${band}">${fmtPct(res.prob)}</span></div>
          ${meter(res.prob, band)}
          ${legs}
          <p class="note">${fmtAm(res.payout)} est. · fair ${fmtAm(res.fair)}</p>
          <div class="row-actions"><button type="button" class="btn" data-act="why-build">Why</button><button type="button" class="cta" data-act="use-build">Add</button></div>
        </div>`;
    }
    result = `<div id="build-result"><div class="trio">${cards}</div>${detail}</div>`;
  }
  const parsed = b.parsed ? `<p class="note">Read as ${esc(b.parsed.risk)} · ${esc(b.parsed.legs)} legs · ${esc(b.parsed.team || "any team")} · ${esc(b.parsed.date || "any date")} · target ${fmtAm(b.parsed.target)}.</p>` : "";
  return `
    <h1 class="largetitle" id="largetitle">Builder</h1>
    <p class="subhead">Priced legs only.</p>
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
    <label class="lbl" for="target">Target odds</label>
    <input id="target" class="field short" inputmode="text" value="${esc(b.target)}">
    <label class="lbl">Risk</label>
    <div class="seg">${["safe", "balanced", "aggressive"].map((risk) => `<button type="button" data-act="risk" data-risk="${risk}" class="${b.risk === risk ? "on" : ""}">${risk}</button>`).join("")}</div>
    ${result}`;
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
      ${bookMark(book)}
      <div class="book-name">${esc(book.name)} ${isBest ? `<span class="tag">Best</span>` : ""}</div>
      <div class="book-count">${esc(count)}</div>
      <div class="book-price num">${esc(price)}</div>
    </button>`;
  }).join("");
  const legs = state.slip.map((leg) => {
    const offer = selected ? offerOf(leg.offers, selected) : null;
    return `<div class="legline"><span>${esc(leg.selection)}</span><span class="num">${offer ? fmtAm(offer.odds) : "—"} <button type="button" class="mini" data-act="why-leg" data-id="${esc(leg.id)}" aria-label="Why">i</button><button type="button" class="mini" data-act="remove" data-id="${esc(leg.id)}" aria-label="Remove">×</button></span></div>`;
  }).join("");
  const model = summary?.complete ? slipModel(state.slip, selected) : null;
  const edge = model?.prob != null && summary?.complete ? model.prob - 1 / summary.dec : null;
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
  const missing = catalog.filter((book) => !book.in_feed);
  const absent = missing.length ? `<p class="note">${esc(missing.map((book) => book.short || book.name).join(", "))} have no lines in this feed.</p>` : "";
  const copied = state.copied === true ? `<p class="note">Slip copied. Pre-filled bets are not supported — enter the legs yourself.</p>`
    : state.copied === false ? `<p class="note">Clipboard was blocked. Select the slip text below.</p><textarea class="field copybox" readonly>${esc(state.copyText)}</textarea>` : "";
  return `
    <div class="books">${cards}</div>
    ${absent}
    ${legs}
    <div class="stats">
      <div class="stat"><span>Est. odds</span><b class="num">${summary?.complete ? fmtAm(summary.american) : "—"}</b></div>
      <div class="stat"><span>Edge</span><b class="num ${edge == null ? "" : edge < -0.001 ? "loss" : edge > 0.001 ? "win" : ""}">${edge == null ? "—" : fmtEdge(edge)}</b></div>
    </div>
    <div class="sheet-foot">
      <button type="button" class="cta" data-act="open-book" ${selected ? "" : "disabled"}>Open in ${esc(selected?.name || "book")}</button>
      <p class="disclaimer">Research only. EdgeLab does not place bets.</p>
      ${copied}
    </div>`;
}

function slipSheet() {
  const inner = state.slip.length ? renderSlip() : `<div class="empty">No picks yet.</div>`;
  return `<div class="sheet" data-act="close-slip"><div class="sheet-card slip-sheet" data-act="stop"><div class="grab"></div><h2 style="margin:0 0 8px">Slip</h2><div class="sheet-body">${inner}</div></div></div>`;
}

function settingsSheet() {
  return `<div class="sheet" data-act="close-sheet"><div class="sheet-card" data-act="stop"><div class="grab"></div>
    <h2>Settings</h2>
    <p>EdgeLab is a research app. It does not place or accept bets, and it never suggests a stake. Prices and model numbers are estimates from public data. A small edge is often just model error. Books price parlays, and especially same-game parlays, with their own correlation, so a real price can differ from the multiplied leg prices shown here.</p>
    <p>If gambling is a problem, call <a href="tel:18004262537">1-800-GAMBLER</a>.</p>
    <p class="note">Updated ${esc(state.meta?.generated_at_et || "—")}.</p>
    <button type="button" class="btn block" data-act="close-sheet">Close</button>
  </div></div>`;
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
  const pendingRows = (state.plays?.pending || []).slice(-12).map((play) => `<div class="prow"><b>${esc(play.selection)} <span class="num">${fmtAm(play.odds)}</span></b><div class="meta">${esc(play.date)} · ${esc(play.sport)} · ${esc(play.tier || "")}</div></div>`).join("");
  const pending = pendingRows ? `<div class="list">${pendingRows}</div>` : `<p class="meta">No pending plays. High and Medium edges are logged when the refresh runs.</p>`;
  const mine = state.myPlays.length ? state.myPlays.map((play) => `<article class="parlay"><div class="parlay-top"><b>${play.legs.length} legs</b><span class="meta">${esc(bookByKey(play.book)?.name || play.book || "")}</span></div><p class="meta">${play.legs.map((leg) => esc(leg.selection)).join(" · ")}</p><button type="button" class="btn" data-act="drop-play" data-id="${esc(play.id)}">Remove</button></article>`).join("") : `<p class="meta">No personal slips on this phone.</p>`;
  return `
    <h1 class="largetitle" id="largetitle">Tracker</h1>
    ${warning ? `<div class="warnbox">${esc(warning)}</div>` : ""}
    <div class="stats">
      <div class="stat"><span>Record</span><b class="num">${recordHtml(overall.record)}</b></div>
      <div class="stat"><span>Hit rate</span><b class="num">${fmtPct(overall.hit_rate)}</b></div>
      <div class="stat"><span>ROI</span><b class="num">${overall.roi_pct == null ? "—" : esc(String(overall.roi_pct)) + "%"}</b></div>
      <div class="stat"><span>CLV</span><b class="num">${overall.clv_avg_pct == null ? "—" : esc(String(overall.clv_avg_pct)) + "%"}</b></div>
    </div>
    <p class="note">${model.n ? `Model called ${fmtPct(model.avg_model_prob)} on average and those sides won ${fmtPct(model.actual_win_rate)}. Direction ${fmtPct(model.direction_hit)}. Brier ${model.brier == null ? "—" : esc(String(model.brier))} (0.25 is a coin flip, lower is better).` : "Model accuracy appears after plays are graded. There is nothing to compare yet."}</p>
    <p class="note">${esc(state.report?.definitions?.roi_pct || "")}</p>
    ${blocks}
    <h3>Waiting on a final</h3>
    ${pending || `<p class="note">No pending recommended plays. The refresh logs High and Medium edges and grades them from ESPN finals.</p>`}
    <h3>My plays</h3>
    ${mine}`;
}

function sheetHtml() {
  const sheet = state.sheet;
  if (!sheet) return "";
  if (sheet.kind === "settings") return settingsSheet();
  if (sheet.kind === "note") {
    return `<div class="sheet" data-act="close-sheet"><div class="sheet-card" data-act="stop"><div class="grab"></div><h2>${esc(sheet.title)}</h2>${(sheet.paragraphs || []).map((p) => `<p>${esc(p)}</p>`).join("")}<button type="button" class="btn block" data-act="close-sheet">Close</button></div></div>`;
  }
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
  const tabChanged = state._painted !== state.tab;
  state._painted = state.tab;
  let body;
  if (state.fatal) body = `<div class="empty">${esc(state.fatal)}</div>`;
  else if (state.tab === "today") body = renderToday();
  else if (state.tab === "edges") body = renderEdges();
  else if (state.tab === "game") body = renderGame();
  else if (state.tab === "builder") body = renderBuilder();
  else if (state.tab === "sgp") body = renderSgp();
  else if (state.tab === "slip") body = renderSlip();
  else body = renderTracker();
  document.getElementById("app").innerHTML = shell(body);
  document.getElementById("splash")?.classList.add("hide");
  const main = document.getElementById("screen");
  const title = document.getElementById("largetitle");
  const nav = document.getElementById("navtitle");
  const header = document.querySelector(".top");
  const phone = document.getElementById("phone");
  if (tabChanged && main) main.classList.add("enter");
  if (main && nav) {
    nav.textContent = title ? title.textContent : "";
    const gameHead = header?.classList.contains("gamehead");
    const onScroll = () => {
      const y = main.scrollTop;
      const word = document.querySelector(".brand span");
      if (word) word.style.opacity = String(Math.max(0, 1 - y / 22));
      if (!gameHead) nav.style.opacity = String(Math.min(1, Math.max(0, (y - 16) / 20)));
      phone?.classList.toggle("scrolled", y > 8);
      header?.classList.toggle("scrolled", y > 8);
    };
    main.onscroll = onScroll;
    onScroll();
  }
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
  if (head === "slip") {
    state.slipOpen = true;
    state.tab = "today";
    render();
    return;
  }
  if (head === "game" && league && id) {
    showGame(league, decodeURIComponent(id));
    return;
  }
  state.tab = ["today", "edges", "builder", "sgp", "slip", "tracker"].includes(head) ? head : "today";
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
    summary.complete ? `Model hit chance: ${fmtPct(slipModel(state.slip, selected).prob)} (same-game legs are correlation-adjusted; a book's SGP price can differ)` : "",
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
  if (act === "tab") {
    if (el.dataset.tab === "slip") { state.slipOpen = true; state.sheet = null; render(); return; }
    state.slipOpen = false;
    go("#" + el.dataset.tab);
    return;
  }
  if (act === "open-slip") { state.slipOpen = true; state.sheet = null; render(); return; }
  if (act === "close-slip") { state.slipOpen = false; render(); return; }
  if (act === "settings") { state.sheet = { kind: "settings" }; state.slipOpen = false; render(); return; }
  if (act === "toggle-board") {
    const game = (state.slate?.days || []).flatMap((day) => day.sports.flatMap((sport) => sport.games || [])).find((item) => String(item.event_id) === el.dataset.id);
    const leg = game && legFor(game, el.dataset.market, el.dataset.side);
    if (!leg) {
      state.sheet = { kind: "note", title: "No model", paragraphs: ["This price is posted. It was not modeled in this refresh, so there is no edge."] };
      render();
      return;
    }
    if (onSlip(leg)) state.slip = state.slip.filter((item) => item.id !== leg.id);
    else addLeg(leg);
    persistSlip();
    render();
    return;
  }
  if (act === "odd-tap" && state.game) {
    const leg = legFromGame(state.game, el.dataset.market, el.dataset.side, activeBook(state.game));
    if (!leg) return;
    if (onSlip(leg)) state.slip = state.slip.filter((item) => item.id !== leg.id);
    else addLeg(leg);
    persistSlip();
    render();
    return;
  }
  if (act === "why-leg") {
    const leg = state.slip.find((item) => item.id === el.dataset.id);
    if (leg) openSheet(leg, state.book);
    return;
  }
  if (act === "why-side" && state.game) {
    const leg = legFromGame(state.game, el.dataset.market, el.dataset.side, activeBook(state.game));
    if (leg) openSheet(leg, activeBook(state.game));
    return;
  }
  if (act === "why-sgp") {
    const card = (state.sgpCards || []).find((item) => item.id === el.dataset.id);
    if (!card) return;
    state.sheet = { kind: "note", title: card.label, paragraphs: [...(card.notes || []), `Weakest leg: ${card.weak.selection}.`, "Books price same-game parlays with their own correlation. A real SGP price can differ from the multiplied leg prices, usually with more hold."] };
    render();
    return;
  }
  if (act === "why-sgpx") {
    state.sheet = { kind: "note", title: "SGPx", paragraphs: ["Each game uses its own correlation adjustment. Different games are treated as independent. A book's SGPx price is not the product of the leg odds."] };
    render();
    return;
  }
  if (act === "why-build" && state.builder.result) {
    const res = state.builder.result;
    state.sheet = { kind: "note", title: "Why this card", paragraphs: [...(res.honest || []), ...(res.correlation || []), ...(res.notes || []), res.priceBasis].filter(Boolean) };
    render();
    return;
  }
  if (act === "sgp-mode") { state.sgpMode = el.dataset.mode; render(); return; }
  if (act === "add-sgp") {
    const card = (state.sgpCards || []).find((item) => item.id === el.dataset.id);
    if (!card) return;
    for (const leg of card.legs) addLeg(leg);
    state.slipOpen = true;
    render();
    return;
  }
  if (act === "toggle-sgpx") {
    const card = (state.sgpCards || []).find((item) => item.id === el.dataset.id);
    if (!card) return;
    if (state.sgpx.includes(card.id)) state.sgpx = state.sgpx.filter((id) => id !== card.id);
    else if (state.sgpx.length < 3 && !state.sgpx.some((id) => (state.sgpCards.find((item) => item.id === id) || {}).event_id === card.event_id)) state.sgpx.push(card.id);
    render();
    return;
  }
  if (act === "add-sgpx") {
    const picked = state.sgpx.map((id) => (state.sgpCards || []).find((item) => item.id === id)).filter(Boolean);
    for (const card of picked) for (const leg of card.legs) addLeg(leg);
    state.slipOpen = true;
    render();
    return;
  }
  if (act === "day") { state.day = el.dataset.day; render(); return; }
  if (act === "sport") { state.sport = el.dataset.sport; render(); return; }
  if (act === "tier") { state.edgeTier = el.dataset.tier; render(); return; }
  if (act === "game") { go(`#game/${el.dataset.league}/${el.dataset.id}`); return; }
  if (act === "edge") {
    const list = el.dataset.prop ? state._propEdges : state._visibleEdges;
    const edge = list?.[Number(el.dataset.index)];
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
    state.slipOpen = true;
    render();
    return;
  }
  if (act === "build") {
    const text = document.getElementById("sentence")?.value ?? state.builder.text;
    state.builder.text = text;
    applyBuild(text);
    render();
    document.getElementById("build-result")?.scrollIntoView({ block: "nearest" });
    return;
  }
  if (act === "legs") { state.builder.legs = Number(el.dataset.n); state.builder.dirty = true; render(); return; }
  if (act === "risk") {
    state.builder.risk = el.dataset.risk;
    state.builder.riskLocked = true;
    if (state.builder.parsed || state.builder.text.trim() || state.builder.alts) {
      applyBuild(state.builder.text);
    }
    render();
    return;
  }
  if (act === "use-build" && state.builder.result?.legs) {
    state.slip = state.builder.result.legs.slice();
    state.bookPinned = false;
    state.copied = null;
    persistSlip();
    state.slipOpen = true;
    render();
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

function applyBuild(text) {
  let spec;
  if (!state.builder.dirty && String(text || "").trim()) spec = parseRequest(text);
  else {
    spec = {
      risk: state.builder.risk,
      legs: Number(state.builder.legs) || 3,
      target: Number(state.builder.target) || 400,
      team: document.getElementById("team")?.value || state.builder.team,
      date: document.getElementById("date")?.value || state.builder.date,
    };
  }
  if (state.builder.riskLocked) spec.risk = state.builder.risk;
  state.builder.team = spec.team || "";
  state.builder.date = spec.date || "";
  state.builder.legs = spec.legs;
  state.builder.target = spec.target;
  state.builder.risk = spec.risk;
  state.builder.parsed = spec;
  state.builder.dirty = false;
  state.builder.alts = buildTrio(spec);
  state.builder.result = state.builder.alts[spec.risk] || state.builder.alts.balanced;
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
  document.getElementById("app").innerHTML = shell(`<div class="skel-title"></div><div class="skel-pills"></div><div class="skel-card"></div><div class="skel-card"></div><div class="skel-card"></div><div class="skel-card"></div>`);
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

if (typeof document !== "undefined") boot();
