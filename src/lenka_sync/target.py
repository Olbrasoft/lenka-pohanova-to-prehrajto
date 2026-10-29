"""Resolve owned targets without confusing Czech and English episode variants."""

from __future__ import annotations

import re
import unicodedata
from bs4 import BeautifulSoup
from sdilej_serialy.target import episode_key, listing_rows
from sdilej_to_prehrajto import prehrajto
import requests
from requests.adapters import HTTPAdapter

MEDIA_EXTENSION = re.compile(r"\.(?:mkv|mp4|avi|m4v|webm|mov|ts|m2ts|mpeg|mpg|wmv)$", re.I)


def clean_name(value):
    value = re.sub(r"\s*\(zpracovává se\)\s*$", "", value, flags=re.I)
    value = MEDIA_EXTENSION.sub("", value.strip())
    value = unicodedata.normalize("NFKC", value).casefold()
    # Uploaded filenames lose punctuation; keep words, resolution and language markers.
    return " ".join(re.sub(r"[^\w\s]", " ", value).split())


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
    headings = []
    for heading in soup.select("h2"):
        visible = heading.select_one(".show-for-large") or heading.select_one(".hide-for-large") or heading
        text = visible.get_text(" ", strip=True)
        if episode_key(text):
            headings.append(text)
    if len(headings) != 1:
        raise RuntimeError("Owned target heading is ambiguous")
    return headings[0]


def rename_video(session, video_id, name):
    """Use the observed Naja GET contract, without transport retries of mutations."""
    adapter = session.get_adapter(prehrajto.BASE_URL) if isinstance(session, requests.Session) else None
    if adapter is not None:
        session.mount(prehrajto.BASE_URL + "/", HTTPAdapter(max_retries=0))
    try:
        response = session.get(
            prehrajto.BASE_URL + "/profil/nahrana-videa",
            params={
                "uploadedVideoListing-videoId": str(video_id),
                "do": "uploadedVideoListing-changeVideoName",
                "uploadedVideoListing-name": name,
            },
            headers={"X-Requested-With": "XMLHttpRequest", "Accept": "application/json"},
            allow_redirects=False,
            timeout=30,
        )
        response.raise_for_status()
        if "application/json" in getattr(response, "headers", {}).get("Content-Type", ""):
            if response.json().get("nameError"):
                raise ValueError("Target rejected the requested title")
    finally:
        if adapter is not None:
            session.mount(prehrajto.BASE_URL + "/", adapter)


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
