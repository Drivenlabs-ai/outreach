"""État machine : curseur de page, historique, status de reprise — écritures atomiques."""
from prospect_engine import state


def test_apply_commit_appends_history_entry():
    st = {"page_cursor": 1, "last_run": None, "history": []}
    state.apply_commit(st, "2026-06-15", 2, 1, 1)
    assert st["last_run"] == "2026-06-15"
    assert st["history"][-1] == {"date": "2026-06-15", "sourced": 2, "true": 1, "false": 1}


def test_apply_commit_does_not_track_seen():
    st = {"page_cursor": 1, "last_run": None, "history": []}
    state.apply_commit(st, "2026-06-15", 3, 0, 0)
    assert "seen_lead_ids" not in st


def test_save_load_state_roundtrip(tmp_path):
    st = {"page_cursor": 2, "last_run": "2026-06-15", "history": []}
    state.save_state(str(tmp_path), st)
    assert state.load_state(str(tmp_path)) == st


def test_load_state_default_when_absent(tmp_path):
    st = state.load_state(str(tmp_path / "nope"))
    assert st == {"page_cursor": 1, "last_run": None, "history": []}


def test_status_set_get_roundtrip(tmp_path):
    state.status_set(str(tmp_path), "phase1_done", True)
    state.status_set(str(tmp_path), "w2_steps", ["campaign", "sequence"])
    assert state.status_get(str(tmp_path), "phase1_done") is True
    assert state.status_get(str(tmp_path), "w2_steps") == ["campaign", "sequence"]


def test_load_status_default_when_absent(tmp_path):
    assert state.load_status(str(tmp_path)) == {
        "phase1_done": False, "w2_steps": [], "edit_in_progress": False, "last_run": None}


def test_set_cursor_writes_page_cursor_and_preserves_rest(tmp_path):
    state.save_state(str(tmp_path), {"page_cursor": 7, "last_run": "2026-06-15", "history": [{"x": 1}]})
    assert state.set_cursor(str(tmp_path), 1) == 1
    st = state.load_state(str(tmp_path))
    assert st["page_cursor"] == 1
    assert st["last_run"] == "2026-06-15" and st["history"] == [{"x": 1}]


def test_set_cursor_on_absent_state_creates_default(tmp_path):
    assert state.set_cursor(str(tmp_path / "fresh"), 5) == 5
    assert state.load_state(str(tmp_path / "fresh")) == {"page_cursor": 5, "last_run": None, "history": []}
