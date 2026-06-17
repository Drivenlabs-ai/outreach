---
spec: 03 — W3 sourcing (le run quotidien)
statut: moteur `source` + workflow livrés et testés (TDD) — 2026-06-17
date: 2026-06-15
dépend de: docs/specs/01-routine-engine.md, docs/specs/02-lemlist-setup.md
---

# Spec 03 — W3 sourcing (le run quotidien)

Le run qui fait le travail chaque jour pour une verticale : **sourcer → scorer (ICP) → rédiger →
charger en review**. Premier *vrai* workflow (fan-out d'agents). La revue + le launch restent après
(le workflow tourne en autonomie, sans pause).

## 0. La frontière déterministe ↔ agentique

- **Le script du workflow** = orchestration déterministe pure (ordre, fan-out, filtrage, agrégation).
  Aucun accès outil : il ne touche pas Lemlist.
- **Les agents** = l'intelligence (score ICP, rédaction, review), en **sorties structurées** (schéma).
- **L'I/O déterministe** (sourcer, charger) = le **moteur**, appelé **par le routeur autour du workflow**
  (le moteur a les outils ; c'est du code testé, pas un LLM).

→ Modèle hybride : le routeur prépare (source) et conclut (load) en déterministe ; le workflow ne
contient que le jugement IA.

## 1. Le flux

```
ROUTEUR (déterministe — moteur)
  1. resolve + prepare              → config, prompts (icpFit + messages), clés requises
  2. source                         → candidats (People DB, filtres, hors déjà-vus, quota lu)
       ↓ args = {candidats, prompts}
  2'. WORKFLOW (agents)
       score    pipeline · 1 agent icpFit / candidat (Haiku, intelligence pure)   → qualifiés
       enrich   [si campaign.json.enrich.enabled] 1 agent AVEC outils web / qualifié
                → trouvailles structurées {…}                                     → contexte
       write    1 agent / qualifié · séquence en un fil (Sonnet) · reçoit le contexte → messages
       ──barrière──
       review   juge Sonnet par BATCH · rubrique → verdict struct                 → approuvés
                (rejeté → 1 régénération → sinon écarté)
       ↓ rend {approuvés : lead + variables (+ contexte si enrich)}
  3. verify (contrat) → load-lead (en review)
  4. record-run (déjà-vus, historique) + log
       ↓
     (après, hors run) revue humaine → launch
```

## 2. Engine — nouvelle commande `source` (vérifié doc 2026-06-15)

`POST /database/people` · body `{filters:[{filterId, in[], out[]}], page, size(1-100)}` → `results[]`
+ `total` + **`limitation`** (appels restants/24 h). Les `results` portent `lead_linkedin_url`,
`full_name`, `title`, `company_name`, etc.

| Élément | Détail |
|---|---|
| `lemlist.search_people(key, filters, page, size)` | wrapper brut |
| `sourcing.source(key, filters, seen, target, *, max_pages)` | pagine, **exclut les déjà-vus** (linkedinUrl), s'arrête à `target` candidats / quota bas / pages épuisées ; **projette** chaque résultat vers la forme lead (`linkedinUrl, fullName, jobTitle, companyName…`) |
| Sortie | `{candidats[], limitation, pages_used, exhausted}` |

Les **filtres** vivent dans `campaign.json` (config de sourcing = intelligence locale, pas structure
de campagne). Lecture du `limitation` = respect du quota natif (pas de throttle custom).

## 3. Le workflow (`workflows/sourcing.workflow.js`)

```js
export const meta = { name, description, phases: ["score","write","review"] }

// args = { candidats, prompts:{icpFit, messages:{...}}, sequence_keys }
const written = await pipeline(args.candidats,
  c  => agent(icpFitPrompt(c), { schema: VERDICT, model: "haiku", phase: "score" }),
  (v, c) => v.qualifie ? agent(writePrompt(c, args.prompts), { schema: MESSAGES, model: "sonnet", phase: "write" }) : null
)
const drafts = written.filter(Boolean)                       // calcul pur (script)
let verdicts = await batchReview(drafts)                     // 1 agent Sonnet / lot → verdicts structurés
const { approuves, aRejeter } = split(drafts, verdicts)      // calcul pur
const regen = await rewriteAndReview(aRejeter)               // 1 régénération + re-review
return { approuves: [...approuves, ...regen.passes] }
```

- **score** : `icpFit` Haiku, naïf (le candidat + le prompt interpolé), verdict `{qualifie, raison}`.
- **write** : Sonnet, séquence **complète en un fil** (chaque message reçoit les précédents pour tenir
  l'angle ouvert par l'icebreaker) ; sortie `{messages:{<clé>:texte}}` sur les clés requises (§ spec 2).
- **review (GATE 2)** : juge Sonnet **par batch**, rubrique booléenne (pas de fait inventé · angle
  cohérent · ≤ longueur · zéro formule interdite · vouvoiement) → verdict par lead. Rejeté → 1
  régénération → sinon écarté.
- Filet déterministe résiduel : `is_clean_message` (moteur) au load, dernier rempart.

### 3.1 Contrat args/return (interface routeur ↔ workflow) — livré

Le routeur source en déterministe (moteur `source`), puis invoque le workflow avec :

```jsonc
args = {
  "candidats": [ { "linkedinUrl", "fullName", "jobTitle", "companyName",
                   "location", "summary", "headline", "people_db_id" } ],
  "prompts": { "icpFit": "…template interpolable…",
               "messages": { "icebreaker": "…", "followup": "…", "closing": "…" } },
  "sequence_keys": ["icebreaker","followup","closing"],   // = engine verify.required_variables
  "models": { "scoring": "haiku", "writing": "sonnet", "judge": "sonnet" },   // défauts montrés
  "enrich": { "enabled": false, "directive": "…", "store": "variable:contexte", "model": "sonnet" },
  "review": { "max_words": 75 }, "review_batch_size": 8                        // optionnels
}
```

Rendu : `{ "approuves": [ { "lead", "variables": { <sequence_keys…>, "contexte?" } } ] }` —
exactement la forme consommée par `load-lead --input`. Après le workflow, le routeur enchaîne
(déterministe, moteur) : `verify` (contrat) → `load-lead` (review) → `record-run` (seen += tous
les sourcés, même les écartés au score) → `log`. Le launch reste manuel.

### 3.2 Frontière self-contained ↔ logique testée

Un `.workflow.js` exécuté par l'outil Workflow est **sandboxé** : pas de `require`/`import`, pas de
`Date.now()`/`Math.random()`. Le workflow doit donc être un seul fichier autonome. Pour garder une
logique **testée** : la source de vérité déterministe vit dans `workflows/lib/sourcing-core.js`
(helpers purs + `runSourcing(env)`, testés par `node --test`) ; `workflows/sourcing.workflow.js` est
**généré** depuis ce core par `workflows/lib/build-workflow.js` (self-contained), et un test garde
l'égalité octet-pour-octet (`tests/js/sourcing-workflow-sync.test.js`). On édite le core, on régénère.

## 3bis. Enrichissement — étape optionnelle, gardée par config

Certaines verticales ont besoin de **contexte que Lemlist ne donne pas** (ex. « cette personne est-elle
cliente de X ? ») pour personnaliser. C'est le **seul agent à outils** du run : il *étend son raisonnement
en autonomie* (recherche web), contrairement aux agents score/write (intelligence pure).

**Flag dans `campaign.json`** — décide si l'étape tourne :
```jsonc
"enrich": {
  "enabled": true,
  "directive": "Vérifie si la personne est cliente de X ; relève tout signal récent pertinent.",
  "store": "variable:contexte"      // où persister : variable de lead (défaut) ou champ contact UI
}
```
Absent ou `enabled:false` → l'étape est **sautée** (score → write direct).

**Flux** : l'agent `enrich` (outils web) tourne **après le score** (seuls les qualifiés sont enrichis —
on ne dépense pas de recherche sur les écartés), rend des **trouvailles structurées**. Elles servent
ensuite : (1) **en vol**, passées à l'agent `write` (le script les tient) ; (2) **persistées** par le
moteur au load, dans une **variable de lead** (`contexte`, auto-créée, hors contrat de séquence) ou un
champ contact si tu en as créé un en UI. Donc la fiche garde le contexte, réutilisable en run ultérieur.

Coût maîtrisé : recherche web par lead = cher → réservé aux verticales qui l'activent.

## 4. Modèles (délégués)

`score = Haiku` (parité prod, ne pas fausser le filtre) · `write = Sonnet` (le copy convertit) ·
`review = Sonnet` (juge). Épinglés en config, surcharge possible par verticale.

## 5. Orchestration (procédure routeur)

Pour la spec 3, la procédure `source → workflow → verify → load → commit → log` est **documentée** et
minimalement câblée ; le câblage fin (résolution slug, dry-run, enchaînement) est finalisé au **routeur**
(spec finale). Le workflow et `source` sont les livrables testés de la spec 3.

## 6. État & contrat (réutilise specs 1–2)

`verify` pré-load (contrat clés↔séquence) · `load-lead` idempotent (reçus) · `record-run`
(déjà-vus glissants, historique) · garde launch (après). Un candidat sourcé entre dans `seen` au
`record-run` même s'il est écarté au score (évite de le re-scorer — gratuit mais inutile).

## 7. Tests

- Engine `source` : pagination, exclusion des déjà-vus, arrêt à `target` / quota bas / épuisement,
  projection des résultats (mock `search_people`).
- `lemlist.search_people` : route `POST /database/people`, body filtres/pagination.
- Workflow : testé via ses parties déterministes (filtrage `drafts`, `split` approuvés/rejetés,
  interpolation des prompts) + un run mocké de `runSourcing` (agents `pipeline`/`parallel` injectés,
  schéma respecté). Les agents eux-mêmes ne sont pas unit-testés (LLM). Cf. `tests/js/sourcing-core.test.js`
  (helpers + run mocké) et `tests/js/sourcing-workflow-sync.test.js` (workflow généré == core).
  Lancement JS : `node --test 'tests/js/**/*.test.js'` (ou `npm run test:js`).

## 8. Hors-scope (specs suivantes)

La **validation du prompt icpFit** (graders : holdout, juge labels — spec 04), **W1** (création
interactive), le **routeur** (point d'entrée). W3 *exécute* le run ; il ne valide pas la qualité du
prompt ni ne crée la verticale.
