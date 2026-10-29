"""Attach exact-source text tracks and label only verified Czech subtitles."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import time
from requests.adapters import HTTPAdapter

from sdilej_serialy.episode_subtitles import attach, read_target_view
from sdilej_serialy.episodes import EpisodeSourceProvider
from sdilej_serialy.pipeline import target_session
from sdilej_serialy.subtitle_target import SubtitleTarget, TargetUnavailable, parse_listing, trusted_detail
from sdilej_to_prehrajto import prehrajto

from .naming import display_name, episode_search_phrase
from . import policy
from .storage import atomic_json, read_json


def followup(root, queue, state, titles, credentials, *, persist=None, runtime_minutes=10, limit=20):
    policy.require_target(credentials["target_email"])
    path = root / "variants/en/state/subtitles.json"
    data = read_json(path, {"account_hash": policy.TARGET_ACCOUNT_HASH, "videos": {}})
    if data.get("account_hash") != policy.TARGET_ACCOUNT_HASH:
        raise ValueError("Subtitle history belongs to another account")
    pending = []
    now = datetime.now(UTC)
    with state._lock:
        for row in queue:
            record = state.data["episodes"].get(row["identity"], {})
            if row.get("subtitles", {}).get("method") != "original_text" or not record.get("upload"):
                continue
            entry = data["videos"].get(record["upload"]["target_video_id"], {})
            if entry.get("title_updated") or entry.get("retry_after", "") > now.isoformat():
                continue
            pending.append((row, record))
    if not pending:
        return {"checked": 0}
    deadline = time.monotonic() + runtime_minutes * 60

    def save():
        with state._lock:
            atomic_json(path, data)
            if persist:
                persist(path)

    provider = EpisodeSourceProvider.authenticated(credentials["source_email"], credentials["source_password"])
    checked = 0
    try:
        with target_session(
            credentials["target_email"], credentials["target_password"], expected_email=credentials["target_email"]
        ) as session:
            session.mount(prehrajto.BASE_URL + "/", HTTPAdapter(max_retries=0))
            api = SubtitleTarget(session)
            for row, record in pending[:limit]:
                if time.monotonic() >= deadline - 90:
                    break
                video_id = record["upload"]["target_video_id"]
                entry = data["videos"].setdefault(video_id, dict(identity=row["identity"], status="pending"))
                if entry["identity"] != row["identity"]:
                    raise ValueError("Subtitle target identity changed")

                def refresh():
                    response = session.get(
                        prehrajto.BASE_URL + "/profil/nahrana-videa",
                        params={"searchPhrase": episode_search_phrase(record["upload"]["display_name"])},
                        timeout=45,
                    )
                    response.raise_for_status()
                    listed, _ = parse_listing(response.text)
                    owned = next((view for view in listed if view.video_id == video_id), None)
                    if owned and trusted_detail(owned.detail_url):
                        entry["detail_url"] = owned.detail_url
                    return read_target_view(api, video_id, owned, entry.get("detail_url", ""))

                def rename(title):
                    prehrajto.rename_video(session, video_id, title)
                    from .transfer import target_confirmed

                    if not target_confirmed(session, video_id, title):
                        raise TargetUnavailable("subtitle_title_update_unconfirmed")
                    with state._lock:
                        record["upload"]["display_name"] = title
                        state.save()

                try:
                    # The upstream helper's marker removal is separate from our final title.
                    attach(
                        row, record, entry, refresh(), api, provider, refresh, save, lambda _: None, deadline=deadline
                    )
                    # Reconcile the same durable intent immediately; never repeat its POST.
                    for _ in range(3):
                        if (
                            not entry.get("intent")
                            or entry.get("status")
                            not in {"upload_unconfirmed", "verifying_language", "verifying_content"}
                            or time.monotonic() >= deadline - 30
                        ):
                            break
                        time.sleep(2)
                        attach(
                            row,
                            record,
                            entry,
                            refresh(),
                            api,
                            provider,
                            refresh,
                            save,
                            lambda _: None,
                            deadline=deadline,
                        )
                    if entry.get("status") == "attached_verified":
                        entry["title_updated"] = False
                        save()
                        rename(display_name(row, titles, subtitles_ready=True))
                        entry["title_updated"] = True
                except Exception as error:
                    from sdilej_serialy.git_state import CheckpointError

                    if isinstance(error, CheckpointError):
                        raise
                    entry.update(
                        status="upload_unconfirmed" if entry.get("intent") else "deferred",
                        error=type(error).__name__,
                        title_updated=False,
                    )
                delay = (
                    2 if entry.get("status") in {"target_processing", "verifying_language", "verifying_content"} else 10
                )
                entry["retry_after"] = (datetime.now(UTC) + timedelta(minutes=delay)).isoformat()
                save()
                checked += 1
    finally:
        provider.session.close()
    return {"checked": checked}
