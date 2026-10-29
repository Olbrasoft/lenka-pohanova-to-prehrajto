import copy
import pytest
from sdilej_serialy.models import Episode
from lenka_sync import reconcile
from lenka_sync.state import VariantState


def test_false_english_completion_is_reviewed_without_changing_czech_video(tmp_path, czech_row, monkeypatch):
    states = {v: VariantState(tmp_path / f"{v}.json", v) for v in ("cz", "en")}
    episode = Episode.from_dict(czech_row["episode"])
    title = "The Big Bang Theory S01E01 Pilot CZ Dabing"
    states["cz"].success(episode, "11", title)
    states["en"].row(episode)["upload"] = {"target_video_id": "11", "display_name": "The Big Bang Theory S01E01 Pilot"}
    before = copy.deepcopy(states["cz"].data)
    monkeypatch.setattr(reconcile, "owned_name", lambda *_: title)
    result = reconcile.repair_cross_variant_records(tmp_path, states, object())
    assert result["false_english_completions_reviewed"] == 1
    assert result["physical_videos_changed"] == 0
    assert states["cz"].data == before
    assert not states["en"].row(episode).get("upload")
    assert states["en"].row(episode)["reconciliation_reviews"][0]["rejected_upload"]["target_video_id"] == "11"


def test_shared_target_with_source_evidence_is_not_reset(tmp_path, czech_row, monkeypatch):
    states = {v: VariantState(tmp_path / f"{v}.json", v) for v in ("cz", "en")}
    episode = Episode.from_dict(czech_row["episode"])
    states["cz"].success(episode, "11", "Show S01E01 CZ Dabing")
    record = states["en"].row(episode)
    record["upload"] = {"target_video_id": "11"}
    record["source"] = {"source_id": "real-source"}
    with pytest.raises(ValueError, match="manual review"):
        reconcile.repair_cross_variant_records(tmp_path, states, object())
    assert record["upload"]["target_video_id"] == "11"


def test_rename_uses_transferred_dimensions_even_if_manifest_upgraded(tmp_path, czech_row, titles, monkeypatch):
    states = {v: VariantState(tmp_path / f"{v}.json", v) for v in ("cz", "en")}
    episode = Episode.from_dict(czech_row["episode"])
    old = "The Big Bang Theory S01E01 Pilot CZ Dabing"
    states["cz"].success(episode, "11", old)
    states["cz"].row(episode)["source"] = {"source_id": "123", "width": 1920, "height": 1080}
    czech_row["selected"].update(width=3840, height=2160)
    visible = {"11": old}
    monkeypatch.setattr(reconcile, "owned_name", lambda _, video_id: visible[video_id])
    monkeypatch.setattr(reconcile, "rename_video", lambda _, video_id, title: visible.update({video_id: title}))
    result = reconcile.rename_tracked(tmp_path, {"cz": [czech_row], "en": []}, states, titles, object())
    assert result["renamed"] == 1
    assert visible["11"] == "The Big Bang Theory S01E01 Pilot 1080p CZ Dabing"
    assert (
        reconcile.rename_tracked(tmp_path, {"cz": [czech_row], "en": []}, states, titles, object())["already_correct"]
        == 1
    )
