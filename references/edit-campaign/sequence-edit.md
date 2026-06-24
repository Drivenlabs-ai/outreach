# Modifier la séquence — flux détaillé (référence edit-campaign)

Chargé par `edit-campaign` pour éditer la séquence d'une campagne. Lemlist = source de vérité : on lit la
séquence live, on la mute par API, aucune représentation locale. Commandes moteur via
`uv run python scripts/routine.py <cmd>`. Les schémas exacts des bodies (par type d'étape, par champ de
schedule) se lisent sur la doc live via `/lemlist` — ne pas les deviner.

## Flux (l'ordre est la garde : valider avant d'écrire)

1. **resolve** la campagne → `campaign_id` + `config_path`.
2. **lire** la séquence : `sequence --config <config_path>` → étapes avec `sequence_id`, `step_id`, `type`,
   `delay`, `subject`, `message`. (Les commandes de mutation relisent l'état de la campagne pour le gate.)
3. **gate** : si la campagne tourne, les commandes de mutation s'arrêtent (STOP). Le dire à l'utilisateur :
   « mets la campagne en pause d'abord » (la pause est un geste séparé, hors edit-campaign).
4. **comprendre** l'intention en langage naturel → traduire en mutations concrètes (quelles étapes, quels
   champs).
5. **preview à deux faces + accord explicite** (mutation live = action sortante) :
   (a) les changements de séquence ; (b) les prompts locaux à créer / ajuster / signaler-orphelin.
   Avertir si des leads sont déjà en cours de séquence (effet non documenté).
6. **appliquer** (le body de chaque mutation est écrit dans un fichier, lu via `--input`) :
   - contenu / objet / délai → `update-step --config <config_path> --sequence-id <id> --step-id <id>
     --input <chemin>` (le body inclut toujours `type`, immuable — sinon l'API rejette en 400).
   - ajout → `add-step --config <config_path> --sequence-id <id> --input <chemin>` (body avec `type` +
     champs requis selon le type ; position via `index`).
   - retrait → `delete-step --config <config_path> --sequence-id <id> --step-id <id>`.
   - réordonnancement → l'`index` d'une étape existante n'est pas modifiable (le PATCH l'ignore en
     silence) : retirer l'étape (`delete-step`) puis la recréer à la position voulue (`add-step` avec
     `index`, honoré à la création).
   - timing fenêtres → le `schedule_id` (skd_…) se lit dans la sortie de `fetch` (champ `schedules`), puis
     `edit-schedule --config <config_path> --schedule-id <id> --input <chemin>`.
   - canal → `type` immuable : `delete-step` puis `add-step` (recreate), en re-posant `index`, `delay`,
     contenu. Le signaler explicitement dans le preview.
7. **synchroniser les prompts locaux** (premier rang) : pour chaque `{{var}}` custom du nouveau jeu, créer
   `prompts/<var>.md` si l'étape est nouvelle, ajuster si l'étape éditée change l'angle (craft `/lemlist`) ;
   une étape retirée peut laisser un prompt orphelin → le signaler.
8. **verify** : `verify --config <config_path>` → `aligned` (zéro `missing_prompts`). Sinon créer / ajuster
   le prompt manquant et re-verify.
9. **confirmer** : nouvelle séquence + couverture du contrat de variables OK.

## Gardes

- Jamais de mutation sur une campagne `running` (gate moteur dur).
- Jamais de mutation sans preview + accord explicite.
- `verify` reste read-only : il constate la couverture, il n'écrit pas vers Lemlist. L'alignement d'angle
  d'un prompt est une responsabilité de craft, pas garanti par verify.
- Mutation partielle (une étape passe, la suivante échoue) → s'arrêter, relire la séquence (`sequence`),
  rapporter l'état réel ; Lemlist porte la vérité.
