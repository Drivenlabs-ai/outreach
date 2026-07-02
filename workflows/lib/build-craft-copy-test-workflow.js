"use strict";
// Generates the self-contained workflows/craft-copy-test.workflow.js from craft-copy-test-core.js.
const fs = require("node:fs");
const path = require("node:path");

const META = {
  name: "craft-copy-test",
  description: "Test avant/après d'un prompt de copy : rejoue l'agent d'écriture réel (parité prod) sur un échantillon, avec l'ancien et le nouveau prompt, et rend les deux jeux de messages côte à côte pour validation humaine. Aucune écriture, aucun gate auto.",
  phases: [
    { title: "write", detail: "1 écriture avant + 1 après par prospect (parité prod), messages bruts côte à côte" },
  ],
};

function buildWorkflowSource() {
  const core = fs.readFileSync(path.join(__dirname, "craft-copy-test-core.js"), "utf8");

  const corePhases = [...new Set([...core.matchAll(/phase:\s*"(\w+)"/g)].map((m) => m[1]))].sort();
  const metaTitles = META.phases.map((p) => p.title).sort();
  if (JSON.stringify(corePhases) !== JSON.stringify(metaTitles)) {
    throw new Error(`META.phases ${JSON.stringify(metaTitles)} out of sync with core phases ${JSON.stringify(corePhases)}`);
  }

  const body = core
    .replace(/^"use strict";\n/, "")
    .replace(/\nmodule\.exports[\s\S]*$/, "\n")
    .trimEnd();
  return [
    "// GENERATED from workflows/lib/craft-copy-test-core.js — do not edit by hand.",
    "// Regenerate: node workflows/lib/build-craft-copy-test-workflow.js   (guarded by tests/js/craft-copy-test-workflow-sync.test.js)",
    `export const meta = ${JSON.stringify(META, null, 2)};`,
    "",
    body,
    "",
    "return await runCraftCopyTest({ agent, pipeline, args });",
    "",
  ].join("\n");
}

module.exports = { buildWorkflowSource, META };

if (require.main === module) {
  const out = path.join(__dirname, "..", "craft-copy-test.workflow.js");
  fs.writeFileSync(out, buildWorkflowSource());
  process.stdout.write(`wrote ${out}\n`);
}
