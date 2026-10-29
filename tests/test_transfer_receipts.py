from types import SimpleNamespace

from sdilej_serialy.models import Episode
from lenka_sync import transfer
from lenka_sync.state import VariantState


def setup_transfer(monkeypatch):
    monkeypatch.setattr(transfer.EpisodeSourceProvider, "authenticated", lambda *_: SimpleNamespace(session=object()))
    monkeypatch.setattr(transfer.prehrajto, "uploaded_video_count", lambda _: 1)
    monkeypatch.setattr(transfer, "existing_episode", lambda *_: None)
    monkeypatch.setattr(transfer, "prepare_source", lambda _, candidate, __: candidate)
    monkeypatch.setattr(transfer, "target_confirmed", lambda *_: True)


def run(row, state):
    return transfer.upload_continuously(
        [row],
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
