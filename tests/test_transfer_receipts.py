from types import SimpleNamespace
import copy
import pytest

from sdilej_serialy.models import Episode
from lenka_sync import transfer
from lenka_sync.state import VariantState
from sdilej_to_prehrajto.models import Candidate
from sdilej_serialy.resilience import TargetPending


def setup_transfer(monkeypatch):
    monkeypatch.setattr(transfer, "rename_video", lambda *_: None)
    monkeypatch.setattr(transfer.EpisodeSourceProvider, "authenticated", lambda *_: SimpleNamespace(session=object()))
    monkeypatch.setattr(transfer.prehrajto, "uploaded_video_count", lambda _: 1)
    monkeypatch.setattr(transfer, "existing_episode", lambda *_, **__: None)
    monkeypatch.setattr(transfer, "prepare_source", lambda _, candidate, __: candidate)
    monkeypatch.setattr(transfer, "target_confirmed", lambda *_: True)


def run(row, state):
    return transfer.upload_continuously(
        row if isinstance(row, list) else [row],
        state,
        workers=1,
        source_email="source",
        source_password="test",
        target_email="target@example.invalid",
        target_password="test",
        target_login=lambda: object(),
        require_original_size=True,
        select_source=lambda value: value,
        recover_source_errors=True,
        recover_target_errors=True,
    )


def test_allocated_target_without_receipt_is_never_uploaded_twice(tmp_path, czech_row, monkeypatch):
    setup_transfer(monkeypatch)
    czech_row["display_name"] = "The Big Bang Theory S01E01 Pilot CZ Dabing"
    state = VariantState(tmp_path / "uploads.json", "cz")
    calls = []

    def relay(_, __, candidate, *args, **kwargs):
        calls.append(candidate.source_id)
        kwargs["on_prepared"]("777", candidate.size_bytes)
        return SimpleNamespace(video_id="777")

    monkeypatch.setattr(transfer.prehrajto, "relay_upload", relay)
    run(czech_row, state)
    record = state.row(Episode.from_dict(czech_row["episode"]))
    assert record["prepared_target"]["target_video_id"] == "777"
    assert not record.get("upload")
    # Simulate a due retry after restart; the saved ID must still block another POST.
    record["attempts"] = []
    run(czech_row, state)
    assert calls == ["123"]
    assert not record.get("upload")


def test_confirmed_upload_requires_exact_bytes_and_http_receipt(tmp_path, czech_row, monkeypatch):
    setup_transfer(monkeypatch)
    czech_row["display_name"] = "The Big Bang Theory S01E01 Pilot CZ Dabing"
    state = VariantState(tmp_path / "uploads.json", "cz")
    monkeypatch.setattr("sdilej_serialy.resilience.requests.post", lambda *_, **__: SimpleNamespace(status_code=201))

    def relay(_, __, candidate, *args, **kwargs):
        kwargs["on_prepared"]("777", candidate.size_bytes)
        reader = SimpleNamespace(position=candidate.size_bytes, total=candidate.size_bytes)
        encoder = SimpleNamespace(fields=[("files", ("episode.mkv", reader, "video/mp4"))])
        kwargs["upload_requester"]("https://upload.invalid", data=encoder)
        return SimpleNamespace(video_id="777")

    monkeypatch.setattr(transfer.prehrajto, "relay_upload", relay)
    assert run(czech_row, state)["uploaded_or_reconciled"] == 1
    record = state.row(Episode.from_dict(czech_row["episode"]))
    assert record["upload"]["target_video_id"] == "777"
    assert "prepared_target" not in record


def accepted(state, row, video_id, name):
    episode = Episode.from_dict(row["episode"])
    candidate = Candidate.from_dict(row["selected"])
    state.prepared(episode, candidate, name)
    record = state.row(episode)
    record["prepared_target"] = dict(target_video_id=video_id, size_bytes=candidate.size_bytes)
    record["transfer_receipt"] = dict(
        target_video_id=video_id, size_bytes=candidate.size_bytes, source_bytes_read=candidate.size_bytes, http_status=201
    )
    return record


def test_accepted_cyrillic_upload_is_renamed_and_completed_without_another_post(tmp_path, czech_row, monkeypatch):
    setup_transfer(monkeypatch)
    original = "Семнадцать мгновений весны S01E01 1 серия 1080p CZ Dabing"
    wanted = "Semnadtsat' mgnoveniy vesny S01E01 1 seriya 1080p CZ Dabing"
    czech_row["display_name"] = wanted
    state = VariantState(tmp_path / "uploads.json", "cz")
    record = accepted(state, czech_row, "777", original)
    monkeypatch.setattr(transfer, "owned_name", lambda *_: "S01E01 1 1080p CZ Dabing.mkv")
    renamed = []
    monkeypatch.setattr(transfer, "rename_video", lambda _, video_id, name: renamed.append((video_id, name)))
    monkeypatch.setattr(transfer.prehrajto, "relay_upload", lambda *_, **__: pytest.fail("Accepted bytes must not be sent again"))
    assert run(czech_row, state)["uploaded_or_reconciled"] == 1
    assert renamed == [("777", wanted)]
    assert record["upload"]["display_name"] == wanted
    assert record["completion_evidence"]["receipt"]["http_status"] == 201


def test_incomplete_receipt_cannot_rename_or_confirm_target(tmp_path, czech_row, monkeypatch):
    state = VariantState(tmp_path / "uploads.json", "cz")
    record = accepted(state, czech_row, "777", "Show S01E01 Pilot 1080p CZ Dabing")
    record["transfer_receipt"]["source_bytes_read"] -= 1
    monkeypatch.setattr(transfer, "owned_name", lambda *_: pytest.fail("Incomplete transfer cannot be reconciled"))
    assert not transfer.confirm_received_target(object(), record, "Show S01E01 Pilot 1080p CZ Dabing")


def test_outside_title_change_is_not_silently_overwritten(tmp_path, czech_row, monkeypatch):
    state = VariantState(tmp_path / "uploads.json", "cz")
    record = accepted(state, czech_row, "777", "Show S01E01 Pilot 1080p CZ Dabing")
    monkeypatch.setattr(transfer, "owned_name", lambda *_: "Other show S01E01 Pilot 1080p CZ Dabing")
    monkeypatch.setattr(transfer, "rename_video", lambda *_: pytest.fail("An outside edit requires review"))
    with pytest.raises(TargetPending):
        transfer.confirm_received_target(object(), record, "Show S01E01 Pilot 1080p CZ Dabing")


def test_one_unreadable_owned_target_does_not_stop_next_episode(tmp_path, czech_row, monkeypatch):
    setup_transfer(monkeypatch)
    state = VariantState(tmp_path / "uploads.json", "cz")
    first, second = copy.deepcopy(czech_row), copy.deepcopy(czech_row)
    first["display_name"] = "Show S01E01 Pilot 1080p CZ Dabing"
    second["identity"] = "42:1:2"
    second["episode"].update(episode=2, episode_id=101)
    second["display_name"] = "Show S01E02 Second 1080p CZ Dabing"
    a = accepted(state, first, "777", first["display_name"])
    b = accepted(state, second, "778", second["display_name"])

    def owned(_, video_id):
        if video_id == "777":
            raise TargetPending("Owned heading is ambiguous")
        return second["display_name"]

    monkeypatch.setattr(transfer, "owned_name", owned)
    monkeypatch.setattr(transfer.prehrajto, "relay_upload", lambda *_, **__: pytest.fail("Neither accepted transfer needs another POST"))
    assert run([first, second], state)["uploaded_or_reconciled"] == 1
    assert a.get("prepared_target") and a.get("transfer_receipt") and not a.get("upload")
    assert b["upload"]["target_video_id"] == "778"
