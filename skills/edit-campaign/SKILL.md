---
name: edit-campaign
description: Déclencher quand l'utilisateur veut modifier ou affiner le ciblage d'une campagne de prospection existante — « affine le ciblage de X », « vise plutôt les Y », « exclus les Z », « resserre l'ICP », « élargis le ciblage », « change les filtres », « le ciblage est trop large / trop étroit ». Couvre les filtres People DB et le prompt icpFit. Ne pas déclencher pour créer une campagne (→ new-campaign) ni pour le run quotidien (→ prospect-routine) ; modifier la séquence, le timing, la config ou dupliquer une verticale n'est pas encore couvert.
---

# edit-campaign — affiner le ciblage d'une campagne existante

## Vue d'ensemble

Affine qui une campagne cible, sans toucher Lemlist. L'utilisateur exprime son intention en langage
naturel (« vise les agences à plusieurs négociateurs, exclus les indépendants ») ; toi (Claude de
session) tu portes la complexité : tu traduis en filtres et/ou ajustes l'icpFit, tu valides sur un
échantillon, tu n'écris qu'après son accord. L'utilisateur ne voit jamais un `filterId` ni un objet JSON.

Le ciblage a deux leviers, tous deux locaux (le moteur les lit à chaque run ; Lemlist n'est pas modifié) :

| Levier | Rôle | Où |
|---|---|---|
| Filtres People DB | ciblage dur : qui entre dans le funnel | `campaign.json` → `filters` |
| Prompt icpFit | ciblage mou : qui passe le jugement IA parmi les sourcés | `prompts/icpFit.md` |

**Commandes moteur** : via `uv run python scripts/routine.py <cmd>` (jamais `python3`).

## Quand l'utiliser

- L'utilisateur veut affiner, resserrer, élargir ou corriger le ciblage d'une campagne existante.
- Pas pour : créer une campagne (→ `new-campaign`), faire tourner le run quotidien (→ `prospect-routine`),
  ou modifier la séquence / le timing / la config (cf. Périmètre).

## Le flux

```
1. resolve     resolve --registry <Prospection/campaigns-registry.json> --slug <ce que dit l'utilisateur>
                → campaign_id + config_path. Slug introuvable → demander lequel (le registre les liste).
2. lire        l'état actuel : filters (campaign.json) + prompts/icpFit.md + fichiers d'intelligence
                (icp.md, persona.md, triggers.md) pour le contexte. Vérifier edit_in_progress (status) :
                si true, une édition est restée inachevée — le signaler et repartir proprement.
3. comprendre  reformuler l'intention jusqu'à être sûr de ce qui change dans le ciblage.
4. traduire    nouveaux filtres People DB (craft /lemlist §3 ; valider filterId/valeurs via
                get-database-filters) et/ou icpFit ajusté. Ne rien écrire encore.
5. valider     status --config <config_path> --set edit_in_progress=true
                source --config <config_path> --target <N> → taille du nouveau pool (total) + échantillon
                  total 0 ou exhausted → filtre trop étroit ou invalide : corriger, ne pas committer.
                workflow icp-check : args = { prompt_icpFit: <icpFit ajusté>, sample: <candidats>,
                  model: "haiku" } → lire les verdicts, comparer à l'ICP visé, itérer. Boucle bornée, accord humain.
                abandon à ce stade → status --config <config_path> --set edit_in_progress=false (rien n'a été écrit)
6. committer   après accord explicite : écrire les nouveaux filters (campaign.json) + le nouvel icpFit.md.
                filtres changés → cursor --config <config_path> --reset (cf. Règle du curseur pour le pourquoi)
                icpFit seul modifié → pas de reset (le pool est inchangé)
                status --config <config_path> --set edit_in_progress=false
7. confirmer   résumer : ancien → nouveau ciblage, nouvelle taille de pool, état du curseur.
```

## Règle du curseur

Changer les filtres change le pool : le `page_cursor` (position dans l'ancien ordre) devient caduc. Le
remettre à 1 (`cursor --config <config_path> --reset`) pour re-balayer le nouveau pool depuis le début.
Coût : re-score one-shot des survivants ; jamais de double-contact (le filtre `out` « déjà en campagne »
et les receipts couvrent). Changer l'icpFit seul ne touche pas le pool — pas de reset.

## Garanties

- **100% local : zéro mutation Lemlist, zéro launch, zéro contact.**
- Validation avant écriture : la taille de pool et icp-check sur échantillon frais précèdent tout commit.
  L'alléger pour un ajustement trivial est un choix explicite, jamais un saut silencieux.
- `filters` et `icpFit.md` ne sont écrits qu'après validation et accord.
- `edit_in_progress` (status.json) marque une édition en cours — `true` pendant, `false` au commit ou à
  l'abandon ; il porte la reprise si une édition est interrompue.

## Périmètre

Couvert : le ciblage (filtres People DB + prompt icpFit). Pas encore couvert :
- modifier la séquence (étapes, corps des messages, timing) ;
- la config et l'état (pause/reprise, réglages campagne, cadence de sourcing, modèles) ;
- dupliquer une verticale vers un nouveau segment puis ajuster.

## Référence

- Craft ICP → filtres People DB : `/lemlist` §3 (filterId / in / out, get-database-filters).
- Contrat icp-check : `args = {prompt_icpFit, sample, model:"haiku"}` → `{verdicts:[{lead, qualifie, raison}]}`.
- Commandes moteur : `resolve`, `source` (renvoie `total`), `status --set edit_in_progress`, `cursor --reset`.
