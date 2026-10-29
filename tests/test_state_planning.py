import pytest
from sdilej_serialy.models import Episode
from lenka_sync.pipeline import planned
from lenka_sync.state import VariantState
from lenka_sync.storage import atomic_json


def test_same_episode_has_two_independent_variants(tmp_path, czech_row, english_row, titles):
    states = {variant: VariantState(tmp_path / f"{variant}.json", variant) for variant in ("cz", "en")}
    queue = {"cz": [czech_row], "en": [english_row]}
    assert [r["variant"] for r in planned(queue, titles, states)] == ["cz", "en"]
    states["cz"].success(Episode.from_dict(czech_row["episode"]), "1000", "uploaded")
    assert [r["variant"] for r in planned(queue, titles, states)] == ["en"]
    assert (
        VariantState(tmp_path / "cz.json", "cz").data["binding"]["account_hash"]
        == __import__("hashlib").sha256(b"target@example.invalid").hexdigest()
    )


def test_foreign_history_is_rejected(tmp_path):
    path = tmp_path / "old.json"
    atomic_json(path, {"schema_version": 1, "episodes": {"1:1:1": {"upload": {"target_video_id": "99"}}}})
    with pytest.raises(ValueError):
        VariantState(path, "cz")


def test_uncertain_allocation_cannot_be_replaced(tmp_path, czech_row, titles):
    states = {variant: VariantState(tmp_path / f"{variant}.json", variant) for variant in ("cz", "en")}
    record = states["cz"].row(Episode.from_dict(czech_row["episode"]))
    record["prepared_target"] = {"target_video_id": "12345", "size_bytes": 500_000_000}
    assert not planned({"cz": [czech_row], "en": []}, titles, states)
    record["transfer_receipt"] = dict(
        target_video_id="12345", size_bytes=500_000_000, source_bytes_read=500_000_000, http_status=200
    )
    assert len(planned({"cz": [czech_row], "en": []}, titles, states)) == 1


def test_unchecked_episode_names_wait_for_metadata(tmp_path, czech_row, titles):
    states = {variant: VariantState(tmp_path / f"{variant}.json", variant) for variant in ("cz", "en")}
    titles["episodes"] = {}
    assert not planned({"cz": [czech_row], "en": []}, titles, states)
    titles["episodes"][czech_row["identity"]] = {"status": "official_english_episode_title_unavailable"}
    assert len(planned({"cz": [czech_row], "en": []}, titles, states)) == 1
