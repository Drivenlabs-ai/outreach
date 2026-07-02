"use strict";
// ===== craft-copy-test-core: before/after copy comparison on the REAL write agent (single source) =====
// craft-copy-test.workflow.js is GENERATED from this file (build-craft-copy-test-workflow.js) and must stay
// byte-identical (tests/js/craft-copy-test-workflow-sync.test.js). Runtime sandboxed: no require/import,
// no Date.now()/Math.random().
//
// The write construction below is a deliberate copy of workflows/lib/sourcing-core.js so the test runs
// EXACTLY the prod writer. Drift is impossible: tests/js/craft-copy-test-core.test.js asserts byte-identical
// function source + deepEqual schema against sourcing-core. (Rule of three: when a 3rd consumer of the write
// path appears, extract a shared write-core inlined by both generators.)

const PROSPECT_FIELDS = ["fullName", "jobTitle", "companyName", "companyDescription", "companyAudience", "location", "headline", "industry", "summary", "linkedinUrl"];

function leadId(lead) { return (lead && (lead.linkedinUrl || lead.people_db_id)) || ""; }
function leadLabel(lead) { return (lead && lead.fullName) || leadId(lead); }

function prospectBlock(lead) {
  const lines = PROSPECT_FIELDS.filter((k) => lead && lead[k]).map((k) => `- ${k}: ${lead[k]}`);
  return `## Prospect à évaluer\n${lines.join("\n")}`;
}

function messagesSchema(sequenceKeys) {
  const properties = {};
  for (const k of sequenceKeys) {
    properties[k] = { type: "string", description: `Message « ${k} » — vouvoiement, prêt à envoyer, sans markdown.` };
  }
  return {
    type: "object", additionalProperties: false,
    properties: { messages: { type: "object", additionalProperties: false, properties, required: [...sequenceKeys] } },
    required: ["messages"],
  };
}

const WRITE_DOCTRINE = [
  "Écris la séquence ENTIÈRE en un seul fil : chaque message prolonge l'angle ouvert par le précédent (tu les reçois tous d'un coup).",
  "Reste sur l'offre décrite par les prompts d'étape : adapte l'angle au prospect, mais ne propose jamais une capacité ou un service que ces prompts ne décrivent pas, même si le profil du prospect suggère un autre besoin ; sinon tu vends une offre qui n'existe pas.",
  "Règles dures : vouvoiement, français natif, une seule idée par message, longueur selon la fiche de chaque étape (aucun plafond imposé ici),",
  "n'ouvre jamais par une question ni par « je », aucun fait inventé, aucun jargon pompeux (leverage, synergies, game-changer…),",
  "pas de formule cliché (« j'espère que vous allez bien », « je me permets », « pour faire suite »), pas d'emoji, ≤ 1 point d'exclamation, pas de tiret cadratin.",
].join(" ");

function buildWritePrompt({ messagesPrompts, sequenceKeys, lead, context, feedback }) {
  const steps = sequenceKeys
    .map((k, i) => `### Message ${i + 1} — clé \`${k}\`\n${(messagesPrompts && messagesPrompts[k]) || ""}`)
    .join("\n\n");
  const ctx = context
    ? `\n\n## Contexte enrichi (à exploiter, vérifié)\n${context.summary || ""}${(context.signals && context.signals.length) ? `\nSignaux : ${context.signals.join(" · ")}` : ""}`
    : "";
  const fb = feedback
    ? `\n\n## Correction demandée (régénération)\nLa version précédente a été rejetée : ${feedback.notes || "non conforme à la rubrique"}. Corrige et respecte toute la rubrique.`
    : "";
  return `${WRITE_DOCTRINE}\n\n${prospectBlock(lead)}${ctx}\n\n## Étapes à rédiger (dans l'ordre)\n${steps}${fb}\n\nRends un objet { "messages": { ${sequenceKeys.map((k) => `"${k}"`).join(", ")} } }.`;
}

// ---- orchestration (env carries the injected runtime globals) ----

async function runCraftCopyTest(env) {
  const { agent, pipeline, args } = env;
  const sample = (args && args.sample) || [];
  const sequenceKeys = (args && args.sequence_keys) || [];
  const promptsBefore = (args && args.prompts_before) || {};
  const promptsAfter = (args && args.prompts_after) || {};
  const model = (args && args.model) || "sonnet";
  const MSG = messagesSchema(sequenceKeys);
  const writeOne = (lead, prompts, tag) =>
    agent(buildWritePrompt({ messagesPrompts: prompts, sequenceKeys, lead, context: null, feedback: null }),
      { schema: MSG, model, phase: "write", label: `${tag}:${leadLabel(lead)}` })
      .then((out) => (out && out.messages) || null, () => null);
  const comparisons = await pipeline(sample, async (lead, _item, i) => {
    const [before, after] = await Promise.all([
      writeOne(lead, promptsBefore, "before"),
      writeOne(lead, promptsAfter, "after"),
    ]);
    return { id: leadId(lead) || `row:${i}`, lead, before, after };
  });
  return { comparisons };
}

module.exports = { PROSPECT_FIELDS, leadId, leadLabel, prospectBlock, messagesSchema, WRITE_DOCTRINE, buildWritePrompt, runCraftCopyTest };
