import html
from types import SimpleNamespace
import pytest

from sdilej_serialy.models import Episode
from lenka_sync import transfer
from lenka_sync.target import existing_episode, clean_name
from lenka_sync.state import VariantState


def response(body):
    return SimpleNamespace(status_code=200, text=body, raise_for_status=lambda: None)


def listing(video_id, name):
    return f"""<div id="uploadedVideoListing"><div><h3>{html.escape(name)}</h3>
        <a href="?do=uploadedVideoListing-deleteVideo&amp;uploadedVideoListing-videoId={video_id}">Delete</a>
        </div></div>"""


def test_czech_episode_cannot_satisfy_english_lookup():
    session = SimpleNamespace(get=lambda *_, **__: response(listing("11", "Show S01E01 Pilot 1080p CZ Dabing")))
    assert existing_episode(session, "Show S01E01 Pilot 1080p") is None
    assert existing_episode(session, "Show S01E01 Pilot 1080p CZ Dabing") == "11"


def test_subtitled_target_cannot_satisfy_plain_lookup():
    session = SimpleNamespace(get=lambda *_, **__: response(listing("11", "Show S01E01 Pilot 1080p CZ Titulky")))
    assert existing_episode(session, "Show S01E01 Pilot 4K", variant="en_plain") is None
    assert existing_episode(session, "Show S01E01 Pilot 1080p", variant="en") == "11"


def test_known_czech_id_cannot_confirm_english_variant():
    session = SimpleNamespace(
        get=lambda *_, **__: response("<h1>Změna složky videa</h1><h2>Show S01E01 Pilot 1080p CZ Dabing.mkv</h2>")
    )
    assert existing_episode(session, "Show S01E01 Pilot 1080p", "11") is None
    assert existing_episode(session, "Show S01E01 Pilot 1080p CZ Dabing", "11") == "11"
    assert clean_name("Show S01E01 ...And the Bag 1080p.mkv (zpracovává se)") == "show s01e01 and the bag 1080p"


def test_owned_heading_does_not_duplicate_mobile_and_desktop_text():
    session = SimpleNamespace(
        get=lambda *_, **__: response("""<h1>Změna složky videa</h1><h2>
      <span class="hide-for-large">Show S01E01 Pilot CZ Dabing.mkv</span>
      <span class="show-for-large color-g650">Show S01E01 Pilot CZ Dabing.mkv</span></h2>""")
    )
    from lenka_sync.target import owned_name

    assert owned_name(session, "11") == "Show S01E01 Pilot CZ Dabing.mkv"


def test_rename_uses_the_live_naja_get_contract():
    from lenka_sync.target import rename_video

    calls = []

    def get(url, **kwargs):
        calls.append((url, kwargs))
        return SimpleNamespace(
            headers={"Content-Type": "application/json"}, json=lambda: {}, raise_for_status=lambda: None
        )

    rename_video(SimpleNamespace(get=get), "88", "Show S01E01 Pilot 1080p")
    assert calls[0][1]["params"] == {
        "uploadedVideoListing-videoId": "88",
        "do": "uploadedVideoListing-changeVideoName",
        "uploadedVideoListing-name": "Show S01E01 Pilot 1080p",
    }
    assert calls[0][1]["allow_redirects"] is False


@pytest.mark.parametrize("first,second", [("cz", "en"), ("en", "en_plain"), ("en_plain", "cz")])
def test_same_target_id_cannot_belong_to_both_variants(tmp_path, czech_row, first, second):
    states = {v: VariantState(tmp_path / f"{v}.json", v) for v in ("cz", "en", "en_plain")}
    for state in states.values():
        state.peers = states
    episode = Episode.from_dict(czech_row["episode"])
    states[first].success(episode, "11", "Show S01E01 1080p")
    with pytest.raises(RuntimeError, match="another language variant"):
        states[second].success(episode, "11", "Show S01E01 1080p")


def test_real_english_transfer_allocates_a_different_id_than_existing_czech(tmp_path, english_row, monkeypatch):
    states = {v: VariantState(tmp_path / f"{v}.json", v) for v in ("cz", "en")}
    for state in states.values():
        state.peers = states
    episode = Episode.from_dict(english_row["episode"])
    base = "The Big Bang Theory S01E01 Pilot 1080p"
    states["cz"].success(episode, "11", base + " CZ Dabing")
    english_row["display_name"] = base

    def get(url, **kwargs):
        if "uprava-slozky" in url:
            title = base if kwargs["params"]["videoId"] == "88" else base + " CZ Dabing"
            return response("<h1>Změna složky videa</h1><h2>" + html.escape(title) + "</h2>")
        return response(listing("11", base + " CZ Dabing"))

    session = SimpleNamespace(get=get)
    monkeypatch.setattr(transfer.EpisodeSourceProvider, "authenticated", lambda *_: SimpleNamespace(session=object()))
    monkeypatch.setattr(transfer.prehrajto, "uploaded_video_count", lambda _: 2)
    monkeypatch.setattr(transfer, "prepare_source", lambda _, candidate, __: candidate)
    monkeypatch.setattr("sdilej_serialy.resilience.requests.post", lambda *_, **__: SimpleNamespace(status_code=201))
    calls = []

    def relay(_, __, candidate, *args, **kwargs):
        calls.append(candidate.source_id)
        kwargs["on_prepared"]("88", candidate.size_bytes)
        reader = SimpleNamespace(position=candidate.size_bytes, total=candidate.size_bytes)
        kwargs["upload_requester"](
            "https://upload.invalid", data=SimpleNamespace(fields=[("files", ("episode.mkv", reader, "video/mp4"))])
        )
        return SimpleNamespace(video_id="88")

    monkeypatch.setattr(transfer.prehrajto, "relay_upload", relay)
    result = transfer.upload_continuously(
        [english_row],
        states["en"],
        workers=1,
        source_email="source",
        source_password="test",
        target_email="target@example.invalid",
        target_password="test",
        target_login=lambda: session,
        require_original_size=True,
        select_source=lambda row: row,
        recover_source_errors=True,
        recover_target_errors=True,
    )
    assert result["uploaded_or_reconciled"] == 1
    assert calls == ["456"]
    assert states["en"].row(episode)["upload"]["target_video_id"] == "88"
    assert states["en"].row(episode)["source"]["audio_language"] == "en"
    assert states["en"].row(episode)["completion_evidence"]["receipt"]["http_status"] == 201


def test_untracked_existing_variant_is_not_counted_as_a_completed_transfer(tmp_path, english_row, monkeypatch):
    state = VariantState(tmp_path / "en.json", "en")
    english_row["display_name"] = "The Big Bang Theory S01E01 Pilot 1080p"
    session = SimpleNamespace(get=lambda *_, **__: response(listing("99", english_row["display_name"])))
    monkeypatch.setattr(transfer.EpisodeSourceProvider, "authenticated", lambda *_: SimpleNamespace(session=object()))
    monkeypatch.setattr(transfer.prehrajto, "uploaded_video_count", lambda _: 1)
    monkeypatch.setattr(
        transfer.prehrajto,
        "relay_upload",
        lambda *_, **__: pytest.fail("Untracked existing variant must not be replayed"),
    )
    result = transfer.upload_continuously(
        [english_row],
        state,
        workers=1,
        source_email="source",
        source_password="test",
        target_email="target@example.invalid",
        target_password="test",
        target_login=lambda: session,
        require_original_size=True,
        recover_target_errors=True,
    )
    assert result["uploaded_or_reconciled"] == 0
    record = state.row(Episode.from_dict(english_row["episode"]))
    assert not record.get("upload")
    assert record["review_target_id"] == "99"


@pytest.mark.parametrize("subtitle_ready", [False, True])
def test_plain_transfer_allocates_own_id_next_to_subtitled_or_processing_target(
    tmp_path, plain_row, monkeypatch, subtitle_ready
):
    states = {v: VariantState(tmp_path / f"{v}.json", v) for v in ("cz", "en", "en_plain")}
    for state in states.values():
        state.peers = states
    episode = Episode.from_dict(plain_row["episode"])
    base = "The Big Bang Theory S01E01 Pilot 4K"
    sibling_name = base + " CZ Titulky" if subtitle_ready else base
    states["en"].success(episode, "11", sibling_name)
    plain_row["display_name"] = base

    def get(url, **kwargs):
        if "uprava-slozky" in url:
            return response("<h1>Změna složky videa</h1><h2>" + html.escape(base) + "</h2>")
        return response(listing("11", sibling_name))

    session = SimpleNamespace(get=get)
    monkeypatch.setattr(transfer.EpisodeSourceProvider, "authenticated", lambda *_: SimpleNamespace(session=object()))
    monkeypatch.setattr(transfer.prehrajto, "uploaded_video_count", lambda _: 2)
    monkeypatch.setattr(transfer, "prepare_source", lambda _, candidate, __: candidate)
    monkeypatch.setattr("sdilej_serialy.resilience.requests.post", lambda *_, **__: SimpleNamespace(status_code=201))

    def relay(_, __, candidate, *args, **kwargs):
        kwargs["on_prepared"]("88", candidate.size_bytes)
        reader = SimpleNamespace(position=candidate.size_bytes, total=candidate.size_bytes)
        kwargs["upload_requester"](
            "https://upload.invalid", data=SimpleNamespace(fields=[("files", ("episode.mkv", reader, "video/mp4"))])
        )
        return SimpleNamespace(video_id="88")

    monkeypatch.setattr(transfer.prehrajto, "relay_upload", relay)
    result = transfer.upload_continuously(
        [plain_row], states["en_plain"], workers=1, source_email="source", source_password="test",
        target_email="target@example.invalid", target_password="test", target_login=lambda: session,
        require_original_size=True, select_source=lambda row: row, recover_target_errors=True,
    )
    assert result["uploaded_or_reconciled"] == 1
    record = states["en_plain"].row(episode)
    assert record["upload"]["target_video_id"] == "88"
    assert record["completion_evidence"]["variant"] == "en_plain"
    assert states["en"].row(episode)["upload"]["target_video_id"] == "11"
