---
spec: 01 — moteur (routine.py)
statut: à valider — résolu sur dédup/cadence (vérif doc Lemlist 2026-06-15)
date: 2026-06-15
dépend de: docs/architecture.md
---

# Spec 01 — Le moteur (`scripts/routine.py`)

Le socle. Seul point d'IO Lemlist déterministe **et** seul gardien de l'état machine. Zéro LLM, zéro décision métier. Tout ce qui est piloté par un modèle (sourcing, scoring, rédaction) vit dans les workflows et appelle ce moteur pour écrire dans Lemlist ou dans l'état.

**Cadrage acté :**
- **Livraison en deux temps** — `load-lead` (composite, charge en review) puis `launch` (séparé, gardé). Modèle « charger **puis** lancer » : lancer entre dans la séquence d'envoi, jamais automatique.
- **Réécriture ciblée** — on garde les primitives saines du v1, on supprime tout le chemin « colonnes + liste synchronisée » (modèle A, invalidé par le smoke test), on reconstruit sur le modèle C.
- **Natif d'abord** (vérifié doc Lemlist, cf. §0) — on ne reconstruit pas ce que Lemlist fait nativement : la cadence d'envoi, la dédup cross-campagne par email, l'opt-out.

---

## 0. Frontière natif Lemlist ↔ moteur (vérifié 2026-06-15)

Ce que **Lemlist gère nativement** → le moteur ne le reconstruit pas :

| Domaine | Comportement natif | Source |
|---|---|---|
| Cadence / sécurité d'envoi | *Sending limits* par boîte (quota/jour, 24 h glissantes), algorithme d'étalement, auto-pause near quota | help 4508367 |
| Dédup cross-campagne | `create-lead?deduplicate=true` → ne crée pas si l'**email** existe dans une autre campagne | API create-lead |
| Opt-out / désinscription | Suppression native à l'envoi (ressource `unsubscribes`) | API unsubscribes |
| Quota People DB | Limite de requêtes/24 h ; la réponse renvoie `limitation` (restant) | API search-people |

Ce qui **reste au moteur** :

| Responsabilité | Pourquoi |
|---|---|
| Respecter le rate limit **API 20 req/2s** (honorer `Retry-After` + backoff sur 429) | Seule limite que *nos appels* peuvent toucher |
| Idempotence **par linkedinUrl** via les reçus | `deduplicate` natif ne matche que l'email ; nos leads LinkedIn-only n'ont pas d'email |
| Toujours passer **`deduplicate=true`** | Backstop cross-campagne par email, gratuit |
| Pré-filtre local sur les reçus (`dedup-check`) | Éviter des appels `create-lead` inutiles — optimisation, pas correction |

**Conséquence** : pas de token-bucket, pas de run-lock, pas de circuit-breaker, pas de dedup-set en cache, pas de `refresh-dedup`. La coordination cross-campagne (design §11.2) sort du périmètre moteur — les *Sending limits* natives en tiennent lieu.

---

## 1. La surface — sous-commandes

| Commande | Rôle | Entrée | Sortie |
|---|---|---|---|
| `prepare` | Bootstrap d'un run : config + prompts + état, vérif auth | `--config`, `--date` | `{date, config, prompts, dry_run}` (STOP si auth/prompt KO) |
| `resolve` | Pont slug ↔ campaign_id via le registre | `--slug` ou `--campaign-id`, `--registry` | `{slug, campaign_id, folder, channels, status, config_path}` |
| `fetch` | Photo lecture-seule d'une campagne Lemlist | `--campaign-id` | `{campaign, sequence, leads, counts}` |
| `dedup-check` | Pré-filtre local (reçus) avant chargement | `--input`, `--config` | `{allowed[], skipped[{lead, reason}]}` |
| `load-lead` | **Chargement composite (modèle C, étapes 1→4)** | `--input` (1 lead + variables), `--config`, `[--confirm]` | `{ok, lead_id, stage_reached, skipped, receipt}` |
| `launch` | **Lancement (étape 5)**, par lead ou par lot, gardé | `--input` (lead_ids), `--config`, `--confirm` | `{launched[], errors[]}` |
| `record-run` | Historique + horodatage du run | `--sourced-file`, `--true`, `--false`, `--date` | `{recorded, history_len}` |
| `status` | Lit/écrit la machine d'état (reprise workflows) | `--get` / `--set k=v` | `status.json` courant |
| `log` | Ajoute une entrée au journal | `--entry-file` | confirmation |

**Disparaît du v1** (mort avec le modèle A) : `push` (colonnes), `check-fields`, `verify-sync`, `record-push`, `build_push_plan`, `expected_columns`, `missing_fields`, la partie colonnes de `contact_payload`. Le compteur `pushed` de l'historique → remplacé par le ledger de reçus.

**Survit, réutilisé** : client HTTP anti-WAF (`api_call`, User-Agent obligatoire) **renforcé** (honorer `Retry-After`/429), écriture d'état atomique (`save_state`), `is_clean_message` (filet anti-message-cassé), `_paginate`, `read_key`, `load_config`.

---

## 2. `load-lead` — chargement composite (étapes 1→4)

Opération atomique au niveau lead. Le workflow W3 boucle dessus ; il ne pilote jamais les appels API un par un.

```
load-lead(lead, variables, campaign_id, list_id)
  0. reçus (campaign_id, lead_key) ──► déjà chargé/lancé ? ──oui──► { skipped: true }
  1. upsert-contact     POST /contacts                          → contact_id (dédup natif linkedinUrl)
  2. add-to-list        POST /contacts/lists/{id}/entities      → audience (liste NON synchronisée)
  3. create-lead        POST /campaigns/{id}/leads?deduplicate=true → lead_id (review ; marche en pause)
  4. set-variables      POST /leads/{id}/variables              → messages free-form (auto-créés)
  ──► écrire le reçu (stage=varset, contact_id, lead_id) ──► { ok, lead_id }
```

**Le lead finit en `review`. Aucun envoi.** Le lancement est l'étape `launch`, séparée et explicite.

**Garanties :**
- **Idempotence par reçu.** Avant de charger, lecture du ledger : un lead déjà chargé (`varset`) ou lancé (`launched`) pour cette campagne → sauté. Run coupé puis relancé = reprise exacte, zéro doublon.
- **Reprise à mi-chaîne.** Le reçu mémorise `contact_id`/`lead_id` + l'étape atteinte ; on ne refait pas les étapes passées. `deduplicate=true` est un second filet.
- **`deduplicate=true` toujours** → si l'email existe dans une autre campagne, Lemlist ne crée pas ; on enregistre `skipped(reason=cross_campaign_email)`.
- **Filet message.** Une variable structurellement cassée (`is_clean_message` faux) → lead rejeté avant l'étape 1.
- **Throttle.** Espacement entre appels pour rester sous 20 req/2s ; sur 429, honorer `Retry-After` + backoff. (Seul mécanisme de rate — cf. §0.)

**Dry-run.** `dry_run: true` (config) **ou** absence de `--confirm` → aucun appel réseau, renvoie le plan. Le chargement réel exige `dry_run: false` **et** `--confirm`.

**Clé de lead** `lead_key` = `linkedinUrl` sinon `email` ; aucun des deux → lead rejeté (impossible à dédupliquer/contacter).

---

## 3. `launch` — lancement (étape 5, gardé)

`POST /leads/review/{id}` par lead ou par lot. **Jamais automatique** (règle dure) : exige `--confirm`. Le lead passe de `review` à la séquence active ; Lemlist étale ensuite l'envoi selon ses *Sending limits* (cf. §0). Met à jour le reçu (`stage=launched`). La garde native de Launch Lead refuse un lead dont une variable requise manque.

---

## 4. `dedup-check` — pré-filtre local (optimisation)

Lit les **reçus** de la verticale et écarte les leads déjà chargés pour cette campagne (`already_loaded`). **Correction tenue ailleurs** : `deduplicate=true` (cross-campagne email) + suppression native (opt-out). `dedup-check` ne fait **aucun appel Lemlist** — pur local, pour éviter des `create-lead` inutiles. Sortie : `{allowed[], skipped[{lead, reason}]}`.

---

## 5. État machine — trois fichiers, un dossier

`~/.claude/outreach/<slug>/` (jamais le Drive) :

| Fichier | Contenu | Écrit par |
|---|---|---|
| `state.json` | `page_cursor` (position dans le pool People DB), `history`, `last_run` | `source` (curseur), `record-run` (historique) |
| `status.json` | phases (`phase1_done`, `w2_steps[]`, `edit_in_progress`, `last_run`) | `status` |
| `receipts.jsonl` | ledger : `{ts, campaign_id, lead_key, contact_id, lead_id, stage, ok}` | `load-lead`, `launch` |

`lead_key` = `linkedinUrl` sinon `email`. Ledger append-only ; lecture = repli sur la dernière ligne par (campaign_id, lead_key) → crash-safe. C'est la source d'idempotence ET le compteur de chargements/lancements.

---

## 6. Contrats config & registre

```jsonc
// campaign.json (verticale, Drive) — lu par le moteur
{ "campaign_id":"cam_…", "slug":"agence-immo", "list_id":"clt_…",
  "state_dir":"~/.claude/outreach/agence-immo",
  "api_key_file":"~/.claude/linkedin-prospect.local.md",
  "sequence":["icebreaker","followup","closing"],
  "dry_run":false, "sourcing_size":50 }

// campaigns-registry.json (racine Prospection, Drive) — lu par resolve
[ { "slug":"agence-immo", "campaign_id":"cam_…", "folder":"Agence Immo",
    "channels":["linkedin","email"], "status":"active", "config_path":"…/campaign.json" } ]
```

Le moteur **lit** ces fichiers, il ne les possède pas (SSoT : l'intelligence métier vit dans le Drive).

---

## 7. Surface API Lemlist mobilisée

`POST /contacts` (upsert) · `POST /contacts/lists/{id}/entities` (add-to-list) · `POST /campaigns/{id}/leads?deduplicate=true` (create-lead) · `POST /leads/{id}/variables` (set-variables) · `POST /leads/review/{id}` (launch) · `GET /campaigns/{id}` + `/leads` (fetch) · `GET /team` (pré-vol auth). Tous via `api_call` (User-Agent obligatoire ; 429 → `Retry-After` + backoff).

---

## 8. Gestion d'erreur

- **Pré-vol** : `GET /team` au `prepare` → STOP si auth KO ; prompt manquant/vide → STOP.
- **429** : honorer `Retry-After`, backoff exponentiel, retry borné (cf. §0 — seul throttle).
- **Par lead** : une étape qui échoue arrête *ce* lead (reçu à `stage_reached`), n'interrompt pas le lot ; erreur collectée, rendue ; le lead reprend au prochain run.
- **Écritures d'état** : toujours atomiques (tmp + replace).

---

## 9. Tests (pytest, `tests/`)

Fonctions pures + transitions, `api_call` mocké :
- `load-lead` : idempotence (reçu → skip), reprise à mi-chaîne, dry-run (zéro réseau), filet message, gestion 429/`Retry-After`, `deduplicate` skip.
- `launch` : refus sans `--confirm`, mise à jour reçu, lot.
- `dedup-check` : `already_loaded` (pur local, reçus).
- `record-run` : append historique, atomicité.
- `resolve` : slug connu / inconnu / via campaign_id inverse.
- `status` : get/set, reprise.

Conserver/adapter les tests v1 pertinents. Lancement : `uv run --with pytest python -m pytest`.

---

## 10. Structure de code (blueprint senior-architect)

`scripts/routine.py` = **shim CLI mince** (entrée stable `python3 scripts/routine.py <cmd>`) qui importe le package `scripts/prospect_engine/`.

```
scripts/routine.py                 # shim : sys.path + prospect_engine.cli.main()
scripts/prospect_engine/
  __init__.py
  cli.py        # argparse + dispatch ; cmd_* lisent fichiers, appellent les modules, print JSON
  config.py     # load_config(path)->(cfg,prompts) · read_key(path) · resolve_campaign(registry, slug|id)
  lemlist.py    # api_call(method,route,key,body,*,max_retries) [UA + 429/Retry-After backoff] · paginate
                #   + wrappers : upsert_contact · add_to_list · create_lead(deduplicate=True) · set_variables · launch_lead · get_campaign(+leads) · get_team
  state.py      # load_state · save_state(atomic) · apply_commit · load/save_status · status_get/set
  receipts.py   # lead_key(lead)->linkedinUrl|email · append_receipt · read_ledger(fold latest par (cid,key)) · lookup
  delivery.py   # is_clean_message · contact_payload · build_load_plan · load_lead(resume via reçu) · launch_leads
  dedup.py      # dedup_check(leads, ledger, campaign_id, seen) -> {allowed, skipped}  (pur, zéro réseau)
```

**Frontières** : `lemlist.py` = seul à faire du réseau ; `delivery.py` orchestre (lemlist + receipts) la chaîne C avec reprise ; `dedup.py`/`state.py`/`receipts.py` = purs/local, testables sans mock ; `cli.py` = glue I/O only. Dépendances : `cli → {config, delivery, dedup, state, fetch}` ; `delivery → {lemlist, receipts, state}` ; jamais l'inverse.

**Schéma reçu** (`receipts.jsonl`) : `{ts, campaign_id, lead_key, contact_id, lead_id, stage∈[upserted,listed,created,varset,launched], ok, error}`. **Reprise** : `load_lead` lit `lookup` → `varset|launched` = skip ; `upserted|listed|created` = reprise à l'étape suivante (réutilise contact_id/lead_id) ; sinon frais.

**Erreurs** : fatal (auth/config/prompt) → `SystemExit("STOP: …")` ; 429 → `Retry-After`+backoff borné dans `api_call` ; erreur par lead → collectée dans le résultat, jamais levée (le lead reprend au run suivant).

---

## 11. Hors-scope (specs ultérieures)

Sourcing People DB (+ lecture du quota `limitation`), scoring `icpFit`, rédaction, orchestration de lot, graders : tout ça vit dans les workflows (specs 02+). Le moteur ne fait que l'IO et l'état.
