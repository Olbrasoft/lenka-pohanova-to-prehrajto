"""Verbatim database names; no translation or filename-derived titles."""

from __future__ import annotations

from collections import Counter
import re
import unicodedata


def normalized(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def combined_title(english: str, original: str | None) -> str:
    english = english.strip()
    original = (original or "").strip()
    if not english:
        raise ValueError("Verified English series title is required")
    return english if not original or normalized(english) == normalized(original) else f"{english} ({original})"


def series_names(metadata: dict) -> dict[str, str]:
    ready = {key: value for key, value in metadata.items() if value.get("english_title")}
    counts = Counter(normalized(value["english_title"]) for value in ready.values())
    dated = Counter((normalized(value["english_title"]), value.get("year")) for value in ready.values())
    result = {}
    for key, value in ready.items():
        title = combined_title(value["english_title"], value.get("original_title"))
        identity, year = normalized(value["english_title"]), value.get("year")
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
    episode_title = episode_metadata.get("english_title")
    if episode_title and normalized(episode_title) != normalized(title):
        title += " " + episode_title.strip()
    if row["variant"] == "cz":
        return title + " CZ Dabing"
    proof = row.get("subtitles", {})
    return title + " CZ Titulky" if (proof.get("method") == "burned_in_ocr_verified" or subtitles_ready) else title


def episode_search_phrase(display: str) -> str:
    match = re.match(r"^(.*?\bS\d+E\d+)\b", display)
    if not match:
        raise ValueError("Target title has no episode code")
    return match[1]
