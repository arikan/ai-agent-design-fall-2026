// The page ranks the day's postings in the browser with a JavaScript port of engine.py's
// prefilter. This checks the port against the engine on the corpus postings:
//   uv run engine.py rank-fixture && node tests/rank_test.js
const fs = require("fs"), path = require("path");
const here = path.join(__dirname, "..");
const html = fs.readFileSync(path.join(here, "console.html"), "utf8");
const block = html.match(/\/\* rank:begin[\s\S]*?\*\/([\s\S]*?)\/\* rank:end \*\//);
if (!block) { console.error("rank block not found in console.html"); process.exit(1); }
const RANK = new Function(block[1] + "; return RANK;")();
const fx = JSON.parse(fs.readFileSync(path.join(here, "tests", "rank_fixture.json"), "utf8"));
let bad = 0;
for (const [i, p] of fx.postings.entries()) {
  const want = fx.expected[i];
  const dropped = RANK.dealBreaker(p, fx.deal_breakers), score = RANK.score(fx.search, p);
  const ok = dropped === want.dropped && Math.abs(score - want.score) < 0.0015;
  if (!ok) { bad++; console.log(`${p.id}: page says ${dropped ?? "kept"} ${score}, engine says ${want.dropped ?? "kept"} ${want.score}`); }
}
console.log(bad ? `${bad} of ${fx.postings.length} differ` : `ok: ${fx.postings.length} postings rank the same in the page and the engine`);
process.exit(bad ? 1 : 0);
