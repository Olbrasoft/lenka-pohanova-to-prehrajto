import copy
import pytest
from types import SimpleNamespace

from sdilej_serialy.models import Episode
from sdilej_to_prehrajto.models import Candidate
from sdilej_to_prehrajto.sdilej import SdilejError
from sdilej_serialy.subtitle_media import SubtitleUnavailable

from lenka_sync.discovery import EnglishDiscovery
from lenka_sync.language import WhisperLanguageDetector, LanguageDetectionError


def test_first_default_audio_cannot_be_proven_by_secondary_english(czech_row, monkeypatch):
    candidate = Candidate.from_dict(czech_row["selected"])
    candidate.download_url = "https://private.invalid/original"
    provider = SimpleNamespace(_get=lambda _: SimpleNamespace(text=""), session=object())
    monkeypatch.setattr("lenka_sync.discovery.parse_detail_html", lambda _, __: candidate)
    monkeypatch.setattr("lenka_sync.discovery.resolve_original", lambda _, detail: detail)
    payload = {
        "streams": [
            dict(codec_type="video", width=1920, height=1080),
            dict(codec_type="audio", tags={"language": "ces"}),
            dict(codec_type="audio", tags={"language": "eng"}),
        ],
        "format": {"duration": 1320},
    }
    discovery = EnglishDiscovery(provider, None, probe=lambda _: payload)
    assert discovery.verify(Episode.from_dict(czech_row["episode"]), candidate, 99999999) is None


def test_incomplete_scan_cannot_choose_subtitle_free_fallback(czech_row):
    first = Candidate.from_dict(czech_row["selected"])
    second = copy.deepcopy(first)
    second.source_id = "456"
    provider = SimpleNamespace(search=lambda _: [first, second])
    discovery = EnglishDiscovery(provider, None)

    def verify(_, candidate, __):
        if candidate.source_id == "456":
            raise SubtitleUnavailable("source_media_timeout")
        return candidate, {"method": "none"}

    discovery.verify = verify
    with pytest.raises(SdilejError):
        discovery.discover(czech_row, {"english_title": "The Big Bang Theory"})


def test_proven_subtitled_source_survives_other_candidate_error(czech_row):
    first = Candidate.from_dict(czech_row["selected"])
    second = copy.deepcopy(first)
    second.source_id = "456"
    discovery = EnglishDiscovery(SimpleNamespace(search=lambda _: [first, second]), None)

    def verify(_, candidate, __):
        if candidate.source_id == "456":
            raise SubtitleUnavailable("source_media_timeout")
        return candidate, {"method": "original_text", "sha256": "a" * 64}

    discovery.verify = verify
    assert discovery.discover(czech_row, {"english_title": "The Big Bang Theory"})[0].source_id == "123"


def test_subtitles_have_priority_over_resolution(czech_row):
    candidate = Candidate.from_dict(czech_row["selected"])
    high = copy.deepcopy(candidate)
    high.source_id, high.width, high.height = "999", 3840, 2160
    discovery = EnglishDiscovery(SimpleNamespace(search=lambda _: [high, candidate]), None)
    discovery.verify = lambda _, selected, __: (
        selected,
        {"method": "none" if selected.source_id == "999" else "original_text"},
    )
    assert discovery.discover(czech_row, {"english_title": "The Big Bang Theory"})[0].source_id == "123"


def test_speech_requires_two_agreeing_first_track_samples(monkeypatch):
    detector = WhisperLanguageDetector(seconds=30)
    samples = iter([("cs", 0.99), ("cs", 0.97), ("en", 0.99)])
    monkeypatch.setattr(detector, "_detect_at", lambda *_: next(samples))
    assert detector.detect_consensus("private", 300, preferred_language="en")[0] == "cs"
    assert detector.audio_stream == "0:a:0"
    samples = iter([("cs", 0.99), ("de", 0.97), ("en", 0.99)])
    with pytest.raises(LanguageDetectionError):
        detector.detect_consensus("private", 300, preferred_language="en")


def test_short_episode_samples_stay_inside_original(monkeypatch):
    detector = WhisperLanguageDetector(seconds=20)
    offsets = []

    def sample(_, offset):
        offsets.append(offset)
        return "en", 0.99

    monkeypatch.setattr(detector, "_detect_at", sample)
    detector.detect_consensus("private", 100)
    assert offsets == [25, 50, 75]
