const test = require("node:test");
const assert = require("node:assert/strict");
const check = require("../../workflows/lib/icp-check-core.js");
const score = require("../../workflows/lib/sourcing-core.js");

const LEAD = { linkedinUrl: "https://lk/a", fullName: "Marie Roy", jobTitle: "Gérante",
  companyName: "Roy Immo", location: "Lyon", summary: "20 ans dans l'immo", headline: "Gérante agence" };

// ---------------------------------------------------------------------------
// parity lock — the alignment pass must run EXACTLY the prod scoring
// ---------------------------------------------------------------------------

test("buildScorePrompt is byte-identical to prod scoring (parity lock)", () => {
  const tpl = "Évalue ce {{jobTitle}} chez {{companyName}}.";
  assert.equal(check.buildScorePrompt(tpl, LEAD), score.buildScorePrompt(tpl, LEAD));
});

test("VERDICT_SCHEMA matches prod scoring (parity lock)", () => {
  assert.deepEqual(check.VERDICT_SCHEMA, score.VERDICT_SCHEMA);
});
