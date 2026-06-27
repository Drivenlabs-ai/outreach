// GENERATED from workflows/lib/icp-check-core.js — do not edit by hand.
// Regenerate: node workflows/lib/build-icp-check-workflow.js   (guarded by tests/js/icp-check-workflow-sync.test.js)
export const meta = {
  "name": "icp-check",
  "description": "Passe d'alignement au setup : juge un échantillon avec le prompt icpFit (Haiku) et rend les verdicts bruts pour relecture/itération par l'agent de session. Aucune écriture, aucun gate auto.",
  "phases": [
    {
      "title": "run",
      "detail": "1 sous-agent icpFit / prospect (Haiku, parité prod) → {qualifie, raison}"
    }
  ]
};

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

const PROSPECT_FIELDS = ["fullName", "jobTitle", "companyName", "companyDescription", "companyAudience", "location", "headline", "industry", "summary", "linkedinUrl"];

function prospectBlock(lead) {
  const lines = PROSPECT_FIELDS.filter((k) => lead && lead[k]).map((k) => `- ${k}: ${lead[k]}`);
  return `## Prospect à évaluer\n${lines.join("\n")}`;
}

function buildScorePrompt(icpFitTemplate, lead) {
  return `${interpolate(icpFitTemplate, lead)}\n\n${prospectBlock(lead)}`;
}

function pairVerdict(lead, verdict) {
  return { lead, qualifie: !!(verdict && verdict.qualifie), raison: (verdict && verdict.raison) || "" };
}

// ---- orchestration (the workflow body; env carries the injected runtime globals) ----

async function runCheck(env) {
  const { agent, pipeline, args } = env;
  const sample = (args && args.sample) || [];
  const prompt = (args && args.prompt_icpFit) || "";
  const model = (args && args.model) || "haiku";
  const verdicts = await pipeline(sample,
    (lead) => agent(buildScorePrompt(prompt, lead),
      { schema: VERDICT_SCHEMA, model, phase: "run", label: `icp:${(lead && (lead.fullName || lead.linkedinUrl)) || ""}` })
      // Per the runtime contract agent() resolves to null on failure (handled below); the rejection arm
      // is belt-and-suspenders so a dead agent degrades to {qualifie:false} instead of nulling the slot.
      .then((v) => pairVerdict(lead, v), () => pairVerdict(lead, null)));
  return { verdicts };
}

return await runCheck({ agent, pipeline, args });
