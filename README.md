# outreach

Plugin Claude Code — pipeline outbound Lemlist multi-verticales : **sourcing → ICP → rédaction → livraison**, piloté par un routeur qui orchestre des workflows réutilisables paramétrés par `campaign_id`.

## Trois foyers, une frontière

| Foyer | Contenu | Où |
|---|---|---|
| **Ce repo** | Le moteur générique : routeur, workflows, scripts déterministes | `Code/drivenlabs-ai/outreach/` (git, plugin AGPL-3.0) |
| **Drive Drivenlabs** | L'intelligence métier : `icp.md`, prompts, datasets, registre des campagnes | `Drivenlabs Team/…/Prospection/` |
| **État machine** | Mémoire des runs : déjà-vus, reçus, journal | `~/.claude/outreach/<slug>/` |

Le pont entre les trois : le **`campaign_id`**. SSoT strict — Lemlist porte la structure (séquence + leads + variables), le Drive porte l'intelligence, aucune réplication.

## Composants

- `skills/driven-outreach/` — le **routeur** (déclenchement langage naturel + dispatch d'intention).
- `skills/new-campaign/` — **W1** : crée une campagne pour une verticale (align ICP/angle interactif → fichiers d'intelligence → `icp-check` → campagne Lemlist → smoke). Un skill piloté par Claude qui orchestre les briques existantes — **zéro nouveau code moteur**.
- `skills/edit-campaign/` — **SP-A + SP-B + SP-C** : modifie une campagne existante — ciblage (filtres + `icpFit`, local), séquence (contenu / structure / timing / canal, Lemlist sur campagne en pause) et config/état (pause/reprise, réglages, cadence de sourcing, flip `dry_run`). Moteur : `cursor` + wrappers de mutation séquence/campagne.
- `scripts/routine.py` — le **moteur** déterministe : seul point d'IO Lemlist + état, modèle de livraison « charger puis lancer ». Zéro LLM.
- `workflows/*.workflow.js` — les **workflows** (fan-out d'agents) : sourcing (W3), alignement du prompt icpFit au setup (`icp-check`). Le runtime des workflows est sandboxé (pas de `require`/`import`) : leur logique déterministe vit dans `workflows/lib/*-core.js` (helpers purs + orchestration, testés par `node --test`), et le `.workflow.js` self-contained en est **généré** sous garde de synchronisation. (W2 lemlist-setup est une procédure déterministe du routeur, pas un workflow.)
- `agents/` — sous-agents sourcing / scoring / juge (à venir).
- `hooks/` — hook `SessionStart` qui synchronise les workflows vers `~/.claude/workflows/`.
- `docs/` — design, architecture, specs.

## Workflows : pourquoi un hook de sync

« Workflow » n'est pas un composant de plugin reconnu par Claude Code. Les `.workflow.js` doivent vivre dans `~/.claude/workflows/` pour devenir des workflows sauvegardés (`/sourcing`, `/icp-check`…). Le repo reste la **source de vérité** ; le hook `SessionStart` (`scripts/sync-workflows.sh`) recopie idempotemment le repo vers cet emplacement à chaque démarrage — install, mise à jour et auto-réparation automatiques.

## Installation

Via la marketplace interne Drivenlabs :

```bash
/plugin marketplace add Drivenlabs-ai/plugins-internal
/plugin install outreach@drivenlabs-ai-internal
```

En développement local :

```bash
claude --plugin-dir /Users/alexandrebouchez/Code/drivenlabs-ai/outreach
```

Clé API Lemlist : `~/.claude/linkedin-prospect.local.md` (`lemlist_api_key:`), hors repo.

## Licence

AGPL-3.0-only — libre et ouvert, copyleft : toute redistribution ou usage en service réseau reste sous la même licence. Voir `LICENSE`.

## Statut

Briques v1 construites et testées (unitaires) : moteur (`routine.py`), W2 (setup Lemlist), W3 (sourcing), `icp-check`, W1 (`new-campaign`) et le routeur (`driven-outreach`). Run live initial effectué (leads chargés en review). v1.5 « modifier une campagne » en cours : l'édition du ciblage (SP-A), de la séquence (SP-B) et de la config/l'état (SP-C) via `edit-campaign` sont livrées ; dupliquer-segment (SP-D) reste au backlog.
