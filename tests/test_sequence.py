"""Édition de séquence : gate d'éditabilité + aplatissement lisible."""
import pytest
from prospect_engine import sequence


def test_ensure_editable_blocks_running():
    with pytest.raises(sequence.CampaignActive):
        sequence.ensure_editable({"status": "running"})


def test_ensure_editable_blocks_unknown_status():
    with pytest.raises(sequence.CampaignActive):
        sequence.ensure_editable({})


def test_ensure_editable_allows_paused_and_draft():
    assert sequence.ensure_editable({"status": "paused"}) == "paused"
    assert sequence.ensure_editable({"status": "draft"}) == "draft"


def test_summarize_flattens_keyed_sequences_with_ids():
    res = {
        "seq_1": {"steps": [
            {"_id": "stp_1", "index": 0, "type": "email", "delay": 0, "subject": "Hi", "message": "{{icebreaker}}"},
            {"_id": "stp_2", "index": 1, "type": "linkedinSend", "delay": 2, "message": "{{followup}}"},
        ]},
    }
    out = sequence.summarize(res)
    assert out == [
        {"sequence_id": "seq_1", "step_id": "stp_1", "index": 0, "type": "email", "delay": 0,
         "subject": "Hi", "message": "{{icebreaker}}"},
        {"sequence_id": "seq_1", "step_id": "stp_2", "index": 1, "type": "linkedinSend", "delay": 2,
         "subject": None, "message": "{{followup}}"},
    ]


def test_summarize_exposes_index_for_reorder():
    res = {"seq_1": {"steps": [{"_id": "stp_1", "index": 3, "type": "email", "message": "m"}]}}
    assert sequence.summarize(res)[0]["index"] == 3


def test_summarize_tolerates_non_dict():
    assert sequence.summarize("oops") == []


def test_summarize_tolerates_missing_steps():
    assert sequence.summarize({"seq_1": {}}) == []


def test_ensure_editable_blocks_none_campaign():
    with pytest.raises(sequence.CampaignActive):
        sequence.ensure_editable(None)


def test_ensure_editable_blocks_empty_and_unknown_status():
    with pytest.raises(sequence.CampaignActive):
        sequence.ensure_editable({"status": ""})
    with pytest.raises(sequence.CampaignActive):
        sequence.ensure_editable({"status": "some_new_label"})


def test_ensure_editable_allows_known_safe_states():
    for s in ("paused", "draft", "ended", "archived", "errors"):
        assert sequence.ensure_editable({"status": s}) == s
