const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { buildWorkflowSource } = require("../../workflows/lib/build-workflow.js");

const WORKFLOW = path.join(__dirname, "..", "..", "workflows", "sourcing.workflow.js");

test("committed sourcing.workflow.js equals the generated source (run: node workflows/lib/build-workflow.js)", () => {
  const committed = fs.readFileSync(WORKFLOW, "utf8");
  assert.equal(committed, buildWorkflowSource());
});

test("generated workflow is self-contained: no require/import, declares meta, calls runSourcing", () => {
  const src = buildWorkflowSource();
  assert.doesNotMatch(src, /\brequire\s*\(/);
  assert.doesNotMatch(src, /^\s*import\s/m);
  assert.doesNotMatch(src, /module\.exports/);
  assert.match(src, /export const meta = /);
  assert.match(src, /return await runSourcing\(\{ agent, pipeline, parallel, phase, log, args \}\)/);
});
