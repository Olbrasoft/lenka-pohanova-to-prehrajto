"""Variant-isolated durable upload histories bound to the Lenka account."""

from sdilej_serialy.pipeline import EpisodeState
from sdilej_serialy.source_transfer import SourceUnavailable
from datetime import UTC, datetime, timedelta
from . import policy


def validate_target_ownership(states):
    owners = {}
    for variant, state in states.items():
        for record in state.data["episodes"].values():
            for field in ("upload", "prepared_target"):
                video_id = record.get(field, {}).get("target_video_id")
                if video_id is None:
                    continue
                video_id = str(video_id)
                if video_id in owners and owners[video_id] != variant:
                    raise ValueError("Persisted target ID is shared across language variants")
                owners[video_id] = variant


class VariantState(EpisodeState):
    def __init__(self, path, variant, *, on_save=None, lock=None):
        if variant not in policy.VARIANTS:
            raise ValueError("Unknown variant")
        super().__init__(path, on_save=on_save)
        expected = {"account_hash": policy.TARGET_ACCOUNT_HASH, "variant": variant, "policy": policy.POLICY}
        if self.data.get("episodes") and self.data.get("binding") != expected:
            raise ValueError("Upload history belongs to a different account or variant")
        if self.data.get("binding", expected) != expected:
            raise ValueError("Upload history binding mismatch")
        self.data["binding"] = expected
        self.variant = variant
        self.peers = {}
        if lock is not None:
            self._lock = lock

    def source_deferred_series(self, *, at=None):
        now = at or datetime.now(UTC)
        with self._lock:
            return {
                series_id for series_id, record in self.data.get("source_outages", {}).items()
                if record.get("retry_after", "") > now.isoformat()
            }

    def failure(self, episode, error):
        with self._lock:
            record = self.row(episode)
            if isinstance(error, SourceUnavailable) and record.get("source", {}).get("source_id") and not record.get("prepared_target"):
                now = datetime.now(UTC)
                series_id = str(episode.series_id)
                outage = self.data.setdefault("source_outages", {}).setdefault(series_id, {})
                recent = {
                    item["identity"]: item for item in outage.get("recent_failures", [])
                    if item["at"] > (now - timedelta(minutes=5)).isoformat()
                }
                recent[episode.identity] = dict(identity=episode.identity, at=now.isoformat())
                outage["recent_failures"] = list(recent.values())[-3:]
                if len(recent) >= 3:
                    outage["retry_after"] = (now + timedelta(minutes=10)).isoformat()
                    print(f"source_series_deferred variant={self.variant} series_id={series_id}", flush=True)
            super().failure(episode, error)

    def success(self, episode, video_id, name):
        with self._lock:
            for variant, peer in self.peers.items():
                if variant == self.variant:
                    continue
                for other in peer.data["episodes"].values():
                    if str(video_id) in {
                        str(other.get("upload", {}).get("target_video_id")),
                        str(other.get("prepared_target", {}).get("target_video_id")),
                    }:
                        raise RuntimeError("Target ID already belongs to another language variant")
            row = self.row(episode)
            receipt = dict(row.get("transfer_receipt") or {})
            source = dict(row.get("source") or {})
            # Persist completion provenance before the base class removes transient fields.
            if receipt:
                row["completion_evidence"] = {
                    "receipt": receipt,
                    "variant": self.variant,
                    "source_id": source.get("source_id"),
                    "source_url": source.get("source_url"),
                    "audio_language": source.get("audio_language"),
                }
            super().success(episode, video_id, name)
