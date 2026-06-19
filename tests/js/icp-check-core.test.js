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

test("PROSPECT_FIELDS is identical to prod scoring (parity lock)", () => {
  // The single-lead buildScorePrompt assertion can't catch a field added on one side only;
  // compare the field lists directly so a new sourcing field can't silently drift.
  assert.ok(Array.isArray(check.PROSPECT_FIELDS), "icp-check must export PROSPECT_FIELDS");
  assert.deepEqual(check.PROSPECT_FIELDS, score.PROSPECT_FIELDS);
});

test("interpolate matches prod scoring on spaced/missing/null tokens (parity lock)", () => {
  const tpl = "{{ jobTitle }}|{{missing}}|{{nul}}";
  const data = { jobTitle: "Gérante", nul: null };
  assert.equal(check.interpolate(tpl, data), score.interpolate(tpl, data));
});

// ---------------------------------------------------------------------------
// pairVerdict
// ---------------------------------------------------------------------------

test("pairVerdict attaches the lead to its verdict", () => {
  assert.deepEqual(check.pairVerdict(LEAD, { qualifie: true, raison: "ICP pile" }),
    { lead: LEAD, qualifie: true, raison: "ICP pile" });
});

test("pairVerdict tolerates a null or incomplete verdict", () => {
  assert.deepEqual(check.pairVerdict(LEAD, null), { lead: LEAD, qualifie: false, raison: "" });
  assert.deepEqual(check.pairVerdict(LEAD, { qualifie: true }), { lead: LEAD, qualifie: true, raison: "" });
});

// ---------------------------------------------------------------------------
// runCheck — orchestration validated by a mocked run (no real LLM)
// ---------------------------------------------------------------------------

const { fakePipeline } = require("./_runtime-mocks.js");
function makeEnv(args, agentImpl, spy) {
  return { args, pipeline: fakePipeline,
    agent: async (prompt, opts) => { if (spy) spy.push({ prompt, opts }); return agentImpl(prompt, opts); } };
}
const SAMPLE = [
  { linkedinUrl: "https://lk/a", fullName: "A Bon", jobTitle: "Gérant" },
  { linkedinUrl: "https://lk/b", fullName: "B Hors", jobTitle: "Stagiaire" },
];

test("runCheck scores each sample lead on Haiku and returns paired verdicts", async () => {
  const spy = [];
  const agentImpl = (prompt) => ({ qualifie: /Gérant/.test(prompt), raison: "x" });
  const out = await check.runCheck(makeEnv(
    { prompt_icpFit: "score {{jobTitle}}", sample: SAMPLE }, agentImpl, spy));
  assert.deepEqual(out.verdicts.map((v) => [v.lead.linkedinUrl, v.qualifie]),
    [["https://lk/a", true], ["https://lk/b", false]]);
  assert.ok(spy.every((c) => c.opts.model === "haiku" && c.opts.phase === "run"));
});

test("runCheck keeps a lead even if its agent returns null", async () => {
  const out = await check.runCheck(makeEnv(
    { prompt_icpFit: "p", sample: [SAMPLE[0]] }, () => null));
  assert.deepEqual(out.verdicts, [{ lead: SAMPLE[0], qualifie: false, raison: "" }]);
});

test("runCheck keeps a lead even if its agent throws (defensive: no run-abort, no null hole)", async () => {
  const out = await check.runCheck(makeEnv(
    { prompt_icpFit: "p", sample: [SAMPLE[0]] }, () => { throw new Error("boom"); }));
  assert.deepEqual(out.verdicts, [{ lead: SAMPLE[0], qualifie: false, raison: "" }]);
});

test("runCheck honours an explicit model override", async () => {
  const spy = [];
  await check.runCheck(makeEnv(
    { prompt_icpFit: "p", sample: [SAMPLE[0]], model: "sonnet" }, () => ({ qualifie: true, raison: "" }), spy));
  assert.equal(spy[0].opts.model, "sonnet");
});
