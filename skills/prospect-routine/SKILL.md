---
name: prospect-routine
description: Déclencher quand l'utilisateur veut faire tourner la prospection outbound — lancer le run / sourcing quotidien d'une campagne existante ("run la prospection agences immo", "source des leads pour X", "fais tourner la campagne Y aujourd'hui", "lance la routine prospection"), ou piloter/auditer une verticale de prospection sans préciser l'action. Créer une campagne de zéro est couvert par le skill new-campaign ; affiner le ciblage d'une campagne existante par le skill edit-campaign ; modifier la séquence, la config ou dupliquer une verticale n'est pas encore couvert.
---

# prospect-routine — routeur

## Vue d'ensemble

Porte d'entrée du pipeline outbound. Lit l'intention de l'utilisateur, résout de quelle campagne il
parle, et passe la main à la bonne brique. Aucun travail métier ici — le routeur aiguille, les briques
font. Le run quotidien est sa vraie valeur ; créer et modifier sont délégués.

## Trois intentions

| L'utilisateur veut… | Destination |
|---|---|
| faire tourner le sourcing du jour | Run quotidien (ci-dessous) |
| créer une campagne de zéro | skill `new-campaign` (il se déclenche seul ; sinon, l'y pointer) |
| modifier le ciblage d'une campagne | skill `edit-campaign` (filtres + icpFit ; il se déclenche seul) |
| modifier la séquence / la config / dupliquer | pas encore couvert — le dire, ne rien muter à la main |

Avant un run, résoudre la campagne : `resolve --registry <racine Prospection/campaigns-registry.json>
--slug <ce que dit l'utilisateur>` → `campaign_id` + `config_path`. Slug introuvable → demander lequel
(le registre liste les campagnes).

Demande de prospection sans action précisée (« occupe-toi de la prospection X ») → proposer le run du
jour, la valeur par défaut.

Commandes moteur : via `uv run python scripts/routine.py <cmd>`.

## Run quotidien

Charge des leads **en review** pour une campagne ; ne lance rien (le launch est une étape séparée et
gardée — cf. Référence). Pipeline en ordre fixe, chaque étape nourrit la suivante :

1. `prepare --config <config_path> --date <date>` → config + prompts + pré-vol auth (STOP si auth ou
   prompt KO : rien ne sert de sourcer sans pouvoir charger).
2. `source --config <config_path>` → candidats inédits (déjà-vus exclus, quota People DB lu).
3. `verify --config <config_path>` → clés de message requises + garde du contrat clés ↔ séquence.
4. workflow `sourcing` sur les candidats → approuvés `{lead, variables}`.
5. `load-lead` par approuvé → lead en review (gardé par `dry_run` ; jamais de launch ici).
6. `record-run` + `log` → déjà-vus, historique, journal.

Séquence détaillée (flags, assemblage des args du workflow, `dry_run`, `launch`, gestion d'erreur) :
`references/prospect-routine/run.md`.

## Créer

Une demande de création de campagne est portée par le skill `new-campaign`. S'il ne s'est pas déclenché
seul, y renvoyer ; ne pas réimplémenter la création ici.

## Modifier

Affiner le ciblage d'une campagne existante (filtres People DB + prompt icpFit) est porté par le skill
`edit-campaign` — il se déclenche seul sur « affine le ciblage », « vise plutôt X », « exclus les Y » ;
sinon l'y renvoyer. 100% local, validé sur échantillon avant tout commit.

Modifier la séquence (étapes, messages, timing), la config ou l'état (pause/reprise, réglages, cadence),
ou dupliquer une verticale vers un nouveau segment n'est pas encore construit. Le dire à l'utilisateur ;
ne pas muter la séquence à la main.

## Référence

- `references/prospect-routine/run.md` — séquence exacte du run, args du workflow sourcing, dry_run, launch.
