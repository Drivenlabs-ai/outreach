# SP-A — Édition du ciblage : Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Donner à une campagne existante un flux « modifier le ciblage » piloté en langage naturel — Claude traduit l'intention en filtres People DB ± prompt icpFit, valide sur échantillon, puis écrit après go ; côté moteur, un seul primitive neuf (commande `cursor`) + l'exposition de `total` au sourcing.

**Architecture:** Moteur fin, orchestration épaisse. Le moteur déterministe (`scripts/prospect_engine/`) gagne deux choses testables : `state.set_cursor` + la commande CLI `cursor` (reset/set/get), et l'exposition de `total` dans `sourcing.source`. Tout le reste — comprendre l'intention NL, traduire en filtres, boucler la validation via `icp-check`, décider du reset curseur — vit dans une nouvelle skill `edit-campaign` (prose pilotée par Claude, pas de code). Le routeur recâble `§Modifier` vers cette skill.

**Tech Stack:** Python 3 (moteur + pytest), exécuté via `uv`. La skill et le routeur sont des fichiers Markdown lus par un modèle. Aucun changement JS.

## Global Constraints

- **Python via `uv` uniquement** — jamais `python3` / `pip` direct. Tests : `uv run --with pytest python -m pytest -q`.
- **Suites vertes avant chaque commit** — Python (ci-dessus) ET JS (`node --test 'tests/js/**/*.test.js'`, inchangé ici mais doit rester vert).
- **Un commit par tâche. NE PAS pusher.** Branche de travail : `v1.5-sp-a-edit-targeting` (déjà créée).
- **Commentaires Python en français** — comme les fichiers voisins du moteur.
- **100% local dans SP-A** — zéro mutation Lemlist, zéro launch, zéro contact.
- **Fichiers lus par un modèle** (SKILL.md, routeur) — invoquer `superpowers:writing-prompts` AVANT de les écrire/modifier (Tasks 3–4).
- **Règle du curseur** (portée par la skill, Task 3) — `cursor --reset` uniquement si les **filtres** ont changé ; un changement d'**icpFit seul** ne reset pas.

---

### Task 1: Commande `cursor` — primitive d'état (state.set_cursor + CLI)

**Files:**
- Modify: `scripts/prospect_engine/state.py` (ajouter `set_cursor`, après les helpers `status_*`)
- Modify: `scripts/prospect_engine/cli.py` (ajouter `cmd_cursor` + le sous-parser `cursor`)
- Test: `tests/test_state.py`, `tests/test_cli.py`

**Interfaces:**
- Consumes: `state.load_state(state_dir) -> dict`, `state.save_state(state_dir, dict)` (existants).
- Produces:
  - `state.set_cursor(state_dir, value) -> value` — charge l'état (défaut si absent), pose `page_cursor=value`, sauve atomiquement, renvoie `value`. Préserve `last_run` / `history`.
  - Commande CLI `cursor --config <p> [--reset | --set <int>]` → imprime `{"page_cursor": <int>}` ; sans flag → imprime la valeur courante.

- [ ] **Step 1: Écrire les tests d'état qui échouent**

Ajouter à `tests/test_state.py` :

```python
def test_set_cursor_writes_page_cursor_and_preserves_rest(tmp_path):
    state.save_state(str(tmp_path), {"page_cursor": 7, "last_run": "2026-06-15", "history": [{"x": 1}]})
    assert state.set_cursor(str(tmp_path), 1) == 1
    st = state.load_state(str(tmp_path))
    assert st["page_cursor"] == 1
    assert st["last_run"] == "2026-06-15" and st["history"] == [{"x": 1}]


def test_set_cursor_on_absent_state_creates_default(tmp_path):
    assert state.set_cursor(str(tmp_path / "fresh"), 5) == 5
    assert state.load_state(str(tmp_path / "fresh")) == {"page_cursor": 5, "last_run": None, "history": []}
```

- [ ] **Step 2: Lancer pour vérifier l'échec**

Run: `uv run --with pytest python -m pytest tests/test_state.py -q`
Expected: FAIL — `AttributeError: module 'prospect_engine.state' has no attribute 'set_cursor'`.

- [ ] **Step 3: Implémenter `set_cursor`**

Dans `scripts/prospect_engine/state.py`, ajouter à la fin (après `status_get`) :

```python
def set_cursor(state_dir, value):
    """Pose le curseur de page (state.json), écriture atomique. Préserve history/last_run.
    Seul point d'écriture du curseur hors du run (le run l'avance via save_state au sourcing)."""
    st = load_state(state_dir)
    st["page_cursor"] = value
    save_state(state_dir, st)
    return value
```

- [ ] **Step 4: Lancer pour vérifier le passage**

Run: `uv run --with pytest python -m pytest tests/test_state.py -q`
Expected: PASS.

- [ ] **Step 5: Écrire les tests CLI qui échouent**

Ajouter à `tests/test_cli.py` (le helper `run(...)` et `_campaign(tmp_path)` existent déjà en haut du fichier) :

```python
def test_cli_cursor_reset_sets_to_one(tmp_path):
    from prospect_engine import state
    cfg = _campaign(tmp_path)
    sd = json.loads(Path(cfg).read_text())["state_dir"]
    state.save_state(sd, {"page_cursor": 9, "last_run": None, "history": []})
    r = run("cursor", "--config", cfg, "--reset")
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout) == {"page_cursor": 1}
    assert state.load_state(sd)["page_cursor"] == 1


def test_cli_cursor_set_then_get(tmp_path):
    cfg = _campaign(tmp_path)
    rs = run("cursor", "--config", cfg, "--set", "12")
    assert rs.returncode == 0, rs.stderr
    assert json.loads(rs.stdout) == {"page_cursor": 12}
    rg = run("cursor", "--config", cfg)
    assert rg.returncode == 0, rg.stderr
    assert json.loads(rg.stdout) == {"page_cursor": 12}


def test_cli_cursor_leaves_status_untouched(tmp_path):
    from prospect_engine import state
    cfg = _campaign(tmp_path)
    sd = json.loads(Path(cfg).read_text())["state_dir"]
    state.status_set(sd, "phase1_done", True)
    run("cursor", "--config", cfg, "--reset")
    assert state.load_status(sd) == {
        "phase1_done": True, "w2_steps": [], "edit_in_progress": False, "last_run": None}
```

- [ ] **Step 6: Lancer pour vérifier l'échec**

Run: `uv run --with pytest python -m pytest tests/test_cli.py -q -k cursor`
Expected: FAIL — `routine.py: error: argument cmd: invalid choice: 'cursor'` (returncode ≠ 0).

- [ ] **Step 7: Implémenter `cmd_cursor` + le sous-parser**

Dans `scripts/prospect_engine/cli.py`, ajouter la commande après `cmd_source` :

```python
def cmd_cursor(a):
    cfg = config.load_cfg_only(a.config)
    sd = cfg["state_dir"]
    if a.reset:
        _emit({"page_cursor": state.set_cursor(sd, 1)})
    elif a.set is not None:
        _emit({"page_cursor": state.set_cursor(sd, a.set)})
    else:
        _emit({"page_cursor": state.load_state(sd).get("page_cursor", 1)})
```

Et enregistrer le sous-parser dans `build_parser()` (après la ligne du parser `source`) :

```python
    p = sub.add_parser("cursor"); p.add_argument("--config", required=True); p.add_argument("--reset", action="store_true"); p.add_argument("--set", type=int, default=None, dest="set"); p.set_defaults(fn=cmd_cursor)
```

- [ ] **Step 8: Lancer pour vérifier le passage**

Run: `uv run --with pytest python -m pytest tests/test_cli.py -q -k cursor`
Expected: PASS (3 tests).

- [ ] **Step 9: Suite complète + commit**

Run: `uv run --with pytest python -m pytest -q`
Expected: tous PASS.

```bash
git add scripts/prospect_engine/state.py scripts/prospect_engine/cli.py tests/test_state.py tests/test_cli.py
git commit -m "moteur — commande cursor (state.set_cursor + CLI reset/set/get) (TDD)"
```

---

### Task 2: `source` expose `total` (taille du pool)

**Files:**
- Modify: `scripts/prospect_engine/sourcing.py` (les deux `return` de `source`)
- Test: `tests/test_sourcing.py`

**Interfaces:**
- Consumes: `lemlist.search_people(key, filters, page, size) -> (status, dict)` ; le `dict` People DB porte `total` (taille du pool filtré) — vérifié sur le compte agence-immo (15 576).
- Produces: `sourcing.source(...)` ajoute `"total"` à son retour : `res.get("total")` sur succès, `None` sur erreur. Champ additif — `cmd_source` l'émet déjà tel quel (`_emit(out)`), aucun changement CLI nécessaire.

- [ ] **Step 1: Écrire les tests qui échouent**

Ajouter à `tests/test_sourcing.py` (le helper `_r(...)` existe déjà) :

```python
def test_source_exposes_total(monkeypatch):
    monkeypatch.setattr(lemlist, "search_people",
                        lambda *a, **k: (200, {"results": [_r("https://lk/a")], "limitation": 1, "total": 15576}))
    out = sourcing.source("KEY", [], cursor=1, target=1)
    assert out["total"] == 15576


def test_source_total_none_on_error(monkeypatch):
    monkeypatch.setattr(lemlist, "search_people", lambda *a, **k: (400, "Parameter filters is invalid"))
    out = sourcing.source("KEY", [], cursor=1, target=1)
    assert out["total"] is None and out["exhausted"] is True
```

- [ ] **Step 2: Lancer pour vérifier l'échec**

Run: `uv run --with pytest python -m pytest tests/test_sourcing.py -q -k total`
Expected: FAIL — `KeyError: 'total'`.

- [ ] **Step 3: Ajouter `total` aux deux retours**

Dans `scripts/prospect_engine/sourcing.py`, fonction `source` :

Retour d'erreur (status ≠ 200) — ajouter `"total": None` :

```python
    if st != 200 or not isinstance(res, dict):
        return {"candidats": [], "limitation": None, "next_cursor": cursor + 1, "exhausted": True, "total": None}
```

Retour de succès — ajouter `"total": res.get("total")` :

```python
    return {"candidats": candidats[:target], "limitation": res.get("limitation"),
            "next_cursor": cursor + 1, "exhausted": len(results) < target, "total": res.get("total")}
```

- [ ] **Step 4: Lancer pour vérifier le passage**

Run: `uv run --with pytest python -m pytest tests/test_sourcing.py -q`
Expected: PASS (les tests existants n'asssertent pas `total` → inchangés ; les 2 nouveaux passent).

- [ ] **Step 5: Suite complète + commit**

Run: `uv run --with pytest python -m pytest -q`
Expected: tous PASS.

```bash
git add scripts/prospect_engine/sourcing.py tests/test_sourcing.py
git commit -m "sourcing — expose total (taille du pool) au retour de source (TDD)"
```

---

### Task 3: Skill `edit-campaign` — orchestration NL du ciblage

**Files:**
- Create: `skills/edit-campaign/SKILL.md`

**Interfaces:**
- Consumes (commandes moteur déjà livrées) : `resolve`, `source` (renvoie `total`, Task 2), `status --set edit_in_progress=…`, `cursor --reset` (Task 1) ; workflow `icp-check` (`args={prompt_icpFit, sample, model:"haiku"}` → `{verdicts:[{lead,qualifie,raison}]}`).
- Produces: un skill prose qui déclenche sur l'intention « affiner le ciblage » et orchestre le flux resolve→lire→comprendre→traduire→valider→committer→confirmer.

Pas de test unitaire (fichier prose lu par un modèle). Vérification = relecture + déclenchement.

- [ ] **Step 1: Invoquer `superpowers:writing-prompts`**

Charger la skill `superpowers:writing-prompts` avant d'écrire le fichier (c'est un fichier lu par un modèle).

- [ ] **Step 2: Écrire `skills/edit-campaign/SKILL.md`**

Contenu cible (ajuster la formulation au passage writing-prompts, garder la substance) :

```markdown
---
name: edit-campaign
description: Déclencher quand l'utilisateur veut modifier ou affiner le CIBLAGE d'une campagne de prospection existante — « affine le ciblage de X », « vise plutôt les Y », « exclus les Z », « resserre/élargis l'ICP », « change les filtres », « le ciblage est trop large ». Couvre les filtres People DB et le prompt icpFit, validés sur échantillon avant tout commit. Ne pas déclencher pour créer une campagne (→ new-campaign) ni pour le run quotidien (→ prospect-routine) ; modifier la séquence, le timing ou la config n'est pas encore couvert (backlog SP-B/SP-C).
---

# edit-campaign — affiner le ciblage d'une campagne existante

## Vue d'ensemble

Affine QUI une campagne cible, sans toucher Lemlist. L'utilisateur exprime son intention en langage
naturel (« vise les agences à plusieurs négociateurs, exclus les indépendants ») ; toi (Claude de
session) tu portes toute la complexité : tu traduis en filtres + ajustes l'icpFit, tu valides sur un
échantillon, et tu n'écris qu'après son go. L'utilisateur ne voit jamais un `filterId` ni un JSON.

Le ciblage a deux leviers, tous deux **locaux** :

| Levier | Quoi | Où |
|---|---|---|
| Filtres People DB | ciblage DUR : qui entre dans le funnel | `campaign.json` → `filters` |
| Prompt icpFit | ciblage MOU : qui passe le jugement IA parmi les sourcés | `prompts/icpFit.md` |

**Commandes moteur** : via `uv run python scripts/routine.py <cmd>` (jamais `python3`).

## Quand l'utiliser

- L'utilisateur veut **affiner / resserrer / élargir / corriger le ciblage** d'une campagne existante.
- Pas pour : créer une campagne (→ `new-campaign`), faire tourner le run (→ `prospect-routine`),
  modifier la séquence / le timing / la config (pas encore couvert — cf. Périmètre).

## Le flux

\`\`\`
1. resolve     resolve --registry <Prospection/campaigns-registry.json> --slug <ce que dit l'utilisateur>
                → campaign_id + config_path. Slug introuvable → demander lequel.
2. lire        l'état actuel : filters (campaign.json) + prompts/icpFit.md + fichiers d'intelligence
                (icp.md, persona.md, triggers.md) pour le contexte.
3. comprendre  reformule l'intention jusqu'à être sûr de ce qui change dans le ciblage.
4. traduire    nouveaux filtres People DB (craft /lemlist §3 ; valide filterId/valeurs via
                get-database-filters) et/ou ajuste prompts/icpFit.md. Ne rien écrire encore.
5. valider     status --config <config_path> --set edit_in_progress=true
                source --config <config_path> --target <N>  → taille du nouveau pool (total) + échantillon
                  total 0 / exhausted → filtre trop étroit ou invalide : corrige, ne committe pas.
                workflow icp-check : args = { prompt_icpFit: <icpFit édité>, sample: <candidats>,
                  model: "haiku" } → lis les verdicts, compare à l'ICP visé, itère. Boucle bornée, sign-off.
6. committer   APRÈS go explicite : écris les nouveaux filters dans campaign.json et le nouvel icpFit.md.
                Si les FILTRES ont changé → cursor --config <config_path> --reset (icpFit seul → pas de reset).
                status --config <config_path> --set edit_in_progress=false
7. confirmer   résume : ancien → nouveau ciblage, nouvelle taille de pool, état du curseur.
\`\`\`

## Règle du curseur

Changer les **filtres** change le pool : le curseur (position dans l'ancien ordre) devient caduc →
`cursor --reset` (retour page 1, re-sweep du nouveau pool). Coût : re-score one-shot des survivants ;
**jamais** de double-contact (filtre `out` « déjà en campagne » + receipts couvrent). Changer l'**icpFit
seul** ne touche pas le pool → pas de reset.

## Garanties / garde

- **100% local. Zéro mutation Lemlist, zéro launch, zéro contact.**
- **Validation avant commit** : prévisualisation (taille de pool) + icp-check sur échantillon frais est la
  norme ; on ne committe pas un ciblage à l'aveugle. L'alléger pour un tweak trivial est explicite, jamais
  un saut silencieux.
- **Anti-écrasement** : `filters` et `icpFit.md` ne sont écrits qu'après validation + go explicite.
- **Reprise** : `edit_in_progress` (status.json) à `true` pendant l'édition, `false` au commit/abandon.

## Périmètre

SP-A = ciblage (filtres + icpFit). Pas encore couvert, en suite :
- **SP-B** — modifier la séquence (étapes, corps des messages, timing) : API Lemlist, à cadrer.
- **SP-C** — config / état (pause/reprise, réglages campagne, cadence de sourcing, modèles).
- **SP-D** — dupliquer une verticale vers un nouveau segment puis ajuster.

## Référence

- Craft ICP → filtres People DB : `/lemlist` §3 (filterId / in / out, get-database-filters).
- Contrat icp-check : `args = {prompt_icpFit, sample, model:"haiku"}` → `{verdicts:[{lead, qualifie, raison}]}`.
- Commandes moteur : `resolve`, `source` (renvoie `total`), `status --set edit_in_progress`, `cursor --reset`.
```

> Note : dans le fichier réel, les trois `\`\`\`` échappés ci-dessus sont des blocs de code normaux (le bloc « Le flux »). L'échappement n'est là que pour l'imbrication dans ce plan.

- [ ] **Step 3: Vérifier le déclenchement et la cohérence**

Relire le fichier : la `description` porte des triggers concrets (« affine le ciblage », « vise plutôt », « exclus les ») et exclut new-campaign / run / séquence. Aucune affirmation fausse sur l'API. Le flux référence uniquement des commandes livrées (Tasks 1–2) + `icp-check`.

- [ ] **Step 4: Suites vertes (rien de cassé) + commit**

Run: `uv run --with pytest python -m pytest -q && node --test 'tests/js/**/*.test.js'`
Expected: tous PASS (aucun code touché — garde-fou).

```bash
git add skills/edit-campaign/SKILL.md
git commit -m "edit-campaign — skill d'édition du ciblage (filtres + icpFit, orchestration NL)"
```

---

### Task 4: Recâbler le routeur `§Modifier` + README

**Files:**
- Modify: `skills/prospect-routine/SKILL.md` (frontmatter `description`, table « Trois intentions », section `## Modifier`)
- Modify: `README.md` (§Composants, §Statut)

**Interfaces:**
- Consumes: la skill `edit-campaign` (Task 3) comme destination de l'intention « modifier le ciblage ».
- Produces: un routeur qui aiguille les éditions de ciblage vers `edit-campaign` et n'affirme plus rien de faux sur l'API Lemlist.

Pas de test unitaire (prose). Vérification = relecture + grep anti-affirmation-fausse.

- [ ] **Step 1: Invoquer `superpowers:writing-prompts`**

Charger `superpowers:writing-prompts` avant d'éditer ces fichiers (lus par un modèle).

- [ ] **Step 2: Mettre à jour la `description` du routeur**

Dans `skills/prospect-routine/SKILL.md`, frontmatter `description`, remplacer la fin « …Créer une campagne de zéro est couvert par le skill new-campaign ; modifier une campagne existante n'est pas encore couvert. » par :

```
Créer une campagne de zéro est couvert par le skill new-campaign ; affiner le ciblage d'une campagne existante par le skill edit-campaign ; modifier la séquence, la config ou dupliquer une verticale n'est pas encore couvert.
```

- [ ] **Step 3: Mettre à jour la table « Trois intentions »**

Remplacer la ligne :

```
| modifier une campagne existante | pas encore couvert — le dire, ne rien muter à la main |
```

par les deux lignes :

```
| modifier le ciblage d'une campagne | skill `edit-campaign` (filtres + icpFit ; il se déclenche seul) |
| modifier séquence / config / dupliquer | pas encore couvert (backlog SP-B/C/D) — le dire, ne rien muter à la main |
```

- [ ] **Step 4: Réécrire la section `## Modifier`**

Remplacer le bloc complet :

```
## Modifier

Modifier une campagne existante (affiner l'ICP, ajouter une étape, changer le timing) n'est pas encore
construit — cela suppose des mutations de séquence Lemlist qui n'existent pas. Le dire à l'utilisateur,
ne pas muter la séquence à la main.
```

par :

```
## Modifier

Affiner le **ciblage** d'une campagne existante (filtres People DB + prompt icpFit) est porté par le skill
`edit-campaign` — y renvoyer (il se déclenche seul sur « affine le ciblage », « vise plutôt X », « exclus
les Y » ; sinon l'y pointer). 100% local, validé sur échantillon avant tout commit.

Les autres éditions ne sont pas encore construites : la **séquence** (étapes, corps des messages, timing —
SP-B), la **config / l'état** (pause/reprise, réglages, cadence — SP-C), et **dupliquer** une verticale
vers un nouveau segment (SP-D). Le dire à l'utilisateur ; ne pas muter la séquence à la main.
```

- [ ] **Step 5: Mettre à jour le README**

Dans `README.md`, §Composants, ajouter après le bullet `skills/new-campaign/` :

```
- `skills/edit-campaign/` — **SP-A** : affine le ciblage d'une campagne existante (filtres People DB + prompt icpFit), validé sur échantillon via `icp-check`. 100% local, zéro mutation Lemlist ; un primitive moteur neuf (`cursor`).
```

Et remplacer la ligne §Statut « Reste : la validation en conditions réelles (run live sur une verticale) et les edits ciblés « modifier une campagne » (v1.5). » par :

```
Run live initial effectué (leads chargés en review). v1.5 « modifier une campagne » en cours : SP-A « modifier le ciblage » (skill `edit-campaign`) livré ; séquence (SP-B), config/état (SP-C), dupliquer-segment (SP-D) au backlog.
```

- [ ] **Step 6: Vérifier l'absence d'affirmation fausse**

Run: `grep -rn "n'existent pas\|n'est pas encore couvert" skills/prospect-routine/SKILL.md`
Expected: plus aucune ligne affirmant que les mutations Lemlist « n'existent pas ». (La mention « pas encore couvert » subsiste uniquement pour séquence/config/dupliquer — légitime.)

- [ ] **Step 7: Suites vertes + commit**

Run: `uv run --with pytest python -m pytest -q && node --test 'tests/js/**/*.test.js'`
Expected: tous PASS.

```bash
git add skills/prospect-routine/SKILL.md README.md
git commit -m "routeur — recâble §Modifier vers edit-campaign (ciblage) + README"
```

---

## Self-Review

**Spec coverage** (`docs/superpowers/specs/2026-06-22-edit-campaign-targeting-design.md`) :
- §Design « primitive moteur neuf : commande `cursor` » → Task 1. ✓
- §Design « source expose total » → Task 2. ✓
- §Design flux 1–7 (resolve→lire→comprendre→traduire→valider→committer→confirmer) → Task 3 (SKILL.md). ✓
- §Design « règle du curseur » (reset si filtres changés, pas si icpFit seul) → Task 1 (primitive) + Task 3 (règle d'orchestration). ✓
- §Design « validation : la norme, jamais sautée en silence » → Task 3, section Garanties. ✓
- §Design « où vit la skill » + §Migration « routeur recâblé » → Task 3 (création) + Task 4 (routeur). ✓
- §État machine « edit_in_progress pour reprise » → Task 3 (flux étapes 5/6 via `status --set`). ✓
- §Critères « plus aucune affirmation fausse sur l'API » → Task 4 Step 6 (grep). ✓
- §Critères « zéro mutation Lemlist » → aucune commande de mutation Lemlist dans aucune tâche ; le flux s'arrête à l'écriture locale + cursor. ✓
- §Hors périmètre (SP-B/C/D) → inscrits dans la skill (Périmètre) et le routeur (table + §Modifier). ✓

**Placeholder scan** : chaque step de code porte le code réel ; les fichiers prose (Tasks 3–4) portent le contenu cible verbatim. Aucun TBD/TODO/« handle edge cases ». ✓

**Type consistency** : `set_cursor(state_dir, value) -> value` cohérent entre Task 1 (def), les tests, et `cmd_cursor` ; le retour CLI `{"page_cursor": int}` cohérent entre `cmd_cursor` et les tests ; `source(...)["total"]` cohérent entre Task 2 (def) et la skill (Task 3 référence `source` « renvoie total »). Commande `cursor --reset` cohérente entre Task 1 (parser) et Task 3 (flux). ✓

**Ordre / dépendances** : Tasks 1–2 (moteur) précèdent Task 3 (skill qui les référence) ; Task 4 (routeur) précédé par Task 3 (cible du routage). ✓
