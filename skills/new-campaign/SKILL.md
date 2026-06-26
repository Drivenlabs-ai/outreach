---
name: new-campaign
description: Déclencher quand l'utilisateur veut monter, créer ou lancer une campagne de prospection outbound pour une nouvelle verticale ou un segment ("crée une campagne pour les agences immo", "nouvelle verticale X", "monte une prospection pour Y", "setup outbound pour Z", "on attaque le marché des cabinets dentaires"), ou démarrer une campagne Lemlist multicanale de zéro. Ne pas déclencher pour faire tourner le sourcing quotidien d'une campagne existante (run/W3) ni pour modifier une campagne déjà créée.
---

# new-campaign (W1) — créer une campagne pour une verticale

## Vue d'ensemble

Crée une verticale de prospection de bout en bout : valide l'ICP et l'angle avec l'utilisateur
(interactif), puis matérialise la campagne en autonomie (fichiers d'intelligence → validation du prompt
`icpFit` → campagne Lemlist → smoke test → prêt).

Principe : toi (Claude de session) tu orchestres des briques déjà construites et testées — tu n'écris pas
de code. Le moteur (`scripts/routine.py`) fait l'I/O Lemlist et l'état ; les workflows `icp-check` et
`sourcing` portent le jugement IA ; `/lemlist` porte la craft (ICP, séquence, copy). Ton rôle : la
conversation d'alignement, la rédaction des fichiers d'intelligence, l'enchaînement des commandes.

Frontière : la phase 1 est interactive (l'ICP/angle exige le jugement de l'utilisateur) ; la phase 2 est
autonome mais s'arrête à deux gardes — avant toute mutation Lemlist et avant le flip `dry_run`.

**Commandes moteur** : toujours via `uv run python scripts/routine.py <cmd>` (jamais `python3` direct) ;
les étapes ci-dessous notent le `<cmd>` seul.

## Quand l'utiliser

- L'utilisateur veut **créer / monter / lancer** une campagne pour une nouvelle verticale ou un segment.
- Pas pour : faire tourner le sourcing quotidien d'une campagne existante (→ run/W3), ni pour modifier
  une campagne déjà créée (→ edits ciblés).

## Le flux

```
Phase 1 (interactif) : recherche + Q&R → valide ICP + angle → gate humain
Phase 2 (autonome)   : fichiers d'intelligence → icp-check → W2 → smoke → flip dry_run
                       ↑ s'arrête avant la 1re mutation Lemlist et avant le flip
```

## Phase 1 — Alignement ICP + angle (interactif)

L'ICP et l'angle sont le choix à fort levier : s'ils sont faux, tout le reste part de travers. Ils
exigent le jugement de l'utilisateur — ne les devine pas.

1. **Positioning transversal** : si `Prospection/icp-global.md` existe, lis-le (la verticale en hérite) ;
   retiens sa version pour `icp_global_version`.
2. **Recherche** la verticale (web + craft `/lemlist` §1–2) : marché, déclencheurs (triggers), pains,
   qui décide.
3. Q&R structurée — chaque arbitrage passe par AskUserQuestion (options pré-rédigées + reco). Converge
   jusqu'à verrouiller :
   - **ICP** — segment précis, basé trigger/pain (pas une liste de critères mous). `/lemlist` §1.
   - **Persona** — le rôle ciblé (pas un département) + la séniorité (calibre la copy). `/lemlist` §2.
   - **Angle** — la thèse du message, le fil que l'icebreaker ouvre.
   - **Filtres People DB** — traduction de l'ICP en filtres de recherche (`filterId` / `in` / `out`).
     `/lemlist` §3.
4. Gate humain — ne quitte pas la phase 1 tant que l'utilisateur n'a pas validé l'ICP + l'angle.
5. **Acte** — crée le dossier d'état + le `campaign.json` draft (cf. Référence), puis marque l'étape :
   `status --config <campaign.json> --set phase1_done=true`.

## Phase 2 — Matérialisation (autonome, gardée)

Tu pilotes ; tu peux faire des checkpoints avec l'utilisateur. Deux gardes : avant la 1re mutation
Lemlist (§3) et avant le flip `dry_run` (§5).

### 1. Écrire les fichiers d'intelligence

Dans le dossier verticale (`Prospection/<Vertical>/`), guidé par la craft `/lemlist` + les sorties de
la phase 1, rédige :
- `icp.md` · `persona.md` · `pain-points.md` · `value-proposition.md` · `triggers.md`
- `prompts/icpFit.md` (qualification) + un `prompts/<step>.md` par message de la séquence — les noms de
  fichiers = clés de variables de la séquence (cf. Référence, contrat de variables). À ce stade la
  campagne n'existe pas encore : reprends les clés connues du template par défaut
  (`icebreaker` / `followup` / `closing`) ; `verify` (§3) réconcilie avec la séquence réelle.
- `campaign.json` draft (forme en Référence ; `dry_run: true`, ids `null`).

Garde : ne pas écraser un fichier d'intelligence existant sans confirmation. (Le hook `PostToolUse` lance
`verify` à chaque écriture de fichier campagne — la dérive prompts ↔ séquence remonte aussitôt.)

### 2. Caler le ciblage (rendement des filtres + alignement icpFit)

Cale les deux étages du ciblage avant d'aller plus loin : les **filtres** (rendement — assez de décideurs
sourcés) et le **prompt icpFit** (le tri fin). La boucle tourne en coulisses ; ne fais émerger qu'un
arbitrage métier réel. Méthode complète + doctrine UX : `references/calibration.md` — la charger avant d'agir.

En bref :
1. `source --config <campaign.json> --sample --target 20` → échantillon + `total`, sans toucher le curseur.
2. Workflow **icp-check** (`args = { prompt_icpFit, sample, model: "haiku" }`) → `verdicts` ; rendement =
   qualifiés / échantillon.
3. Rendement bas → recale les filtres (séniorité + taille, **jamais le titre**) ; ratés de jugement → édite
   `prompts/icpFit.md`. Ré-échantillonne. Boucle bornée, jugée d'après l'ICP.
4. Tranche seul ; ne remonte que portée↔précision (fondu dans le gate de la phase 1) ou une audience trop
   petite. Clos par un récap en clair (filtres retenus = le filet large ; le vrai tri, c'est l'IA).

### 3. W2 — créer la campagne Lemlist

**Garde : demande le go de l'utilisateur avant la 1re mutation Lemlist** — les étapes ci-dessous créent
une vraie campagne + liste.

Reprise : aucune commande moteur n'écrit `w2_steps`, c'est toi qui le tiens — c'est le seul garde-fou
contre une re-duplication au re-run. Avant d'agir, lis-le (`status --config <campaign.json> --get
w2_steps`) et saute toute étape déjà inscrite. Après chaque étape, ré-inscris la liste cumulée complète
(`--set` remplace, il n'ajoute pas), entre guillemets pour qu'elle atteigne le shell intacte.

1. `"campaign"` absent de `w2_steps` : `duplicate-campaign --template-id <DEFAULT_FLOW_TEMPLATE_ID> --name
   <verticale>` → relève `campaign_id` + `sequence_id` (stdout) → `status --config <campaign.json> --set
   'w2_steps=["campaign"]'`. `DEFAULT_FLOW_TEMPLATE_ID` vient de la Référence ; si tu ne l'as pas,
   demande-le à l'utilisateur (ne l'invente jamais).
2. `"list"` absent : `create-list --name <verticale>` → relève `list_id` → `status --config
   <campaign.json> --set 'w2_steps=["campaign","list"]'`.
3. `verify --campaign-id <campaign_id de l'étape 1> --prompts-dir <Prospection/<Vertical>/prompts>` → doit
   être `aligned` (zéro `missing_prompts`) ; sinon corrige les prompts et re-verify. (On passe
   `--campaign-id` parce que le `campaign.json` n'a pas encore les ids à ce stade.)
4. `"register"` absent : assemble le contenu final de `campaign.json` (le draft + `campaign_id` et
   `list_id` des étapes 1–2) dans un fichier, et l'entrée registre (forme en Référence) dans un autre.
   Puis `register-campaign --registry <racine Prospection/campaigns-registry.json — cf. Référence>
   --campaign-json <campaign.json de la verticale> --data-file <fichier-campaign-final> --entry-file
   <fichier-entrée>` → `status --config <campaign.json> --set 'w2_steps=["campaign","list","register"]'`.
   Cette commande recopie `--data-file` dans `--campaign-json` : l'overwrite du `campaign.json` est ici la
   promotion draft→final légitime, hors de la garde anti-écrasement (qui vise les fichiers d'intelligence).

### 4. Smoke test — 1 lead en review

1. `source --config <campaign.json> --target 1` → 1 candidat.
2. Lance le workflow **sourcing** sur ce candidat → `{ lead, variables }`.
3. Écris ce `{lead, variables}` dans un fichier, puis `load-lead --config <campaign.json> --input <chemin>
   --confirm` (`--input` est un chemin de fichier, lu sur disque) → charge le lead **en review** (jamais lancé).
4. L'utilisateur revoit le lead dans Lemlist (identité + messages générés).

### 5. Passer en prêt (flip dry_run)

**Garde dure : ne flip `dry_run` à `false` que sur confirmation explicite de l'utilisateur.** Une fois
confirmé, mets `dry_run: false` dans `campaign.json`. La campagne est prête — le run quotidien (W3) peut
tourner ; le launch reste un geste séparé et gardé, hors de W1.

## Robustesse & reprise

- Reprise : `status` porte `phase1_done` (Phase 1 §5) et `w2_steps[]` (§3) ; lus avant chaque phase, ils
  font sauter ce qui est déjà fait.
- Garde anti-écrasement des fichiers d'intelligence : §1. Pas de launch dans W1 : §5.

## Référence

Détail du scaffold de verticale (arbre des fichiers, forme de `campaign.json`, id du template de flux
par défaut, contrat de variables) : `references/new-campaign/vertical-scaffold.md`.
Calibration du ciblage (rendement des filtres + tri icpFit, doctrine UX) : `references/calibration.md`.
