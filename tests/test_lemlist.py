"""Client HTTP Lemlist : auth Basic, User-Agent anti-WAF, retry 429/Retry-After, routage wrappers."""
import io
import urllib.error

from prospect_engine import lemlist


class FakeResp:
    def __init__(self, status, body):
        self.status = status
        self._body = body

    def read(self):
        return self._body.encode()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_api_call_success_parses_json(monkeypatch):
    monkeypatch.setattr(lemlist.urllib.request, "urlopen",
                        lambda req, timeout=30: FakeResp(200, '{"_id":"ctc_1"}'))
    status, body = lemlist.api_call("GET", "/team", "KEY")
    assert status == 200
    assert body["_id"] == "ctc_1"


def test_api_call_returns_text_when_not_json(monkeypatch):
    monkeypatch.setattr(lemlist.urllib.request, "urlopen",
                        lambda req, timeout=30: FakeResp(200, "plain ok"))
    status, body = lemlist.api_call("GET", "/x", "KEY")
    assert body == "plain ok"


def test_api_call_sets_basic_auth_and_user_agent(monkeypatch):
    captured = {}

    def fake(req, timeout=30):
        captured["auth"] = req.get_header("Authorization")
        captured["ua"] = req.get_header("User-agent")
        return FakeResp(200, "{}")

    monkeypatch.setattr(lemlist.urllib.request, "urlopen", fake)
    lemlist.api_call("GET", "/team", "SECRET")
    assert captured["auth"].startswith("Basic ")
    assert captured["ua"]  # User-Agent obligatoire (sinon 403 WAF)


def test_api_call_retries_on_429_then_succeeds(monkeypatch):
    n = {"calls": 0}
    slept = []

    def fake(req, timeout=30):
        n["calls"] += 1
        if n["calls"] == 1:
            raise urllib.error.HTTPError("u", 429, "slow", {"Retry-After": "1"}, io.BytesIO(b"rate"))
        return FakeResp(200, '{"ok":true}')

    monkeypatch.setattr(lemlist.urllib.request, "urlopen", fake)
    monkeypatch.setattr(lemlist.time, "sleep", lambda s: slept.append(s))
    status, body = lemlist.api_call("POST", "/x", "KEY", {"a": 1})
    assert status == 200 and body["ok"] is True
    assert n["calls"] == 2
    assert slept and slept[0] >= 1  # honore Retry-After


def test_api_call_returns_error_on_4xx(monkeypatch):
    def fake(req, timeout=30):
        raise urllib.error.HTTPError("u", 400, "bad", {}, io.BytesIO(b"Bad team"))

    monkeypatch.setattr(lemlist.urllib.request, "urlopen", fake)
    status, body = lemlist.api_call("GET", "/x", "KEY")
    assert status == 400 and "Bad team" in body


def test_create_lead_always_passes_deduplicate(monkeypatch):
    captured = {}

    def fake_api(method, route, key, body=None, **kw):
        captured["route"] = route
        return 200, {"_id": "lea_1"}

    monkeypatch.setattr(lemlist, "api_call", fake_api)
    lemlist.create_lead("KEY", "cam_1", {"email": "a@b.c"})
    assert "deduplicate=true" in captured["route"]
    assert "/campaigns/cam_1/leads" in captured["route"]


def test_launch_lead_uses_review_route(monkeypatch):
    captured = {}

    def fake_api(method, route, key, body=None, **kw):
        captured["route"] = route
        captured["method"] = method
        return 200, {}

    monkeypatch.setattr(lemlist, "api_call", fake_api)
    lemlist.launch_lead("KEY", "lea_42")
    assert captured["route"] == "/leads/review/lea_42"
    assert captured["method"] == "POST"


def test_duplicate_campaign_route_and_name(monkeypatch):
    cap = {}

    def fake(method, route, key, body=None, **kw):
        cap.update(method=method, route=route, body=body)
        return 200, {"_id": "cam_new", "sequenceId": "seq_1"}

    monkeypatch.setattr(lemlist, "api_call", fake)
    lemlist.duplicate_campaign("KEY", "cam_tpl", "Agence Immo")
    assert cap["method"] == "POST"
    assert cap["route"] == "/campaigns/cam_tpl/duplicate"
    assert cap["body"] == {"name": "Agence Immo"}


def test_create_list_route_and_body(monkeypatch):
    cap = {}

    def fake(method, route, key, body=None, **kw):
        cap.update(route=route, body=body)
        return 200, {"_id": "clt_1"}

    monkeypatch.setattr(lemlist, "api_call", fake)
    lemlist.create_list("KEY", "Agence Immo")
    assert cap["route"] == "/contacts/lists"
    assert cap["body"] == {"name": "Agence Immo"}


def test_get_campaign_sequences_route(monkeypatch):
    cap = {}
    monkeypatch.setattr(lemlist, "api_call",
                        lambda m, route, k, body=None, **kw: cap.update(route=route) or (200, {}))
    lemlist.get_campaign_sequences("KEY", "cam_1")
    assert cap["route"] == "/campaigns/cam_1/sequences"


def test_get_lead_by_id_route(monkeypatch):
    cap = {}
    monkeypatch.setattr(lemlist, "api_call",
                        lambda m, route, k, body=None, **kw: cap.update(route=route) or (200, {"variables": {}}))
    lemlist.get_lead("KEY", "lea_1")
    assert cap["route"].startswith("/leads") and "id=lea_1" in cap["route"]


def test_search_people_route_and_body(monkeypatch):
    cap = {}

    def fake(method, route, key, body=None, **kw):
        cap.update(method=method, route=route, body=body)
        return 200, {"results": [], "limitation": 1999}

    monkeypatch.setattr(lemlist, "api_call", fake)
    lemlist.search_people("KEY", [{"filterId": "f1", "in": ["x"]}], page=1, size=25)
    assert cap["method"] == "POST" and cap["route"] == "/database/people"
    assert cap["body"] == {"filters": [{"filterId": "f1", "in": ["x"]}], "page": 1, "size": 25}


def test_get_contacts_none_on_fetch_failure(monkeypatch):
    # Échec de récupération → None (distinct d'une liste vide légitime) pour que le sourcing avertisse.
    monkeypatch.setattr(lemlist, "api_call", lambda method, route, key, *a, **k: (500, "err"))
    assert lemlist.get_contacts("KEY") is None


def test_get_contacts_paginates_on_success(monkeypatch):
    def fake(method, route, key, *a, **k):
        if route == "/contacts?limit=1":
            return (200, {"data": [{}]})            # sonde OK
        return (200, {"data": [{"linkedinUrl": "https://lk/a"}]})  # page (<100 → stop)
    monkeypatch.setattr(lemlist, "api_call", fake)
    assert lemlist.get_contacts("KEY") == [{"linkedinUrl": "https://lk/a"}]


def test_add_step_route_method_body(monkeypatch):
    cap = {}
    def fake(method, route, key, body=None, **kw):
        cap.update(method=method, route=route, body=body); return 200, {"_id": "stp_1"}
    monkeypatch.setattr(lemlist, "api_call", fake)
    lemlist.add_step("KEY", "seq_1", {"type": "email", "subject": "S", "message": "M"})
    assert cap["method"] == "POST" and cap["route"] == "/sequences/seq_1/steps"
    assert cap["body"] == {"type": "email", "subject": "S", "message": "M"}


def test_update_step_route_method_body(monkeypatch):
    cap = {}
    def fake(method, route, key, body=None, **kw):
        cap.update(method=method, route=route, body=body); return 200, {}
    monkeypatch.setattr(lemlist, "api_call", fake)
    lemlist.update_step("KEY", "seq_1", "stp_9", {"type": "email", "message": "M2"})
    assert cap["method"] == "PATCH" and cap["route"] == "/sequences/seq_1/steps/stp_9"
    assert cap["body"] == {"type": "email", "message": "M2"}


def test_delete_step_route_method_no_body(monkeypatch):
    cap = {}
    def fake(method, route, key, body=None, **kw):
        cap.update(method=method, route=route, body=body); return 200, {"ok": True}
    monkeypatch.setattr(lemlist, "api_call", fake)
    lemlist.delete_step("KEY", "seq_1", "stp_9")
    assert cap["method"] == "DELETE" and cap["route"] == "/sequences/seq_1/steps/stp_9"
    assert cap["body"] is None


def test_update_schedule_route_method_body(monkeypatch):
    cap = {}
    def fake(method, route, key, body=None, **kw):
        cap.update(method=method, route=route, body=body); return 200, {}
    monkeypatch.setattr(lemlist, "api_call", fake)
    lemlist.update_schedule("KEY", "skd_1", {"start": "09:00", "end": "17:00"})
    assert cap["method"] == "PATCH" and cap["route"] == "/schedules/skd_1"
    assert cap["body"] == {"start": "09:00", "end": "17:00"}


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
