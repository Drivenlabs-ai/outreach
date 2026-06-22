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


def test_cli_record_run_then_dedup_flags_seen(tmp_path):
    cfg = _campaign(tmp_path)
    sourced = tmp_path / "sourced.json"
    # forme réelle : le fichier candidats porte des dicts projetés (pas des ids nus)
    sourced.write_text(json.dumps([{"linkedinUrl": "https://lk/a", "fullName": "A B"}]))
    r1 = run("record-run", "--config", cfg, "--date", "2026-06-15",
             "--sourced-file", str(sourced), "--true", "1", "--false", "0")
    assert r1.returncode == 0, r1.stderr

    leads = tmp_path / "leads.json"
    leads.write_text(json.dumps([{"linkedinUrl": "https://lk/a", "fullName": "A B"},
                                 {"linkedinUrl": "https://lk/b", "fullName": "C D"}]))
    r2 = run("dedup-check", "--config", cfg, "--input", str(leads))
    assert r2.returncode == 0, r2.stderr
    out = json.loads(r2.stdout)
    assert [l["linkedinUrl"] for l in out["allowed"]] == ["https://lk/b"]
    assert out["skipped"][0]["reason"] == "already_seen"


def test_cmd_source_wires_filters_and_cursor(monkeypatch, tmp_path, capsys):
    from prospect_engine import cli, config, sourcing, state
    cfg = {"filters": [{"filterId": "f1", "in": ["x"]}], "api_key_file": "x", "state_dir": str(tmp_path), "sourcing_size": 25}
    monkeypatch.setattr(config, "load_cfg_only", lambda p: cfg)
    monkeypatch.setattr(config, "read_key", lambda p: "KEY")
    monkeypatch.setattr(state, "load_state", lambda d: {"page_cursor": 3})
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
    monkeypatch.setattr(lemlist, "search_people",
                        lambda key, filters, page, size: (200, {"results": [], "limitation": 1}))

    class A:
        config = str(cfg)
        target = None
    cli.cmd_source(A())
    assert state.load_state(str(sd))["page_cursor"] == 2
