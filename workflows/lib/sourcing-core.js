"use strict";
// ===== sourcing-core: deterministic logic for W3 (single source of truth) =====
// sourcing.workflow.js is GENERATED from this file by build-workflow.js and must
// stay byte-identical (guarded by tests/js/sourcing-workflow-sync.test.js). The
// workflow runtime is sandboxed: no require/import, no Date.now()/Math.random().
// Everything below is therefore pure JS with the agent runtime injected as `env`.

function interpolate(template, data) {
  return String(template == null ? "" : template).replace(/\{\{\s*([\w.]+)\s*\}\}/g, (_, k) => {
    const v = data ? data[k] : undefined;
    return v == null ? "" : String(v);
  });
}

// ---- schemas (structured agent outputs) ----

const VERDICT_SCHEMA = {
  type: "object", additionalProperties: false,
  properties: {
    qualifie: { type: "boolean", description: "Le prospect correspond-il à l'ICP ?" },
    raison: { type: "string", description: "Justification courte ancrée sur les faits du prospect." },
  },
  required: ["qualifie", "raison"],
};

// ---- lead identity + prompt assembly ----

const PROSPECT_FIELDS = ["fullName", "jobTitle", "companyName", "location", "headline", "summary", "linkedinUrl"];

function leadId(lead) { return (lead && (lead.linkedinUrl || lead.people_db_id)) || ""; }
function leadLabel(lead) { return (lead && lead.fullName) || leadId(lead); }

function prospectBlock(lead) {
  const lines = PROSPECT_FIELDS.filter((k) => lead && lead[k]).map((k) => `- ${k}: ${lead[k]}`);
  return `## Prospect à évaluer\n${lines.join("\n")}`;
}

function buildScorePrompt(icpFitTemplate, lead) {
  return `${interpolate(icpFitTemplate, lead)}\n\n${prospectBlock(lead)}`;
}

// ---- enrich (the only tool-using agent: web research) ----

const ENRICH_SCHEMA = {
  type: "object", additionalProperties: false,
  properties: {
    summary: { type: "string", description: "Synthèse actionnable des trouvailles (1-3 phrases)." },
    signals: { type: "array", items: { type: "string" }, description: "Signaux récents pertinents (déclencheurs, actualités)." },
  },
  required: ["summary"],
};

function buildEnrichPrompt(directive, lead) {
  return [
    "Tu es un agent de recherche. Utilise la recherche web pour enrichir le prospect ci-dessous.",
    directive ? `Directive : ${directive}` : "",
    prospectBlock(lead),
    "Rends une synthèse actionnable (summary) et les signaux récents pertinents (signals). N'invente rien : si une info n'est pas vérifiable, ne la rapporte pas.",
  ].filter(Boolean).join("\n\n");
}

// ---- write (full sequence in one thread) ----

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
  "Règles dures : vouvoiement, français natif, corps ≤ ~75 mots par message, une seule idée par message,",
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

// ---- review (GATE 2: boolean rubric, judged by batch) ----

function reviewSchema() {
  return {
    type: "object", additionalProperties: false,
    properties: {
      verdicts: {
        type: "array",
        items: {
          type: "object", additionalProperties: false,
          properties: {
            id: { type: "string" },
            no_fabrication: { type: "boolean", description: "Aucun fait/chiffre/résultat inventé." },
            angle_coherent: { type: "boolean", description: "L'angle tient sur tout le fil, ancré sur le prospect." },
            within_length: { type: "boolean", description: "Chaque message ≤ longueur cible." },
            no_banned_phrases: { type: "boolean", description: "Aucune formule cliché / jargon / ouverture interdite." },
            vouvoiement: { type: "boolean", description: "Français, vouvoiement constant." },
            pass: { type: "boolean", description: "Vrai UNIQUEMENT si tous les critères ci-dessus sont vrais." },
            notes: { type: "string", description: "Si échec : ce qui cloche, en une phrase." },
          },
          required: ["id", "no_fabrication", "angle_coherent", "within_length", "no_banned_phrases", "vouvoiement", "pass"],
        },
      },
    },
    required: ["verdicts"],
  };
}

const REVIEW_RUBRIC = [
  "Évalue chaque lead sur 5 critères booléens (la garde déterministe is_clean_message couvre déjà markdown/tirets — juge le fond) :",
  "1. no_fabrication — aucun fait, chiffre, résultat ou « cliente de X » non étayé par les faits/contexte fournis.",
  "2. angle_coherent — un angle unique, spécifique au prospect, qui tient du premier au dernier message.",
  "3. within_length — chaque message reste dans la longueur cible.",
  "4. no_banned_phrases — pas de jargon (leverage, synergies, game-changer…), pas de flatterie générique, pas d'ouverture par une question ou par « je », pas de « pour faire suite / j'espère que vous allez bien », pas d'ALL CAPS, ≤ 1 « ! ».",
  "5. vouvoiement — français natif, vouvoiement constant.",
  "pass = vrai SEULEMENT si les 5 sont vrais.",
].join("\n");

function buildReviewPrompt({ batch, sequenceKeys, maxWords }) {
  const cards = batch.map((d) => {
    const facts = prospectBlock(d.lead);
    const ctx = d.context && d.context.summary ? `\nContexte : ${d.context.summary}` : "";
    const msgs = sequenceKeys.map((k) => `  [${k}] ${(d.messages && d.messages[k]) || ""}`).join("\n");
    return `--- lead id: ${d.id} ---\n${facts}${ctx}\nMessages :\n${msgs}`;
  }).join("\n\n");
  return `Tu es juge qualité outbound. Longueur cible : ≤ ${maxWords} mots par message.\n\n${REVIEW_RUBRIC}\n\n## Leads à juger\n${cards}\n\nRends { "verdicts": [ … ] } avec un verdict par lead id ci-dessus.`;
}

module.exports = {
  interpolate, VERDICT_SCHEMA, leadId, leadLabel, buildScorePrompt,
  ENRICH_SCHEMA, buildEnrichPrompt, messagesSchema, buildWritePrompt,
  reviewSchema, buildReviewPrompt,
};
