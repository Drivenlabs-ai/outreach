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

test("buildScorePrompt surfaces the lead industry when present", () => {
  const out = core.buildScorePrompt("x", { fullName: "Marie Roy", industry: "Real Estate" });
  assert.match(out, /industry: Real Estate/);
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

test("REVIEW_SCHEMA declares the boolean rubric per verdict", () => {
  const item = core.REVIEW_SCHEMA.properties.verdicts.items;
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

test("draftId falls back to a row index when the lead has no identifier", () => {
  assert.equal(core.draftId({ linkedinUrl: "https://lk/a" }, 3), "https://lk/a");
  assert.equal(core.draftId({ people_db_id: "p1" }, 3), "p1");
  assert.equal(core.draftId({}, 3), "row:3");
});

test("buildApproved sanitizes the context so is_clean_message never drops the lead", () => {
  // em/en dashes and over-length would be rejected by the engine's is_clean_message net.
  const dashed = core.buildApproved({ lead: {}, messages: { icebreaker: "x" }, context: { summary: "cliente — de X" } }, "contexte");
  assert.equal(dashed.variables.contexte, "cliente - de X");
  const long = core.buildApproved({ lead: {}, messages: { icebreaker: "x" }, context: { summary: "mot ".repeat(200).trim() } }, "contexte");
  assert.ok(long.variables.contexte.split(/\s+/).length <= 150);
});

test("buildApproved stores no context variable when the summary is empty", () => {
  const out = core.buildApproved({ lead: {}, messages: { icebreaker: "x" }, context: { summary: "" } }, "contexte");
  assert.deepEqual(out.variables, { icebreaker: "x" });
});

// ---------------------------------------------------------------------------
// runSourcing — orchestration validated by a mocked run (no real LLM)
// ---------------------------------------------------------------------------

// Faithful runtime mocks, mirroring the Workflow tool contract (shared).
const { fakePipeline, fakeParallel } = require("./_runtime-mocks.js");
function makeEnv(args, agentImpl, spy) {
  return {
    args, pipeline: fakePipeline, parallel: fakeParallel, phase: () => {}, log: () => {},
    agent: async (prompt, opts) => { if (spy) spy.push({ phase: opts.phase, prompt, opts }); return agentImpl(prompt, opts); },
  };
}
const baseArgs = {
  candidats: [
    { linkedinUrl: "https://lk/a", fullName: "A Qual", jobTitle: "Gérant" },
    { linkedinUrl: "https://lk/b", fullName: "B NoQual", jobTitle: "Stagiaire" },
  ],
  prompts: { icpFit: "score {{jobTitle}}", icebreaker: "P-ice", closing: "P-clo" },
  sequence_keys: ["icebreaker", "closing"],
};

test("runSourcing qualifies, writes, approves; drops non-qualified", async () => {
  const spy = [];
  const agentImpl = (prompt, opts) => {
    if (opts.phase === "score") return { qualifie: /Gérant/.test(prompt), raison: "x" };
    if (opts.phase === "write") return { messages: { icebreaker: "Bonjour", closing: "Au plaisir" } };
    if (opts.phase === "review") return { verdicts: [{ id: "https://lk/a", pass: true }] };
    throw new Error("unexpected phase " + opts.phase);
  };
  const out = await core.runSourcing(makeEnv(baseArgs, agentImpl, spy));
  assert.equal(out.approuves.length, 1);
  assert.equal(out.approuves[0].lead.linkedinUrl, "https://lk/a");
  assert.deepEqual(Object.keys(out.approuves[0].variables), ["icebreaker", "closing"]);
  assert.ok(!spy.some((c) => c.phase === "enrich"));
});

test("runSourcing threads each per-step prompt from the flat prompts dict into write", async () => {
  const spy = [];
  const agentImpl = (prompt, opts) => {
    if (opts.phase === "score") return { qualifie: true, raison: "x" };
    if (opts.phase === "write") return { messages: { icebreaker: "i", closing: "c" } };
    if (opts.phase === "review") return { verdicts: [{ id: "https://lk/a", pass: true }, { id: "https://lk/b", pass: true }] };
    throw new Error("unexpected " + opts.phase);
  };
  await core.runSourcing(makeEnv(baseArgs, agentImpl, spy));
  const writePrompt = spy.find((c) => c.phase === "write").prompt;
  assert.match(writePrompt, /P-ice/);
  assert.match(writePrompt, /P-clo/);
});

test("runSourcing pins models per spec (score=haiku, write=sonnet, review=sonnet)", async () => {
  const seen = {};
  const agentImpl = (prompt, opts) => {
    seen[opts.phase] = opts.model;
    if (opts.phase === "score") return { qualifie: true, raison: "x" };
    if (opts.phase === "write") return { messages: { icebreaker: "i", closing: "c" } };
    if (opts.phase === "review") return { verdicts: [{ id: "https://lk/a", pass: true }, { id: "https://lk/b", pass: true }] };
    throw new Error("unexpected " + opts.phase);
  };
  await core.runSourcing(makeEnv(baseArgs, agentImpl));
  assert.equal(seen.score, "haiku");
  assert.equal(seen.write, "sonnet");
  assert.equal(seen.review, "sonnet");
});

test("runSourcing regenerates a rejected draft once, then approves it", async () => {
  let reviewCalls = 0;
  const agentImpl = (prompt, opts) => {
    if (opts.phase === "score") return { qualifie: true, raison: "x" };
    if (opts.phase === "write") return { messages: { icebreaker: "v", closing: "w" } };
    if (opts.phase === "review") {
      reviewCalls += 1;
      return { verdicts: [{ id: "https://lk/a", pass: reviewCalls > 1 }, { id: "https://lk/b", pass: reviewCalls > 1 }] };
    }
    throw new Error("unexpected " + opts.phase);
  };
  const args = { ...baseArgs, candidats: [baseArgs.candidats[0], { linkedinUrl: "https://lk/b", fullName: "B", jobTitle: "Gérant" }] };
  const out = await core.runSourcing(makeEnv(args, agentImpl));
  assert.equal(out.approuves.length, 2);
  assert.equal(reviewCalls, 2);
});

test("runSourcing discards a draft still failing after the single regeneration", async () => {
  const agentImpl = (prompt, opts) => {
    if (opts.phase === "score") return { qualifie: /Gérant/.test(prompt), raison: "x" };
    if (opts.phase === "write") return { messages: { icebreaker: "v", closing: "w" } };
    if (opts.phase === "review") return { verdicts: [{ id: "https://lk/a", pass: false, notes: "nope" }] };
    throw new Error("unexpected " + opts.phase);
  };
  const out = await core.runSourcing(makeEnv(baseArgs, agentImpl));
  assert.deepEqual(out.approuves, []);
});

test("runSourcing runs enrich only when enabled and only for qualified, persisting context", async () => {
  const spy = [];
  const agentImpl = (prompt, opts) => {
    if (opts.phase === "score") return { qualifie: /Gérant/.test(prompt), raison: "x" };
    if (opts.phase === "enrich") return { summary: "cliente de X", signals: ["a recruté"] };
    if (opts.phase === "write") return { messages: { icebreaker: "i", closing: "c" } };
    if (opts.phase === "review") return { verdicts: [{ id: "https://lk/a", pass: true }] };
    throw new Error("unexpected " + opts.phase);
  };
  const args = { ...baseArgs, enrich: { enabled: true, directive: "vérifie X", store: "variable:contexte" } };
  const out = await core.runSourcing(makeEnv(args, agentImpl, spy));
  const enrichCalls = spy.filter((c) => c.phase === "enrich");
  assert.equal(enrichCalls.length, 1);
  assert.equal(enrichCalls[0].opts.agentType, "general-purpose"); // the only tool-using agent
  assert.equal(out.approuves[0].variables.contexte, "cliente de X");
});

test("runSourcing returns no approvals on an empty candidate list without calling agents", async () => {
  const spy = [];
  const out = await core.runSourcing(makeEnv({ ...baseArgs, candidats: [] }, () => { throw new Error("no agent"); }, spy));
  assert.deepEqual(out.approuves, []);
  assert.equal(spy.length, 0);
});
