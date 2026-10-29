import copy
import pytest


@pytest.fixture
def czech_row():
    return dict(
        identity="42:1:1",
        variant="cz",
        lenka_policy="lenka-series-variants-v1",
        quality_policy="original-media-v4",
        episode=dict(
            episode_id=100,
            series_id=42,
            series_title="Teorie velkého třesku",
            series_original_title="The Big Bang Theory",
            season=1,
            episode=1,
            title="Pilotní díl",
            runtime_min=22,
        ),
        selected=dict(
            source_id="123",
            url="https://sdilej.cz/123/episode.mkv",
            title="The Big Bang Theory S01E01 CZ.mkv",
            filename="The Big Bang Theory S01E01 CZ.mkv",
            width=1920,
            height=1080,
            size_bytes=500_000_000,
            duration_sec=1320,
            audio_language="cs",
            language_probability=0.98,
            language_tier="czech_audio",
            match_tier="strong",
            match_evidence={},
        ),
        catalog=dict(priority_rank=1, priority_score=9.1),
    )


@pytest.fixture
def english_row(czech_row):
    row = copy.deepcopy(czech_row)
    row["variant"] = "en"
    row["selected"].update(
        source_id="456",
        url="https://sdilej.cz/456/episode-en.mkv",
        audio_language="en",
        language_tier="foreign_audio",
        match_evidence={
            "lenka": dict(policy="lenka-series-variants-v1", first_audio_verified=True, subtitles_checked=True)
        },
    )
    row["subtitles"] = {"method": "original_text", "sha256": "a" * 64, "language": "cs"}
    return row


@pytest.fixture
def plain_row(english_row):
    row = copy.deepcopy(english_row)
    row["variant"] = "en_plain"
    row["subtitles"] = {"method": "none"}
    row["selected"].update(source_id="789", url="https://sdilej.cz/789/plain.mkv", width=3840, height=2160)
    return row


@pytest.fixture
def titles():
    return {
        "series": {
            "42": dict(
                english_title="The Big Bang Theory", original_title="The Big Bang Theory", original_language="en"
            )
        },
        "episodes": {"42:1:1": {"english_title": "Pilot"}},
    }


@pytest.fixture(autouse=True)
def synthetic_target_account(monkeypatch):
    import hashlib
    from lenka_sync import policy

    monkeypatch.setattr(policy, "TARGET_ACCOUNT_HASH", hashlib.sha256(b"target@example.invalid").hexdigest())
