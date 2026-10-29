import hashlib
from types import SimpleNamespace
from sdilej_serialy.models import Episode
from lenka_sync import subtitles
from lenka_sync.state import VariantState
from lenka_sync.storage import atomic_json, read_json


class Session:
    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass

    def mount(self, *_):
        pass

    def get(self, *_, **__):
        return SimpleNamespace(text="listing", raise_for_status=lambda: None)


def setup(tmp_path, english_row, monkeypatch, *, tracks):
    row = english_row
    row["subtitles"] = dict(method="original_text", sha256=hashlib.sha256(b"subtitle").hexdigest())
    state = VariantState(tmp_path / "variants/en/state/uploads.json", "en")
    episode = Episode.from_dict(row["episode"])
    state.row(episode)["source"] = dict(
        source_id=row["selected"]["source_id"],
        source_url=row["selected"]["url"],
        size_bytes=row["selected"]["size_bytes"],
    )
    state.success(episode, "777", "The Big Bang Theory S01E01 Pilot")
    view = SimpleNamespace(
        video_id="777",
        title="The Big Bang Theory S01E01 Pilot",
        ready=True,
        detail_url="https://prehraj.to/episode/abcdef0123456789",
        action="upload",
        tracks=tracks,
        has_czech=bool(tracks),
        unknown_tracks=False,
    )
    api = SimpleNamespace(
        refresh=lambda *_: view,
        verify_content=lambda *_: True,
        upload=lambda *_: (_ for _ in ()).throw(AssertionError("Subtitle POST must not be repeated")),
    )
    provider = SimpleNamespace(session=SimpleNamespace(close=lambda: None))
    monkeypatch.setattr(subtitles.EpisodeSourceProvider, "authenticated", lambda *_: provider)
    monkeypatch.setattr(subtitles, "target_session", lambda *_, **__: Session())
    monkeypatch.setattr(subtitles, "SubtitleTarget", lambda _: api)
    monkeypatch.setattr(subtitles, "parse_listing", lambda _: ([view], 1))
    return state


def credentials():
    return dict(
        source_email="source", source_password="test", target_email="target@example.invalid", target_password="test"
    )


def test_uncertain_subtitle_post_is_only_reconciled(tmp_path, english_row, titles, monkeypatch):
    state = setup(tmp_path, english_row, monkeypatch, tracks=[])
    path = tmp_path / "variants/en/state/subtitles.json"
    atomic_json(
        path,
        dict(
            account_hash=__import__("hashlib").sha256(b"target@example.invalid").hexdigest(),
            videos={
                "777": dict(
                    identity=english_row["identity"],
                    status="upload_unconfirmed",
                    intent=dict(filename="episode-777.srt", before_ids=[]),
                )
            },
        ),
    )
    subtitles.followup(tmp_path, [english_row], state, titles, credentials())
    data = read_json(path)
    assert data["videos"]["777"]["status"] == "upload_unconfirmed"
    assert not data["videos"]["777"].get("title_updated")
    assert not state.data["episodes"][english_row["identity"]]["upload"]["display_name"].endswith("CZ Titulky")


def test_czech_label_is_added_only_after_target_content_verification(tmp_path, english_row, titles, monkeypatch):
    track = dict(id="11", czech=True, processing=False, language_action="")
    state = setup(tmp_path, english_row, monkeypatch, tracks=[track])
    renamed = []
    monkeypatch.setattr(
        subtitles.prehrajto, "rename_video", lambda _, video_id, title: renamed.append((video_id, title))
    )
    monkeypatch.setattr("lenka_sync.transfer.target_confirmed", lambda *_: True)
    subtitles.followup(tmp_path, [english_row], state, titles, credentials())
    assert renamed == [("777", "The Big Bang Theory S01E01 Pilot CZ Titulky")]
    saved = read_json(tmp_path / "variants/en/state/subtitles.json")
    assert saved["videos"]["777"]["title_updated"] is True
