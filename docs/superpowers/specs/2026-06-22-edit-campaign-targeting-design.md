# Modifier une campagne — SP-A : édition du ciblage

**Date** : 2026-06-22 · **Statut** : design validé, à planifier (writing-plans).
**Périmètre** : SP-A, première tranche de v1.5 « modifier une campagne ». Affiner le **ciblage**
d'une campagne existante (qui on source), sans toucher Lemlist. Couche orchestration (nouvelle skill
`edit-campaign`) + **un** primitive moteur (reset du curseur) + exposition de `total` au sourcing.
Un seul spec.

## Contexte / problème

Le run quotidien (v1) et la création (`new-campaign`) sont livrés. **Modifier une campagne existante
n'est pas couvert** : le routeur (`skills/prospect-routine/SKILL.md §Modifier`) le déclare hors-couverture
et affirme — **à tort** — que « les mutations de séquence Lemlist n'existent pas ».

Cette affirmation est **fausse**, vérifiée contre la doc live Lemlist v2 le 2026-06-22 : la mutation de
séquence par API est pleinement supportée (`POST/PATCH/DELETE /sequences/{seqId}/steps`,
`PATCH /campaigns/{id}`, `PATCH /schedules/{id}` + association). « Modifier » est donc *buildable*. Mais
le périmètre est trop large pour un spec — il a été découpé en quatre sous-projets (SP-A ciblage, SP-B
séquence, SP-C config/état, SP-D dupliquer-segment) ; **SP-A en premier** (décision Alex, 2026-06-22).

SP-A est le levier le plus **fréquent** (on tune le ciblage en continu les premières semaines) et le plus
**sûr** : les deux leviers de ciblage vivent **en local**, pas dans Lemlist.

```
Filtres People DB   → ciblage DUR : qui entre dans le funnel        (campaign.json → "filters")
Prompt icpFit       → ciblage MOU : qui passe le jugement IA parmi les sourcés  (prompts/icpFit.md)
```

**Principe directeur (Alex)** : toute la complexité est portée par Claude (session). L'humain exprime
son intention en **langage naturel** (« vise les agences à plusieurs négociateurs, exclus les
indépendants ») ; il ne voit jamais un `filterId` ni un objet JSON. La surface humaine = une conversation.
Doctrine : objectif + vision, pas procédure — laisser l'intelligence travailler.

## Faits moteur vérifiés (2026-06-22)

- **`page_cursor` vit dans `state.json`**, écrit atomiquement (`state.save_state`, tmp + `os.replace`).
  **Aucune commande ne le reset aujourd'hui** : `status` ne touche que `status.json`. Éditer `state.json`
  à la main contournerait l'écriture atomique → le reset **doit** passer par le moteur.
- **`status.json` porte déjà `edit_in_progress`** (`STATUS_DEFAULT`, à côté de `phase1_done` / `w2_steps`) :
  le foothold de reprise d'un flux d'édition est déjà prévu.
- **`source()` ne lève pas sur filtre invalide** : il renvoie `{candidats:[], exhausted:true,
  next_cursor:cursor+1}`. Il a `res["total"]` (taille du pool) sous la main mais **ne l'expose pas**.
- **`icp-check` est réutilisable tel quel** — workflow livré (spec 04). Contrat :
  `args = {prompt_icpFit, sample, model:"haiku"}` → `{verdicts:[{lead, qualifie, raison}]}`. La décision
  d'alignement + l'itération du prompt vivent dans l'agent de session, hors workflow.
- **People DB** : `people-database/get-database-filters` liste les `filterId` et valeurs valides ; l'ordre
  du pool est stable entre deux recherches identiques (cf. spec curseur).

## Design

Approche retenue : **moteur fin, orchestration épaisse**. Claude comprend l'intention NL et traduit ;
le moteur ne gagne qu'un primitive déterministe (reset curseur) + expose `total`. Réutilise `source` et
`icp-check` tels quels. Colle à la frontière du codebase : CLI = glue I/O déterministe, jugement =
workflows / agent de session.

(Alternatives écartées : *moteur épais* — une commande transactionnelle `edit-targeting` — n'apporte
qu'un gain d'atomicité marginal puisque le moteur ne comprend pas le NL et que Claude traduit de toute
façon ; *manuel sans outillage* laisse le curseur caduc sauter le front du nouveau pool en silence.)

### Flux (orchestré par Claude)

```
1. resolve     campagne (slug → campaign_id + config_path)
2. lire        l'état actuel : filters (campaign.json) + icpFit.md + fichiers d'intelligence (contexte)
3. comprendre  l'intention NL de l'utilisateur
4. traduire    nouveaux filtres People DB (validés via get-database-filters) ± icpFit ajusté
5. PRÉVISUALISER + VALIDER
               source --target N  → taille du nouveau pool (total) + échantillon frais
               → icp-check sur l'échantillon avec l'icpFit (édité) → verdicts
               → itérer avec l'utilisateur jusqu'à alignement (boucle bornée, sign-off humain)
6. GO explicite → écrire filters + icpFit ; SI les FILTRES ont changé → reset page_cursor à 1 (moteur)
7. confirmer   ancien → nouveau ciblage, nouvelle taille de pool, état du curseur
```

Le set d'exclusion « déjà en campagne » (filtre `out`) et les receipts sont inchangés — ils continuent de
garantir le « jamais deux fois » indépendamment de cette édition.

### Règle du curseur (cœur de correction)

Changer les **filtres** change le pool → la position du curseur (dans l'ancien ordre) devient caduque.
**Reset à 1** sur tout changement de filtres : re-sweep du nouveau pool depuis le début. Coût = re-score
**one-shot** des survivants qui restent dans le nouveau pool ; **jamais** de double-contact (filtre `out` +
receipts couvrent). Un changement d'**icpFit seul** ne touche pas le pool → **pas de reset**.

C'est de l'orchestration (Claude décide « les filtres ont-ils changé ? »), exécutée via le primitive
moteur ci-dessous.

### Primitive moteur neuf

- **Commande `cursor`** (state.json, écriture atomique) :
  `cursor --config <config_path> --reset` → `page_cursor = 1` ;
  `cursor --config <config_path> --set <N>` → `page_cursor = N` ;
  `cursor --config <config_path>` (ou `--get`) → imprime la valeur courante.
  Séparée de `status` parce qu'elle touche `state.json`, pas `status.json`.
- **`source` expose `total`** : ajouter `"total": res.get("total")` au retour de `sourcing.source()`
  (et le propager dans `cmd_source`). C'est le feedback « ton nouveau ciblage = ~8 200 prospects » qui
  rend l'édition lisible et sert de détection « filtre invalide / pool vide » (total 0).

Tout le reste = orchestration + commandes existantes (`resolve`, `source`) + workflow `icp-check` +
édition de fichiers (campaign.json `filters`, `prompts/icpFit.md`).

### Validation : la norme, jamais sautée en silence

La prévisualisation (taille de pool) + `icp-check` sur échantillon est le **chemin par défaut** : on ne
committe pas un nouveau ciblage sans avoir vu le nouveau pool et jugé un échantillon frais. Pour un tweak
trivial, l'utilisateur peut alléger la boucle — mais l'allègement est **explicite**, jamais un saut
silencieux.

### Où vit la skill

Nouvelle skill `skills/edit-campaign/SKILL.md`, sœur de `new-campaign`. Le routeur
`prospect-routine/SKILL.md §Modifier` est **recâblé** vers elle pour les éditions de **ciblage**, et la
phrase fausse (« mutations Lemlist n'existent pas ») disparaît ; SP-B / SP-C / SP-D y sont notés comme
suite. La craft de traduction ICP → filtres reste déléguée à `/lemlist` §3 (pas de duplication).

### État machine

- **Conservé** : `page_cursor` (state.json), `receipts` (inchangés).
- **Utilisé** : `edit_in_progress` (status.json) — posé à `true` pendant l'édition (reprise + garde
  anti-double-édition concurrente), remis à `false` au commit ou à l'abandon.
- **Muté** : `page_cursor := 1` (via `cursor --reset`) quand les filtres changent.

## Migration

Rien à migrer : `edit_in_progress` existe déjà dans `STATUS_DEFAULT`, aucun changement de schéma d'état.
Le seul ajout est la commande `cursor` et le champ `total` au retour de `source` (additif, rétro-compatible).
Le routeur `§Modifier` est réécrit (orchestration, pas d'état).

## Erreurs / bornes

- **Filtre invalide / pool vide** → `source` renvoie `total:0` (ou `exhausted:true`, `candidats:[]`).
  Claude le détecte, **ne committe pas**, repropose une traduction.
- **`get-database-filters` KO** → fallback : valider par la recherche d'échantillon (`total`) ; ne jamais
  committer un filtre à l'aveugle.
- **Reset curseur** → re-score one-shot des survivants ; jamais de double-contact.
- **`icp-check`** → boucle bornée, sign-off humain, pas de seuil automatique, pas de boucle infinie.
- **Garde anti-écrasement** → `filters` et `icpFit.md` ne sont écrits qu'**après** validation + go explicite
  (mirroir de la garde `new-campaign §1`).
- **Édition concurrente** → `edit_in_progress=true` signale une édition en cours ; reprise propre.

## Tests

La partie déterministe est testée ; le jugement (NL → filtres, boucle de validation) vit dans la skill /
le workflow, comme pour `new-campaign` et le run — non testé unitairement.

- `cursor --reset` met `page_cursor` à 1 (écriture atomique vérifiée) ; `cursor --set N` pose `N` ;
  `cursor --get` lit la valeur courante.
- `source` (et `cmd_source`) expose `total` dans son retour (mock People DB avec `total`).
- Garde : `cursor` opère sur `state.json` et laisse `status.json` intact (et réciproquement).
- Suites vertes (Python + JS) — JS inchangé ici (le primitive est Python).

## Hors périmètre

- **SP-B — séquence** (API Lemlist : add/remove/reorder étapes, corps statique + subject, timing). Ouvre
  le **fork d'architecture** : « modifier la séquence » inverse l'invariant actuel (le local pousserait
  *vers* Lemlist, alors qu'aujourd'hui la séquence est SSoT et le local s'y conforme). À trancher dans un
  brainstorm dédié. Contraintes connues : pause avant `DELETE`, `type` d'étape immuable (delete+recreate),
  effet sur les leads en cours de séquence non documenté.
- **SP-C — config / état** : pause/reprise de campagne, réglages (`update-campaign` : stop-conditions,
  senders, tracking, autoReview), op-config locale (`sourcing_size`, `models`, `enrich`, flip `dry_run`).
- **SP-D — dupliquer-segment** : cloner une verticale existante vers un nouveau segment puis ajuster.
  Composition de SP-A + SP-B ; suppose d'étendre `new-campaign` pour templater depuis une verticale
  existante (la résolution d'un template via le registre n'est pas câblée aujourd'hui).
- **Édition des valeurs de variables de message** (`prompts/<step>.md` autres qu'icpFit) : déjà couverte
  par le run (le prochain run reprend le prompt édité) — pas de flux neuf. YAGNI.
- **Aucune mutation Lemlist dans SP-A.**

## Critères de succès

- L'utilisateur affine le ciblage en langage naturel, sans jamais voir un `filterId` ni un JSON.
- Un changement de **filtres** reset le curseur à 1 ; un changement d'**icpFit seul** ne le reset pas.
- La validation (taille de pool + `icp-check` sur échantillon frais) précède tout commit ; **rien n'est
  écrit sans go explicite**.
- Zéro mutation Lemlist, zéro launch, zéro contact.
- Le routeur `§Modifier` route vers `edit-campaign` ; plus aucune affirmation fausse sur l'API.
- Suites vertes (Python + JS).
