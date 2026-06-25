"""Sourcing People DB : une page au curseur, exclusion native, projection, fin de pool."""
from prospect_engine import lemlist, sourcing


def _r(url, name="X Y", title="Gérant", company="Agence"):
    return {"lead_linkedin_url": url, "full_name": name, "title": title,
            "current_exp_company_name": company, "location": "Lyon", "lead_id": url[-1]}


def _page(*urls, limitation=1999):
    return (200, {"results": [_r(u) for u in urls], "limitation": limitation})


def test_source_projects_result_to_lead(monkeypatch):
    monkeypatch.setattr(lemlist, "search_people", lambda *a, **k: _page("https://lk/a"))
    out = sourcing.source("KEY", [], cursor=1, target=1)
    lead = out["candidats"][0]
    assert lead["linkedinUrl"] == "https://lk/a"
    assert lead["fullName"] == "X Y" and lead["jobTitle"] == "Gérant" and lead["companyName"] == "Agence"


def test_source_fetches_cursor_page_and_advances(monkeypatch):
    seen = {}
    def fake(key, filters, page, size):
        seen["page"], seen["size"] = page, size
        return _page("https://lk/a", "https://lk/b")
    monkeypatch.setattr(lemlist, "search_people", fake)
    out = sourcing.source("KEY", [], cursor=4, target=2)
    assert seen["page"] == 4 and seen["size"] == 2
    assert out["next_cursor"] == 5


def test_source_injects_out_filter_from_exclude(monkeypatch):
    cap = {}
    def fake(key, filters, page, size):
        cap["filters"] = filters
        return _page("https://lk/b")
    monkeypatch.setattr(lemlist, "search_people", fake)
    sourcing.source("KEY", [{"filterId": "country", "in": ["France"], "out": []}],
                    cursor=1, target=5, exclude={"https://lk/a"})
    out_f = [f for f in cap["filters"] if f["filterId"] == "leadLinkedInUrl"]
    assert out_f and out_f[0]["in"] == [] and out_f[0]["out"] == ["https://lk/a"]


def test_source_excludes_urls_client_side(monkeypatch):
    monkeypatch.setattr(lemlist, "search_people", lambda *a, **k: _page("https://lk/a", "https://lk/b"))
    out = sourcing.source("KEY", [], cursor=1, target=5, exclude={"https://lk/a"})
    assert [c["linkedinUrl"] for c in out["candidats"]] == ["https://lk/b"]


def test_source_dedups_within_page(monkeypatch):
    monkeypatch.setattr(lemlist, "search_people", lambda *a, **k: _page("https://lk/a", "https://lk/a"))
    out = sourcing.source("KEY", [], cursor=1, target=5)
    assert len(out["candidats"]) == 1


def test_source_marks_exhausted_on_short_page(monkeypatch):
    monkeypatch.setattr(lemlist, "search_people", lambda *a, **k: _page("https://lk/a"))
    out = sourcing.source("KEY", [], cursor=1, target=50)
    assert out["exhausted"] is True and out["next_cursor"] == 2


def test_source_not_exhausted_on_full_page(monkeypatch):
    monkeypatch.setattr(lemlist, "search_people", lambda *a, **k: _page("https://lk/a", "https://lk/b"))
    out = sourcing.source("KEY", [], cursor=1, target=2)
    assert out["exhausted"] is False


def test_source_propagates_limitation(monkeypatch):
    monkeypatch.setattr(lemlist, "search_people", lambda *a, **k: _page("https://lk/a", limitation=42))
    out = sourcing.source("KEY", [], cursor=1, target=1)
    assert out["limitation"] == 42


def test_loaded_urls_keeps_only_this_campaign_members():
    contacts = [
        {"linkedinUrl": "https://lk/a", "campaigns": [{"campaignId": "cam_1"}]},
        {"linkedinUrl": "https://lk/b", "campaigns": [{"campaignId": "cam_2"}]},
        {"linkedinUrl": "https://lk/c", "campaigns": []},
        {"campaigns": [{"campaignId": "cam_1"}]},  # sans linkedinUrl → ignoré
    ]
    assert sourcing.loaded_urls(contacts, "cam_1") == {"https://lk/a"}


def test_loaded_urls_caps_at_limit():
    contacts = [{"linkedinUrl": f"https://lk/{i}", "campaigns": [{"campaignId": "cam_1"}]}
                for i in range(10)]
    assert len(sourcing.loaded_urls(contacts, "cam_1", cap=3)) == 3


def test_source_exposes_total(monkeypatch):
    monkeypatch.setattr(lemlist, "search_people",
                        lambda *a, **k: (200, {"results": [_r("https://lk/a")], "limitation": 1, "total": 15576}))
    out = sourcing.source("KEY", [], cursor=1, target=1)
    assert out["total"] == 15576


def test_source_total_none_on_error(monkeypatch):
    monkeypatch.setattr(lemlist, "search_people", lambda *a, **k: (400, "Parameter filters is invalid"))
    out = sourcing.source("KEY", [], cursor=1, target=1)
    assert out["total"] is None and out["exhausted"] is True


# --- projection : titre depuis l'expérience courante + industrie ---
# People DB ne renvoie plus `title` au top-level ; le titre vit dans `experiences[].title`.
# L'expérience courante = celle dont `company_name` == `current_exp_company_name`.

def test_project_jobtitle_from_current_experience():
    raw = {
        "lead_linkedin_url": "https://lk/a", "full_name": "Jade M",
        "current_exp_company_name": "ALEXANDRY IMMOBILIER",
        "current_exp_company_subindustry": "Real Estate",
        "experiences": [
            {"company_name": "ANCIENNE SCI", "title": "Stagiaire", "order_in_profile": 2, "date_to": "2020"},
            {"company_name": "ALEXANDRY IMMOBILIER", "title": "Négociatrice Immobilier", "order_in_profile": 1},
        ],
        "lead_id": "a",
    }
    lead = sourcing._project(raw)
    assert lead["jobTitle"] == "Négociatrice Immobilier"
    assert lead["industry"] == "Real Estate"


def test_project_jobtitle_falls_back_to_title_normalized():
    raw = {"lead_linkedin_url": "u", "current_exp_company_name": "CO", "lead_id": "u",
           "experiences": [{"company_name": "CO", "title_normalized": "Real Estate Agent", "order_in_profile": 1}]}
    assert sourcing._project(raw)["jobTitle"] == "Real Estate Agent"


def test_project_jobtitle_falls_back_to_most_recent_when_no_company_match():
    raw = {"lead_linkedin_url": "u", "current_exp_company_name": "INTROUVABLE", "lead_id": "u",
           "experiences": [
               {"company_name": "X", "title": "Récent", "order_in_profile": 1},
               {"company_name": "Y", "title": "Ancien", "order_in_profile": 3},
           ]}
    assert sourcing._project(raw)["jobTitle"] == "Récent"


def test_project_industry_falls_back_to_company_industry():
    raw = {"lead_linkedin_url": "u", "lead_id": "u",
           "current_exp_company_industry": "Real Estate and Equipment Rental Services"}
    assert sourcing._project(raw)["industry"] == "Real Estate and Equipment Rental Services"


def test_project_no_experiences_uses_top_level_title():
    raw = {"lead_linkedin_url": "u", "title": "Gérant", "lead_id": "u"}
    assert sourcing._project(raw)["jobTitle"] == "Gérant"
