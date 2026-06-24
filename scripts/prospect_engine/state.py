"""État machine local — jamais dans le Drive.

Deux fichiers dans `~/.claude/outreach/<slug>/` :
  state.json  : page_cursor (position dans le pool People DB), history, last_run
  status.json : phases de reprise des workflows (phase1_done, w2_steps, edit_in_progress, last_run)

Toutes les écritures sont atomiques (tmp + os.replace) — jamais d'état corrompu sur crash.
"""
import json
import os
import tempfile
from pathlib import Path

STATE_DEFAULT = {"page_cursor": 1, "last_run": None, "history": []}
STATUS_DEFAULT = {"phase1_done": False, "w2_steps": [], "edit_in_progress": False, "last_run": None}


# ---------- helpers purs ----------

def apply_commit(state, date, n_sourced, n_true, n_false):
    """Append l'historique du run + horodate. Aucune mémoire de déjà-vus ici : l'exclusion au
    sourcing se fait par le curseur de page + le filtre `out` (leads déjà en campagne)."""
    state["last_run"] = date
    state["history"].append({"date": date, "sourced": n_sourced, "true": n_true, "false": n_false})
    return state


# ---------- IO atomique ----------

def _atomic_write(path, payload):
    d = path.parent
    d.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=1)
        os.replace(tmp, path)
    except Exception:
        os.unlink(tmp)
        raise


def load_state(state_dir):
    p = Path(state_dir).expanduser() / "state.json"
    if not p.exists():
        return dict(STATE_DEFAULT, history=[])
    return json.loads(p.read_text(encoding="utf-8"))


def save_state(state_dir, state):
    _atomic_write(Path(state_dir).expanduser() / "state.json", state)


# ---------- status (reprise des workflows) ----------

def load_status(state_dir):
    p = Path(state_dir).expanduser() / "status.json"
    if not p.exists():
        return dict(STATUS_DEFAULT, w2_steps=[])
    return json.loads(p.read_text(encoding="utf-8"))


def save_status(state_dir, status):
    _atomic_write(Path(state_dir).expanduser() / "status.json", status)


def status_set(state_dir, key, value):
    status = load_status(state_dir)
    status[key] = value
    save_status(state_dir, status)
    return status


def status_get(state_dir, key=None):
    status = load_status(state_dir)
    return status if key is None else status.get(key)


def set_cursor(state_dir, value):
    """Pose le curseur de page (state.json), écriture atomique. Préserve history/last_run.
    Seul point d'écriture du curseur hors du run (le run l'avance via save_state au sourcing)."""
    st = load_state(state_dir)
    st["page_cursor"] = value
    save_state(state_dir, st)
    return value
