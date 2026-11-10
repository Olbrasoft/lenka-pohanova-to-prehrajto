from copy import deepcopy
from datetime import UTC, datetime, timedelta

from sdilej_serialy.models import Episode
from sdilej_serialy.source_transfer import SourceUnavailable
from sdilej_to_prehrajto.models import Candidate

from lenka_sync.pipeline import planned
from lenka_sync.state import VariantState


def fail(state, row, *, allocated=False):
    episode = Episode.from_dict(row["episode"])
    state.prepared(episode, Candidate.from_dict(row["selected"]), "Source")
    if allocated:
        state.row(episode)["prepared_target"] = dict(target_video_id=str(episode.number), size_bytes=500_000_000)
    state.failure(episode, SourceUnavailable("Original unavailable"))


def episodes(czech_row):
    result = []
    for number in range(1, 5):
        row = deepcopy(czech_row)
        row["identity"] = f"42:1:{number}"
        row["episode"].update(episode=number, episode_id=100+number)
        result.append(row)
    return result


def test_unavailable_series_yields_to_other_ready_series_and_retries_later(tmp_path, czech_row, titles):
    state = VariantState(tmp_path / "cz.json", "cz")
    unavailable = episodes(czech_row)
    for row in unavailable[:3]:
        fail(state, row)
    other = deepcopy(czech_row)
    other.update(identity="43:1:1", catalog={"priority_rank": 2})
    other["episode"].update(series_id=43)
    titles["series"]["43"] = {"original_title": "Available", "original_language": "en"}
    titles["episodes"][other["identity"]] = {"original_title": "Pilot"}
    titles["episodes"][unavailable[-1]["identity"]] = {"original_title": "Fourth"}
    ready = planned({"cz": unavailable + [other]}, titles, {"cz": state})
    assert [row["identity"] for row in ready] == ["43:1:1"]
    restored = VariantState(state.path, "cz")
    assert restored.source_deferred_series() == {"42"}
    assert not restored.source_deferred_series(at=datetime.now(UTC) + timedelta(minutes=11))


def test_repeating_one_episode_failure_does_not_block_its_series(tmp_path, czech_row):
    state = VariantState(tmp_path / "cz.json", "cz")
    for _ in range(3):
        fail(state, czech_row)
    assert not state.source_deferred_series()


def test_allocated_target_failures_do_not_defer_other_episode_sources(tmp_path, czech_row):
    state = VariantState(tmp_path / "cz.json", "cz")
    for row in episodes(czech_row)[:3]:
        fail(state, row, allocated=True)
    assert not state.source_deferred_series()
