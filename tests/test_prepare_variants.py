from copy import deepcopy
from types import SimpleNamespace

from sdilej_serialy.models import Episode
from sdilej_to_prehrajto.models import Candidate

from lenka_sync.pipeline import prepare, sources
from lenka_sync.policy import ENGLISH_SELECTION_POLICY
from lenka_sync.state import VariantState
from lenka_sync.storage import atomic_json, read_json, write_rows


def test_existing_subtitled_upload_is_preserved_and_missing_plain_variant_is_prepared(
    tmp_path, czech_row, english_row, plain_row, titles
):
    write_rows(tmp_path / "variants/cz/manifests/selected-episodes.jsonl", [czech_row])
    write_rows(tmp_path / "variants/en/manifests/selected-episodes.jsonl", [english_row])
    atomic_json(tmp_path / "state/titles.json", titles)
    # Old successful discovery must not prevent checking the newly added variant.
    atomic_json(
        tmp_path / "variants/en/state/discovery.json",
        {czech_row["identity"]: dict(status="verified", retry_after="2999-01-01T00:00:00+00:00")},
    )
    state = VariantState(tmp_path / "variants/en/state/uploads.json", "en")
    state.success(Episode.from_dict(czech_row["episode"]), "777", "Existing subtitled upload")
    before = deepcopy(state.data)
    replacement = Candidate.from_dict(english_row["selected"])
    replacement.source_id = "999"
    replacement.url = "https://sdilej.cz/999/replacement.mkv"
    found = {
        "en": (replacement, english_row["subtitles"]),
        "en_plain": (Candidate.from_dict(plain_row["selected"]), plain_row["subtitles"]),
    }
    discovery = SimpleNamespace(discover=lambda *_, **__: found)
    result = prepare(tmp_path, discovery=discovery)
    queue = sources(tmp_path)
    assert result["selected"] == {"en": 1, "en_plain": 1}
    assert queue["en"][0] == english_row
    assert queue["en_plain"][0]["selected"]["source_id"] == "789"
    assert read_json(state.path) == before
    progress = read_json(tmp_path / "variants/en/state/discovery.json")[czech_row["identity"]]
    assert progress["selection_policy"] == ENGLISH_SELECTION_POLICY
    assert progress["available_variants"] == ["en", "en_plain"]


def test_missing_subtitled_source_does_not_clone_plain_video(tmp_path, czech_row, plain_row, titles):
    write_rows(tmp_path / "variants/cz/manifests/selected-episodes.jsonl", [czech_row])
    atomic_json(tmp_path / "state/titles.json", titles)
    found = {"en_plain": (Candidate.from_dict(plain_row["selected"]), plain_row["subtitles"])}
    result = prepare(tmp_path, discovery=SimpleNamespace(discover=lambda *_, **__: found))
    assert result["selected"] == {"en": 0, "en_plain": 1}
    assert sources(tmp_path)["en"] == []


def test_same_original_cannot_be_prepared_twice_with_different_subtitle_labels(
    tmp_path, czech_row, english_row, titles
):
    write_rows(tmp_path / "variants/cz/manifests/selected-episodes.jsonl", [czech_row])
    atomic_json(tmp_path / "state/titles.json", titles)
    candidate = Candidate.from_dict(english_row["selected"])
    found = {"en": (candidate, english_row["subtitles"]), "en_plain": (candidate, {"method": "none"})}
    result = prepare(tmp_path, discovery=SimpleNamespace(discover=lambda *_, **__: found))
    assert result["selected"] == {"en": 0, "en_plain": 0}
    assert read_json(tmp_path / "variants/en/state/discovery.json")[czech_row["identity"]]["status"] == "ValueError"
