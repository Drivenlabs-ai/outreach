# Run quotidien — séquence détaillée (référence prospect-routine)

Chargé par le routeur pour le run. Le run charge des leads en review ; il ne lance jamais (le launch est
une étape séparée, plus bas). Pré-requis : campagne résolue (`resolve` a donné `campaign_id` +
`config_path`) ; date du jour pour l'historique. Commandes via `uv run python scripts/routine.py <cmd>`.

## Séquence (ordre fixe)

1. **prepare** — `prepare --config <config_path> --date <date>` → `{config, seenIds, prompts, dry_run}`.
   Pré-vol auth (`GET /team`) : STOP si KO ; prompt manquant ou vide : STOP. `prompts` est un dict plat
   `{icpFit, <step>:…}`.
2. **source** — `source --config <config_path>` → `{candidats, limitation, exhausted}`. `candidats` =
   leads inédits (déjà-vus exclus) projetés en forme lead ; `limitation` = quota People DB restant,
   s'arrêter s'il est bas.
3. **verify** — `verify --config <config_path>` → `{aligned, prompt_keys, …}`. `aligned` doit être vrai
   (sinon corriger les prompts : un lead sans ses variables ne se lancera pas). `prompt_keys` = les clés
   de message = `sequence_keys` pour le workflow.
4. **workflow sourcing** — invoquer le workflow `sourcing` avec
   `args = { candidats, prompts: <prompts de prepare>, sequence_keys: <prompt_keys de verify>,
   models: <config.models>, enrich: <config.enrich> }` → `{ approuves: [{lead, variables}] }`.
5. **load** — pour chaque approuvé : `load-lead --config <config_path> --input <{lead,variables}>`
   (ajouter `--confirm` seulement si `config.dry_run` est `false`). Charge en review, idempotent (reçus).
6. **record-run** — `record-run --config <config_path> --date <date> --sourced-file <tous les candidats
   sourcés> --true <nb chargés> --false <nb écartés>` → déjà-vus glissants + historique. Tous les
   candidats sourcés entrent dans les déjà-vus, même écartés au score (évite de les re-scorer).
7. **log** — `log --config <config_path> --entry-file <résumé du run>`.

## dry_run

`config.dry_run: true`, ou `load-lead` sans `--confirm` → renvoie le plan, zéro écriture réseau. Charger
réellement exige `dry_run: false` ET `--confirm`. Ne jamais flip `dry_run` dans le run — c'est le geste
final de `new-campaign`, sur confirmation humaine.

## Launch — étape séparée et gardée

Le run s'arrête à « en review ». **Lancer (entrer dans la séquence d'envoi) est un geste explicite, jamais
automatique** : après revue humaine dans Lemlist, `launch --config <config_path> --input <lead_ids>
--confirm`. La garde native de Launch Lead refuse tout lead dont une variable requise est vide.

## Erreurs

- auth / config / prompt KO au `prepare` → STOP (le run ne démarre pas).
- une étape `load-lead` échoue pour un lead → ce lead reprend au prochain run (reçu) ; le lot continue.
