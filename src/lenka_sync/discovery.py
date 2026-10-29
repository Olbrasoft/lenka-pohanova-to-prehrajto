"""Inspect English originals, selecting the highest resolution then smallest file."""

from __future__ import annotations

from dataclasses import replace
import hashlib
import json
import re
import time

from sdilej_serialy.episodes import episode_match, runtime_acceptable
from sdilej_serialy.models import Episode
from sdilej_serialy.quality import resolution_rank
from sdilej_serialy.source_detail import parse_detail_html, resolve_original
from sdilej_serialy.subtitle_media import extract_original, run_media, SubtitleUnavailable, normalize_srt
from sdilej_to_prehrajto.models import LanguageTier, MatchTier
from sdilej_to_prehrajto.sdilej import SdilejError

from .policy import POLICY
from .subtitle_visual import inspect_burned_in


class EnglishDiscovery:
    def __init__(self, provider, detector, *, probe=None, visual=None):
        self.provider = provider
        self.detector = detector
        self.probe = probe or self.probe_original
        self.visual = visual or inspect_burned_in

    @staticmethod
    def probe_original(url):
        return json.loads(
            run_media(
                [
                    "ffprobe",
                    "-v",
                    "error",
                    "-rw_timeout",
                    "20000000",
                    "-show_streams",
                    "-show_format",
                    "-of",
                    "json",
                    url,
                ],
                90,
            )
        )

    def verify(self, episode, candidate, deadline):
        detail = parse_detail_html(self.provider._get(candidate.url).text, candidate)
        detail = resolve_original(self.provider.session, detail)
        media = self.probe(detail.download_url)
        audio = [s for s in media.get("streams", []) if s.get("codec_type") == "audio"]
        video = next((s for s in media.get("streams", []) if s.get("codec_type") == "video"), None)
        if not audio or not video:
            return None
        for stream in [audio[0], *(s for s in audio if s.get("disposition", {}).get("default"))]:
            language = stream.get("tags", {}).get("language", "und").lower()
            if language not in {"en", "eng", "english", "und", ""}:
                return None
        duration = int(float(media.get("format", {}).get("duration") or 0))
        if not runtime_acceptable(episode, duration):
            return None
        tier, evidence = episode_match(episode, detail.title)
        if tier not in {MatchTier.SOLID, MatchTier.STRONG}:
            return None
        # A dedicated detector extracts only the original file's first audio track.
        language, confidence = self.detector.detect_consensus(detail.download_url, duration, preferred_language="en")
        if confidence < 0.65:
            raise SdilejError("English speech is inconclusive")
        if language != "en":
            return None
        detail = replace(
            detail,
            duration_sec=duration,
            width=int(video["width"]),
            height=int(video["height"]),
            video_codec=video.get("codec_name"),
            match_tier=tier,
            match_evidence=evidence,
            audio_language="en",
            language_probability=confidence,
            language_tier=LanguageTier.FOREIGN_AUDIO,
            language_evidence="whisper_original_first_audio",
        )
        proof = {"method": "none"}
        try:
            payload, _ = extract_original(
                self.provider.session,
                dict(source_id=detail.source_id, source_url=detail.url, source_filename=detail.filename),
                deadline=deadline,
            )
            payload = normalize_srt(payload)
            proof = dict(method="original_text", sha256=hashlib.sha256(payload).hexdigest(), language="cs")
        except SubtitleUnavailable as error:
            if str(error) not in {"source_czech_text_missing", "source_czech_full_text_unsupported"}:
                raise
            visual = self.visual(detail.download_url, duration, deadline=deadline)
            if visual.get("visual_status") == "uncertain":
                raise SdilejError("Burned-in subtitle evidence is inconclusive")
            if visual.get("visual_status") == "czech_burned_in_verified":
                proof = dict(method="burned_in_ocr_verified", language="cs", **visual)
            elif re.search(r"\b(?:cz|české|ceske)[ ._-]*(?:tit|titulky|subs?)\b", detail.title, re.I):
                raise SdilejError("Claimed Czech subtitles require review")
        detail.match_evidence["lenka"] = dict(policy=POLICY, first_audio_verified=True, subtitles_checked=True)
        return detail, proof

    def discover(self, source, series, *, runtime_seconds=300):
        # Search exactly the semantic episode whose Czech source was imported.
        episode = replace(
            Episode.from_dict(source["episode"]),
            series_title=series.get("english_title") or series["original_title"],
            series_original_title=series.get("original_title"),
        )
        deadline = time.monotonic() + runtime_seconds
        self.provider.discovery_timeout_seconds = runtime_seconds
        candidates = self.provider.search(episode)
        resolved, incomplete = [], False
        for candidate in candidates:
            if time.monotonic() >= deadline:
                incomplete = True
                break
            try:
                found = self.verify(episode, candidate, deadline)
                if found:
                    resolved.append(found)
            except Exception:
                # An unresolved original may have a higher resolution or smaller size.
                incomplete = True
        if incomplete:
            raise SdilejError("English verification incomplete; best resolution and size are unconfirmed")
        selected = min(
            resolved,
            key=lambda value: (
                -resolution_rank(value[0].width, value[0].height),
                value[0].size_bytes,
                value[1]["method"] == "none",
                value[0].source_id,
            ),
            default=None,
        )
        return selected
