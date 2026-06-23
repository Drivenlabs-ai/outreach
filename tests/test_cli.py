"""Intégration CLI : l'entrée stable `python3 scripts/routine.py <cmd>` dispatche correctement.
Couvre les commandes sans réseau (resolve, status, dedup-check, record-run)."""
import json
import subprocess
import sys
from pathlib import Path

ROUTINE = Path(__file__).resolve().parent.parent / "scripts" / "routine.py"


def run(*args):
    return subprocess.run([sys.executable, str(ROUTINE), *args], capture_output=True, text=True)


def _campaign(tmp_path):
    cfg = tmp_path / "campaign.json"
    cfg.write_text(json.dumps({"campaign_id": "cam_1", "slug": "agence-immo",
                               "state_dir": str(tmp_path / "state")}))
    return str(cfg)


def test_cli_resolve_by_slug(tmp_path):
    reg = tmp_path / "reg.json"
    reg.write_text(json.dumps([{"slug": "agence-immo", "campaign_id": "cam_1"},
                               {"slug": "saas-cto", "campaign_id": "cam_2"}]))
    r = run("resolve", "--registry", str(reg), "--slug", "agence-immo")
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)["campaign_id"] == "cam_1"


def test_cli_status_set_then_get(tmp_path):
    cfg = _campaign(tmp_path)
    run("status", "--config", cfg, "--set", "phase1_done=true")
    r = run("status", "--config", cfg, "--get", "phase1_done")
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout) == {"phase1_done": True}


def test_cli_record_run_appends_history(tmp_path):
    cfg = _campaign(tmp_path)
    sourced = tmp_path / "sourced.json"
    sourced.write_text(json.dumps([{"linkedinUrl": "https://lk/a", "fullName": "A B"}]))
    r = run("record-run", "--config", cfg, "--date", "2026-06-15",
            "--sourced-file", str(sourced), "--true", "1", "--false", "0")
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)["history_len"] == 1


def test_cli_dedup_flags_already_loaded(tmp_path):
    from prospect_engine import receipts
    cfg = _campaign(tmp_path)
    state_dir = json.loads(Path(cfg).read_text())["state_dir"]
    receipts.append_receipt(state_dir, {"campaign_id": "cam_1", "lead_key": "https://lk/a",
                                        "stage": "varset", "ok": True})
    leads = tmp_path / "leads.json"
    leads.write_text(json.dumps([{"linkedinUrl": "https://lk/a", "fullName": "A B"},
                                 {"linkedinUrl": "https://lk/b", "fullName": "C D"}]))
    r = run("dedup-check", "--config", cfg, "--input", str(leads))
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert [l["linkedinUrl"] for l in out["allowed"]] == ["https://lk/b"]
    assert out["skipped"][0]["reason"] == "already_loaded"


def test_cmd_source_wires_filters_and_cursor(monkeypatch, tmp_path, capsys):
    from prospect_engine import cli, config, lemlist, sourcing, state
    cfg = {"filters": [{"filterId": "f1", "in": ["x"]}], "api_key_file": "x", "state_dir": str(tmp_path), "sourcing_size": 25, "campaign_id": "cam_1"}
    monkeypatch.setattr(config, "load_cfg_only", lambda p: cfg)
    monkeypatch.setattr(config, "read_key", lambda p: "KEY")
    monkeypatch.setattr(state, "load_state", lambda d: {"page_cursor": 3})
    monkeypatch.setattr(lemlist, "get_contacts", lambda key: [])
    cap = {}

    def fake_source(key, filters, cursor, target, **kw):
        cap.update(filters=filters, cursor=cursor, target=target)
        return {"candidats": [], "limitation": 9, "next_cursor": 4, "exhausted": True}

    monkeypatch.setattr(sourcing, "source", fake_source)

    class A:
        config = "x"
        target = 5
    cli.cmd_source(A())
    out = json.loads(capsys.readouterr().out)
    assert cap["filters"] == [{"filterId": "f1", "in": ["x"]}] and cap["target"] == 5
    assert cap["cursor"] == 3
    assert out["limitation"] == 9


def test_cli_register_campaign(tmp_path):
    reg = tmp_path / "reg.json"
    reg.write_text("[]")
    cj = tmp_path / "v" / "campaign.json"
    data = tmp_path / "data.json"
    data.write_text(json.dumps({"campaign_id": "cam_1", "slug": "x"}))
    entry = tmp_path / "entry.json"
    entry.write_text(json.dumps({"slug": "x", "campaign_id": "cam_1", "status": "active"}))
    r = run("register-campaign", "--registry", str(reg), "--campaign-json", str(cj),
            "--data-file", str(data), "--entry-file", str(entry))
    assert r.returncode == 0, r.stderr
    assert json.loads(reg.read_text())[0]["slug"] == "x"
    assert json.loads(cj.read_text())["campaign_id"] == "cam_1"


def test_cmd_source_persists_advanced_cursor(monkeypatch, tmp_path):
    from prospect_engine import cli, lemlist, state
    sd = tmp_path / "state"
    keyfile = tmp_path / "k.md"
    keyfile.write_text("lemlist_api_key: X")
    cfg = tmp_path / "campaign.json"
    cfg.write_text(json.dumps({"state_dir": str(sd), "api_key_file": str(keyfile),
                               "campaign_id": "cam_1", "filters": [], "sourcing_size": 5}))
    monkeypatch.setattr(lemlist, "get_contacts", lambda key: [])
    monkeypatch.setattr(lemlist, "search_people",
                        lambda key, filters, page, size: (200, {"results": [], "limitation": 1}))

    class A:
        config = str(cfg)
        target = None
    cli.cmd_source(A())
    assert state.load_state(str(sd))["page_cursor"] == 2


def test_cmd_source_excludes_campaign_members(monkeypatch, tmp_path):
    from prospect_engine import cli, lemlist, state
    sd = tmp_path / "state"
    keyfile = tmp_path / "k.md"
    keyfile.write_text("lemlist_api_key: X")
    cfg = tmp_path / "campaign.json"
    cfg.write_text(json.dumps({"state_dir": str(sd), "api_key_file": str(keyfile),
                               "campaign_id": "cam_1", "filters": [], "sourcing_size": 5}))
    monkeypatch.setattr(lemlist, "get_contacts",
                        lambda key: [{"linkedinUrl": "https://lk/a", "campaigns": [{"campaignId": "cam_1"}]}])
    captured = {}
    def fake_search(key, filters, page, size):
        captured["filters"] = filters
        return (200, {"results": [{"lead_linkedin_url": "https://lk/a", "lead_id": "a"},
                                  {"lead_linkedin_url": "https://lk/b", "lead_id": "b"}],
                      "limitation": 1})
    monkeypatch.setattr(lemlist, "search_people", fake_search)

    class A:
        config = str(cfg)
        target = None
    cli.cmd_source(A())
    out_f = [f for f in captured["filters"] if f["filterId"] == "leadLinkedInUrl"]
    assert out_f and out_f[0]["out"] == ["https://lk/a"]


def test_cmd_source_warns_on_contacts_fetch_failure(monkeypatch, tmp_path, capsys):
    from prospect_engine import cli, lemlist, state
    sd = tmp_path / "state"
    keyfile = tmp_path / "k.md"
    keyfile.write_text("lemlist_api_key: X")
    cfg = tmp_path / "campaign.json"
    cfg.write_text(json.dumps({"state_dir": str(sd), "api_key_file": str(keyfile),
                               "campaign_id": "cam_1", "filters": [], "sourcing_size": 5}))
    monkeypatch.setattr(lemlist, "get_contacts", lambda key: None)
    monkeypatch.setattr(lemlist, "search_people",
                        lambda key, filters, page, size: (200, {"results": [], "limitation": 1}))

    class A:
        config = str(cfg)
        target = None
    cli.cmd_source(A())
    assert "déjà en campagne" in capsys.readouterr().err
    assert state.load_state(str(sd))["page_cursor"] == 2


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


def test_cmd_source_warns_on_exclusion_cap(monkeypatch, tmp_path, capsys):
    from prospect_engine import cli, lemlist, sourcing
    sd = tmp_path / "state"
    keyfile = tmp_path / "k.md"
    keyfile.write_text("lemlist_api_key: X")
    cfg = tmp_path / "campaign.json"
    cfg.write_text(json.dumps({"state_dir": str(sd), "api_key_file": str(keyfile),
                               "campaign_id": "cam_1", "filters": [], "sourcing_size": 5}))
    big = [{"linkedinUrl": f"https://lk/{i}", "campaigns": [{"campaignId": "cam_1"}]}
           for i in range(sourcing.EXCLUDE_CAP + 3)]
    monkeypatch.setattr(lemlist, "get_contacts", lambda key: big)
    monkeypatch.setattr(lemlist, "search_people",
                        lambda key, filters, page, size: (200, {"results": [], "limitation": 1}))

    class A:
        config = str(cfg)
        target = None
    cli.cmd_source(A())
    assert "plafonn" in capsys.readouterr().err


def test_cmd_sequence_summarizes(monkeypatch, tmp_path, capsys):
    from prospect_engine import cli, config, lemlist
    cfg = {"api_key_file": "x", "campaign_id": "cam_1"}
    monkeypatch.setattr(config, "load_cfg_only", lambda p: cfg)
    monkeypatch.setattr(config, "read_key", lambda p: "KEY")
    monkeypatch.setattr(lemlist, "get_campaign_sequences",
                        lambda key, cid: (200, {"seq_1": {"steps": [{"_id": "stp_1", "type": "email",
                                                                     "delay": 0, "message": "{{icebreaker}}"}]}}))
    class A: config = "x"
    cli.cmd_sequence(A())
    out = json.loads(capsys.readouterr().out)
    assert out["steps"][0]["sequence_id"] == "seq_1" and out["steps"][0]["step_id"] == "stp_1"


def test_cmd_add_step_blocked_when_campaign_running(monkeypatch, tmp_path):
    from prospect_engine import cli, config, lemlist
    cfg = {"api_key_file": "x", "campaign_id": "cam_1"}
    monkeypatch.setattr(config, "load_cfg_only", lambda p: cfg)
    monkeypatch.setattr(config, "read_key", lambda p: "KEY")
    monkeypatch.setattr(lemlist, "get_campaign", lambda key, cid: (200, {"status": "running"}))
    called = {"add": False}
    monkeypatch.setattr(lemlist, "add_step", lambda *a, **k: called.__setitem__("add", True) or (200, {}))
    body = tmp_path / "b.json"; body.write_text(json.dumps({"type": "email", "subject": "S", "message": "M"}))
    class A:
        config = "x"; sequence_id = "seq_1"; input = str(body)
    with __import__("pytest").raises(SystemExit):
        cli.cmd_add_step(A())
    assert called["add"] is False  # mutation jamais appelée si campagne active


def test_cmd_add_step_passes_when_paused(monkeypatch, tmp_path, capsys):
    from prospect_engine import cli, config, lemlist
    cfg = {"api_key_file": "x", "campaign_id": "cam_1"}
    monkeypatch.setattr(config, "load_cfg_only", lambda p: cfg)
    monkeypatch.setattr(config, "read_key", lambda p: "KEY")
    monkeypatch.setattr(lemlist, "get_campaign", lambda key, cid: (200, {"status": "paused"}))
    cap = {}
    monkeypatch.setattr(lemlist, "add_step",
                        lambda key, sid, body: cap.update(sid=sid, body=body) or (200, {"_id": "stp_9"}))
    body = tmp_path / "b.json"; body.write_text(json.dumps({"type": "email", "subject": "S", "message": "M"}))
    class A:
        config = "x"; sequence_id = "seq_1"; input = str(body)
    cli.cmd_add_step(A())
    out = json.loads(capsys.readouterr().out)
    assert cap["sid"] == "seq_1" and cap["body"]["type"] == "email" and out["status"] == 200


def test_cmd_delete_step_blocked_when_campaign_running(monkeypatch):
    from prospect_engine import cli, config, lemlist
    cfg = {"api_key_file": "x", "campaign_id": "cam_1"}
    monkeypatch.setattr(config, "load_cfg_only", lambda p: cfg)
    monkeypatch.setattr(config, "read_key", lambda p: "KEY")
    monkeypatch.setattr(lemlist, "get_campaign", lambda key, cid: (200, {"status": "running"}))
    called = {"del": False}
    monkeypatch.setattr(lemlist, "delete_step", lambda *a, **k: called.__setitem__("del", True) or (200, {}))
    class A:
        config = "x"; sequence_id = "seq_1"; step_id = "stp_1"
    with __import__("pytest").raises(SystemExit):
        cli.cmd_delete_step(A())
    assert called["del"] is False  # mutation jamais appelée si campagne active


def test_cmd_update_step_blocked_when_campaign_running(monkeypatch, tmp_path):
    from prospect_engine import cli, config, lemlist
    cfg = {"api_key_file": "x", "campaign_id": "cam_1"}
    monkeypatch.setattr(config, "load_cfg_only", lambda p: cfg)
    monkeypatch.setattr(config, "read_key", lambda p: "KEY")
    monkeypatch.setattr(lemlist, "get_campaign", lambda key, cid: (200, {"status": "running"}))
    called = {"upd": False}
    monkeypatch.setattr(lemlist, "update_step", lambda *a, **k: called.__setitem__("upd", True) or (200, {}))
    body = tmp_path / "b.json"; body.write_text(json.dumps({"type": "email", "message": "M"}))
    class A:
        config = "x"; sequence_id = "seq_1"; step_id = "stp_1"; input = str(body)
    with __import__("pytest").raises(SystemExit):
        cli.cmd_update_step(A())
    assert called["upd"] is False


def test_cmd_edit_schedule_blocked_when_campaign_running(monkeypatch, tmp_path):
    from prospect_engine import cli, config, lemlist
    cfg = {"api_key_file": "x", "campaign_id": "cam_1"}
    monkeypatch.setattr(config, "load_cfg_only", lambda p: cfg)
    monkeypatch.setattr(config, "read_key", lambda p: "KEY")
    monkeypatch.setattr(lemlist, "get_campaign", lambda key, cid: (200, {"status": "running"}))
    called = {"sched": False}
    monkeypatch.setattr(lemlist, "update_schedule", lambda *a, **k: called.__setitem__("sched", True) or (200, {}))
    body = tmp_path / "b.json"; body.write_text(json.dumps({"start": "09:00"}))
    class A:
        config = "x"; schedule_id = "skd_1"; input = str(body)
    with __import__("pytest").raises(SystemExit):
        cli.cmd_edit_schedule(A())
    assert called["sched"] is False
