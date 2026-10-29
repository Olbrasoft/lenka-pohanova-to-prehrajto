"""Command line entry point for the independent Lenka series pipeline."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .importer import import_sources
from .metadata import Metadata
from .pipeline import credentials, planned, prepare, sources, upload
from .state import VariantState
from .subtitles import followup


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("mode", choices=["import", "titles", "plan", "prepare", "upload", "continuous", "subtitles"])
    result.add_argument("--root", type=Path, default=Path.cwd())
    result.add_argument("--upstream", type=Path)
    result.add_argument("--limit", type=int, default=10)
    result.add_argument("--workers", type=int, default=3)
    result.add_argument("--runtime-minutes", type=int, default=40)
    result.add_argument("--persist-git-state", action="store_true")
    return result


def main(argv=None):
    arguments = parser()
    args = arguments.parse_args(argv)
    if not 1 <= args.limit <= 500 or not 1 <= args.workers <= 6 or not 1 <= args.runtime_minutes <= 300:
        arguments.error("limit must be 1..500, workers 1..6, runtime-minutes 1..300")
    root = args.root.resolve()
    if args.mode == "import":
        if args.upstream is None:
            arguments.error("import requires --upstream")
        result = import_sources(root, args.upstream.resolve())
    elif args.mode == "titles":
        result = Metadata(root).resolve(limit=args.limit, runtime_minutes=args.runtime_minutes)
    elif args.mode == "plan":
        states = {
            variant: VariantState(root / f"variants/{variant}/state/uploads.json", variant) for variant in ("cz", "en")
        }
        queue = planned(sources(root), Metadata(root).snapshot(), states, args.limit)
        result = [
            {
                "variant": row["variant"],
                "identity": row["identity"],
                "title": row["display_name"],
                "source": row["selected"]["url"],
                "width": row["selected"]["width"],
                "height": row["selected"]["height"],
            }
            for row in queue
        ]
    elif args.mode == "prepare":
        result = prepare(root, limit=args.limit, runtime_minutes=args.runtime_minutes, persist=args.persist_git_state)
    elif args.mode == "subtitles":
        from sdilej_serialy.git_state import GitCheckpointPersister

        state = VariantState(root / "variants/en/state/uploads.json", "en")
        publisher = GitCheckpointPersister(root, (state.path,)) if args.persist_git_state else None
        state.on_save = publisher
        result = followup(
            root,
            sources(root)["en"],
            state,
            Metadata(root).snapshot(),
            credentials(),
            persist=publisher,
            runtime_minutes=args.runtime_minutes,
            limit=args.limit,
        )
    else:
        result = upload(
            root,
            workers=args.workers,
            limit=args.limit,
            runtime_minutes=args.runtime_minutes,
            continuous=args.mode == "continuous",
            persist=args.persist_git_state,
        )
    if args.persist_git_state and args.mode in {"import", "titles"}:
        from sdilej_serialy.git_state import GitCheckpointPersister

        paths = (
            (
                root / "variants/cz/manifests/selected-episodes.jsonl",
                root / "backlog/series-episodes.jsonl.gz",
                root / "reports/import.json",
            )
            if args.mode == "import"
            else (root / "state/titles.json",)
        )
        GitCheckpointPersister(root, paths[1:])(paths[0])
    print(json.dumps(result, ensure_ascii=False))
    return 0


def entrypoint():
    try:
        raise SystemExit(main())
    except Exception as error:
        # Exceptions may carry authenticated request URLs. Output their class only.
        print(f"failed={type(error).__name__}")
        raise SystemExit(1) from None


if __name__ == "__main__":
    entrypoint()
