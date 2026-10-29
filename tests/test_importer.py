import copy
from lenka_sync.importer import import_sources
from lenka_sync.storage import atomic_json, rows, write_rows


def upstream_fixture(path, row):
    metadata = {**row["episode"], "priority_rank": 1, "imdb_rating": 9.1, "imdb_votes": 1000}
    write_rows(path / "backlog/series-episodes.jsonl.gz", [metadata])
    write_rows(path / "manifests/selected-episodes.jsonl", [row])


def test_import_sources_without_target_history(tmp_path, czech_row):
    upstream, root = tmp_path / "upstream", tmp_path / "lenka"
    czech_row.update(target_account="a", queue_rank=1, upload={"target_video_id": "999"})
    upstream_fixture(upstream, czech_row)
    first = import_sources(root, upstream)
    assert first["imported"] == 1
    imported = rows(root / "variants/cz/manifests/selected-episodes.jsonl")[0]
    assert not {"target_account", "queue_rank", "upload", "target_video_id"} & imported.keys()
    assert not (root / "variants/cz/state/uploads.json").exists()
    assert import_sources(root, upstream)["imported"] == 0


def test_highest_resolution_beats_an_older_completed_source(tmp_path, czech_row):
    upstream, root = tmp_path / "upstream", tmp_path / "lenka"
    completed = copy.deepcopy(czech_row)
    newer = copy.deepcopy(czech_row)
    newer["selected"].update(source_id="777", url="https://sdilej.cz/777/better.mkv", width=3840, height=2160)
    upstream_fixture(upstream, newer)
    generation = upstream / "dual/example"
    write_rows(generation / "manifest.jsonl", [completed])
    atomic_json(generation / "state.json", {"episodes": {completed["identity"]: {"upload": {"target_video_id": "99"}}}})
    import_sources(root, upstream)
    assert rows(root / "variants/cz/manifests/selected-episodes.jsonl")[0]["selected"]["source_id"] == "777"


def test_queued_sources_upgrade_but_uploaded_source_bindings_remain(tmp_path, czech_row):
    upstream, root = tmp_path / "upstream", tmp_path / "lenka"
    upstream_fixture(upstream, czech_row)
    import_sources(root, upstream)
    better = copy.deepcopy(czech_row)
    better["selected"].update(source_id="777", url="https://sdilej.cz/777/uhd.mkv", width=3840, height=2160)
    write_rows(upstream / "manifests/quality-upgrades.jsonl", [better])
    assert import_sources(root, upstream)["queued_upgrades"] == 1
    best = copy.deepcopy(better)
    best["selected"].update(source_id="888", url="https://sdilej.cz/888/smaller-uhd.mkv", size_bytes=400_000_000)
    write_rows(upstream / "manifests/quality-upgrades.jsonl", [best])
    atomic_json(
        root / "variants/cz/state/uploads.json",
        {"episodes": {czech_row["identity"]: {"upload": {"target_video_id": "99"}}}},
    )
    assert import_sources(root, upstream)["queued_upgrades"] == 0
    assert rows(root / "variants/cz/manifests/selected-episodes.jsonl")[0]["selected"]["source_id"] == "777"


def test_foreign_sources_are_not_imported(tmp_path, english_row):
    upstream, root = tmp_path / "upstream", tmp_path / "lenka"
    upstream_fixture(upstream, english_row)
    assert import_sources(root, upstream)["czech_sources"] == 0
