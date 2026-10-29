import copy
import threading
import time

from sdilej_serialy.models import Episode
from sdilej_serialy.source_transfer import SourceUnavailable

from lenka_sync import pipeline
from lenka_sync.storage import atomic_json, read_json, write_rows


def seed(root, czech_row, english_row, titles):
    titles["episodes"]["42:1:2"] = {"status": "official_english_episode_title_unavailable"}
    czech = [czech_row, copy.deepcopy(czech_row)]
    english = [english_row, copy.deepcopy(english_row)]
    for variant in (czech, english):
        variant[1]["identity"] = "42:1:2"
        variant[1]["episode"].update(episode=2, episode_id=101)
        variant[1]["selected"].update(
            source_id=variant[1]["selected"]["source_id"] + "0",
            url=variant[1]["selected"]["url"]
            .replace("/episode", "/second-episode")
            .replace("/" + variant[1]["selected"]["source_id"] + "/", "/" + variant[1]["selected"]["source_id"] + "0/"),
        )
    write_rows(root / "variants/cz/manifests/selected-episodes.jsonl", czech)
    write_rows(root / "variants/en/manifests/selected-episodes.jsonl", english)
    atomic_json(root / "state/titles.json", titles)


def test_three_workers_are_shared_across_variants(tmp_path, czech_row, english_row, titles, monkeypatch):
    seed(tmp_path, czech_row, english_row, titles)
    monkeypatch.setattr(
        pipeline,
        "credentials",
        lambda: dict(
            source_email="source", source_password="test", target_email="target@example.invalid", target_password="test"
        ),
    )
    monkeypatch.setattr(pipeline, "followup", lambda *_, **__: {"checked": 0})
    lock = threading.Lock()
    active = maximum = 0

    def transfer(selected, state, **kwargs):
        nonlocal active, maximum
        assert kwargs["workers"] == 1 and kwargs["require_original_size"]
        with lock:
            active += 1
            maximum = max(maximum, active)
        time.sleep(0.03)
        row = selected[0]
        state.success(Episode.from_dict(row["episode"]), row["selected"]["source_id"], row["display_name"])
        with lock:
            active -= 1
        return {"uploaded_or_reconciled": 1}

    monkeypatch.setattr(pipeline, "upload_continuously", transfer)
    result = pipeline.upload(tmp_path, workers=3, limit=4, runtime_minutes=1)
    assert result["confirmed_uploads"] == 4
    assert maximum == 3
    for variant in ("cz", "en"):
        assert len(read_json(tmp_path / f"variants/{variant}/state/uploads.json")["episodes"]) == 2


def test_source_login_outage_defers_without_losing_other_variant(tmp_path, czech_row, english_row, titles, monkeypatch):
    seed(tmp_path, czech_row, english_row, titles)
    monkeypatch.setattr(pipeline, "credentials", lambda: {})
    monkeypatch.setattr(pipeline, "followup", lambda *_, **__: {})

    def transfer(*_, **__):
        raise SourceUnavailable("do not expose this authenticated URL")

    monkeypatch.setattr(pipeline, "upload_continuously", transfer)
    result = pipeline.upload(tmp_path, workers=2, limit=2, runtime_minutes=1)
    assert result["confirmed_uploads"] == 0
    state = read_json(tmp_path / "variants/cz/state/uploads.json")
    assert state["episodes"]["42:1:1"]["attempts"][-1]["error"] == "SourceUnavailable"
