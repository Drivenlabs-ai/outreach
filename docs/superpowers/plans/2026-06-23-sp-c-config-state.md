# SP-C — Config / état : Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Piloter la config et l'état d'une campagne en langage naturel — pause/reprise + réglages (Lemlist), op-config locale + flip `dry_run` (campaign.json) — et durcir au passage les défauts SP-B remontés en revue (lecture fail-closed, exit non-zéro sur erreur, gate en allowlist).

**Architecture:** Moteur fin + orchestration NL + 3ᵉ facette d'`edit-campaign` (comme SP-A/SP-B). Le moteur gagne 3 wrappers d'I/O (`pause_campaign`, `start_campaign`, `update_campaign`) + leurs commandes CLI ; un helper `_emit_result_or_stop` impose un exit non-zéro sur erreur API à toutes les commandes de mutation (SP-B + SP-C) ; `cmd_sequence` devient fail-closed ; `sequence.ensure_editable` passe en allowlist. L'op-config locale et `dry_run` restent des éditions de `campaign.json` par Claude (aucun code moteur). Lemlist reste source de vérité ; `verify` intact ; run inchangé.

**Tech Stack:** Python 3 (moteur + pytest) via `uv`. Skill + référence + routeur = Markdown lus par un modèle. Aucun changement JS.

## Global Constraints

- **Python via `uv` uniquement** — jamais `python3` / `pip`. Tests : `uv run --with pytest python -m pytest -q`.
- **Suites vertes avant chaque commit** — Python (ci-dessus) ET JS (`node --test 'tests/js/**/*.test.js'`, inchangé, doit rester vert).
- **Un commit par tâche. NE PAS pusher.** Branche : `v1.5-sp-c-config-state` (créée, base main).
- **Commentaires Python en français** — comme les fichiers voisins.
- **Lemlist = source de vérité** ; wrappers pass-through (aucun schéma de body hardcodé : `/lemlist`).
- **Surface NL** : l'utilisateur ne voit jamais un identifiant, un champ d'API ni un JSON (skill, Tasks 4-5).
- **Garde `dry_run`** : flip uniquement sur confirmation explicite (orchestration) ; jamais par le run.
- **Fichiers lus par un modèle** (SKILL.md, référence, routeur, specs) — invoquer `superpowers:writing-prompts` (+ `plugin-dev:skill-development` pour la skill) AVANT de les écrire (Tasks 4-5).

---

### Task 1: Wrappers d'I/O campagne (lemlist.py)

**Files:**
- Modify: `scripts/prospect_engine/lemlist.py` (ajouter 3 wrappers après `update_schedule`)
- Test: `tests/test_lemlist.py`

**Interfaces:**
- Consumes: `api_call(method, route, key, body=None)` (existant).
- Produces (modèle C) :
  - `pause_campaign(key, campaign_id) -> (status, res)` — `POST /campaigns/{campaign_id}/pause` (no body)
  - `start_campaign(key, campaign_id) -> (status, res)` — `POST /campaigns/{campaign_id}/start` (no body)
  - `update_campaign(key, campaign_id, body) -> (status, res)` — `PATCH /campaigns/{campaign_id}`

- [ ] **Step 1: Écrire les tests qui échouent**

Ajouter à `tests/test_lemlist.py` :

```python
def test_pause_campaign_route_method(monkeypatch):
    cap = {}
    def fake(method, route, key, body=None, **kw):
        cap.update(method=method, route=route, body=body); return 200, {"state": "paused"}
    monkeypatch.setattr(lemlist, "api_call", fake)
    lemlist.pause_campaign("KEY", "cam_1")
    assert cap["method"] == "POST" and cap["route"] == "/campaigns/cam_1/pause" and cap["body"] is None


def test_start_campaign_route_method(monkeypatch):
    cap = {}
    def fake(method, route, key, body=None, **kw):
        cap.update(method=method, route=route, body=body); return 200, {"state": "running"}
    monkeypatch.setattr(lemlist, "api_call", fake)
    lemlist.start_campaign("KEY", "cam_1")
    assert cap["method"] == "POST" and cap["route"] == "/campaigns/cam_1/start" and cap["body"] is None


def test_update_campaign_route_method_body(monkeypatch):
    cap = {}
    def fake(method, route, key, body=None, **kw):
        cap.update(method=method, route=route, body=body); return 200, {}
    monkeypatch.setattr(lemlist, "api_call", fake)
    lemlist.update_campaign("KEY", "cam_1", {"stopOnEmailReplied": True})
    assert cap["method"] == "PATCH" and cap["route"] == "/campaigns/cam_1"
    assert cap["body"] == {"stopOnEmailReplied": True}
```

- [ ] **Step 2: Lancer pour vérifier l'échec**

Run: `uv run --with pytest python -m pytest tests/test_lemlist.py -q -k "pause_campaign or start_campaign or update_campaign"`
Expected: FAIL — `AttributeError: module 'prospect_engine.lemlist' has no attribute 'pause_campaign'`.

- [ ] **Step 3: Implémenter les 3 wrappers**

Dans `scripts/prospect_engine/lemlist.py`, après `update_schedule` :

```python
def pause_campaign(key, campaign_id):
    """Met une campagne en pause (arrête l'envoi). No-op si elle ne tourne pas. Sans body."""
    return api_call("POST", f"/campaigns/{campaign_id}/pause", key)


def start_campaign(key, campaign_id):
    """Démarre/reprend une campagne (état → running). No-op si déjà running. Sans body. C'est le start
    campagne-level (moteur d'envoi), distinct du lead-launch (`launch_lead`)."""
    return api_call("POST", f"/campaigns/{campaign_id}/start", key)


def update_campaign(key, campaign_id, body):
    """Édite les réglages d'une campagne (PATCH). `body` pass-through (stop-conditions, sendUserIds,
    tracking, autoReview… — cf. doc live `/lemlist`). Aucun schéma hardcodé ici."""
    return api_call("PATCH", f"/campaigns/{campaign_id}", key, body)
```

- [ ] **Step 4: Lancer pour vérifier le passage**

Run: `uv run --with pytest python -m pytest tests/test_lemlist.py -q`
Expected: PASS.

- [ ] **Step 5: Suite complète + commit**

Run: `uv run --with pytest python -m pytest -q`
Expected: tous PASS.

```bash
git add scripts/prospect_engine/lemlist.py tests/test_lemlist.py
git commit -m "lemlist — wrappers pause/start/update campagne (TDD)"
```

---

### Task 2: Durcissement SP-B (gate allowlist + lecture fail-closed + exit non-zéro)

**Files:**
- Modify: `scripts/prospect_engine/sequence.py` (`ensure_editable` → allowlist)
- Modify: `scripts/prospect_engine/cli.py` (`cmd_sequence` fail-closed ; helper `_emit_result_or_stop` ; appliqué aux 4 commandes de mutation SP-B)
- Test: `tests/test_sequence.py`, `tests/test_cli.py`

**Interfaces:**
- Produces:
  - `sequence.EDITABLE_STATES` (set) + `ensure_editable` éditable **uniquement** si `status` ∈ EDITABLE_STATES.
  - `cli._emit_result_or_stop(st, res)` — émet `{status, result}` puis `raise SystemExit(1)` si `st` hors 2xx.
  - `cmd_sequence` : `raise SystemExit` si la lecture est non-200.

- [ ] **Step 1: Écrire les tests qui échouent (sequence.py allowlist)**

Ajouter à `tests/test_sequence.py` :

```python
def test_ensure_editable_blocks_empty_and_unknown_status():
    import pytest as _pytest
    with _pytest.raises(sequence.CampaignActive):
        sequence.ensure_editable({"status": ""})
    with _pytest.raises(sequence.CampaignActive):
        sequence.ensure_editable({"status": "some_new_label"})


def test_ensure_editable_allows_known_safe_states():
    for s in ("paused", "draft", "ended", "archived", "errors"):
        assert sequence.ensure_editable({"status": s}) == s
```

- [ ] **Step 2: Lancer pour vérifier l'échec**

Run: `uv run --with pytest python -m pytest tests/test_sequence.py -q -k "empty_and_unknown or known_safe"`
Expected: FAIL — `ensure_editable({"status": ""})` ne lève pas (le code actuel ne bloque que `None`).

- [ ] **Step 3: Implémenter l'allowlist**

Dans `scripts/prospect_engine/sequence.py`, remplacer `ensure_editable` :

```python
EDITABLE_STATES = {"paused", "draft", "ended", "archived", "errors"}


def ensure_editable(campaign):
    """Garde dure avant toute mutation de séquence. Éditable UNIQUEMENT si `status` est un état connu non
    en envoi (`EDITABLE_STATES`). Tout le reste bloque — `running` (envoi actif), `None`, `""`, ou un label
    inconnu : on ne mute jamais à l'aveugle. Renvoie le `status` si éditable."""
    status = (campaign or {}).get("status")
    if status == "running":
        raise CampaignActive("campagne active (running) — mets-la en pause avant d'éditer la séquence")
    if status not in EDITABLE_STATES:
        raise CampaignActive(f"état de campagne non éditable (status={status!r}) — refusé par sécurité")
    return status
```

- [ ] **Step 4: Lancer (les tests sequence existants + nouveaux passent)**

Run: `uv run --with pytest python -m pytest tests/test_sequence.py -q`
Expected: PASS (les anciens — running/None/paused/draft — restent verts ; les 2 nouveaux passent).

- [ ] **Step 5: Écrire les tests qui échouent (cli : fail-closed + exit non-zéro)**

Ajouter à `tests/test_cli.py` :

```python
def test_cmd_sequence_stops_on_read_failure(monkeypatch):
    from prospect_engine import cli, config, lemlist
    cfg = {"api_key_file": "x", "campaign_id": "cam_1"}
    monkeypatch.setattr(config, "load_cfg_only", lambda p: cfg)
    monkeypatch.setattr(config, "read_key", lambda p: "KEY")
    monkeypatch.setattr(lemlist, "get_campaign_sequences", lambda key, cid: (401, "unauthorized"))
    class A: config = "x"
    with __import__("pytest").raises(SystemExit):
        cli.cmd_sequence(A())


def test_cmd_delete_step_exits_nonzero_on_api_error(monkeypatch):
    from prospect_engine import cli, config, lemlist
    cfg = {"api_key_file": "x", "campaign_id": "cam_1"}
    monkeypatch.setattr(config, "load_cfg_only", lambda p: cfg)
    monkeypatch.setattr(config, "read_key", lambda p: "KEY")
    monkeypatch.setattr(lemlist, "get_campaign", lambda key, cid: (200, {"status": "paused"}))
    monkeypatch.setattr(lemlist, "delete_step", lambda *a, **k: (404, "Step not found"))
    class A:
        config = "x"; sequence_id = "seq_1"; step_id = "stp_x"
    with __import__("pytest").raises(SystemExit):
        cli.cmd_delete_step(A())
```

- [ ] **Step 6: Lancer pour vérifier l'échec**

Run: `uv run --with pytest python -m pytest tests/test_cli.py -q -k "stops_on_read_failure or exits_nonzero"`
Expected: FAIL — `cmd_sequence` n'émet pas d'erreur sur 401 ; `cmd_delete_step` sort en 0 sur 404.

- [ ] **Step 7: Implémenter le fail-closed + le helper exit-non-zéro**

Dans `scripts/prospect_engine/cli.py` : ajouter le helper près de `_emit` :

```python
def _emit_result_or_stop(st, res):
    """Émet le résultat d'une mutation puis sort en code non-zéro si l'API a échoué (status hors 2xx) —
    la règle « stop on partial failure » devient imposée, pas seulement documentée."""
    _emit({"status": st, "result": res})
    if not (200 <= st < 300):
        raise SystemExit(1)
```

Réécrire `cmd_sequence` (fail-closed) :

```python
def cmd_sequence(a):
    cfg = config.load_cfg_only(a.config)
    key = config.read_key(cfg["api_key_file"])
    st, res = lemlist.get_campaign_sequences(key, cfg["campaign_id"])
    if st != 200:
        raise SystemExit(f"STOP: lecture de la séquence → {st} (lecture KO ; on n'édite pas à l'aveugle)")
    _emit({"steps": sequence.summarize(res)})
```

Dans `cmd_add_step`, `cmd_update_step`, `cmd_delete_step`, `cmd_edit_schedule`, remplacer la dernière ligne
`st, res = lemlist.<...>(...)` suivie de `_emit({"status": st, "result": res})` par un appel via le helper.
Exemple pour `cmd_delete_step` :

```python
def cmd_delete_step(a):
    cfg = config.load_cfg_only(a.config)
    key = config.read_key(cfg["api_key_file"])
    _editable_or_stop(key, cfg["campaign_id"])
    st, res = lemlist.delete_step(key, a.sequence_id, a.step_id)
    _emit_result_or_stop(st, res)
```

Appliquer le même remplacement (`_emit_result_or_stop(st, res)` à la place de `_emit({"status": st, "result": res})`) à `cmd_add_step`, `cmd_update_step`, `cmd_edit_schedule`.

- [ ] **Step 8: Lancer pour vérifier le passage**

Run: `uv run --with pytest python -m pytest tests/test_cli.py -q`
Expected: PASS (les tests SP-B existants — gate bloqué, pass-when-paused — restent verts ; les 2 nouveaux passent).

- [ ] **Step 9: Suite complète + commit**

Run: `uv run --with pytest python -m pytest -q`
Expected: tous PASS.

```bash
git add scripts/prospect_engine/sequence.py scripts/prospect_engine/cli.py tests/test_sequence.py tests/test_cli.py
git commit -m "durcissement SP-B — gate allowlist + cmd_sequence fail-closed + exit non-zéro sur erreur API (revue, TDD)"
```

---

### Task 3: Commandes CLI config/état (pause / resume / update-campaign)

**Files:**
- Modify: `scripts/prospect_engine/cli.py` (`cmd_campaign_pause`, `cmd_campaign_resume`, `cmd_update_campaign` + sous-parsers)
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `lemlist.{pause_campaign, start_campaign, update_campaign}` (Task 1), `cli._emit_result_or_stop` (Task 2), `config.{load_cfg_only, read_key}`.
- Produces: commandes `campaign-pause`, `campaign-resume`, `update-campaign` (body depuis `--input`). Toutes émettent via `_emit_result_or_stop` (exit non-zéro sur erreur). Pas de gate « doit être en pause » (pause/réglages sont sûrs).

- [ ] **Step 1: Écrire les tests qui échouent**

Ajouter à `tests/test_cli.py` :

```python
def test_cmd_campaign_pause_calls_wrapper(monkeypatch, capsys):
    from prospect_engine import cli, config, lemlist
    cfg = {"api_key_file": "x", "campaign_id": "cam_1"}
    monkeypatch.setattr(config, "load_cfg_only", lambda p: cfg)
    monkeypatch.setattr(config, "read_key", lambda p: "KEY")
    cap = {}
    monkeypatch.setattr(lemlist, "pause_campaign", lambda key, cid: cap.update(cid=cid) or (200, {"state": "paused"}))
    class A: config = "x"
    cli.cmd_campaign_pause(A())
    assert cap["cid"] == "cam_1" and json.loads(capsys.readouterr().out)["status"] == 200


def test_cmd_campaign_resume_calls_start(monkeypatch, capsys):
    from prospect_engine import cli, config, lemlist
    cfg = {"api_key_file": "x", "campaign_id": "cam_1"}
    monkeypatch.setattr(config, "load_cfg_only", lambda p: cfg)
    monkeypatch.setattr(config, "read_key", lambda p: "KEY")
    cap = {}
    monkeypatch.setattr(lemlist, "start_campaign", lambda key, cid: cap.update(cid=cid) or (200, {"state": "running"}))
    class A: config = "x"
    cli.cmd_campaign_resume(A())
    assert cap["cid"] == "cam_1"


def test_cmd_update_campaign_passes_body(monkeypatch, tmp_path, capsys):
    from prospect_engine import cli, config, lemlist
    cfg = {"api_key_file": "x", "campaign_id": "cam_1"}
    monkeypatch.setattr(config, "load_cfg_only", lambda p: cfg)
    monkeypatch.setattr(config, "read_key", lambda p: "KEY")
    cap = {}
    monkeypatch.setattr(lemlist, "update_campaign", lambda key, cid, body: cap.update(cid=cid, body=body) or (200, {}))
    body = tmp_path / "b.json"; body.write_text(json.dumps({"stopOnEmailReplied": True}))
    class A:
        config = "x"; input = str(body)
    cli.cmd_update_campaign(A())
    assert cap["cid"] == "cam_1" and cap["body"] == {"stopOnEmailReplied": True}


def test_cmd_campaign_pause_exits_nonzero_on_error(monkeypatch, capsys):
    from prospect_engine import cli, config, lemlist
    cfg = {"api_key_file": "x", "campaign_id": "cam_1"}
    monkeypatch.setattr(config, "load_cfg_only", lambda p: cfg)
    monkeypatch.setattr(config, "read_key", lambda p: "KEY")
    monkeypatch.setattr(lemlist, "pause_campaign", lambda key, cid: (403, "blocked"))
    class A: config = "x"
    with __import__("pytest").raises(SystemExit):
        cli.cmd_campaign_pause(A())
```

- [ ] **Step 2: Lancer pour vérifier l'échec**

Run: `uv run --with pytest python -m pytest tests/test_cli.py -q -k "campaign_pause or campaign_resume or update_campaign"`
Expected: FAIL — `AttributeError: module 'prospect_engine.cli' has no attribute 'cmd_campaign_pause'` (+ `invalid choice`).

- [ ] **Step 3: Implémenter les commandes + sous-parsers**

Dans `scripts/prospect_engine/cli.py`, ajouter (après `cmd_edit_schedule`) :

```python
def cmd_campaign_pause(a):
    cfg = config.load_cfg_only(a.config)
    key = config.read_key(cfg["api_key_file"])
    st, res = lemlist.pause_campaign(key, cfg["campaign_id"])
    _emit_result_or_stop(st, res)


def cmd_campaign_resume(a):
    cfg = config.load_cfg_only(a.config)
    key = config.read_key(cfg["api_key_file"])
    st, res = lemlist.start_campaign(key, cfg["campaign_id"])
    _emit_result_or_stop(st, res)


def cmd_update_campaign(a):
    cfg = config.load_cfg_only(a.config)
    key = config.read_key(cfg["api_key_file"])
    body = json.loads(Path(a.input).read_text(encoding="utf-8"))
    st, res = lemlist.update_campaign(key, cfg["campaign_id"], body)
    _emit_result_or_stop(st, res)
```

Enregistrer les sous-parsers dans `build_parser()` (après `edit-schedule`) :

```python
    p = sub.add_parser("campaign-pause"); p.add_argument("--config", required=True); p.set_defaults(fn=cmd_campaign_pause)
    p = sub.add_parser("campaign-resume"); p.add_argument("--config", required=True); p.set_defaults(fn=cmd_campaign_resume)
    p = sub.add_parser("update-campaign"); p.add_argument("--config", required=True); p.add_argument("--input", required=True); p.set_defaults(fn=cmd_update_campaign)
```

- [ ] **Step 4: Lancer pour vérifier le passage**

Run: `uv run --with pytest python -m pytest tests/test_cli.py -q -k "campaign_pause or campaign_resume or update_campaign"`
Expected: PASS.

- [ ] **Step 5: Suite complète + commit**

Run: `uv run --with pytest python -m pytest -q`
Expected: tous PASS.

```bash
git add scripts/prospect_engine/cli.py tests/test_cli.py
git commit -m "cli — commandes config/état (campaign-pause/resume + update-campaign, exit non-zéro) (TDD)"
```

---

### Task 4: Skill `edit-campaign` — facette « config / état » + référence

**Files:**
- Modify: `skills/edit-campaign/SKILL.md` (frontmatter `description` + section « Modifier la config / l'état » + « Périmètre »)
- Create: `references/edit-campaign/config-state.md`

**Interfaces:**
- Consumes (commandes livrées) : `campaign-pause`, `campaign-resume`, `update-campaign` (Task 3) ; `resolve`, `status` (existants) ; édition de `campaign.json` (op-config + dry_run).
- Produces: une 3ᵉ facette prose qui déclenche sur l'intention « config / état » et orchestre les 4 leviers (preview + confirmation ; garde dure dry_run).

Pas de test unitaire (prose). Vérification = relecture + déclenchement.

- [ ] **Step 1: Invoquer `superpowers:writing-prompts` ET `plugin-dev:skill-development`**

Charger les deux avant d'écrire (fichiers lus par un modèle ; SKILL.md reste lean, détail en référence).

- [ ] **Step 2: Étendre la `description` du frontmatter**

Ajouter des déclencheurs config/état, sans résumé de workflow. Remplacer la phrase de périmètre actuelle
« Couvre le ciblage (filtres People DB + prompt icpFit) et la séquence (...). » par :

```
Couvre le ciblage (filtres People DB + prompt icpFit), la séquence (contenu, étapes, timing, canal) et la config/l'état (mettre en pause / reprendre, réglages de campagne, cadence de sourcing, modèles, activer la campagne pour de vrai) — « mets la campagne en pause », « relance-la », « arrête d'envoyer si on répond », « passe le sourcing à 30 par jour », « active-la pour de vrai ».
```

- [ ] **Step 3: Ajouter la section « Modifier la config / l'état » (lean, renvoie à la référence)**

Après la section « Modifier la séquence », ajouter :

```markdown
## Modifier la config / l'état

Piloter l'état et les réglages d'une campagne, et l'op-config locale du run. Quatre leviers :

| Levier | Nature | Garde |
|---|---|---|
| Pause / reprise | Lemlist (campaign-pause / campaign-resume) | preview + confirmation |
| Réglages campagne | Lemlist (update-campaign : stop-conditions, senders, tracking, autoReview) | preview + confirmation |
| Op-config locale | campaign.json (sourcing_size, models, enrich) | écrit après confirmation |
| Flip dry_run | campaign.json (true ↔ false) | garde dure : confirmation explicite, deux sens |

Mutations Lemlist = actions sortantes : preview + confirmation, jamais silencieux. Pas de gate « doit être
en pause » (pauser/régler est sûr). Le flip `dry_run` à `false` fait charger réellement les leads au
prochain run — confirmation explicite obligatoire, dans les deux sens. Le **launch** (entrer des leads en
séquence d'envoi) reste un geste séparé, hors de cette skill.

Flux détaillé (par levier, gardes, résolution des réglages) : `references/edit-campaign/config-state.md`
— le charger avant d'agir.
```

- [ ] **Step 4: Mettre à jour la section « Périmètre »**

Réécrire la section « Périmètre » :

```markdown
## Périmètre

Couvert : le ciblage (filtres + icpFit), la séquence (contenu, structure, timing, canal) et la config /
l'état (pause/reprise, réglages campagne, op-config locale, flip dry_run). Pas encore couvert : dupliquer
une verticale vers un nouveau segment puis ajuster.
```

- [ ] **Step 5: Écrire la référence `references/edit-campaign/config-state.md`**

Créer `references/edit-campaign/config-state.md` (contenu cible ; ajuster au passage writing-prompts) :

```markdown
# Modifier la config / l'état — flux détaillé (référence edit-campaign)

Chargé par `edit-campaign` pour piloter l'état/les réglages d'une campagne et l'op-config locale du run.
Commandes moteur via `uv run python scripts/routine.py <cmd>`. Les champs exacts de `update-campaign` se
lisent sur la doc live via `/lemlist` — ne pas les deviner.

## Quatre leviers, par nature

- **Pause / reprise** (Lemlist, sortant) : `campaign-pause --config <config_path>` /
  `campaign-resume --config <config_path>`. Preview (« je mets X en pause ») + confirmation. Reprendre
  redémarre le moteur d'envoi de la campagne ; ça n'entre pas de nouveaux leads en séquence (le launch
  des leads en review est un geste séparé, hors de cette skill).
- **Réglages campagne** (Lemlist, sortant) : écrire le body dans un fichier, puis
  `update-campaign --config <config_path> --input <chemin>`. Couvre stop-conditions (stop sur réponse /
  meeting / clic), senders (`sendUserIds`), tracking (open/click/reply), autoReview. Preview en clair de
  ce qui change + confirmation. Champs exacts : `/lemlist`.
- **Op-config locale** (campaign.json, local) : éditer `sourcing_size` (cadence du run), `models`
  (scoring/writing/judge), `enrich`. Preview + confirmation, puis écrire `campaign.json`. Effet au
  prochain run.
- **Flip dry_run** (campaign.json, local, haut risque) : passer `dry_run` `true ↔ false`. **Garde dure :
  confirmation explicite, dans les deux sens.** `false` = la campagne charge réellement les leads au run ;
  `true` = re-arme la sécurité. Jamais flipé par le run.

## Gardes

- Toute mutation Lemlist = action sortante → preview + confirmation explicite, jamais silencieux.
- Pas de gate « doit être en pause » (pauser/régler/op-config sont sûrs, sans l'effet non documenté de
  l'édition de séquence).
- `update-campaign` sur une campagne à stratégie de sender dynamique rejette `sendUserIds` → le signaler.
- Les commandes de mutation sortent en code non-zéro sur erreur API → s'arrêter, relire l'état, rapporter.
```

- [ ] **Step 6: Vérifier le déclenchement et la cohérence**

Relire : `description` = déclencheurs config/état sans résumé de workflow ; section SKILL lean ; référence
sans champ d'API hardcodé ; garde dure dry_run présente ; launch toujours hors périmètre.

- [ ] **Step 7: Suites vertes + commit**

Run: `uv run --with pytest python -m pytest -q && node --test 'tests/js/**/*.test.js'`
Expected: tous PASS (aucun code touché — garde-fou).

```bash
git add skills/edit-campaign/SKILL.md references/edit-campaign/config-state.md
git commit -m "edit-campaign — facette « config / état » + référence (pause/reprise, réglages, op-config, dry_run)"
```

---

### Task 5: Routeur + README + nettoyage des specs SP-B

**Files:**
- Modify: `skills/prospect-routine/SKILL.md` (table « Trois intentions » + section « Créer / Modifier » + table « Références »)
- Modify: `README.md` (bullet `skills/edit-campaign/` + §Statut)
- Modify: `docs/superpowers/specs/2026-06-23-edit-campaign-sequence-design.md` (nettoyage clean-slate : TOCTOU + associate_schedule)

**Interfaces:**
- Consumes: la skill `edit-campaign` étendue (Task 4).
- Produces: un routeur qui route config/état vers `edit-campaign` ; des specs SP-B alignés sur la réalité.

Pas de test unitaire (prose). Vérification = relecture + grep.

- [ ] **Step 1: Invoquer `superpowers:writing-prompts`**

Charger avant d'éditer (fichiers lus par un modèle).

- [ ] **Step 2: Routeur — table « Trois intentions »**

Remplacer les deux lignes :

```
| modifier le ciblage ou la séquence d'une campagne | skill `edit-campaign` (ciblage + séquence) |
| modifier la config ou dupliquer une verticale | pas encore couvert — le dire, ne rien muter à la main |
```

par :

```
| modifier le ciblage, la séquence ou la config d'une campagne | skill `edit-campaign` |
| dupliquer une verticale vers un nouveau segment | pas encore couvert — le dire, ne rien muter à la main |
```

- [ ] **Step 3: Routeur — section « Créer / Modifier »**

Remplacer les deux puces « Modifier… » par :

```markdown
- **Modifier le ciblage, la séquence ou la config / l'état** d'une campagne existante → skill
  `edit-campaign`. Ciblage (filtres + icpFit) : local. Séquence (contenu/structure/timing/canal) et config
  /état (pause/reprise, réglages, cadence, flip dry_run) : mutations Lemlist gardées (preview + confirmation)
  ou éditions locales ; prompts resynchronisés pour la séquence.
- **Dupliquer une verticale** vers un nouveau segment → pas encore construit. Le dire à l'utilisateur ;
  ne pas muter à la main.
```

- [ ] **Step 4: Routeur — table « Références »**

Remplacer la ligne `Modifier le ciblage ou la séquence` par :

```
| Modifier le ciblage / la séquence / la config | skill `edit-campaign` (séquence → `references/edit-campaign/sequence-edit.md` ; config → `references/edit-campaign/config-state.md`) |
```

- [ ] **Step 5: README**

Remplacer le bullet `skills/edit-campaign/` par :

```
- `skills/edit-campaign/` — **SP-A + SP-B + SP-C** : modifie une campagne existante — ciblage (filtres + `icpFit`, local), séquence (contenu / structure / timing / canal, Lemlist sur campagne en pause) et config/état (pause/reprise, réglages, cadence de sourcing, flip `dry_run`). Moteur : `cursor` + wrappers de mutation séquence/campagne.
```

Et §Statut, remplacer « l'édition du ciblage (SP-A) et de la séquence (SP-B) via `edit-campaign` sont livrées ; config/état (SP-C) et dupliquer-segment (SP-D) restent au backlog. » par :

```
l'édition du ciblage (SP-A), de la séquence (SP-B) et de la config/l'état (SP-C) via `edit-campaign` sont livrées ; dupliquer-segment (SP-D) reste au backlog.
```

- [ ] **Step 6: Nettoyer les specs SP-B (clean-slate)**

Dans `docs/superpowers/specs/2026-06-23-edit-campaign-sequence-design.md` :
- Retirer la sur-affirmation que le gate est « impossible à contourner par l'orchestration » (le gate est best-effort sur add/update — Lemlist ne bloque côté serveur que `delete` si running ; TOCTOU inhérent, mitigé par la pause humaine). Reformuler la phrase concernée pour refléter ça.
- Retirer `associate_schedule` des sections moteur/tests du spec (jamais implémenté, YAGNI — la réalité fait foi).

- [ ] **Step 7: Vérifier la cohérence**

Run: `grep -n "pas encore couvert\|backlog\|associate_schedule\|impossible à contourner" skills/prospect-routine/SKILL.md README.md docs/superpowers/specs/2026-06-23-edit-campaign-sequence-design.md`
Expected: config/état n'apparaît plus comme non couverte (seul dupliquer/SP-D reste) ; plus de `associate_schedule` ni de « impossible à contourner » dans le spec SP-B.

- [ ] **Step 8: Suites vertes + commit**

Run: `uv run --with pytest python -m pytest -q && node --test 'tests/js/**/*.test.js'`
Expected: tous PASS.

```bash
git add skills/prospect-routine/SKILL.md README.md docs/superpowers/specs/2026-06-23-edit-campaign-sequence-design.md
git commit -m "routeur + README — config/état couverte par edit-campaign (SP-C) + nettoyage specs SP-B"
```

---

## Self-Review

**Spec coverage** (`docs/superpowers/specs/2026-06-23-edit-campaign-config-state-design.md`) :
- 4 leviers : pause/reprise + réglages (Task 1 wrappers + Task 3 commandes) ; op-config + dry_run (Task 4 skill, édition campaign.json par Claude). ✓
- Garde dure dry_run, preview+confirmation, pas de gate pause → Task 4 (skill/référence). ✓
- Durcissement SP-B (fail-closed lecture, exit non-zéro, gate allowlist, nettoyage specs) → Task 2 + Task 5 Step 6. ✓
- Nouvelles commandes exit non-zéro → Task 3 (via `_emit_result_or_stop` de Task 2). ✓
- Où ça vit + bascule routeur → Task 4/5. ✓
- Schémas body non hardcodés (golden rule) → Task 1 (pass-through) + Task 4 (renvoi /lemlist). ✓

**Placeholder scan** : code réel à chaque step ; prose cible verbatim ; seuls renvois externes = `/lemlist` pour les schémas (golden rule). ✓

**Type consistency** : `pause_campaign(key, campaign_id)` / `start_campaign(key, campaign_id)` / `update_campaign(key, campaign_id, body)` cohérents Task 1 ↔ Task 3. `_emit_result_or_stop(st, res)` défini Task 2, consommé Task 3. `EDITABLE_STATES` + `ensure_editable` cohérents Task 2 ↔ tests. Commandes (`campaign-pause`/`campaign-resume`/`update-campaign`) cohérentes Task 3 ↔ Task 4/5. ✓

**Ordre / dépendances** : Task 1 (wrappers) → Task 2 (durcissement + helper) → Task 3 (commandes, consomme 1+2) → Task 4 (skill, référence les commandes) → Task 5 (routeur + nettoyage). ✓
