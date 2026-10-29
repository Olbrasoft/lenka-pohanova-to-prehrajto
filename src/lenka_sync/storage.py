"""Atomic, credential-free local records."""

from __future__ import annotations

import gzip
import json
from pathlib import Path
from sdilej_serialy.pipeline import atomic_json
from sdilej_serialy.git_state import GitCheckpointPersister


class Publisher(GitCheckpointPersister):
    def read_snapshot(self, paths):
        """Read all producer files from one immutable remote revision."""
        if any(path.startswith("/") or ".." in Path(path).parts for path in paths):
            raise ValueError("Snapshot paths must stay inside the repository")
        with self.lock:
            self._run("fetch", "origin", "main")
            revision = self._run("rev-parse", "FETCH_HEAD").stdout.strip()
            result = {}
            for path in paths:
                exists = self._run("ls-tree", "--name-only", revision, "--", path).stdout.strip()
                result[path] = self._run("show", f"{revision}:{path}").stdout if exists else ""
            return result


def read_json(path: Path, default=None):
    return json.loads(path.read_text()) if path.exists() else ({} if default is None else default)


def rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def write_rows(path: Path, values: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    payload = "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in values)
    if path.suffix == ".gz":
        with temporary.open("wb") as output:
            output.write(gzip.compress(payload.encode(), mtime=0))
    else:
        temporary.write_text(payload)
    temporary.replace(path)


__all__ = ["Publisher", "atomic_json", "read_json", "rows", "write_rows"]
