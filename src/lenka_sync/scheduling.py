"""Admit original media that can finish within the available runner time."""

from datetime import UTC, datetime, timedelta
import math
import os
from statistics import median

from sdilej_serialy.resilience import receipt_matches


def execution_environment():
    return "github_actions" if os.environ.get("GITHUB_ACTIONS") == "true" else "local"


def upload_rate(states, runtime, *, now=None):
    """Learn from complete accepted uploads in the same execution environment."""
    now = now or datetime.now(UTC)
    recent = []
    for state in states.values():
        for record in state.data["episodes"].values():
            stats = record.get("transfer_statistics", {})
            evidence = record.get("completion_evidence") or {}
            receipt = evidence.get("receipt", {}) if isinstance(evidence, dict) else {}
            uploaded = record.get("upload", {})
            if not all(isinstance(value, dict) for value in (stats, receipt, uploaded)):
                continue
            if (
                not uploaded
                or stats.get("environment") != execution_environment()
                or stats.get("target_video_id") != uploaded.get("target_video_id")
                or receipt.get("target_video_id") != uploaded.get("target_video_id")
                or receipt.get("http_status") not in (200, 201)
                or not receipt.get("size_bytes")
                or stats.get("source_bytes_read") != receipt.get("size_bytes")
                or receipt.get("source_bytes_read") != receipt.get("size_bytes")
            ):
                continue
            try:
                finished = datetime.fromisoformat(stats["finished_at"])
                seconds = float(stats["elapsed_seconds"])
                rate = stats["source_bytes_read"] / seconds
                if seconds <= 0 or not math.isfinite(rate) or rate <= 0:
                    continue
                if not now - timedelta(hours=24) <= finished <= now + timedelta(minutes=1):
                    continue
            except (KeyError, TypeError, ValueError, ZeroDivisionError):
                continue
            recent.append((finished, rate))
    if recent:
        return median(rate for _, rate in sorted(recent)[-5:])
    rate = float(runtime.get("upload_rate_bytes_per_second", 1024 * 1024))
    if not math.isfinite(rate) or rate <= 0:
        raise ValueError("Upload rate must be a positive finite number")
    return rate


def transfer_bytes(row, states):
    record = states[row["variant"]].data["episodes"].get(row["identity"], {})
    # Receipt-bound reconciliation sends no media and must remain available.
    if receipt_matches(record):
        return 0
    return row["selected"]["size_bytes"]


def select_transfers(ready, states, pending, *, capacity, rate, seconds_left, runtime):
    """Keep catalog order within the long and short transfer lanes."""
    if capacity <= 0:
        return []
    maximum = max(0, int(rate * seconds_left * 0.8))
    short_limit = min(maximum, int(rate * float(runtime.get("short_transfer_minutes", 30)) * 60))
    long_slots = max(0, int(runtime.get("max_long_transfers", 1)))
    long_slots -= sum(transfer_bytes(row, states) > short_limit for row in pending)
    selected = []
    for row in ready:
        size = transfer_bytes(row, states)
        if size > maximum:
            continue
        if size > short_limit:
            if long_slots <= 0:
                continue
            long_slots -= 1
        selected.append(row)
        if len(selected) >= capacity:
            break
    return selected
