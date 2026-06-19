"use strict";
// ===== icp-check-core: deterministic logic for the icpFit alignment pass (single source) =====
// icp-check.workflow.js is GENERATED from this file (build-icp-check-workflow.js) and must stay
// byte-identical (tests/js/icp-check-workflow-sync.test.js). Runtime is sandboxed: no require/import,
// no Date.now()/Math.random().
//
// The scoring construction below is a deliberate copy of workflows/lib/sourcing-core.js so the test
// runs EXACTLY the prod judgment. Drift is impossible: tests/js/icp-check-core.test.js asserts
// byte-identical output + deepEqual schema against sourcing-core. (When a 3rd consumer appears, extract
// a shared score-core inlined by both generators — rule of three.)

function interpolate(template, data) {
  return String(template == null ? "" : template).replace(/\{\{\s*([\w.]+)\s*\}\}/g, (_, k) => {
    const v = data ? data[k] : undefined;
    return v == null ? "" : String(v);
  });
}

const VERDICT_SCHEMA = {
  type: "object", additionalProperties: false,
  properties: {
    qualifie: { type: "boolean", description: "Le prospect correspond-il à l'ICP ?" },
    raison: { type: "string", description: "Justification courte ancrée sur les faits du prospect." },
  },
  required: ["qualifie", "raison"],
};

const PROSPECT_FIELDS = ["fullName", "jobTitle", "companyName", "location", "headline", "summary", "linkedinUrl"];

function prospectBlock(lead) {
  const lines = PROSPECT_FIELDS.filter((k) => lead && lead[k]).map((k) => `- ${k}: ${lead[k]}`);
  return `## Prospect à évaluer\n${lines.join("\n")}`;
}

function buildScorePrompt(icpFitTemplate, lead) {
  return `${interpolate(icpFitTemplate, lead)}\n\n${prospectBlock(lead)}`;
}

module.exports = { interpolate, VERDICT_SCHEMA, prospectBlock, buildScorePrompt };
