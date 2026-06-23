# Modifier une campagne — SP-C : config / état

**Date** : 2026-06-23 · **Statut** : design validé, à planifier (writing-plans).
**Périmètre** : SP-C, troisième tranche de v1.5 « modifier une campagne ». Config et état d'une campagne :
pause/reprise, réglages campagne (Lemlist), op-config locale, flip `dry_run`. Troisième facette de la skill
`edit-campaign` + wrappers moteur. Un seul spec.

## Contexte / problème

SP-A (ciblage) et SP-B (séquence) sont livrés et mergés sur main. SP-C ouvre le dernier levier d'édition
avant le test en conditions réelles : **config / état**. C'est un mélange de **mutations Lemlist** (état
de la campagne + réglages) et d'**éditions locales** (op-config du run, garde `dry_run`).

**Principe directeur (constant sur toute v1.5, validé Alex)** : la surface humaine est une conversation en
langage naturel ; Claude (session) porte toute la complexité ; l'utilisateur ne voit jamais un
identifiant, un champ d'API ni un objet JSON. Il dit « mets la campagne X en pause », « arrête d'envoyer
dès qu'on répond », « passe le sourcing à 30 par jour », « active-la pour de vrai » — Claude traduit,
prévisualise, et n'écrit qu'après accord.

## Périmètre — quatre leviers

```
Pause / reprise    → Lemlist (pause-campaign / start-campaign)        SORTANT
Réglages campagne  → Lemlist PATCH /campaigns (stop-conditions,       SORTANT
                      senders, tracking, autoReview)
Op-config locale   → campaign.json (sourcing_size, models, enrich)    LOCAL
Flip dry_run       → campaign.json (true ↔ false)                     LOCAL, haut risque
```

## Faits API / moteur vérifiés

API Lemlist v2 (doc live 2026-06-22 ; méthode/chemin exacts de pause/start à reconfirmer au plan via
`/lemlist`, golden rule) :

- **Pause / reprise** : `campaigns/pause-campaign` et `campaigns/start-campaign` (existence confirmée par
  la map de ressources). `start-campaign` est aussi la mécanique du launch — ici on l'emploie au niveau
  campagne (reprise), pas pour entrer des leads en séquence (le launch reste hors v1.5).
- **`PATCH /campaigns/{id}`** — champs mutables (vérifiés) : `name`, `stopOnEmailReplied`,
  `stopOnMeetingBooked`, `stopOnLinkClicked` (+`stopOnLinkClickedFilter`), `leadsPausedByInterest`,
  `opportunityReplied`, `opportunityClicked`, `autoLeadInterest`, `disableTrackOpen`, `disableTrackClick`,
  `disableTrackReply`, `disableOutOfOffice`, `sequenceSharing`, `sendUserIds` (assigne les senders ;
  rejeté sur une campagne à stratégie de sender dynamique), `autoReview`, `autoReviewConditions`.
- **`get_campaign`** porte `status` (`running`/`paused`/`draft`/…) — déjà utilisé par le gate SP-B.

Moteur (`scripts/prospect_engine/`) :

- `lemlist.api_call(method, route, key, body=None)` → primitive réseau unique ; wrappers one-liners
  (modèle C). `get_campaign` existant.
- `campaign.json` porte `sourcing_size`, `models {scoring, writing, judge}`, `enrich {enabled, …}`,
  `dry_run` (cf. `references/new-campaign/vertical-scaffold.md`). SP-A édite déjà `campaign.json`
  directement (filtres) — même mécanisme pour l'op-config et `dry_run`.
- **Garde `dry_run` existante** : `new-campaign` §5 ne flip `dry_run` à `false` que sur confirmation
  explicite ; `run.md` interdit au run de flip `dry_run`. SP-C ne change pas ces deux règles.
- **Absent** : tout wrapper pause/start/update de campagne.

## Design

Approche : **moteur fin + orchestration NL + 3ᵉ facette d'edit-campaign** (identique SP-A/SP-B). **Pas de
fork d'architecture** : Lemlist reste source de vérité pour l'état et les réglages de campagne ;
l'op-config et `dry_run` vivent en local dans `campaign.json` (comme les filtres SP-A). `verify` n'est pas
concerné (aucune séquence touchée) ; le run et le sourcing sont inchangés.

### Nature et garde par levier

- **Pause / reprise** (Lemlist) : action sortante → **preview + confirmation explicite**, jamais
  silencieux. **Pas de gate « doit être en pause »** (contrairement à SP-B) : pauser/reprendre est sûr,
  sans l'effet non documenté de l'édition de séquence. Reprendre une campagne ne lance pas de nouveaux
  leads par soi-même — c'est le launch (hors v1.5) qui entre des leads en séquence.
- **Réglages campagne** (Lemlist `PATCH /campaigns`) : mutations non destructives mais sortantes →
  preview + confirmation. Assigner un sender (`sendUserIds`) est un réglage couvert ici ; le **launch**
  reste un geste séparé hors v1.5.
- **Op-config locale** (`campaign.json` : `sourcing_size`, `models`, `enrich`) : 100% local → écrit après
  confirmation (pas de garde dure ; c'est de la cadence / des modèles). Effet au prochain run.
- **Flip `dry_run`** (`campaign.json`) : **garde dure** — confirmation explicite, dans **les deux sens**
  (`false` = la campagne charge réellement les leads au run ; `true` = re-arme la sécurité). SP-C est le
  home canonique du flip ; `new-campaign` garde son flip final de création, sous la même garde.

### Flux (orchestré par Claude)

```
1. resolve la campagne → campaign_id + config_path
2. comprendre l'intention NL → quel(s) levier(s), quelle valeur
3. selon la nature :
   - Lemlist (pause/reprise/réglages) : preview du changement + confirmation → muter par le moteur
   - op-config locale : preview + confirmation → écrire campaign.json
   - flip dry_run : preview de l'effet (false = chargement réel au run) + CONFIRMATION DURE → écrire campaign.json
4. confirmer : ancien → nouvel état/réglage/config
```

### Moteur — ajouts (déterministes, modèle C)

- `lemlist` : `pause_campaign(key, campaign_id)`, `start_campaign(key, campaign_id)`,
  `update_campaign(key, campaign_id, body)` (PATCH pass-through ; aucun schéma de body hardcodé — `/lemlist`).
- Commandes CLI : `campaign-pause`, `campaign-resume`, `update-campaign` (body lu depuis `--input`).
  **Elles sortent en code non-zéro sur erreur API** (status hors 2xx) — cf. Durcissement.
- Op-config locale + flip `dry_run` : **pas de code moteur** — édition de `campaign.json` par Claude
  (comme les filtres SP-A) ; la garde `dry_run` est portée par l'orchestration (skill).

### Où ça vit

Troisième facette de `edit-campaign` : section « Modifier la config / l'état » (lean) renvoyant au flux
détaillé en `references/edit-campaign/config-state.md`. Le routeur `prospect-routine` bascule la ligne
config/état de « pas encore couvert » à « couvert par edit-campaign ». Après SP-C, seul **SP-D**
(dupliquer une verticale) reste au backlog.

Le `SKILL.md` d'edit-campaign aura trois facettes (ciblage / séquence / config-état) : garder le corps
lean, le détail en références (progressive disclosure).

## Durcissement SP-B (intégré à SP-C)

La revue de code de SP-B a remonté trois défauts réels (sur main) et deux imprécisions de spec. Comme SP-C
étend les mêmes fichiers et patterns, le durcissement est intégré ici plutôt qu'en hotfix séparé (décision
Alex ; `edit-campaign` n'a pas encore tourné en conditions réelles).

- **Lecture fail-closed** : `cmd_sequence` jette le status de `get_campaign_sequences` → sur non-200, il
  émet `{"steps": []}` (exit 0), indistinguable d'une séquence vide. Corriger : sur status hors 2xx, STOP
  (erreur explicite), comme `cmd_prepare`. Une lecture qui gate les mutations doit échouer **fermé**.
- **Exit non-zéro sur erreur de mutation** : `add_step`/`update_step`/`delete_step`/`update_schedule` (SP-B)
  **et** les nouvelles commandes SP-C (`campaign-pause`/`campaign-resume`/`update-campaign`) émettent leur
  JSON puis sortent en non-zéro si status hors 2xx — la règle « stop on partial failure » devient imposée
  par le moteur, pas seulement documentée.
- **Gate en allowlist** : `sequence.ensure_editable` ne bloque aujourd'hui que `status is None`. Un `""`
  ou un label inconnu passe comme éditable. Inverser : éditable **uniquement** si `status` est dans
  l'ensemble sûr connu (`paused`, `draft`, `ended`, `archived`, `errors`) ; sinon STOP (running, inconnu,
  vide). Le gate ne mute jamais à l'aveugle.
- **Specs SP-B nettoyés** (clean-slate) : retirer la sur-affirmation « impossible à contourner par
  l'orchestration » (vraie pour `delete` que Lemlist bloque côté serveur si running, pas pour `add`/`update`
  — TOCTOU inhérent, mitigé par la pause humaine) ; retirer `associate_schedule` de la liste moteur/tests
  du spec SP-B (jamais implémenté, YAGNI — la réalité fait foi).

## Migration

Aucune migration d'état. Ajouts additifs (3 wrappers + commandes + section de skill + référence) + le
durcissement (corrections sur fichiers SP-B existants, sans changement de contrat public). Le routeur et le
README passent config/état de backlog à couvert.

## Erreurs / bornes

- `sendUserIds` sur une campagne à stratégie de sender dynamique → rejet API : le signaler, ne pas
  réessayer à l'aveugle.
- Pause d'une campagne déjà en pause / reprise d'une déjà active → relire l'état (`get_campaign`) et
  rapporter l'état réel ; ne pas présumer.
- Flip `dry_run` dans les deux sens, toujours sous confirmation dure ; jamais par le run.
- Mutation Lemlist en échec → rapporter le code, ne pas présumer le résultat.

## Tests

Partie déterministe testée ; l'orchestration (NL → réglages, édition locale, garde dry_run) vit dans la
skill, non testée unitairement (comme SP-A/SP-B/W1).

- Wrappers `pause_campaign` / `start_campaign` / `update_campaign` : route, méthode, body corrects (API
  mockée).
- Commandes CLI : dispatch + body depuis `--input` (mocké) ; **exit non-zéro quand le status est hors 2xx**.
- Durcissement : `cmd_sequence` STOP (SystemExit) sur lecture non-200 ; `ensure_editable` bloque `""` et un
  label inconnu, bloque `running`/`None`, autorise `paused`/`draft` (allowlist).
- Suites vertes (Python + JS ; JS inchangé).

## Hors périmètre

- **Launch** (entrer des leads dans la séquence d'envoi) → geste séparé et gardé, hors v1.5 (décision
  Alex). SP-C peut assigner un sender (`sendUserIds`) mais ne lance pas.
- **Dupliquer une verticale** vers un nouveau segment → SP-D.
- Refonte du run / du sourcing / de la séquence (SP-B) / du ciblage (SP-A).

## Critères de succès

- L'utilisateur pilote la config/l'état en langage naturel, sans voir un identifiant, un champ d'API ni
  un JSON.
- Mutations Lemlist (pause/reprise/réglages) : preview + confirmation, jamais silencieux ; pas de gate
  « doit être en pause ».
- Flip `dry_run` : confirmation dure dans les deux sens ; jamais par le run.
- Lemlist reste source de vérité pour l'état/les réglages ; l'op-config vit en local ; `verify` intact ;
  run inchangé.
- Suites vertes (Python + JS).
