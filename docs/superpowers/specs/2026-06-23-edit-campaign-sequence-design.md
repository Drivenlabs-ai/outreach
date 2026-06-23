# Modifier une campagne — SP-B : édition de la séquence

**Date** : 2026-06-23 · **Statut** : design validé, à planifier (writing-plans).
**Périmètre** : SP-B, deuxième tranche de v1.5 « modifier une campagne ». Éditer la **séquence** d'une
campagne existante (contenu, structure, timing, canal) via l'API Lemlist, en gardant les prompts d'agents
locaux synchronisés. Couche orchestration (extension de la skill `edit-campaign`) + I/O Lemlist de mutation
de séquence dans le moteur. Un seul spec.

## Contexte / problème

SP-A (édition du ciblage) est livré (PR #2). SP-B ouvre le deuxième levier : **modifier la séquence** —
ce que disent les messages (texte statique + objet), l'ordre et le nombre d'étapes, les délais et fenêtres
d'envoi, le canal d'une étape. Aujourd'hui la séquence n'est éditable qu'à la main dans l'UI Lemlist ; le
moteur ne sait que la **lire** (`get_campaign_sequences`, `verify`).

L'API Lemlist v2 de mutation de séquence existe (vérifié contre la doc live le 2026-06-22). SP-B la câble.
Deux décisions structurantes ont été tranchées en brainstorm (2026-06-23) :

1. **Lemlist = source de vérité.** Édition directe par API : on lit la séquence live, on applique les
   mutations, on ne stocke **jamais** la séquence en local. L'invariant actuel est préservé.
2. **Gate dur : campagne en pause.** SP-B refuse de muter une campagne qui tourne. La pause est un geste
   séparé (SP-C / UI), conscient. Uniforme pour les quatre types d'édition.

**Principe directeur (identique SP-A)** : toute la complexité sur Claude ; l'humain parle en langage
naturel (« ajoute une relance à J+5 », « reformule l'icebreaker plus direct », « passe l'étape 3 en
LinkedIn ») ; il ne voit jamais un `stepId` ni un payload.

**Consigne intégrée (Alex)** : éditer la séquence et **synchroniser les prompts d'agents locaux** est
indissociable. Toute étape ajoutée ou éditée qui introduit/déplace un `{{var}}` exige un prompt local
aligné, sinon la variable sort vide et le lead ne se lance pas. La synchronisation des prompts est une
**étape de premier rang** du flux, pas un avertissement en fin de course.

## Invariant et frontière d'écriture

`verify.py` est et reste **read-only** : « la séquence Lemlist est la vérité ; le local s'y conforme ; on
n'écrit JAMAIS vers Lemlist depuis ici ». SP-B n'y touche pas. SP-B introduit un **chemin d'écriture de
séquence neuf, séparé et explicitement gardé** (nouveaux wrappers d'I/O + commandes dédiées), comme
`delivery.py` écrit des leads. Conséquence :

- Le **run quotidien et le sourcing n'écrivent toujours jamais** la séquence — inchangé.
- Seul le flux d'édition SP-B écrit la séquence, sur campagne en pause et confirmation explicite.
- `verify` garde son rôle : après mutation, il confirme que les prompts locaux **couvrent** les variables
  de la nouvelle séquence (présence). Il ne juge pas l'**alignement d'angle** d'un prompt — ça reste la
  responsabilité de craft de la session.

## Faits API / moteur vérifiés

API Lemlist v2 (doc live 2026-06-22 ; schémas exacts à reconfirmer au plan via `/lemlist`, golden rule) :

- `GET /campaigns/{id}/sequences` → séquences keyées par id ; chaque step : `_id`, `type`, `delay`
  (jours, 0–1500), `index`, `message`, `subject`, `emailTemplateId`, `sequenceId`.
- `POST /sequences/{seqId}/steps` → ajoute une étape. `type` requis (18 valeurs : `email`, `linkedinInvite`,
  `linkedinSend`, `manual`, `phone`, `whatsappMessage`, `sms`, …). Champs requis par type (ex. `email` →
  `subject`+`message`) ; position via `index`, délai via `delay`.
- `PATCH /sequences/{seqId}/steps/{stepId}` → édite `subject`, `message`, `altMessage`, `delay`, … ; `type`
  **présent dans le body mais immuable**.
- `DELETE /sequences/{seqId}/steps/{stepId}` → supprime. **400 si la campagne tourne.**
- `PATCH /schedules/{id}` + `POST /campaigns/{id}/schedules/{id}` → fenêtres d'envoi (start/end HH:mm,
  weekdays 1–7, timezone, `secondsToWait`).
- **Changer le `type` est impossible en place** → delete + recreate.
- **Effet d'une édition sur les leads déjà au milieu de la séquence : non documenté.**

Moteur (`scripts/prospect_engine/`) :

- `lemlist.api_call(method, route, key, body=None)` → `(status, parsed)` : primitive réseau unique
  (User-Agent obligatoire, auth Basic, throttle 429). Les wrappers d'endpoint sont des one-liners (modèle C).
- Lectures existantes réutilisables : `get_campaign_sequences`, `get_campaign`.
- `verify.verify(key, campaign_id, prompts_dir)` → `{aligned, missing_prompts, orphan_prompts,
  sequence_variables, prompt_keys}`. `missing_prompts` (variable de message sans prompt) = **bloquant** ;
  `orphan_prompts` (prompt sans variable) = avertissement. `BUILTINS` (firstName, companyName…) sans prompt.
- **Absent** : tout wrapper d'écriture de séquence/step/schedule, et tout détecteur d'état pause/actif.

## Design

Approche : **moteur fin + orchestration NL** (identique SP-A / W2). Le moteur gagne les I/O de mutation
déterministes + le gate ; le jugement (NL → mutations, rédaction de la copy, rédaction/ajustement des
prompts, décision de structure) vit en session.

### Flux (orchestré par Claude)

```
1. resolve campagne → campaign_id + config_path
2. lire la séquence live (get_campaign_sequences) + l'état de la campagne (get_campaign)
3. GATE : si la campagne tourne → STOP, « mets-la en pause d'abord » (pause = SP-C / UI, hors SP-B)
4. montrer la séquence actuelle en clair : par étape, type · délai · objet · message ({{variables}})
5. comprendre l'intention NL → traduire en mutations concrètes (quelles étapes, quels champs)
6. PREVIEW à deux faces + confirmation explicite :
      (a) changements de séquence (ajout / édition / retrait / réordonnancement / timing / canal)
      (b) prompts locaux à créer / ajuster / signaler-orphelin pour couvrir le nouveau jeu de {{var}}
7. appliquer les mutations de séquence (campagne en pause garantie par le gate) :
      contenu/objet/délai → update_step (PATCH) ; ajout → add_step (POST) ; retrait → delete_step (DELETE) ;
      réordonnancement → index ; timing fenêtres → schedule ; canal → delete_step + add_step (recreate)
8. SYNCHRONISER LES PROMPTS LOCAUX (premier rang) :
      pour chaque {{var}} custom du NOUVEAU jeu : créer prompts/<var>.md si l'étape est nouvelle,
      ajuster prompts/<var>.md si l'étape éditée change l'angle (craft /lemlist) ;
      étape retirée → prompt potentiellement orphelin : le signaler (retrait au choix de l'utilisateur)
9. verify → aligned (missing_prompts vide). Sinon créer/ajuster le prompt manquant, re-verify.
10. confirmer : nouvelle séquence + état du contrat de variables (couverture OK)
```

### Les quatre types d'édition

- **Contenu** : `update_step` sur `message` / `subject`. Si l'angle change, ajuster le prompt qui génère le
  `{{var}}` de l'étape (présence garantie par verify ; alignement d'angle = craft session).
- **Structure** : `add_step` / `delete_step` + `index` pour réordonner. Ajout d'une étape avec un nouveau
  `{{var}}` → nouveau prompt local (étape 8). Retrait → prompt orphelin signalé.
- **Timing** : `delay` par étape (update_step) ; fenêtres d'envoi via schedule. Ne touche pas le contenu.
- **Canal** : `type` immuable → `delete_step` + `add_step` (recreate), en re-posant `index`, `delay`,
  contenu. Le plus invasif ; preview explicite de la recréation.

### Gate « campagne en pause » (moteur, dur)

Le gate n'est pas qu'une discipline de skill : les commandes de mutation **lisent l'état de la campagne
(`get_campaign`) et refusent** (sortie en erreur) si elle tourne. Comme `dry_run` garde `load-lead`, le
gate garde toute mutation de séquence. C'est une garde best-effort (check-then-act, sans API atomique) :
Lemlist ne bloque côté serveur que `delete` si la campagne tourne ; pour `add`/`update`, le gate client +
la pause humaine préalable sont la protection. (Le champ `status` — running/paused/… — est lu via `get_campaign`.)

### Garde sortante

Toute mutation touche une campagne Lemlist live → **preview + confirmation explicite avant la 1re
mutation** (comme la garde W2 de `new-campaign`). Jamais de mutation silencieuse. Le preview montre les
deux faces (séquence + prompts).

### Moteur — ajouts (déterministes, modèle C)

- `lemlist` : `add_step(key, sequence_id, body)`, `update_step(key, sequence_id, step_id, body)`,
  `delete_step(key, sequence_id, step_id)`, `update_schedule(key, schedule_id, body)` — chacun un
  `api_call` one-liner.
- Une fonction de gate (lit `get_campaign`, renvoie actif/pause) réutilisée par les commandes de mutation.
- Commandes CLI : une lecture formatée de la séquence (pour l'étape 4, expose `sequence_id` + `step_id` +
  champs), et les mutations gardées (body lu depuis un fichier, comme `load-lead --input`).
- `verify` (existant) réutilisé tel quel à l'étape 9.

### Où ça vit

Extension de la skill `edit-campaign` : une section « Modifier la séquence » dans `SKILL.md` (lean) qui
renvoie au flux détaillé en `references/edit-campaign/sequence-edit.md` (gardes, contrat de variables,
recreate de canal). Le routeur `prospect-routine §Modifier` bascule la ligne séquence de « backlog » à
« couvert par edit-campaign ».

## Migration

Aucune migration d'état : SP-B n'ajoute pas d'état machine. Ajouts additifs (wrappers d'I/O + commandes +
section de skill + référence). Le routeur et le README passent la séquence de backlog à couvert.

## Erreurs / bornes

- **Campagne active** → gate : refus net, message « mets-la en pause d'abord ». Non bloquant pour le reste.
- **`delete_step` sur campagne active** → 400 Lemlist (doublé par le gate, qui l'attrape avant l'appel).
- **`type` immuable** → jamais de PATCH de type ; canal = delete+recreate explicite.
- **Leads en cours de séquence** → effet non documenté : **avertir** dans le preview (l'édition peut
  affecter les leads déjà engagés ; la pause préalable est le moment conscient).
- **Contrat de variables** → `missing_prompts` non vide après mutation = bloquant : créer le prompt avant de
  clore. `orphan_prompts` = avertissement (étape retirée).
- **Mutation partielle** (une étape réussit, la suivante échoue) → s'arrêter, rapporter l'état réel de la
  séquence (re-lire), ne pas présumer ; reprise manuelle possible (Lemlist porte la vérité).

## Tests

Partie déterministe testée ; le jugement (NL → mutations, rédaction copy/prompts) vit en session, non testé
unitairement (comme SP-A / W1).

- Wrappers `add_step` / `update_step` / `delete_step` / `update_schedule` : route, méthode et body corrects
  (API mockée).
- Gate : commande de mutation sur campagne active → refus (erreur) sans appel de mutation ; sur campagne en
  pause → l'appel passe.
- Lecture formatée de séquence : expose `sequence_id`, `step_id`, type, délai, message/objet (mock).
- `verify` réutilisé : couverture après ajout d'un `{{var}}` (missing_prompts) ; retrait (orphan_prompts).
- Suites vertes (Python + JS ; JS inchangé).

## Hors périmètre

- **Pause / reprise comme intention** et **réglages campagne** (`PATCH /campaigns` : stop-conditions,
  senders, tracking) → SP-C. SP-B ne fait que **lire** l'état pour le gate.
- **Dupliquer une verticale** vers un nouveau segment → SP-D.
- **Édition des valeurs de variables** (génération par les prompts) → déjà couverte par le run ; SP-B touche
  le prompt seulement quand une étape l'exige (couverture du contrat).
- **Versionnage / diff local de la séquence** → écarté (Lemlist = source de vérité, fork tranché).

## Critères de succès

- L'utilisateur édite la séquence en langage naturel (contenu, structure, timing, canal) sans voir un
  `stepId` ni un payload.
- Aucune mutation sur une campagne qui tourne (gate moteur dur) ; aucune mutation sans preview + accord.
- Toute étape ajoutée/éditée est **couverte par un prompt local** : `verify` aligned (missing_prompts vide)
  en fin de flux.
- Lemlist reste source de vérité : aucune représentation locale de la séquence ; le run n'écrit jamais la
  séquence ; `verify` reste read-only.
- Suites vertes (Python + JS).
