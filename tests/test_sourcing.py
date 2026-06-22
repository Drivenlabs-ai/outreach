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
