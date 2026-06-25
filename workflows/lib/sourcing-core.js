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

const PROSPECT_FIELDS = ["fullName", "jobTitle", "companyName", "location", "headline", "industry", "summary", "linkedinUrl"];

function leadId(lead) { return (lead && (lead.linkedinUrl || lead.people_db_id)) || ""; }
function leadLabel(lead) { return (lead && lead.fullName) || leadId(lead); }
// Stable per-run key: a candidate without any identifier still gets a unique id,
// so id-less leads never collide on "" when verdicts are matched in splitVerdicts.
function draftId(lead, index) { return leadId(lead) || `row:${index}`; }

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

const REVIEW_SCHEMA = {
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

// ---- pure post-processing ----

function filterDrafts(written) {
  return (written || []).filter((d) => d && d.messages && typeof d.messages === "object" && Object.keys(d.messages).length > 0);
}

function splitVerdicts(drafts, verdicts) {
  const byId = new Map();
  for (const v of verdicts || []) if (v && v.id != null) byId.set(String(v.id), v);
  const approuves = [], aRejeter = [];
  for (const d of drafts) {
    const v = byId.get(String(d.id));
    if (v && v.pass) approuves.push({ ...d, verdict: v });
    else aRejeter.push({ ...d, verdict: v || { pass: false, notes: "no_verdict" } });
  }
  return { approuves, aRejeter };
}

function chunk(arr, size) {
  const out = [];
  for (let i = 0; i < arr.length; i += size) out.push(arr.slice(i, i + size));
  return out;
}

function parseStoreKey(store) {
  if (typeof store !== "string") return null;
  const m = store.match(/^variable:(.+)$/);
  return m ? m[1].trim() : null;
}

// Mirrors the two rules of the engine's delivery.is_clean_message that free prose
// can realistically trip: em/en dashes and the word cap. Keep these in sync with
// scripts/prospect_engine/delivery.py if that net changes.
const VARIABLE_MAX_WORDS = 150;

function sanitizeForVariable(text) {
  const words = String(text == null ? "" : text).replace(/[—–]/g, "-").trim().split(/\s+/).filter(Boolean);
  return words.slice(0, VARIABLE_MAX_WORDS).join(" ");
}

function contextValue(context) {
  if (context == null) return null;
  return sanitizeForVariable(typeof context === "string" ? context : context.summary) || null;
}

// Policy: message variables are passed through verbatim — the writer owns them
// (doctrine + review gate), and silently truncating outbound copy would be worse
// than the engine's load-net rejecting it. Only the workflow-managed metadata
// (`contexte`) is sanitized, so it never blocks an otherwise-good lead at load.
function buildApproved(draft, storeKey) {
  const variables = { ...draft.messages };
  const v = storeKey && contextValue(draft.context);
  if (v) variables[storeKey] = v;
  return { lead: draft.lead, variables };
}

// ---- orchestration (the workflow body; env carries the injected runtime globals) ----

async function batchReview(env, drafts, { sequenceKeys, maxWords, judgeModel, reviewBatchSize }) {
  const batches = chunk(drafts, reviewBatchSize);
  const lists = await env.parallel(batches.map((b) => async () =>
    env.agent(buildReviewPrompt({ batch: b, sequenceKeys, maxWords }),
      { schema: REVIEW_SCHEMA, model: judgeModel, phase: "review", label: `review:${b.length}` })));
  const verdicts = [];
  for (const l of lists) if (l && Array.isArray(l.verdicts)) verdicts.push(...l.verdicts);
  return verdicts;
}

async function reviewAndSplit(env, drafts, opts) {
  return splitVerdicts(drafts, await batchReview(env, drafts, opts));
}

async function runSourcing(env) {
  const { agent, pipeline } = env;
  const { candidats = [], prompts = {}, sequence_keys: sequenceKeys = [], enrich = { enabled: false },
    models = {}, review = {}, review_batch_size: reviewBatchSize = 8 } = env.args || {};
  const scoreModel = models.scoring || "haiku";
  const writeModel = models.writing || "sonnet";
  const judgeModel = models.judge || "sonnet";
  const storeKey = parseStoreKey(enrich.store);
  const MSG_SCHEMA = messagesSchema(sequenceKeys);
  const reviewOpts = { sequenceKeys, maxWords: review.max_words || 75, judgeModel, reviewBatchSize };

  // Single write call shape, shared by the first pass and the regeneration.
  const writeDraft = async (draft, label, feedback) => {
    const out = await agent(buildWritePrompt({ messagesPrompts: prompts, sequenceKeys, lead: draft.lead, context: draft.context, feedback }),
      { schema: MSG_SCHEMA, model: writeModel, phase: "write", label });
    return { ...draft, messages: out && out.messages };
  };

  if (!candidats.length) return { approuves: [] };

  // score → (enrich) → write, as one barrier-free pipeline.
  const written = await pipeline(
    candidats,
    (lead) => agent(buildScorePrompt(prompts.icpFit, lead),
      { schema: VERDICT_SCHEMA, model: scoreModel, phase: "score", label: `score:${leadLabel(lead)}` }),
    async (verdict, lead, i) => {
      if (!verdict || !verdict.qualifie) return null;
      const context = enrich.enabled
        ? await agent(buildEnrichPrompt(enrich.directive, lead),
            { schema: ENRICH_SCHEMA, model: enrich.model || judgeModel, agentType: enrich.agent_type || "general-purpose", phase: "enrich", label: `enrich:${leadLabel(lead)}` })
        : null;
      return { id: draftId(lead, i), lead, context };
    },
    (acc) => (acc ? writeDraft(acc, `write:${leadLabel(acc.lead)}`) : null),
  );

  const drafts = filterDrafts(written);
  if (!drafts.length) return { approuves: [] };

  const { approuves, aRejeter } = await reviewAndSplit(env, drafts, reviewOpts);

  // One regeneration of the rejects (with the verdict as feedback), then a single re-review.
  let regenPass = [];
  if (aRejeter.length) {
    const regen = filterDrafts(await env.parallel(aRejeter.map((d) => () => writeDraft(d, `rewrite:${d.id}`, d.verdict))));
    if (regen.length) regenPass = (await reviewAndSplit(env, regen, reviewOpts)).approuves;
  }

  return { approuves: [...approuves, ...regenPass].map((d) => buildApproved(d, storeKey)) };
}

module.exports = {
  interpolate, VERDICT_SCHEMA, PROSPECT_FIELDS, leadId, leadLabel, draftId, buildScorePrompt,
  ENRICH_SCHEMA, buildEnrichPrompt, messagesSchema, buildWritePrompt,
  REVIEW_SCHEMA, buildReviewPrompt,
  filterDrafts, splitVerdicts, chunk, parseStoreKey, buildApproved,
  batchReview, reviewAndSplit, runSourcing,
};
