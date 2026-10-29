"""Resolve official series and episode names through identity-checked TMDB records."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import os
import time
import requests

from .naming import normalized
from .storage import atomic_json, read_json, rows


class MetadataUnavailable(RuntimeError):
    pass


class Metadata:
    def __init__(self, root, *, session=None, api_key=None):
        self.root = root
        self.path = root / "state/titles.json"
        self.data = read_json(self.path, {"series": {}, "episodes": {}})
        self.overrides = read_json(root / "config/titles.json", {"series": {}, "episodes": {}})
        self.session = session or requests.Session()
        self.api_key = api_key if api_key is not None else os.environ.get("TMDB_API_KEY")
        self.seasons = {}

    def snapshot(self):
        return {kind: {**self.data.get(kind, {}), **self.overrides.get(kind, {})} for kind in ("series", "episodes")}

    def get(self, endpoint, **params):
        if not self.api_key:
            raise MetadataUnavailable("TMDB_API_KEY is required for official title resolution")
        try:
            response = self.session.get(
                "https://api.themoviedb.org/3/" + endpoint, params={"api_key": self.api_key, **params}, timeout=25
            )
            response.raise_for_status()
            return response.json()
        except (requests.RequestException, ValueError):
            # Request exceptions can contain the API key. Never persist their text.
            raise MetadataUnavailable("Metadata request failed") from None

    def resolve_series(self, row):
        original = row.get("series_original_title")
        if not original:
            raise MetadataUnavailable("Original database title is missing")
        matches = {}
        first = self.get("search/tv", query=original, language="en-US", page=1)
        pages = int(first.get("total_pages", 1))
        if pages > 5:
            raise MetadataUnavailable("Series identity search is ambiguous")
        for page in range(1, max(1, pages) + 1):
            data = first if page == 1 else self.get("search/tv", query=original, language="en-US", page=page)
            for candidate in data.get("results", []):
                if normalized(candidate.get("original_name", "")) == normalized(original):
                    matches[candidate["id"]] = candidate
        if len(matches) != 1:
            raise MetadataUnavailable("Series identity is missing or ambiguous")
        tmdb_id = next(iter(matches))
        detail = self.get(f"tv/{tmdb_id}", language="en-US")
        if detail.get("id") != tmdb_id or normalized(detail.get("original_name", "")) != normalized(original):
            raise MetadataUnavailable("Series identity changed")
        english = detail.get("name") if detail.get("original_language") == "en" else None
        if not english:
            translations = self.get(f"tv/{tmdb_id}/translations").get("translations", [])
            names = {t.get("data", {}).get("name", "").strip() for t in translations if t.get("iso_639_1") == "en"}
            names.discard("")
            if len(names) == 1:
                english = names.pop()
        if not english:
            raise MetadataUnavailable("Official English title is missing or ambiguous")
        return dict(
            english_title=english.strip(),
            original_title=detail["original_name"].strip(),
            original_language=detail.get("original_language"),
            tmdb_id=tmdb_id,
            year=(detail.get("first_air_date") or "")[:4] or None,
            source=f"https://www.themoviedb.org/tv/{tmdb_id}",
        )

    def resolve_episode(self, row, series):
        tmdb_id, season, number = series.get("tmdb_id"), row["season"], row["episode"]
        if not tmdb_id:
            return None
        key = (tmdb_id, season)
        if key not in self.seasons:
            self.seasons[key] = self.get(f"tv/{tmdb_id}/season/{season}", language="en-US")
        data = self.seasons[key]
        if data.get("season_number") != season:
            raise MetadataUnavailable("Season numbering mismatch")
        matching = [
            e
            for e in data.get("episodes", [])
            if e.get("episode_number") == number
            and e.get("season_number") == season
            and e.get("show_id", tmdb_id) == tmdb_id
        ]
        if len(matching) != 1:
            return None
        title = matching[0].get("name") if series.get("original_language") == "en" else None
        if series.get("original_language") != "en":
            translations = self.get(f"tv/{tmdb_id}/season/{season}/episode/{number}/translations").get(
                "translations", []
            )
            names = {t.get("data", {}).get("name", "").strip() for t in translations if t.get("iso_639_1") == "en"}
            names.discard("")
            if len(names) == 1:
                title = names.pop()
        # Generic placeholders are not official episode names.
        if not title or normalized(title) in {f"episode {number}", f"epizoda {number}"}:
            return None
        return dict(
            english_title=title.strip(),
            tmdb_id=matching[0]["id"],
            source=f"https://www.themoviedb.org/tv/{tmdb_id}/season/{season}/episode/{number}",
        )

    def resolve(self, *, limit=100, runtime_minutes=20):
        if not self.api_key:
            raise MetadataUnavailable("TMDB_API_KEY is required for official title resolution")
        catalog = rows(self.root / "backlog/series-episodes.jsonl.gz")
        deadline = time.monotonic() + runtime_minutes * 60
        checked, resolved = 0, 0
        snapshot = self.snapshot()
        for row in catalog:
            if checked >= limit or time.monotonic() >= deadline:
                break
            key = str(row["series_id"])
            series = snapshot["series"].get(key, {})
            identity = f"{key}:{row['season']}:{row['episode']}"
            now = datetime.now(UTC)
            episode = snapshot["episodes"].get(identity, {})
            if not series.get("english_title"):
                if series.get("retry_after", "") > now.isoformat():
                    continue
                checked += 1
                try:
                    series = self.resolve_series(row)
                    self.data["series"][key] = snapshot["series"][key] = series
                    resolved += 1
                except MetadataUnavailable:
                    self.data["series"][key] = snapshot["series"][key] = dict(
                        status="unresolved", retry_after=(now + timedelta(hours=6)).isoformat()
                    )
                    self.save()
                    continue
            if not episode or episode.get("retry_after", "") <= now.isoformat() and not episode.get("english_title"):
                checked += 1
                try:
                    found = self.resolve_episode(row, series)
                    self.data["episodes"][identity] = found or dict(
                        status="official_english_episode_title_unavailable",
                        retry_after=(now + timedelta(days=7)).isoformat(),
                    )
                except MetadataUnavailable:
                    self.data["episodes"][identity] = dict(
                        status="deferred", retry_after=(now + timedelta(hours=6)).isoformat()
                    )
                snapshot["episodes"][identity] = self.data["episodes"][identity]
            self.save()
        return dict(
            checked=checked,
            resolved_series=resolved,
            named_series=sum(bool(v.get("english_title")) for v in self.snapshot()["series"].values()),
        )

    def save(self):
        atomic_json(self.path, self.data)
