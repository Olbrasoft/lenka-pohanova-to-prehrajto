"""One shared transfer pool, independent Czech, subtitled and plain histories."""

from __future__ import annotations

from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import UTC, datetime, timedelta
import os
import json
import threading
import time

from sdilej_serialy.episodes import EpisodeSourceProvider
from sdilej_serialy.git_state import GitCheckpointPersister
from sdilej_serialy.pipeline import target_session
from sdilej_serialy.resilience import receipt_matches, transient_http
from sdilej_serialy.models import Episode
from sdilej_serialy.source_transfer import SourceUnavailable

from .discovery import EnglishDiscovery
from .language import WhisperLanguageDetector
from .metadata import Metadata
from .naming import display_name, series_names
from .policy import POLICY, VARIANTS, ENGLISH_VARIANTS, ENGLISH_SELECTION_POLICY, target_credentials, upload_eligible
from .state import VariantState, validate_target_ownership
from .storage import Publisher, atomic_json, read_json, rows, write_rows
from .subtitles import followup
from .transfer import upload_continuously


def credentials(environ=os.environ):
    email, password = target_credentials(environ)
    source_email, source_password = environ.get("SDILEJ_EMAIL"), environ.get("SDILEJ_PASSWORD")
    if not source_email or not source_password:
        raise ValueError("SDILEJ_EMAIL and SDILEJ_PASSWORD are required")
    return dict(
        source_email=source_email, source_password=source_password, target_email=email, target_password=password
    )


def sources(root):
    queue = {variant: rows(root / f"variants/{variant}/manifests/selected-episodes.jsonl") for variant in VARIANTS}
    return validate_sources(queue)


def validate_sources(queue):
    czech = {row["identity"] for row in queue["cz"]}
    for variant, selected in queue.items():
        if len({row["identity"] for row in selected}) != len(selected) or any(
            row.get("variant") != variant for row in selected
        ):
            raise ValueError("Source queue has duplicate identities or a wrong variant")
    if any(row["identity"] not in czech for variant in ENGLISH_VARIANTS for row in queue.get(variant, [])):
        raise ValueError("English queue contains an episode without an imported Czech source")
    return queue


def planned(queue, titles, states, limit=10, excluded=frozenset(), variants=None):
    ready = []
    names = series_names(titles["series"])
    for variant in states if variants is None else variants:
        state = states[variant]
        deferred = state.retry_deferred_identities()
        for source in queue.get(variant, []):
            identity = source["identity"]
            record = state.data["episodes"].get(identity, {})
            active_claim = record.get("claim", {}).get("lease_expires_at", "") > datetime.now(UTC).isoformat()
            if (
                (variant, identity) in excluded
                or identity in deferred
                or record.get("upload")
                or active_claim
                or record.get("review_target_id")
                or record.get("prepared_target")
                and not receipt_matches(record)
                or not upload_eligible(source)
            ):
                continue
            try:
                saved_name = record.get("source", {}).get("display_name") if record.get("prepared_target") else None
                row = {**source, "display_name": saved_name or display_name(source, titles, names=names)}
            except KeyError:
                continue
            # Resume an allocated target with the same name, even after metadata grows.
            if record.get("prepared_target") and record.get("source", {}).get("display_name"):
                row["display_name"] = record["source"]["display_name"]
            ready.append(row)
    ready.sort(key=lambda row: (row["catalog"].get("priority_rank") or 10**9, row["identity"], VARIANTS.index(row["variant"])))
    return ready[:limit]


def prepare(root, *, limit=50, runtime_minutes=40, persist=False, discovery=None):
    paths = {variant: root / f"variants/{variant}/manifests/selected-episodes.jsonl" for variant in ENGLISH_VARIANTS}
    progress_path = root / "variants/en/state/discovery.json"
    selected = {variant: {row["identity"]: row for row in rows(path)} for variant, path in paths.items()}
    progress = read_json(progress_path)
    titles = Metadata(root).snapshot()
    publisher = GitCheckpointPersister(root, (*paths.values(), progress_path), min_interval_seconds=5) if persist else None
    if discovery is None:
        provider = EpisodeSourceProvider.authenticated(os.environ["SDILEJ_EMAIL"], os.environ["SDILEJ_PASSWORD"])
        discovery = EnglishDiscovery(provider, WhisperLanguageDetector())
    deadline, checked = time.monotonic() + runtime_minutes * 60, 0
    czech = sources(root)["cz"]
    # Four fresh episodes, then one older retry, preserving catalog order in both lanes.
    fresh = [r for r in czech if progress.get(r["identity"], {}).get("selection_policy") != ENGLISH_SELECTION_POLICY]
    retries = sorted(
        (r for r in czech if progress.get(r["identity"], {}).get("selection_policy") == ENGLISH_SELECTION_POLICY),
        key=lambda r: progress[r["identity"]].get("checked_at", ""),
    )
    ordered = []
    while fresh or retries:
        ordered.extend(fresh[:4])
        del fresh[:4]
        if retries:
            ordered.append(retries.pop(0))
    for source in ordered:
        if checked >= limit or time.monotonic() >= deadline:
            break
        identity = source["identity"]
        series = titles["series"].get(str(source["episode"]["series_id"]), {})
        now = datetime.now(UTC)
        if (
            all(identity in selected[variant] for variant in ENGLISH_VARIANTS)
            or not series.get("original_title")
            or progress.get(identity, {}).get("selection_policy") == ENGLISH_SELECTION_POLICY
            and progress.get(identity, {}).get("retry_after", "") > now.isoformat()
        ):
            continue
        checked += 1
        status, delay = "not_found", timedelta(days=7)
        try:
            found = discovery.discover(source, series, runtime_seconds=min(600, max(1, deadline - time.monotonic())))
            discovered = {}
            for variant, (candidate, proof) in found.items():
                if variant not in ENGLISH_VARIANTS:
                    raise ValueError("Unknown discovered English variant")
                row = {key: source[key] for key in ("identity", "episode", "catalog")}
                row.update(selected=candidate.to_dict(), variant=variant, lenka_policy=POLICY, subtitles=proof)
                if not upload_eligible(row):
                    raise ValueError("English source did not pass the variant policy")
                discovered[variant] = row
            if len({row["selected"]["source_id"] for row in discovered.values()}) != len(discovered):
                raise ValueError("One original cannot represent both subtitle variants")
            for variant, row in discovered.items():
                # Existing rows may already be claimed by the live uploader. Never replace their source.
                selected[variant].setdefault(identity, row)
            if found:
                status = "verified"
        except Exception as error:
            status, delay = type(error).__name__, timedelta(hours=1)
        progress[identity] = dict(
            status=status,
            selection_policy=ENGLISH_SELECTION_POLICY,
            available_variants=[variant for variant in ENGLISH_VARIANTS if identity in selected[variant]],
            checked_at=now.isoformat(),
            retry_after=(now + delay).isoformat(),
        )
        for variant, path in paths.items():
            write_rows(path, list(selected[variant].values()))
        atomic_json(progress_path, progress)
        if publisher:
            publisher(progress_path)
    return dict(checked=checked, selected={variant: len(values) for variant, values in selected.items()})


def upload(root, *, workers=3, limit=3, runtime_minutes=240, continuous=False, persist=False, variant="all"):
    creds = credentials()
    lock = threading.RLock()
    paths = tuple(root / f"variants/{variant}/state/uploads.json" for variant in VARIANTS)
    publisher = Publisher(root, paths + (root / "variants/en/state/subtitles.json",)) if persist else None
    states = {
        variant: VariantState(path, variant, on_save=publisher, lock=lock) for variant, path in zip(VARIANTS, paths)
    }
    validate_target_ownership(states)
    for state in states.values():
        state.peers = states
        state.release_orphaned_claims()
    stop, paused = threading.Event(), threading.Event()
    deadline = time.monotonic() + runtime_minutes * 60
    subtitle_deadline = min(deadline + 90 * 60, time.monotonic() + 330 * 60)
    pending, reserved, submitted, completed = {}, set(), 0, 0
    draining = False
    maintenance = None
    next_subtitles = 0
    subtitle_dirty = False
    queue, titles = sources(root), Metadata(root).snapshot()

    def execute(row):
        try:
            return upload_continuously(
                [row],
                states[row["variant"]],
                workers=1,
                **creds,
                target_login=lambda: target_session(
                    creds["target_email"], creds["target_password"], expected_email=creds["target_email"]
                ),
                require_original_size=True,
                select_source=lambda selected: selected,
                recover_source_errors=True,
                recover_target_errors=True,
                stop_event=stop,
                transient_pause=paused,
                claim_deadline=deadline,
            )
        except SourceUnavailable as error:
            states[row["variant"]].failure(Episode.from_dict(row["episode"]), error)
            return {"source_unavailable": True}
        except Exception as error:
            if transient_http(error):
                paused.set()
                states[row["variant"]].failure(Episode.from_dict(row["episode"]), error)
                return {"target_deferred": True}
            stop.set()
            raise

    with ThreadPoolExecutor(max_workers=workers) as transfers, ThreadPoolExecutor(max_workers=1) as subtitles:
        while True:
            for future in list(pending):
                if future.done():
                    row = pending.pop(future)
                    reserved.remove((row["variant"], row["identity"]))
                    future.result()
                    if row["variant"] == "en":
                        subtitle_dirty = True
                    completed += 1
            if maintenance is not None and maintenance.done():
                try:
                    maintenance.result()
                except Exception as error:
                    from sdilej_serialy.git_state import CheckpointError

                    if isinstance(error, (CheckpointError, ValueError)):
                        raise
                    print(f"subtitle_followup_deferred={type(error).__name__}", flush=True)
                maintenance = None
            now = time.monotonic()
            if now < deadline and not draining and not stop.is_set() and not paused.is_set():
                if publisher:
                    manifest_paths = {
                        variant: f"variants/{variant}/manifests/selected-episodes.jsonl" for variant in VARIANTS
                    }
                    snapshot = publisher.read_snapshot(
                        [*manifest_paths.values(), "state/titles.json", "config/titles.json", "config/runtime.json"]
                    )
                    for variant in VARIANTS:
                        remote = snapshot[manifest_paths[variant]]
                        queue[variant] = [json.loads(line) for line in remote.splitlines() if line.strip()]
                    validate_sources(queue)
                    titles = json.loads(snapshot["state/titles.json"] or '{"series":{},"episodes":{}}')
                    overrides = json.loads(snapshot["config/titles.json"] or '{"series":{},"episodes":{}}')
                    titles = {
                        kind: {**titles.get(kind, {}), **overrides.get(kind, {})} for kind in ("series", "episodes")
                    }
                    runtime = json.loads(snapshot["config/runtime.json"] or "{}")
                else:
                    queue, titles = sources(root), Metadata(root).snapshot()
                    runtime = read_json(root / "config/runtime.json")
                draining = runtime.get("admit_uploads", True) is False
                capacity = workers - len(pending)
                if draining:
                    capacity = 0
                if not continuous:
                    capacity = min(capacity, limit - submitted)
                with lock:
                    selected = planned(
                        queue,
                        titles,
                        states,
                        max(0, capacity),
                        reserved,
                        variants=VARIANTS if variant == "all" else (variant,),
                    )
                for row in selected:
                    reserved.add((row["variant"], row["identity"]))
                    pending[transfers.submit(execute, row)] = row
                    submitted += 1
            # Separate sessions and a separate thread keep subtitles moving while uploads run.
            if (
                maintenance is None
                and (now >= next_subtitles or subtitle_dirty)
                and now < subtitle_deadline
                and (now < deadline or pending)
            ):
                maintenance = subtitles.submit(
                    followup,
                    root,
                    queue["en"],
                    states["en"],
                    titles,
                    creds,
                    persist=publisher,
                    runtime_minutes=min(10, max(1, int((subtitle_deadline - now) / 60))),
                )
                next_subtitles = now + 600
                subtitle_dirty = False
            active = [*pending, *([maintenance] if maintenance else [])]
            if active:
                wait(active, timeout=15, return_when=FIRST_COMPLETED)
            elif stop.is_set() or draining or now >= deadline or not continuous and submitted >= limit:
                break
            elif continuous:
                if paused.is_set():
                    time.sleep(60)
                    paused.clear()
                else:
                    time.sleep(min(30, max(0, deadline - now)))
            else:
                break
    if stop.is_set():
        raise RuntimeError("Transfers stopped after an integrity error; inspect the durable state")
    return dict(
        submitted=submitted,
        finished_attempts=completed,
        confirmed_uploads=sum(bool(r.get("upload")) for s in states.values() for r in s.data["episodes"].values()),
    )
