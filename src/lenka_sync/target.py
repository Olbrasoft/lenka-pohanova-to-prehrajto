"""Resolve owned targets without confusing Czech and English episode variants."""

from __future__ import annotations

import re
import unicodedata
from bs4 import BeautifulSoup
from sdilej_serialy.target import episode_key, listing_rows
from sdilej_to_prehrajto import prehrajto

MEDIA_EXTENSION = re.compile(r"\.(?:mkv|mp4|avi|m4v|webm|mov|ts|m2ts|mpeg|mpg|wmv)$", re.I)


def clean_name(value):
    value = re.sub(r"\s*\(zpracovává se\)\s*$", "", value, flags=re.I)
    value = MEDIA_EXTENSION.sub("", value.strip())
    return " ".join(re.sub(r"\*+", " ", unicodedata.normalize("NFKC", value)).casefold().split())


def name_variant(value):
    name = clean_name(value)
    if re.search(r"\bcz\s+dabing$", name):
        return "cz"
    if re.search(r"\b(?:sk|de|fr)\s+dabing$", name):
        return "other"
    return "en"


def owned_name(session, video_id):
    if not str(video_id).isdigit():
        raise ValueError("Invalid target ID")
    response = session.get(
        prehrajto.BASE_URL + "/profil/uprava-slozky-videa", params={"videoId": str(video_id)}, timeout=30
    )
    if response.status_code == 404:
        return None
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    if not any("Změna složky videa" in heading.get_text(" ", strip=True) for heading in soup.select("h1")):
        raise RuntimeError("Owned target page is unavailable")
    headings = [h.get_text(" ", strip=True) for h in soup.select("h2") if episode_key(h.get_text(" ", strip=True))]
    if len(headings) != 1:
        raise RuntimeError("Owned target heading is ambiguous")
    return headings[0]


def existing_episode(session, name, known_id=None):
    """A saved ID must match exactly; fresh lookups retain the language variant."""
    if known_id is not None:
        visible = owned_name(session, known_id)
        return str(known_id) if visible is not None and clean_name(visible) == clean_name(name) else None
    match = re.match(r"^(.*?\s+S\d+E\d+)\b", name, re.I)
    if not match:
        raise ValueError("Missing episode code")
    response = session.get(
        prehrajto.BASE_URL + "/profil/nahrana-videa", params={"searchPhrase": re.sub(r"\*+", " ", match[1])}, timeout=30
    )
    response.raise_for_status()
    if "uploadedVideoListing" not in response.text:
        raise RuntimeError("Target listing unavailable; refusing new upload")
    matches = [
        row
        for row in listing_rows(response.text)
        if row["key"] == episode_key(name) and name_variant(row["name"]) == name_variant(name)
    ]
    if len(matches) > 1:
        raise RuntimeError("Multiple targets exist for the same episode variant")
    return matches[0]["id"] if matches else None
