import pytest
from lenka_sync.metadata import Metadata, MetadataUnavailable


def test_series_identity_is_exact_and_unique(tmp_path, monkeypatch):
    api = Metadata(tmp_path, api_key="test")
    responses = {
        "search/tv": {"results": [{"id": 10, "original_name": "Dark"}], "total_pages": 1},
        "tv/10": dict(id=10, name="Dark", original_name="Dark", original_language="de", first_air_date="2017-12-01"),
        "tv/10/translations": {"translations": [{"iso_639_1": "en", "data": {"name": "Dark"}}]},
    }
    monkeypatch.setattr(api, "get", lambda endpoint, **_: responses[endpoint])
    assert api.resolve_series({"series_original_title": "Dark"})["tmdb_id"] == 10
    responses["search/tv"]["results"].append({"id": 20, "original_name": "Dark"})
    with pytest.raises(MetadataUnavailable):
        api.resolve_series({"series_original_title": "Dark"})


def test_episode_uses_original_language_without_english_translation(tmp_path, monkeypatch):
    api = Metadata(tmp_path, api_key="test")

    def get(endpoint, **_):
        if endpoint.endswith("translations"):
            return {"translations": [{"iso_639_1": "de", "data": {"name": "Geheimnisse"}}]}
        return {
            "season_number": 1,
            "episodes": [dict(id=100, season_number=1, episode_number=1, show_id=10, name="Geheimnisse")],
        }

    monkeypatch.setattr(api, "get", get)
    assert (
        api.resolve_episode({"season": 1, "episode": 1}, {"tmdb_id": 10, "original_language": "de"})["original_title"]
        == "Geheimnisse"
    )


def test_wrong_episode_numbering_cannot_supply_name(tmp_path, monkeypatch):
    api = Metadata(tmp_path, api_key="test")
    monkeypatch.setattr(api, "get", lambda *_, **__: {"season_number": 2, "episodes": []})
    with pytest.raises(MetadataUnavailable):
        api.resolve_episode({"season": 1, "episode": 1}, {"tmdb_id": 10, "original_language": "en"})
