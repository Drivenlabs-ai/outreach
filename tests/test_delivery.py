"""Livraison modèle C : chaîne composite load-lead (idempotente, reprise, dry-run) + launch gardé."""
import pytest

from prospect_engine import delivery, lemlist, receipts


# ---------- fonctions pures ----------

def test_is_clean_message_accepts_clean_text():
    assert delivery.is_clean_message("Bonjour, j'ai vu votre agence à Lyon. On échange ?")


def test_is_clean_message_rejects_em_dash():
    assert not delivery.is_clean_message("Bonjour — rapide question")


def test_is_clean_message_rejects_markdown_or_formula():
    assert not delivery.is_clean_message("```\nmessage\n```")
    assert not delivery.is_clean_message("**copie littérale**")


def test_is_clean_message_rejects_empty():
    assert not delivery.is_clean_message("   ")


def test_contact_payload_splits_name_and_excludes_company():
    p = delivery.contact_payload({"fullName": "Marie Dupont", "linkedinUrl": "https://lk/in/m",
                                  "jobTitle": "Gérante", "companyName": "Agence X"})
    assert p["firstName"] == "Marie" and p["lastName"] == "Dupont"
    assert p["linkedinUrl"] == "https://lk/in/m"
    assert "companyName" not in p  # /contacts rejette companyName (400)


# ---------- orchestration (lemlist mocké) ----------

@pytest.fixture
def rec(monkeypatch):
    """Recorder : remplace les wrappers lemlist, journalise les appels, réponses configurables."""
    calls = []
    resp = {"upsert_contact": (201, {"_id": "ctc_1"}), "add_to_list": (200, {}),
            "create_lead": (200, {"_id": "lea_1"}),
            "update_variable": (200, {"ok": True}), "create_variable": (200, {"ok": True}),
            "launch_lead": (200, {}),
            # get_lead : Lemlist renvoie les variables en clés top-level du lead, pas sous `variables`.
            "get_lead": (200, {"_id": "lea_1", "icebreaker": "x", "followup": "x", "closing": "x"})}

    def mk(name):
        def fn(*a, **k):
            calls.append((name, a, k))
            return resp[name]
        return fn

    for name in resp:
        monkeypatch.setattr(lemlist, name, mk(name))
    return {"calls": calls, "resp": resp, "names": lambda: [c[0] for c in calls]}


CLEAN = {"icebreaker": "Bonjour, vu votre agence. On échange ?"}
LEAD = {"fullName": "Marie Dupont", "linkedinUrl": "https://lk/in/m"}


def test_load_lead_dry_run_does_no_network(rec, tmp_path):
    out = delivery.load_lead("KEY", LEAD, CLEAN, "cam_1", "clt_1", str(tmp_path),
                             confirm=False, dry_run=True)
    assert out.get("plan") and rec["names"]() == []


def test_load_lead_fresh_runs_full_chain_and_writes_varset(rec, tmp_path):
    out = delivery.load_lead("KEY", LEAD, CLEAN, "cam_1", "clt_1", str(tmp_path),
                             confirm=True, dry_run=False)
    assert out["ok"] and out["lead_id"] == "lea_1"
    assert rec["names"]() == ["upsert_contact", "add_to_list", "create_lead", "update_variable"]
    assert receipts.lookup(str(tmp_path), "cam_1", "https://lk/in/m")["stage"] == "varset"


def test_load_lead_extracts_id_from_wrapped_response(rec, tmp_path):
    # API réelle : POST /contacts (et create-lead) nichent l'entité sous `data`,
    # avec un statut 201. L'id doit être extrait de data._id, pas seulement du top-level.
    rec["resp"]["upsert_contact"] = (201, {"success": True, "data": {"_id": "ctc_w"}})
    rec["resp"]["create_lead"] = (201, {"success": True, "data": {"_id": "lea_w"}})
    out = delivery.load_lead("KEY", LEAD, CLEAN, "cam_1", "clt_1", str(tmp_path),
                             confirm=True, dry_run=False)
    assert out["ok"] and out["lead_id"] == "lea_w" and out["contact_id"] == "ctc_w"
    assert rec["names"]() == ["upsert_contact", "add_to_list", "create_lead", "update_variable"]


def test_load_lead_skips_when_already_varset(rec, tmp_path):
    receipts.append_receipt(str(tmp_path), {"campaign_id": "cam_1", "lead_key": "https://lk/in/m",
                                            "stage": "varset", "ok": True, "lead_id": "lea_1"})
    out = delivery.load_lead("KEY", LEAD, CLEAN, "cam_1", "clt_1", str(tmp_path),
                             confirm=True, dry_run=False)
    assert out["skipped"] and rec["names"]() == []


def test_load_lead_resumes_from_created_only_sets_variables(rec, tmp_path):
    receipts.append_receipt(str(tmp_path), {"campaign_id": "cam_1", "lead_key": "https://lk/in/m",
                                            "stage": "created", "ok": True,
                                            "contact_id": "ctc_1", "lead_id": "lea_1"})
    out = delivery.load_lead("KEY", LEAD, CLEAN, "cam_1", "clt_1", str(tmp_path),
                             confirm=True, dry_run=False)
    assert out["ok"] and rec["names"]() == ["update_variable"]
    assert receipts.lookup(str(tmp_path), "cam_1", "https://lk/in/m")["stage"] == "varset"


def test_load_lead_creates_variable_when_update_says_not_found(rec, tmp_path):
    # PATCH échoue (variable custom encore sans définition) → POST de création en repli.
    rec["resp"]["update_variable"] = (400, {"ok": False, "status": "Variables icebreaker not found"})
    out = delivery.load_lead("KEY", LEAD, CLEAN, "cam_1", "clt_1", str(tmp_path),
                             confirm=True, dry_run=False)
    assert out["ok"]
    assert rec["names"]() == ["upsert_contact", "add_to_list", "create_lead",
                              "update_variable", "create_variable"]


def test_load_lead_variables_non_notfound_error_does_not_create(rec, tmp_path):
    # Une erreur PATCH qui n'est PAS 'not found' ne doit pas déclencher de POST de repli
    # (sinon Lemlist crée une variable doublon suffixée, ex. 'followup 1').
    rec["resp"]["update_variable"] = (500, {"ok": False, "status": "server error"})
    out = delivery.load_lead("KEY", LEAD, CLEAN, "cam_1", "clt_1", str(tmp_path),
                             confirm=True, dry_run=False)
    assert out["ok"] is False and out["error"]["stage"] == "variables"
    assert "create_variable" not in rec["names"]()


def test_load_lead_rejects_broken_message_before_network(rec, tmp_path):
    out = delivery.load_lead("KEY", LEAD, {"icebreaker": "texte — cassé"}, "cam_1", "clt_1",
                             str(tmp_path), confirm=True, dry_run=False)
    assert out["skipped"] and out["reason"] == "broken_message"
    assert rec["names"]() == []


def test_load_lead_dedup_skip_when_create_returns_no_id(rec, tmp_path):
    rec["resp"]["create_lead"] = (200, {})  # email déjà dans une autre campagne → pas inséré
    out = delivery.load_lead("KEY", {"fullName": "A B", "email": "a@b.c"}, CLEAN, "cam_1", "clt_1",
                             str(tmp_path), confirm=True, dry_run=False)
    assert out["skipped"] and out["reason"] == "cross_campaign_email"


REQUIRED = ["icebreaker", "followup", "closing"]


def test_launch_leads_refuses_without_confirm(rec, tmp_path):
    out = delivery.launch_leads("KEY", [{"lead_id": "lea_1", "lead_key": "k1"}], "cam_1",
                                str(tmp_path), REQUIRED, confirm=False)
    assert out["launched"] == [] and rec["names"]() == []


def test_launch_leads_launches_when_variables_complete(rec, tmp_path):
    out = delivery.launch_leads("KEY", [{"lead_id": "lea_1", "lead_key": "k1"}], "cam_1",
                                str(tmp_path), REQUIRED, confirm=True)
    assert out["launched"] == ["lea_1"]
    assert "launch_lead" in rec["names"]()
    assert receipts.lookup(str(tmp_path), "cam_1", "k1")["stage"] == "launched"


def test_launch_leads_refuses_lead_with_empty_required_variable(rec, tmp_path):
    rec["resp"]["get_lead"] = (200, {"icebreaker": "x", "followup": "", "closing": "x"})
    out = delivery.launch_leads("KEY", [{"lead_id": "lea_1", "lead_key": "k1"}], "cam_1",
                                str(tmp_path), REQUIRED, confirm=True)
    assert out["launched"] == []
    assert out["skipped"][0]["reason"] == "variables_incompletes"
    assert "followup" in out["skipped"][0]["missing"]
    assert "launch_lead" not in rec["names"]()
