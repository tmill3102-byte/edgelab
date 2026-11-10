"use strict";

const fs = require("fs");
const path = require("path");
const vm = require("vm");

const root = path.resolve(__dirname, "..");
const code = fs.readFileSync(path.join(root, "site/app.js"), "utf8");
const context = {
  console,
  setTimeout,
  clearTimeout,
  localStorage: { getItem() { return null; }, setItem() {} },
  navigator: {},
};
vm.createContext(context);
vm.runInContext(code, context);

const legs = JSON.parse(fs.readFileSync(path.join(root, "site/data/legs.json"), "utf8"));
if (!Array.isArray(legs) || legs.length < 20) {
  console.error("legs.json is too small to test the builder");
  process.exit(1);
}
vm.runInContext(`state.legs = ${JSON.stringify(legs)};`, context);

const spec = { legs: 4, target: 400, team: "", date: "" };
const risks = ["safe", "balanced", "aggressive"];
const built = {};
for (const risk of risks) {
  built[risk] = vm.runInContext(`runBuild(${JSON.stringify({ ...spec, risk })})`, context);
}

function ids(result) {
  return (result.legs || []).map((leg) => leg.id).sort();
}
function fail(message) {
  console.error(message);
  for (const risk of risks) {
    const row = built[risk];
    console.error(risk, row.error || "", (row.legs || []).map((leg) => `${leg.selection} ${row.prob && ""}`).join(" | "));
    if (row.legs) {
      console.error("  hit", row.prob, "price", row.payout, row.legs.map((leg) => {
        const offer = Object.values(leg.offers)[0];
        return `${leg.selection} ${offer.odds} p=${offer.model_prob}`;
      }).join("; "));
    }
  }
  process.exit(1);
}

for (const risk of risks) {
  if (!built[risk].legs || built[risk].legs.length < 2) fail(`${risk} did not return a card`);
}
const sets = risks.map((risk) => ids(built[risk]).join("|"));
if (new Set(sets).size !== 3) fail("safe, balanced, and aggressive returned the same legs");
if (!(built.safe.prob > built.balanced.prob && built.balanced.prob > built.aggressive.prob)) {
  fail(`hit chances are not ordered safe > balanced > aggressive (${built.safe.prob} ${built.balanced.prob} ${built.aggressive.prob})`);
}
for (const leg of built.aggressive.legs) {
  const odds = Object.values(leg.offers)[0].odds;
  if (!(odds >= 100)) fail(`aggressive leg is not plus money: ${leg.selection} ${odds}`);
}
for (const leg of built.safe.legs) {
  const odds = Object.values(leg.offers)[0].odds;
  if (!(odds < 0)) fail(`safe leg is not a favorite: ${leg.selection} ${odds}`);
}

const byEvent = {};
for (const leg of legs) (byEvent[leg.event_id] ||= []).push(leg);
let compared = 0;
for (const group of Object.values(byEvent)) {
  const tiers = vm.runInContext(`buildGameSgps(state.legs.filter(leg => leg.event_id === ${JSON.stringify(group[0].event_id)}))`, context);
  const filled = ["safer", "balanced", "longshot", "lotto"]
    .map((key) => tiers[key])
    .filter(Boolean);
  const keys = filled.map((row) => row.legs.map((leg) => leg.id).sort().join("|"));
  if (new Set(keys).size !== keys.length) fail("two SGP tiers returned the same legs");
  if (filled.length >= 2) compared += 1;
}
if (!compared) fail("no game produced two different SGP tiers");

console.log("builder risks differ");
for (const risk of risks) {
  console.log(risk, (built[risk].prob * 100).toFixed(1) + "%", built[risk].payout, built[risk].legs.map((leg) => leg.selection).join(", "));
}
console.log("sgp games with 2+ tiers", compared);

context.document = { getElementById() { return null; } };
vm.runInContext(`
  state.builder.text = "safe 4 leg parlay browns sunday +400";
  state.builder.dirty = false;
  state.builder.riskLocked = true;
  state.builder.risk = "aggressive";
  applyBuild(state.builder.text);
  if (state.builder.parsed.risk !== "aggressive") throw new Error("tapped risk lost to the sentence");
  if (state.builder.result.spec.risk !== "aggressive") throw new Error("built card ignored the tapped risk");
  const probs = ["safe","balanced","aggressive"].map(risk => state.builder.alts[risk].prob);
  if (!(probs[0] > probs[1] && probs[1] > probs[2])) throw new Error("trio hit chances did not separate: " + probs);
`, context);
console.log("risk control wins over the sentence");
console.log("ok");
