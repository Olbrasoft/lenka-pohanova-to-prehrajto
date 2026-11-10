from copy import deepcopy
from datetime import UTC, datetime
import json
from types import SimpleNamespace

from sdilej_serialy.models import Episode
from lenka_sync.scheduling import execution_environment, select_transfers, upload_rate
from lenka_sync.state import VariantState
from lenka_sync.transfer import report_transfer_progress


def row(template, number, size):
    item = deepcopy(template)
    item["identity"] = f"42:1:{number}"
    item["episode"].update(episode=number, episode_id=number)
    item["selected"].update(source_id=str(number), size_bytes=size)
    return item


def select(ready, states, pending=(), capacity=3, seconds=330*60):
    return select_transfers(
        ready, states, pending, capacity=capacity, rate=65536, seconds_left=seconds, runtime={},
    )


def test_large_originals_do_not_block_shorter_originals_or_exceed_runner_time(tmp_path, czech_row):
    states = {"cz": VariantState(tmp_path / "cz.json", "cz")}
    ready = [row(czech_row, i+1, size) for i, size in enumerate((2_800_000_000, 600_000_000, 90_000_000, 80_000_000))]
    before = deepcopy(ready)
    chosen = select(ready, states)
    assert [r["identity"] for r in chosen] == ["42:1:2", "42:1:3", "42:1:4"]
    assert ready == before
    assert not states["cz"].data["episodes"]
    assert all((r["selected"]["width"], r["selected"]["height"]) == (1920, 1080) for r in chosen)


def test_running_long_transfer_keeps_other_slots_available_for_short_episodes(tmp_path, czech_row):
    states = {"cz": VariantState(tmp_path / "cz.json", "cz")}
    running = row(czech_row, 1, 600_000_000)
    ready = [row(czech_row, 2, 500_000_000), row(czech_row, 3, 80_000_000)]
    assert select(ready, states, [running]) == [ready[1]]
    assert not select(ready, states, seconds=60)


def test_accepted_target_reconciliation_bypasses_media_transfer_budget(tmp_path, czech_row):
    states = {"cz": VariantState(tmp_path / "cz.json", "cz")}
    received = row(czech_row, 1, 2_800_000_000)
    record = states["cz"].row(Episode.from_dict(received["episode"]))
    record["prepared_target"] = dict(target_video_id="777", size_bytes=2_800_000_000)
    record["transfer_receipt"] = dict(
        target_video_id="777", size_bytes=2_800_000_000, source_bytes_read=2_800_000_000, http_status=201,
    )
    assert select([received], states, seconds=0) == [received]


def performance_record(video_id, *, status=201, environment=None):
    return dict(
        upload={"target_video_id": video_id},
        completion_evidence={"receipt": dict(
            target_video_id=video_id, size_bytes=100_000_000, source_bytes_read=100_000_000, http_status=status,
        )},
        transfer_statistics=dict(
            target_video_id=video_id, source_bytes_read=100_000_000, elapsed_seconds=100,
            finished_at=datetime.now(UTC).isoformat(), environment=environment or execution_environment(),
        ),
    )


def test_rate_uses_only_completed_receipted_transfers_from_same_environment(tmp_path):
    state = VariantState(tmp_path / "cz.json", "cz")
    state.data["episodes"] = {
        "42:1:1": performance_record("1"),
        "42:1:2": performance_record("2", status=503),
        "42:1:3": performance_record("3", environment="other"),
        "42:1:4": {**performance_record("4"), "upload": None},
        "42:1:5": {**performance_record("5"), "completion_evidence": None},
    }
    assert upload_rate({"cz": state}, {"upload_rate_bytes_per_second": 49152}) == 1_000_000
    state.data["episodes"].pop("42:1:1")
    assert upload_rate({"cz": state}, {"upload_rate_bytes_per_second": 49152}) == 49152


def test_progress_does_not_claim_acceptance_or_expose_other_reader_attributes(monkeypatch, capsys):
    class Stop:
        calls = 0

        def wait(self, _):
            self.calls += 1
            return self.calls > 1

    reader = SimpleNamespace(position=100, total=100, last_progress_at=95, private_token="private-signed-token")
    monkeypatch.setattr("lenka_sync.transfer.time.monotonic", lambda: 100)
    report_transfer_progress(reader, Stop(), "777", 80)
    output = capsys.readouterr().out
    payload = json.loads(output)
    assert payload["phase"] == "awaiting_gateway_receipt"
    assert payload["relay_progress_bytes"] == 100
    assert "private-signed-token" not in output
