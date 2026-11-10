"""Original-language database names with target-compatible romanization."""

from __future__ import annotations

from collections import Counter
from functools import lru_cache
import re
import unicodedata
from anyascii import anyascii
from sdilej_serialy.quality import resolution_label


def normalized(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


@lru_cache(maxsize=4096)
def japanese_text(value: str) -> str:
    from pykakasi import kakasi

    return " ".join(" ".join(item["hepburn"] for item in kakasi().convert(value)).split())


def target_text(value: str, *, language=None) -> str:
    """Romanize non-Latin letters while retaining Latin names and accents."""
    if language == "ja" and any(
        char.isalpha() and not unicodedata.name(char, "").startswith("LATIN ") for char in value
    ):
        # Kanji readings depend on language. Generic Han transliteration would
        # produce Chinese readings for Japanese episode names.
        value = japanese_text(value)
        if any(char.isalpha() and not unicodedata.name(char, "").startswith("LATIN ") for char in value):
            raise KeyError("Japanese title has no verified romanization")
    parts = []
    for char in unicodedata.normalize("NFC", value):
        if char.isalpha() and not unicodedata.name(char, "").startswith("LATIN "):
            replacement = anyascii(char)
            if not replacement:
                raise KeyError("Original title has a letter without a romanization")
            parts.append(replacement)
        else:
            parts.append(char)
    result = "".join(parts).strip()
    if not result:
        raise KeyError("Original title has no target-compatible text")
    return result


def combined_title(english: str, original: str | None) -> str:
    english = english.strip()
    original = (original or "").strip()
    if not english:
        raise ValueError("Verified English series title is required")
    return english if not original or normalized(english) == normalized(original) else f"{english} ({original})"


def series_names(metadata: dict) -> dict[str, str]:
    ready, titles = {}, {}
    for key, value in metadata.items():
        if not value.get("original_title"):
            continue
        try:
            titles[key] = target_text(value["original_title"], language=value.get("original_language"))
        except KeyError:
            continue
        ready[key] = value
    counts = Counter(normalized(title) for title in titles.values())
    dated = Counter((normalized(titles[key]), value.get("year")) for key, value in ready.items())
    result = {}
    for key, value in ready.items():
        title = titles[key]
        identity, year = normalized(title), value.get("year")
        if counts[identity] > 1:
            title += f" ({year})" if year else ""
            if not year or dated[identity, year] > 1:
                title += f" [ID {key}]"
        result[key] = title
    return result


def display_name(row: dict, titles: dict, *, subtitles_ready=False, names=None) -> str:
    episode = row["episode"]
    series_id = str(episode["series_id"])
    title = (series_names(titles["series"]) if names is None else names)[series_id]
    title += f" S{episode['season']:02d}E{episode['episode']:02d}"
    episode_metadata = titles.get("episodes", {}).get(row["identity"], {})
    if not episode_metadata or episode_metadata.get("status") == "deferred":
        raise KeyError("Official episode title has not been checked yet")
    original_language = titles["series"][series_id].get("original_language")
    episode_title = episode_metadata.get("original_title")
    if not episode_title and original_language == "en":
        episode_title = episode_metadata.get("english_title")
    if (
        not episode_title
        and original_language != "en"
        and episode_metadata.get("status") != "official_original_episode_title_unavailable"
    ):
        raise KeyError("Original-language episode title has not been checked yet")
    if episode_title and normalized(episode_title) != normalized(title):
        title += " " + target_text(episode_title, language=original_language)
    selected = row["selected"]
    if not selected.get("width") or not selected.get("height"):
        raise ValueError("Verified original resolution is required")
    title += " " + resolution_label(selected["width"], selected["height"])
    title = title.replace("...", "…")
    if row["variant"] == "cz":
        return title + " CZ Dabing"
    if row["variant"] == "en_plain":
        return title
    proof = row.get("subtitles", {})
    title = title.replace("...", "…")
    return title + " CZ Titulky" if (proof.get("method") == "burned_in_ocr_verified" or subtitles_ready) else title


def episode_search_phrase(display: str) -> str:
    match = re.match(r"^(.*?\bS\d+E\d+)\b", display)
    if not match:
        raise ValueError("Target title has no episode code")
    return match[1]
