"""Account, source and language guards shared by planning and execution."""

from __future__ import annotations

import re
import hashlib
from urllib.parse import urlsplit
from sdilej_serialy.models import Episode

TARGET_ACCOUNT_HASH = "19da1e635356d18e87b35f2950dec4e0fbefbea7bcaef2bd12f29c52ed4343e8"
POLICY = "lenka-series-variants-v1"


def stable_source(selected: dict) -> bool:
    try:
        url = urlsplit(selected.get("url", ""))
        return bool(
            re.fullmatch(r"\d+", str(selected.get("source_id", "")))
            and url.scheme == "https"
            and url.hostname == "sdilej.cz"
            and url.port in (None, 443)
            and not url.username
            and not url.password
            and not url.query
            and not url.fragment
            and url.path.split("/")[1:2] == [str(selected["source_id"])]
            and not any(selected.get(key) for key in ("download_url", "sample_url"))
        )
    except (ValueError, KeyError):
        return False


def verified_media(row: dict, language: str) -> bool:
    selected = row.get("selected", {})
    try:
        episode = Episode.from_dict(row["episode"])
        return bool(
            row.get("identity") == episode.identity
            and episode.season >= 0
            and episode.number > 0
            and stable_source(selected)
            and selected.get("audio_language") == language
            and selected.get("language_probability", 0) >= 0.65
            and selected.get("match_tier") in {"solid", "strong"}
            and all(
                isinstance(selected.get(key), (int, float)) and selected[key] > 0
                for key in ("width", "height", "duration_sec", "size_bytes")
            )
            and selected["size_bytes"] >= 1024 * 1024
        )
    except (KeyError, TypeError, ValueError):
        return False


def upload_eligible(row: dict) -> bool:
    if row.get("lenka_policy") != POLICY or row.get("variant") not in {"cz", "en"}:
        return False
    if not verified_media(row, "cs" if row["variant"] == "cz" else "en"):
        return False
    if row["variant"] == "cz":
        return row["selected"].get("language_tier") == "czech_audio"
    evidence = row["selected"].get("match_evidence", {}).get("lenka", {})
    return (
        evidence.get("policy") == POLICY
        and evidence.get("first_audio_verified") is True
        and evidence.get("subtitles_checked") is True
    )


def require_target(email):
    if hashlib.sha256(email.strip().casefold().encode()).hexdigest() != TARGET_ACCOUNT_HASH:
        raise ValueError("Target credentials must belong to the Lenka account")


def target_credentials(environ):
    email = environ.get("PREHRAJTO_EMAIL", "").strip().casefold()
    password = environ.get("PREHRAJTO_PASSWORD", "")
    require_target(email)
    if not password:
        raise ValueError("Target password is required")
    return email, password
