const test = require("node:test");
const assert = require("node:assert/strict");
const core = require("../../workflows/lib/craft-copy-test-core.js");
const prod = require("../../workflows/lib/sourcing-core.js");
const { fakePipeline } = require("./_runtime-mocks.js");

test("write path is byte-identical to sourcing-core (no drift)", () => {
  assert.equal(core.WRITE_DOCTRINE, prod.WRITE_DOCTRINE);
  assert.equal(core.buildWritePrompt.toString(), prod.buildWritePrompt.toString());
  assert.equal(core.prospectBlock.toString(), prod.prospectBlock.toString());
  assert.equal(core.leadId.toString(), prod.leadId.toString());
  assert.equal(core.leadLabel.toString(), prod.leadLabel.toString());
  assert.deepEqual(core.PROSPECT_FIELDS, prod.PROSPECT_FIELDS);
  assert.deepEqual(core.messagesSchema(["icebreaker", "closing"]), prod.messagesSchema(["icebreaker", "closing"]));
});

test("runCraftCopyTest writes each lead with before AND after prompts, real writer shape", async () => {
  const seen = [];
  const agent = (prompt, opts) => {
    seen.push({ label: opts.label, model: opts.model, phase: opts.phase, prompt });
    return Promise.resolve({ messages: { icebreaker: opts.label.startsWith("before") ? "AVANT" : "APRES" } });
  };
  const out = await core.runCraftCopyTest({
    agent, pipeline: fakePipeline,
    args: {
      sample: [{ linkedinUrl: "https://lk/a", fullName: "Marie Roy", jobTitle: "Gérante" }],
      sequence_keys: ["icebreaker"],
      prompts_before: { icebreaker: "ANCIEN-PROMPT" },
      prompts_after: { icebreaker: "NOUVEAU-PROMPT" },
    },
  });
  assert.equal(out.comparisons.length, 1);
  assert.equal(out.comparisons[0].before.icebreaker, "AVANT");
  assert.equal(out.comparisons[0].after.icebreaker, "APRES");
  assert.ok(seen.some((c) => c.prompt.includes("ANCIEN-PROMPT")));
  assert.ok(seen.some((c) => c.prompt.includes("NOUVEAU-PROMPT")));
  assert.ok(seen.every((c) => c.phase === "write"));
});

test("runCraftCopyTest keeps the lead even if a write fails (null side)", async () => {
  const agent = () => Promise.reject(new Error("dead"));
  const out = await core.runCraftCopyTest({
    agent, pipeline: fakePipeline,
    args: { sample: [{ linkedinUrl: "https://lk/a" }], sequence_keys: ["icebreaker"], prompts_before: {}, prompts_after: {} },
  });
  assert.equal(out.comparisons.length, 1);
  assert.equal(out.comparisons[0].before, null);
  assert.equal(out.comparisons[0].after, null);
});
