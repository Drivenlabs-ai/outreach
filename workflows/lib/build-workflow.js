"use strict";
// Generates the self-contained workflows/sourcing.workflow.js from sourcing-core.js.
// The workflow runtime forbids require/import, so the core is inlined: we strip its
// module.exports, prepend the (pure-literal) meta, and append the global-wired call.
// tests/js/sourcing-workflow-sync.test.js guards committed === generated.
const fs = require("node:fs");
const path = require("node:path");

const META = {
  name: "sourcing",
  description: "W3 — score (Haiku) → enrich (optionnel) → write (Sonnet) → review par batch (Sonnet, 1 régénération). Orchestration pure ; l'I/O Lemlist reste au moteur.",
  phases: [
    { title: "score", detail: "icpFit Haiku par candidat (intelligence pure)" },
    { title: "enrich", detail: "recherche web par qualifié, si campaign.json.enrich.enabled" },
    { title: "write", detail: "séquence complète en un fil, Sonnet" },
    { title: "review", detail: "juge Sonnet par batch, rubrique booléenne, rejet → 1 régénération" },
  ],
};

function buildWorkflowSource() {
  const core = fs.readFileSync(path.join(__dirname, "sourcing-core.js"), "utf8");
  const body = core.replace(/\nmodule\.exports[\s\S]*$/, "\n").trimEnd();
  return [
    "// GENERATED from workflows/lib/sourcing-core.js — do not edit by hand.",
    "// Regenerate: node workflows/lib/build-workflow.js   (guarded by tests/js/sourcing-workflow-sync.test.js)",
    `export const meta = ${JSON.stringify(META, null, 2)};`,
    "",
    body,
    "",
    "return await runSourcing({ agent, pipeline, parallel, phase, log, args });",
    "",
  ].join("\n");
}

module.exports = { buildWorkflowSource, META };

if (require.main === module) {
  const out = path.join(__dirname, "..", "sourcing.workflow.js");
  fs.writeFileSync(out, buildWorkflowSource());
  process.stdout.write(`wrote ${out}\n`);
}
