"""Variant-isolated durable upload histories bound to the Lenka account."""

from sdilej_serialy.pipeline import EpisodeState
from . import policy


class VariantState(EpisodeState):
    def __init__(self, path, variant, *, on_save=None, lock=None):
        if variant not in {"cz", "en"}:
            raise ValueError("Unknown variant")
        super().__init__(path, on_save=on_save)
        expected = {"account_hash": policy.TARGET_ACCOUNT_HASH, "variant": variant, "policy": policy.POLICY}
        if self.data.get("episodes") and self.data.get("binding") != expected:
            raise ValueError("Upload history belongs to a different account or variant")
        if self.data.get("binding", expected) != expected:
            raise ValueError("Upload history binding mismatch")
        self.data["binding"] = expected
        if lock is not None:
            self._lock = lock
