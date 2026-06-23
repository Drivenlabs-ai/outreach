# Modifier la config / l'état — flux détaillé (référence edit-campaign)

Chargé par `edit-campaign` pour piloter l'état/les réglages d'une campagne et l'op-config locale du run.
Commandes moteur via `uv run python scripts/routine.py <cmd>`. Les champs exacts de `update-campaign` se
lisent sur la doc live via `/lemlist` — ne pas les deviner.

## Quatre leviers, par nature

- **Pause / reprise** (Lemlist, sortant) : `campaign-pause --config <config_path>` /
  `campaign-resume --config <config_path>`. Preview (« je mets X en pause ») + confirmation. Reprendre
  remet la campagne en état d'envoi ; ça n'entre pas de nouveaux leads en séquence (le launch des leads en
  review reste un geste séparé, hors de cette skill).
- **Réglages campagne** (Lemlist, sortant) : écrire le body dans un fichier, puis
  `update-campaign --config <config_path> --input <chemin>`. Couvre stop-conditions (stop sur réponse /
  meeting / clic), senders (`sendUserIds`), tracking (open/click/reply), autoReview. Mutation sortante,
  non réannulable sans un second appel → preview en clair de ce qui change + confirmation. Champs exacts : `/lemlist`.
- **Op-config locale** (campaign.json, local) : éditer `sourcing_size` (cadence du run), `models`
  (scoring/writing/judge), `enrich`. Preview + confirmation, puis écrire `campaign.json`. Effet au
  prochain run.
- **Flip dry_run** (campaign.json, local, haut risque) : passer `dry_run` `true ↔ false`. Garde dure :
  confirmation explicite, dans les deux sens. `false` = la campagne charge réellement les leads au run ;
  `true` = re-arme la sécurité. Jamais flipé par le run.

## Gardes

- Toute mutation Lemlist = action sortante → preview + confirmation explicite, jamais silencieux.
- Pas de gate « doit être en pause » (pauser/régler/op-config sont sûrs, sans l'effet non documenté de
  l'édition de séquence).
- `update-campaign` sur une campagne à stratégie de sender dynamique rejette `sendUserIds` → le signaler.
- Les commandes de mutation sortent en code non-zéro sur erreur API → s'arrêter, relire l'état, rapporter.
