# Run quotidien — séquence détaillée (référence driven-outreach)

Chargé par le routeur pour le run. Le run charge des leads en review ; il ne lance jamais (le launch est
une étape séparée, plus bas). Pré-requis : campagne résolue (`resolve` a donné `campaign_id` +
`config_path`) ; date du jour pour l'historique. Commandes via `uv run python scripts/routine.py <cmd>`.

## Séquence (ordre fixe)

Deux données circulent en mémoire entre les étapes (pas via `--config`) : les `prompts` de `prepare` et
les `sequence_keys` de `verify`. Tout le reste se relit depuis `<config_path>`. Les flags `--input`,
`--sourced-file`, `--entry-file` attendent un **chemin de fichier** que tu écris d'abord (le moteur les
lit sur disque), pas une valeur inline.

1. **prepare** — `prepare --config <config_path> --date <date>` → `{config, prompts, dry_run}`.
   Pré-vol auth (`GET /team`) : STOP si KO ; prompt manquant ou vide : STOP. `prompts` = dict plat
   `{icpFit, <step>:…}`, à porter jusqu'à l'étape 4.
2. **source** — `source --config <config_path>` → `{candidats, limitation, next_cursor, exhausted}`.
   `candidats` = leads de la page courante du pool People DB (le curseur de page avance et se persiste
   automatiquement ; les leads déjà en campagne sont exclus par filtre natif `out`). Écris ce tableau
   `candidats` dans un fichier : il resservira au `record-run` (§6) pour le décompte. S'arrêter si
   `limitation` (quota People DB) est bas ou `exhausted` (fin de pool → élargir les filtres).
3. **verify** — `verify --config <config_path>` → `{aligned, sequence_variables, …}`. `aligned` doit être
   vrai (sinon corriger les prompts : un lead sans ses variables ne se lancera pas). `sequence_keys` =
   les variables de message de la séquence = `sequence_variables` hors champs natifs (firstName,
   companyName, jobTitle…) ; `aligned` garantit qu'un prompt existe pour chacune.
4. **workflow sourcing** — invoquer le workflow `sourcing` avec
   `args = { candidats, prompts: <ceux de prepare>, sequence_keys: <de l'étape 3>, models: <config.models>,
   enrich: <config.enrich> }` → `{ approuves: [{lead, variables}] }`.
5. **load** — pour chaque approuvé : écris son `{lead, variables}` dans un fichier, puis `load-lead
   --config <config_path> --input <chemin> --confirm`. Charge en review, idempotent (reçus). `--confirm`
   est toujours passé ; c'est `dry_run` qui garde (ci-dessous).
6. **record-run** — `record-run --config <config_path> --date <date> --sourced-file <chemin du fichier
   candidats de l'étape 2> --true <nb chargés> --false <nb écartés>` → append historique + horodatage
   (le décompte sourcé vient du fichier). Le non-re-score est assuré par le curseur de page (§2), pas par
   record-run.
7. **log** — écris le résumé du run dans un fichier, puis `log --config <config_path> --entry-file <chemin>`.

## dry_run

`config.dry_run: true` → `load-lead` renvoie le plan et n'écrit rien, même avec `--confirm` : c'est la
garde. Le run passe toujours `--confirm` (son rôle est de charger en review) ; sur une campagne encore en
`dry_run: true`, rien n'est écrit. Charger réellement = campagne en `dry_run: false`. Ne jamais flip
`dry_run` dans le run — c'est le geste final de `new-campaign`, sur confirmation humaine.

## Launch — étape séparée et gardée

Le run s'arrête à « en review ». **Lancer (entrer dans la séquence d'envoi) est un geste explicite, jamais
automatique** : après revue humaine dans Lemlist, `launch --config <config_path> --input <lead_ids>
--confirm`. La garde native de Launch Lead refuse tout lead dont une variable requise est vide.

## Erreurs

- auth / config / prompt KO au `prepare` → STOP (le run ne démarre pas).
- une étape `load-lead` échoue pour un lead → ce lead reprend au prochain run (reçu) ; le lot continue.
