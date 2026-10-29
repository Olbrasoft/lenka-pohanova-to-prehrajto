import pytest
from lenka_sync.naming import combined_title, display_name, series_names
from lenka_sync.policy import upload_eligible, target_credentials


def test_names_follow_marketa(czech_row, english_row, titles):
    assert display_name(czech_row, titles) == "The Big Bang Theory S01E01 Pilot CZ Dabing"
    assert display_name(english_row, titles) == "The Big Bang Theory S01E01 Pilot"
    assert display_name(english_row, titles, subtitles_ready=True).endswith("Pilot CZ Titulky")
    english_row["subtitles"] = {"method": "burned_in_ocr_verified"}
    assert display_name(english_row, titles).endswith("Pilot CZ Titulky")


def test_original_title_and_missing_episode_title(czech_row, titles):
    titles["series"]["42"].update(english_title="Money Heist", original_title="La casa de papel")
    titles["episodes"] = {czech_row["identity"]: {"status": "official_english_episode_title_unavailable"}}
    assert display_name(czech_row, titles) == "Money Heist (La casa de papel) S01E01 CZ Dabing"
    assert "Pilotní" not in display_name(czech_row, titles)
    assert combined_title(" DARK ", "Dark") == "DARK"


def test_series_name_collisions():
    data = {"1": dict(english_title="The Office", year="2001"), "2": dict(english_title="The Office", year="2005")}
    assert series_names(data) == {"1": "The Office (2001)", "2": "The Office (2005)"}
    data["2"]["year"] = "2001"
    assert "[ID 1]" in series_names(data)["1"]


@pytest.mark.parametrize(
    "field,value",
    [
        ("audio_language", "sk"),
        ("language_probability", 0.4),
        ("match_tier", "ambiguous"),
        ("size_bytes", 18),
        ("url", "https://sdilej.cz/123/x?token=secret"),
        ("url", "https://sdilej.cz.attacker/123/x"),
        ("download_url", "secret"),
    ],
)
def test_reject_unproven_or_unsafe_czech(czech_row, field, value):
    czech_row["selected"][field] = value
    assert not upload_eligible(czech_row)


def test_independent_english_proof(english_row):
    assert upload_eligible(english_row)
    english_row["selected"]["match_evidence"]["lenka"]["first_audio_verified"] = False
    assert not upload_eligible(english_row)


def test_pin_single_account():
    assert (
        target_credentials({"PREHRAJTO_EMAIL": "target@example.invalid", "PREHRAJTO_PASSWORD": "test"})[0]
        == "target@example.invalid"
    )
    with pytest.raises(ValueError):
        target_credentials({"PREHRAJTO_EMAIL": "other@example.invalid", "PREHRAJTO_PASSWORD": "test"})
