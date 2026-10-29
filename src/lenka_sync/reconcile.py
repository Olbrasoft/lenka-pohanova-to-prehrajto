"""Review legacy cross-variant records and rename owned videos without replaying media."""

from __future__ import annotations

from datetime import UTC, datetime
from .naming import display_name
from .storage import read_json, atomic_json
from .target import owned_name, clean_name, name_variant, rename_video


def repair_cross_variant_records(root, states, session, *, persist=None):
    subtitle_path = root / "variants/en/state/subtitles.json"
    subtitle_data = read_json(subtitle_path, {})
    czech = {
        str(r["upload"]["target_video_id"]): (identity, r)
        for identity, r in states["cz"].data["episodes"].items()
        if r.get("upload")
    }
    reviewed = []
    # Validate the entire repair before changing any history.
    for identity, record in states["en"].data["episodes"].items():
        upload = record.get("upload")
        if not upload or str(upload["target_video_id"]) not in czech:
            continue
        video_id = str(upload["target_video_id"])
        if subtitle_data.get("videos", {}).get(video_id, {}).get("intent"):
            raise ValueError("Subtitle intent exists for a shared target; manual review required")
        czech_identity, other = czech[video_id]
        if (
            czech_identity != identity
            or record.get("source")
            or record.get("completion_evidence")
            or record.get("prepared_target")
            or record.get("transfer_receipt")
        ):
            raise ValueError("Cross-variant allocation has evidence requiring manual review")
        visible = owned_name(session, video_id)
        if (
            visible is None
            or name_variant(visible) != "cz"
            or clean_name(visible) != clean_name(other["upload"]["display_name"])
        ):
            raise ValueError("Shared target is not the confirmed Czech variant")
        reviewed.append((identity, video_id, dict(upload), visible))
    for identity, video_id, upload, visible in reviewed:
        record = states["en"].data["episodes"][identity]
        record.setdefault("reconciliation_reviews", []).append(
            dict(
                rejected_upload=upload,
                actual_czech_title=visible,
                reason="legacy_episode_lookup_reused_czech_target",
                reviewed_at=datetime.now(UTC).isoformat(),
            )
        )
        record.pop("upload")
        previous = subtitle_data.get("videos", {}).get(video_id)
        if previous and previous.get("identity") == identity:
            if previous.get("intent"):
                raise ValueError("Subtitle intent exists for a shared target; manual review required")
            subtitle_data.setdefault("legacy_reviews", {})[video_id] = subtitle_data["videos"].pop(video_id)
    if reviewed:
        states["en"].save()
        atomic_json(subtitle_path, subtitle_data)
        if persist:
            persist(subtitle_path)
    return {"false_english_completions_reviewed": len(reviewed), "physical_videos_changed": 0}


def rename_tracked(root, queue, states, titles, session, *, persist=None):
    subtitles = read_json(root / "variants/en/state/subtitles.json", {}).get("videos", {})
    result = {"renamed": 0, "already_correct": 0, "deferred": []}
    for variant in ("cz", "en"):
        by_identity = {r["identity"]: r for r in queue[variant]}
        for identity, record in states[variant].data["episodes"].items():
            upload, source = record.get("upload"), record.get("source", {})
            if not upload:
                continue
            if not source.get("source_id") or identity not in by_identity:
                result["deferred"].append(
                    {"identity": identity, "variant": variant, "reason": "source_binding_missing"}
                )
                continue
            row = {
                **by_identity[identity],
                "selected": {**by_identity[identity]["selected"], "width": source["width"], "height": source["height"]},
            }
            video_id = str(upload["target_video_id"])
            attached = subtitles.get(video_id, {}).get("status") == "attached_verified"
            try:
                wanted = display_name(row, titles, subtitles_ready=attached)
            except KeyError:
                result["deferred"].append(
                    {"identity": identity, "variant": variant, "reason": "original_metadata_pending"}
                )
                continue
            current = owned_name(session, video_id)
            if current is None or name_variant(current) != variant:
                raise ValueError("Owned video does not match its recorded variant")
            if clean_name(current) != clean_name(wanted):
                if clean_name(current) != clean_name(upload["display_name"]):
                    raise ValueError("Target title changed outside the tracked state")
                rename_video(session, video_id, wanted)
                if clean_name(owned_name(session, video_id) or "") != clean_name(wanted):
                    raise RuntimeError("Target rename was not confirmed")
                result["renamed"] += 1
            else:
                result["already_correct"] += 1
            upload["display_name"] = wanted
            source["display_name"] = wanted
            states[variant].save()
    return result
