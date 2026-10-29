"""Variant-isolated durable upload histories bound to the Lenka account."""

from sdilej_serialy.pipeline import EpisodeState
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
