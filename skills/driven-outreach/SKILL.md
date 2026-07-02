---
name: driven-outreach
description: Déclencher quand l'utilisateur veut faire tourner la prospection outbound — lancer le run / sourcing quotidien d'une campagne existante ("run la prospection agences immo", "source des leads pour X", "fais tourner la campagne Y aujourd'hui", "lance la routine prospection"), ou piloter/auditer une verticale de prospection sans préciser l'action. Créer une campagne de zéro est couvert par le skill new-campaign ; affiner le ciblage, la séquence ou la config d'une campagne existante par le skill edit-campaign ; dupliquer une verticale vers un nouveau segment n'est pas encore couvert.
---

# driven-outreach — routeur

## Vue d'ensemble

Porte d'entrée du pipeline outbound. Lit l'intention de l'utilisateur, résout de quelle campagne il
parle, et passe la main à la bonne brique. Aucun travail métier ici — le routeur aiguille, les briques
font. Le run quotidien est sa vraie valeur ; créer et modifier sont délégués à leurs skills.

## Les briques (la frontière)

Trois types d'outils, frontière nette entre déterministe et jugement IA :

- **Moteur** — `uv run python scripts/routine.py <cmd>`. I/O déterministe, zéro LLM : **le moteur est le
  seul point d'accès à Lemlist et à l'état machine**. Chaque commande lit ses fichiers, appelle l'API,
  imprime du JSON. La surface complète des commandes et de leurs flags est documentée là où elles servent
  (run → `run.md` ; création / édition → les skills `new-campaign` / `edit-campaign`).
- **Workflows** — `/sourcing`, `/icp-check`. Fan-out d'agents IA : le jugement (scoring, rédaction,
  qualification). Invoqués par le routeur et les skills ; ils ne font aucune I/O Lemlist eux-mêmes.
- **Skills** — `new-campaign`, `edit-campaign`. Orchestration d'une intention complète : ils enchaînent
  moteur + workflows et portent les gardes. Ce routeur en est un.

Ne jamais muter Lemlist à la main : passer par le moteur, via la brique de l'intention.

## Les intentions

| L'utilisateur veut… | Destination |
|---|---|
| faire tourner le sourcing du jour | Run quotidien (ci-dessous) |
| créer une campagne de zéro | skill `new-campaign` |
| modifier le ciblage, la séquence ou la config d'une campagne | skill `edit-campaign` |
| affûter / réécrire la copy d'un message (icebreaker, relance, clôture) | skill `craft-copy` |
| dupliquer une verticale vers un nouveau segment | pas encore couvert — le dire, ne rien muter à la main |

`new-campaign`, `edit-campaign` et `craft-copy` se déclenchent seuls sur leur intention ; s'ils ne l'ont
pas fait, l'y renvoyer. Demande sans action précisée (« occupe-toi de la prospection X ») → proposer le run du jour, la
valeur par défaut.

Avant un run, résoudre la campagne : `resolve --registry <racine Prospection/campaigns-registry.json>
--slug <ce que dit l'utilisateur>` → `campaign_id` + `config_path`. Slug introuvable → demander lequel (le
registre liste les campagnes).

## Run quotidien

Charge des leads en review pour une campagne ; ne lance rien (le launch est une étape séparée et gardée).
Pipeline en ordre fixe, chaque étape nourrit la suivante :

1. `prepare` → config + prompts + pré-vol auth (STOP si auth ou prompt KO).
2. `source` → candidats inédits (curseur de page, exclusion « déjà en campagne », quota People DB).
3. `verify` → garde du contrat clés de message ↔ séquence.
4. workflow `sourcing` sur les candidats → approuvés `{lead, variables}`.
5. `load-lead` par approuvé → lead en review (gardé par `dry_run` ; jamais de launch ici).
6. `record-run` + `log` → curseur, historique, journal.

Ce résumé ne suffit pas à exécuter : les flags exacts, l'assemblage des args du workflow, `dry_run`, le
`launch` gardé et la gestion d'erreur vivent dans `references/driven-outreach/run.md`.

## Créer / Modifier

- **Créer** une campagne → skill `new-campaign` (recherche ICP/angle interactive, fichiers d'intelligence,
  création Lemlist, smoke test).
- **Modifier le ciblage, la séquence ou la config / l'état** d'une campagne existante → skill
  `edit-campaign`. Ciblage (filtres + icpFit) : local. Séquence (structure/timing/canal/champs statiques) et
  config / état (pause/reprise, réglages, cadence, flip dry_run) : mutations Lemlist gardées (preview +
  confirmation) ou éditions locales.
- **Affûter / réécrire la copy d'un message** (icebreaker, relance, clôture) → skill `craft-copy` :
  clarifie le changement avec l'utilisateur, écrit la fiche du prompt, teste avant/après en conditions
  réelles. C'est le foyer du craft de copy — edit-campaign y renvoie après avoir créé une clé d'étape.
- **Dupliquer une verticale** vers un nouveau segment → pas encore construit. Le dire à l'utilisateur ;
  ne pas muter à la main.

## Références — charge avant d'agir

Une commande lancée sans sa référence (ordre, flags, gardes) casse le contrat. **Dans le doute, charge la
référence : mieux vaut une de trop qu'une de moins.**

| Intention | Charge avant d'agir |
|---|---|
| Run quotidien | `references/driven-outreach/run.md` |
| Créer une campagne | skill `new-campaign` (+ sa réf `references/new-campaign/vertical-scaffold.md`) |
| Modifier le ciblage / la séquence / la config | skill `edit-campaign` (séquence → `references/edit-campaign/sequence-edit.md` ; config → `references/edit-campaign/config-state.md`) |
| Affûter / réécrire la copy d'un message | skill `craft-copy` (+ ses réfs `references/craft-copy/`) |

Les skills chargent eux-mêmes leurs propres références ; le routeur n'a qu'à les déclencher.
