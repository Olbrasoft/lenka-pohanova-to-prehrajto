"""Import Czech originals, without another account's upload history."""

from __future__ import annotations

import copy
from pathlib import Path
from sdilej_serialy.quality import QUALITY_POLICY, resolution_rank

from .policy import POLICY, verified_media
from .storage import atomic_json, read_json, rows, write_rows


def import_sources(root: Path, upstream: Path) -> dict:
    catalog = rows(upstream / "backlog/series-episodes.jsonl.gz")
    previous_catalog = rows(root / "backlog/series-episodes.jsonl.gz")
    catalog_by_id = {f"{r['series_id']}:{r['season']}:{r['episode']}": r for r in previous_catalog + catalog}
    proven, available = {}, {}
    candidates = rows(upstream / "manifests/selected-episodes.jsonl") + rows(
        upstream / "manifests/quality-upgrades.jsonl"
    )
    for directory in sorted((upstream / "dual").glob("*")):
        queue = {r["identity"]: r for r in rows(directory / "manifest.jsonl") + rows(directory / "additions.jsonl")}
        candidates.extend(queue.values())
        state = read_json(directory / "state.json").get("episodes", {})
        for identity, record in state.items():
            if not record.get("upload") or identity not in queue:
                continue
            source = record.get("source", {})
            base = copy.deepcopy(queue[identity])
            if source.get("source_id") and source.get("source_url"):
                # Completed transfers take precedence only when bound to their actual source.
                binding = {
                    "source_id": "source_id",
                    "url": "source_url",
                    "title": "source_title",
                    "filename": "source_filename",
                    "size_bytes": "size_bytes",
                    "duration_sec": "duration_sec",
                    "width": "width",
                    "height": "height",
                    "audio_language": "audio_language",
                    "language_probability": "language_probability",
                    "language_tier": "language_tier",
                    "match_evidence": "match_evidence",
                }
                selected = {key: source[value] for key, value in binding.items() if value in source}
                # State records omit match_tier; their candidate was already checked against this episode.
                selected["match_tier"] = base["selected"].get("match_tier")
                base["selected"] = selected
            if base.get("quality_policy") == QUALITY_POLICY and verified_media(base, "cs"):
                proven[identity] = base
    for row in candidates + list(proven.values()):
        if row.get("quality_policy") != QUALITY_POLICY or not verified_media(row, "cs"):
            continue
        key = row["identity"]
        selected = row["selected"]
        score = (-resolution_rank(selected["width"], selected["height"]), selected["size_bytes"])
        old = available.get(key)
        if old is None or score < old[0]:
            available[key] = (score, row)
    chosen = {key: value[1] for key, value in available.items()}
    path = root / "variants/cz/manifests/selected-episodes.jsonl"
    existing = {row["identity"]: row for row in rows(path)}
    used_sources = {row["selected"]["source_id"] for row in existing.values()}
    uploaded_state = read_json(root / "variants/cz/state/uploads.json").get("episodes", {})
    locked = {
        identity
        for identity, record in uploaded_state.items()
        if any(record.get(key) for key in ("upload", "prepared_target", "claim"))
    }
    imported, upgraded = 0, 0
    ranked = sorted(
        chosen.items(), key=lambda item: (catalog_by_id.get(item[0], {}).get("priority_rank") or 10**9, item[0])
    )
    for identity, row in ranked:
        previous = existing.get(identity)
        if identity in locked or identity not in catalog_by_id:
            continue
        if previous:
            old = previous["selected"]
            new = row["selected"]
            if (-resolution_rank(new["width"], new["height"]), new["size_bytes"]) >= (
                -resolution_rank(old["width"], old["height"]),
                old["size_bytes"],
            ):
                continue
        if row["selected"]["source_id"] in used_sources:
            continue
        # Explicit whitelist excludes target IDs, allocation intents, owners and credentials.
        clean = dict(
            identity=identity,
            episode=copy.deepcopy(row["episode"]),
            selected=copy.deepcopy(row["selected"]),
            variant="cz",
            lenka_policy=POLICY,
            provenance=(
                "upstream_completed_upload"
                if identity in proven and proven[identity]["selected"]["source_id"] == row["selected"]["source_id"]
                else "upstream_verified_manifest"
            ),
        )
        for key in ("download_url", "sample_url"):
            clean["selected"].pop(key, None)
        clean["catalog"] = {
            key: catalog_by_id[identity].get(key)
            for key in ("priority_rank", "priority_score", "imdb_rating", "imdb_votes")
        }
        if previous:
            used_sources.remove(previous["selected"]["source_id"])
            upgraded += 1
        else:
            imported += 1
        existing[identity] = clean
        used_sources.add(clean["selected"]["source_id"])
    ordered = sorted(existing.values(), key=lambda r: (r["catalog"].get("priority_rank") or 10**9, r["identity"]))
    write_rows(path, ordered)
    identities = {row["identity"] for row in ordered}
    write_rows(
        root / "backlog/series-episodes.jsonl.gz", [row for key, row in catalog_by_id.items() if key in identities]
    )
    report = dict(
        imported=imported,
        queued_upgrades=upgraded,
        czech_sources=len(ordered),
        series=len({r["episode"]["series_id"] for r in ordered}),
    )
    atomic_json(root / "reports/import.json", report)
    return report
