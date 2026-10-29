import subprocess
from lenka_sync.storage import Publisher


def git(directory, *arguments):
    return subprocess.run(["git", *arguments], cwd=directory, text=True, capture_output=True, check=True).stdout.strip()


def test_queue_and_metadata_are_read_from_one_revision(tmp_path):
    remote, checkout = tmp_path / "remote", tmp_path / "checkout"
    remote.mkdir()
    checkout.mkdir()
    git(remote, "init", "-b", "main")
    git(remote, "config", "user.name", "Test")
    git(remote, "config", "user.email", "test@example.invalid")
    for name in ("queue", "titles"):
        (remote / name).write_text("original")
    git(remote, "add", ".")
    git(remote, "commit", "-m", "test: original source snapshot")
    git(checkout, "init", "-b", "main")
    git(checkout, "remote", "add", "origin", str(remote))
    publisher = Publisher(checkout)
    original_run = publisher._run
    moved = False

    def run(*arguments, **kwargs):
        nonlocal moved
        result = original_run(*arguments, **kwargs)
        if arguments[0] == "show" and not moved:
            # The producer publishes a new queue while the uploader reads its files.
            (remote / "queue").write_text("updated")
            (remote / "titles").write_text("updated")
            git(remote, "add", ".")
            git(remote, "commit", "-m", "test: concurrent source publication")
            moved = True
        return result

    publisher._run = run
    assert publisher.read_snapshot(["queue", "titles", "missing"]) == {
        "queue": "original",
        "titles": "original",
        "missing": "",
    }
    assert publisher.read_snapshot(["queue", "titles"]) == {"queue": "updated", "titles": "updated"}
