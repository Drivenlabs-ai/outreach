# Sourcing-state — marque-page + exclusion « déjà en campagne »

**Date** : 2026-06-22 · **Statut** : design validé, à implémenter (writing-plans).
**Périmètre** : couche sourcing/état du moteur (`scripts/prospect_engine/` : `sourcing.py`,
`state.py`, `cli.py`). Un seul spec.

## Contexte / problème

Le sourcing People DB re-présente les mêmes prospects à chaque run → on **re-paye le scoring IA**
sur des profils déjà jugés. Découvert pendant le premier run live (2026-06-21).

Cause, dans le moteur actuel :
- `seen_lead_ids` (mémoire locale censée exclure les déjà-vus) était **cassé** : `record-run`
  stockait les dicts candidats au lieu de la clé `linkedinUrl`, et la dédup comparait sur la
  mauvaise clé. (Le bug de stockage a été corrigé au passage ; la mémoire reste néanmoins inadaptée
  — voir Design.)
- `sourcing.source()` **n'utilise pas** `page_cursor` : il repart **page 1** à chaque appel. Sans
  exclusion fonctionnelle, il rend donc les mêmes premiers résultats run après run.

**Hors sujet ici** : la garantie « jamais contacter deux fois » est déjà assurée, indépendamment de
cette couche, par les `receipts` (skip au `load-lead`) + le dedup natif Lemlist (`deduplicate=true`,
par email). Ce spec ne traite que l'**efficacité du sourcing** (ne pas re-scorer) et l'**exclusion
des leads déjà en campagne**.

## Faits terrain vérifiés (2026-06-22, compte Lemlist agence-immo)

- **Pool** des filtres agence-immo = **15 576** prospects (`total`), **ordre stable** entre deux
  recherches identiques (mêmes résultats, même ordre).
- **Exclusion native** : le filtre `{"filterId":"leadLinkedInUrl","in":[],"out":[<urls>]}` exclut
  les URLs côté serveur, **indépendamment de la position** (immunisé à la pagination). **Plafond
  ~1000 URLs** : 1000 → 200 OK, 3000 → 400 « Parameter filters is invalid ».
- **Pas** de lookup contact par URL : `GET /contacts?linkedinUrl=X` ignore le paramètre et renvoie
  tous les contacts. L'exclusion passe donc par le filtre `out`, pas par un check unitaire.
- `get_campaign_leads` renvoie des champs minimaux (`_id`, `state`, `contactId`) — **pas** de
  `linkedinUrl`. Le **contact**, lui, porte `linkedinUrl` + `campaigns: [{campaignId, leadState}]`.

## Design

Deux mécanismes aux rôles **disjoints** :

```
1. MARQUE-PAGE (cursor)              → déroule le pool de 15k vers l'avant, ~1 page/run.
   gère les REJETÉS (~95%)             On ne repasse pas dessus → pas de re-score. Supprime seen_lead_ids.

2. EXCLUSION « déjà en campagne »    → set des chargés (~5%), petit → tient sous le cap `out`.
   via le filtre `out` (Lemlist)       Indépendant de la position → un lead déjà en campagne n'est
                                        jamais re-présenté, même si le marque-page dérive/reboucle.
                                        C'est « Lemlist = mémoire » pour les contactés.
```

### 1. Marque-page

- **État** : `page_cursor` (entier). `seen_lead_ids` **supprimé** de l'état et du code.
- `source()` lit le curseur et recherche **à partir de cette page** (taille de page = lot de
  sourcing du run), renvoie `{candidats, next_cursor, limitation, exhausted}`.
- `cmd_source` **persiste `next_cursor` immédiatement** au moment du sourcing — le curseur avance dès
  qu'on source, indépendamment de la réussite du downstream (si un run échoue après, on ne re-source
  pas les mêmes au prochain).
- **Granularité (détail laissé au plan)** : approche recommandée = une page par run, `size` = lot
  visé, `page` = curseur, `cursor += 1` par run (pas d'arithmétique d'offset, pas de tail de page
  sautée). Le filtre `out` (mécanisme 2) peut réduire légèrement un lot quand une page recoupe des
  chargés — acceptable.
- **Fin de pool** (page au-delà du `total` / résultats vides) → `exhausted: true` = signal « tout
  l'ICP a été screené, élargir les filtres ». Option : reset du curseur à 1 → re-sweep → ré-évaluation
  (capte les changements de poste).

### 2. Exclusion « déjà en campagne »

- Avant la recherche, construire le set des `linkedinUrl` **chargés dans cette campagne**, **depuis
  Lemlist** (SSoT, intention de l'utilisateur) : paginer les contacts, garder ceux dont
  `contact.campaigns` inclut ce `campaign_id`, collecter leurs `linkedinUrl`.
- Injecter `{"filterId":"leadLinkedInUrl","in":[],"out":[<urls>]}` dans les filtres de la recherche.
- **Borne** : si le set dépasse le cap (~1000), garder les plus récents et **loguer** l'atteinte du
  plafond (réaliste : < 1000 pendant longtemps — à ~5 chargés/jour, ~780 décideurs sur tout le pool).
- **Fallback** : si le fetch Lemlist échoue, le run **continue sans ce filtre** (le marque-page +
  les `receipts` au load couvrent) — non bloquant.

### Flux du run

```
resolve → prepare → [set d'exclusion lu depuis Lemlist] → source(cursor, out=chargés)
        → persiste cursor → verify → workflow sourcing → load-lead → record-run + log
```

Le set d'exclusion est lu **une fois par run**, au sourcing.

### État machine

- **Conservé** : `page_cursor` (entier, reconstructible) ; `receipts` (inchangés).
- **Supprimé** : `seen_lead_ids` (et la logique de merge associée).

## Migration

- Retirer `seen_lead_ids` de l'état et du code (`state.py`, `cli.py cmd_record_run`).
- `page_cursor` repart de sa valeur courante (1). Conséquence **one-shot** au premier run du nouveau
  code : un re-sweep depuis la page 1 — les leads déjà en campagne exclus par `out`, quelques rejetés
  re-scorés une seule fois. Acceptable.

## Erreurs / bornes

- Fetch du set d'exclusion KO → run sans le filtre `out` (dégradé, non bloquant).
- Set d'exclusion > cap → tronquer aux plus récents + log.
- Fin de pool → `exhausted: true`.
- Dérive d'ordre Lemlist → re-score rare / skip mineur ; **jamais** de double contact ; curseur
  réinitialisable à tout moment sans risque.

## Tests

- `source()` lit le curseur, recherche à partir de cette page, renvoie `next_cursor` avancé (mock
  People DB ordonné stable) ; deux runs consécutifs ne renvoient pas les mêmes candidats.
- `source()` injecte le filtre `out` quand un set d'exclusion est fourni (un chargé est exclu).
- Construction du set chargés : contacts filtrés sur `campaigns` contenant le `campaign_id` →
  `linkedinUrl`.
- Fallback : fetch chargés KO → source sans `out`, pas d'erreur.
- Fin de pool → `exhausted: true`.
- Garde : plus aucune référence à `seen_lead_ids` (Python + JS).

## Hors périmètre

- **Staging list Lemlist** (mémoire 100 % hors-machine, incluant les rejetés) : reporté (YAGNI). Le
  pool (15k) dépasse le cap `out` (~1k) → une exclusion totale portée par Lemlist est inopérante à
  cette échelle ; le marque-page suffit. À reconsidérer si la dérive fait mal en pratique.
- Refonte du scoring/écriture, des filtres ICP, du `launch`.

## Critères de succès

- Deux runs consécutifs ne re-scorent pas les mêmes rejetés (le curseur a avancé).
- Un lead déjà en campagne n'est jamais re-présenté au sourcing.
- `seen_lead_ids` a disparu ; l'état de sourcing = `page_cursor` + `receipts`.
- Suites vertes (JS + Python).
