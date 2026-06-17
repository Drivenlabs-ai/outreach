const test = require("node:test");
const assert = require("node:assert/strict");
const core = require("../../workflows/lib/sourcing-core.js");

// ---------------------------------------------------------------------------
// interpolate
// ---------------------------------------------------------------------------

test("interpolate fills present tokens", () => {
  assert.equal(
    core.interpolate("Bonjour {{fullName}} de {{companyName}}", { fullName: "A B", companyName: "Acme" }),
    "Bonjour A B de Acme",
  );
});

test("interpolate blanks missing or null tokens", () => {
  assert.equal(core.interpolate("x {{ghost}} y {{nul}} z", { nul: null }), "x  y  z");
});

test("interpolate tolerates inner spaces and leaves plain text", () => {
  assert.equal(core.interpolate("{{ jobTitle }} fixe", { jobTitle: "Gérant" }), "Gérant fixe");
});

// ---------------------------------------------------------------------------
// score prompt + verdict schema + lead identity
// ---------------------------------------------------------------------------

test("buildScorePrompt embeds the interpolated template and the candidate facts", () => {
  const lead = { linkedinUrl: "https://lk/a", fullName: "Marie Roy", jobTitle: "Gérante", companyName: "Roy Immo", location: "Lyon" };
  const out = core.buildScorePrompt("Évalue ce {{jobTitle}}.", lead);
  assert.match(out, /Évalue ce Gérante\./);
  assert.match(out, /Marie Roy/);
  assert.match(out, /Roy Immo/);
  assert.match(out, /Lyon/);
});

test("VERDICT_SCHEMA requires qualifie and raison", () => {
  assert.deepEqual(core.VERDICT_SCHEMA.required, ["qualifie", "raison"]);
  assert.equal(core.VERDICT_SCHEMA.properties.qualifie.type, "boolean");
});

test("leadId/leadLabel fall back through identifiers", () => {
  assert.equal(core.leadId({ people_db_id: "p1" }), "p1");
  assert.equal(core.leadLabel({ linkedinUrl: "https://lk/x" }), "https://lk/x");
});

// ---------------------------------------------------------------------------
// write prompt + messages schema + enrich
// ---------------------------------------------------------------------------

test("messagesSchema mirrors sequence_keys exactly", () => {
  const s = core.messagesSchema(["icebreaker", "closing"]);
  assert.deepEqual(Object.keys(s.properties.messages.properties), ["icebreaker", "closing"]);
  assert.deepEqual(s.properties.messages.required, ["icebreaker", "closing"]);
  assert.equal(s.properties.messages.additionalProperties, false);
});

test("buildWritePrompt embeds each step prompt, keys, context and feedback", () => {
  const out = core.buildWritePrompt({
    messagesPrompts: { icebreaker: "ACCROCHE-PROMPT", followup: "RELANCE-PROMPT" },
    sequenceKeys: ["icebreaker", "followup"],
    lead: { fullName: "Marie Roy", jobTitle: "Gérante" },
    context: { summary: "Cliente de X depuis 2020", signals: ["a recruté"] },
    feedback: { notes: "angle trop générique", angle_coherent: false },
  });
  assert.match(out, /ACCROCHE-PROMPT/);
  assert.match(out, /RELANCE-PROMPT/);
  assert.match(out, /icebreaker/);
  assert.match(out, /Cliente de X depuis 2020/);
  assert.match(out, /angle trop générique/);
  assert.match(out, /Marie Roy/);
});

test("buildWritePrompt omits context and feedback sections when absent", () => {
  const out = core.buildWritePrompt({
    messagesPrompts: { icebreaker: "P" }, sequenceKeys: ["icebreaker"], lead: { fullName: "A" },
  });
  assert.doesNotMatch(out, /Contexte enrichi/);
  assert.doesNotMatch(out, /Correction demandée/);
});

test("ENRICH_SCHEMA requires summary", () => {
  assert.deepEqual(core.ENRICH_SCHEMA.required, ["summary"]);
});

test("buildEnrichPrompt carries the directive and the prospect", () => {
  const out = core.buildEnrichPrompt("Vérifie si cliente de X", { fullName: "Marie Roy" });
  assert.match(out, /Vérifie si cliente de X/);
  assert.match(out, /Marie Roy/);
});

// ---------------------------------------------------------------------------
// review (GATE 2 boolean rubric, by batch)
// ---------------------------------------------------------------------------

test("reviewSchema declares the boolean rubric per verdict", () => {
  const item = core.reviewSchema().properties.verdicts.items;
  for (const k of ["id", "no_fabrication", "angle_coherent", "within_length", "no_banned_phrases", "vouvoiement", "pass"]) {
    assert.ok(item.required.includes(k), `missing ${k}`);
  }
});

test("buildReviewPrompt lists each draft, its messages and the rubric", () => {
  const out = core.buildReviewPrompt({
    batch: [
      { id: "https://lk/a", lead: { fullName: "Marie Roy" }, messages: { icebreaker: "Bonjour..." } },
      { id: "https://lk/b", lead: { fullName: "Jean Sol" }, messages: { icebreaker: "Salut..." } },
    ],
    sequenceKeys: ["icebreaker"], maxWords: 75,
  });
  assert.match(out, /https:\/\/lk\/a/);
  assert.match(out, /https:\/\/lk\/b/);
  assert.match(out, /Marie Roy/);
  assert.match(out, /75/);
  assert.match(out, /vouvoiement/i);
  assert.match(out, /pass/i);
});

// ---------------------------------------------------------------------------
// pure post-processing: filter / split / chunk / approve / store key
// ---------------------------------------------------------------------------

test("filterDrafts drops nulls and message-less entries", () => {
  const out = core.filterDrafts([null, { messages: {} }, { messages: { icebreaker: "x" } }, undefined]);
  assert.equal(out.length, 1);
  assert.equal(out[0].messages.icebreaker, "x");
});

test("splitVerdicts partitions by id and pass, defaulting missing verdicts to reject", () => {
  const drafts = [{ id: "a", messages: {} }, { id: "b", messages: {} }, { id: "c", messages: {} }];
  const verdicts = [{ id: "a", pass: true }, { id: "b", pass: false, notes: "trop long" }];
  const { approuves, aRejeter } = core.splitVerdicts(drafts, verdicts);
  assert.deepEqual(approuves.map((d) => d.id), ["a"]);
  assert.deepEqual(aRejeter.map((d) => d.id), ["b", "c"]);
  assert.equal(aRejeter.find((d) => d.id === "c").verdict.notes, "no_verdict");
});

test("chunk splits into batches", () => {
  assert.deepEqual(core.chunk([1, 2, 3, 4, 5], 2), [[1, 2], [3, 4], [5]]);
});

test("parseStoreKey extracts the variable name", () => {
  assert.equal(core.parseStoreKey("variable:contexte"), "contexte");
  assert.equal(core.parseStoreKey("field:foo"), null);
  assert.equal(core.parseStoreKey(undefined), null);
});

test("buildApproved shapes {lead, variables} and persists context to the store variable", () => {
  const draft = { lead: { linkedinUrl: "https://lk/a" }, messages: { icebreaker: "x", closing: "y" }, context: { summary: "cliente de X" } };
  assert.deepEqual(core.buildApproved(draft, "contexte"),
    { lead: { linkedinUrl: "https://lk/a" }, variables: { icebreaker: "x", closing: "y", contexte: "cliente de X" } });
  assert.deepEqual(core.buildApproved({ lead: {}, messages: { icebreaker: "x" } }, null).variables, { icebreaker: "x" });
});
