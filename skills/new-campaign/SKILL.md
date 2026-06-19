---
name: new-campaign
description: Crée une nouvelle campagne de prospection outbound pour une verticale dans le plugin prospect-routine. Déclencher quand l'utilisateur veut monter, créer ou lancer une campagne pour un segment ("crée une campagne pour les agences immo", "nouvelle verticale X", "monte une prospection pour Y", "setup outbound pour Z", "on attaque le marché des cabinets dentaires"), ou démarrer une campagne Lemlist multicanale de zéro. Ne pas déclencher pour faire tourner (sourcing quotidien) ou modifier une campagne existante.
---

# new-campaign (W1) — créer une campagne pour une verticale

## Vue d'ensemble

Crée une verticale de prospection de bout en bout : **valide l'ICP et l'angle avec l'utilisateur
(interactif), puis matérialise la campagne en autonomie** (fichiers d'intelligence → validation du
prompt `icpFit` → campagne Lemlist → smoke test → prêt).

**Principe** : toi (Claude de session) tu **orchestres des briques déjà construites et testées** — tu
n'écris pas de code. Le moteur (`scripts/routine.py`) fait l'I/O Lemlist et l'état ; les workflows
`icp-check` et `sourcing` portent le jugement IA ; `/lemlist` porte la craft (ICP, séquence, copy). Ton
rôle : la conversation d'alignement, la rédaction des fichiers d'intelligence, et l'enchaînement des
commandes.

**Frontière dure** : la phase 1 est **interactive** (l'ICP/angle exige le jugement de l'utilisateur) ;
la phase 2 est **autonome** mais s'arrête à deux gardes — avant toute **mutation Lemlist** et avant le
**flip `dry_run`**.

## Quand l'utiliser

- L'utilisateur veut **créer / monter / lancer** une campagne pour une nouvelle verticale ou un segment.
- Pas pour : faire tourner le sourcing quotidien d'une campagne existante (→ run/W3), ni pour modifier
  une campagne déjà créée (→ edits ciblés).

## Le flux

```
Phase 1 (interactif) : recherche + Q&R → valide ICP + angle → GATE humain
Phase 2 (autonome)   : fichiers d'intelligence → icp-check → W2 → smoke → flip dry_run
                       ↑ s'arrête avant la 1re mutation Lemlist ET avant le flip
```

## Phase 1 — Alignement ICP + angle (interactif)

L'ICP et l'angle sont **le choix à fort levier** : s'ils sont faux, tout le reste part de travers. Ils
exigent le jugement de l'utilisateur — ne les devine pas.

1. **Positioning transversal** : si `Prospection/icp-global.md` existe, lis-le (la verticale en hérite) ;
   retiens sa version pour `icp_global_version`.
2. **Recherche** la verticale (web + craft `/lemlist` §1–2) : marché, déclencheurs (triggers), pains,
   qui décide.
3. **Q&R structurée** — chaque arbitrage passe par **AskUserQuestion** (options pré-rédigées + reco).
   Converge jusqu'à verrouiller :
   - **ICP** — segment précis, basé trigger/pain (pas une liste de critères mous). `/lemlist` §1.
   - **Persona** — le rôle ciblé (pas un département) + la séniorité (calibre la copy). `/lemlist` §2.
   - **Angle** — la thèse du message, le fil que l'icebreaker ouvre.
   - **Filtres People DB** — traduction de l'ICP en filtres de recherche (`filterId` / `in` / `out`).
     `/lemlist` §3.
4. **GATE humain** — ne quitte pas la phase 1 tant que l'utilisateur n'a pas **validé explicitement
   l'ICP + l'angle**.
5. **Acte** — crée le dossier d'état + le `campaign.json` draft (cf. Référence), puis marque l'étape :
   `python3 scripts/routine.py status --config <campaign.json> --set phase1_done=true`.

## Phase 2 — Matérialisation (autonome, gardée)

Tu pilotes ; tu peux faire des checkpoints avec l'utilisateur. Deux gardes dures : **§3 (avant la 1re
mutation Lemlist)** et **§5 (avant le flip `dry_run`)**.

### 1. Écrire les fichiers d'intelligence

Dans le dossier verticale (`Prospection/<Vertical>/`), guidé par la craft `/lemlist` + les sorties de
la phase 1, rédige :
- `icp.md` · `persona.md` · `pain-points.md` · `value-proposition.md` · `triggers.md`
- `prompts/icpFit.md` (qualification) + un `prompts/<step>.md` par message de la séquence — les **noms de
  fichiers = clés de variables** de la séquence (cf. Référence, contrat de variables).
- `campaign.json` draft (forme en Référence ; `dry_run: true`, ids `null`).

**Garde** : ne JAMAIS écraser un fichier existant sans confirmation. (Le hook `PostToolUse` lance `verify`
à chaque écriture de fichier campagne — la dérive prompts ↔ séquence remonte immédiatement.)

### 2. icp-check — aligner le prompt icpFit

Boucle jusqu'à ce que le jugement Haiku colle à l'intention :
1. `python3 scripts/routine.py source --config <campaign.json> --target 15` → échantillon.
2. Lance le workflow **icp-check** : `args = { prompt_icpFit: <contenu de prompts/icpFit.md>, sample:
   <candidats>, model: "haiku" }`.
3. Lis les `verdicts`, compare chacun à l'ICP visé, repère les ratés → **édite `prompts/icpFit.md`** →
   relance. Boucle jugée à la main, bornée (pas de seuil automatique, pas de boucle infinie).
4. **Sign-off** : l'utilisateur valide l'alignement avant de continuer.

### 3. W2 — créer la campagne Lemlist

**GARDE : demande le go de l'utilisateur avant la 1re mutation Lemlist** (les étapes ci-dessous créent une
vraie campagne + liste). Procédure idempotente (cf. spec 02), trace dans `status.w2_steps[]` :
1. `duplicate-campaign --template-id <DEFAULT_FLOW_TEMPLATE_ID> --name <verticale>` → `campaign_id`
   (+ `sequence_id`).
2. `create-list --name <verticale>` → `list_id`.
3. `verify --config <campaign.json>` → doit être `aligned` (zéro `missing_prompts`) ; sinon corrige les
   prompts et re-verify.
4. `register-campaign --registry <campaigns-registry.json> --campaign-json <campaign.json> --data-file
   <ids> --entry-file <entry>` → écrit le `campaign.json` final (ids remplis) + l'entrée registre.

`DEFAULT_FLOW_TEMPLATE_ID` : cf. Référence.

### 4. Smoke test — 1 lead en review

1. `source --config <campaign.json> --target 1` → 1 candidat.
2. Lance le workflow **sourcing** sur ce candidat → `{ lead, variables }`.
3. `load-lead --config <campaign.json> --input <{lead,variables}> --confirm` → charge le lead **en
   review** (jamais lancé).
4. L'utilisateur revoit le lead dans Lemlist (identité + messages générés).

### 5. Passer en prêt (flip dry_run)

**GARDE DURE : ne flip `dry_run` à `false` que sur confirmation explicite de l'utilisateur.** Une fois
confirmé, mets `dry_run: false` dans `campaign.json`. La campagne est prête — le run quotidien (W3) peut
tourner, et le **launch reste un geste séparé et gardé** (jamais en W1).

## Robustesse & reprise

- **Reprise** : `status` porte `phase1_done` et `w2_steps[]`. Au re-run, saute ce qui est fait — ne
  re-duplique jamais la campagne.
- **Idempotence W2** : chaque étape franchie est inscrite ; check-exists avant create (spec 02).
- **Jamais** d'overwrite de fichier local sans confirmation. **Jamais** de launch en W1.

## Référence

Détail du scaffold de verticale (arbre des fichiers, forme de `campaign.json`, id du template de flux
par défaut, contrat de variables) : `references/new-campaign/vertical-scaffold.md`.
