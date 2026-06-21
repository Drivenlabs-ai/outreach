---
name: prospect-routine
description: Déclencher quand l'utilisateur veut faire tourner la prospection outbound — lancer le run / sourcing quotidien d'une campagne existante ("run la prospection agences immo", "source des leads pour X", "fais tourner la campagne Y aujourd'hui", "lance la routine prospection"), ou piloter/auditer une verticale de prospection sans préciser l'action. Créer une campagne de zéro est couvert par le skill new-campaign ; modifier une campagne existante n'est pas encore couvert.
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
| modifier une campagne existante | pas encore couvert — le dire, ne rien muter à la main |

Avant un run, résoudre la campagne : `resolve --registry <racine Prospection/campaigns-registry.json>
--slug <ce que dit l'utilisateur>` → `campaign_id` + `config_path`. Slug introuvable → demander lequel
(le registre liste les campagnes).

Commandes moteur : via `uv run python scripts/routine.py <cmd>`.

## Run quotidien

Charge des leads **en review** pour une campagne ; ne lance rien (le launch est une étape séparée et
gardée — cf. Référence). Pipeline en ordre fixe, chaque étape nourrit la suivante :

1. `prepare --config <config_path> --date <date>` → config + prompts + pré-vol auth (STOP si auth ou
   prompt KO : rien ne sert de sourcer sans pouvoir charger).
2. `source --config <config_path>` → candidats inédits (déjà-vus exclus, quota People DB lu).
3. `verify --config <config_path>` → clés de message requises + garde du contrat clés ↔ séquence.
4. workflow `sourcing` sur les candidats → approuvés `{lead, variables}`.
5. `load-lead` par approuvé → lead en review.
6. `record-run` + `log` → déjà-vus, historique, journal.

Séquence détaillée (flags, assemblage des args du workflow, `dry_run`, `launch`, gestion d'erreur) :
`references/prospect-routine/run.md`.

## Créer

Une demande de création de campagne est portée par le skill `new-campaign`. S'il ne s'est pas déclenché
seul, y renvoyer ; ne pas réimplémenter la création ici.

## Modifier

Modifier une campagne existante (affiner l'ICP, ajouter une étape, changer le timing) n'est pas encore
construit — cela suppose des mutations de séquence Lemlist qui n'existent pas. Le dire à l'utilisateur,
ne pas muter la séquence à la main.

## Référence

- `references/prospect-routine/run.md` — séquence exacte du run, args du workflow sourcing, dry_run, launch.
