"""Tests for healthcheck.py.

These tests reproduce the bug reported in issue #94500: a per-intake rsyslog
output action can get stuck (e.g. a GnuTLS/omfwd worker-thread hang) while the
rsyslogd process itself keeps running. Docker's `restart: always` policy never
kicks in because the container never exits, so log forwarding for the affected
intake(s) silently stops until someone manually restarts the container.

healthcheck.py is expected to detect, from rsyslog's impstats JSON log, that
an intake's output action has stopped making progress while its queue keeps
receiving/holding events, and to report it as stalled after a few consecutive
observations (to avoid false positives on a single quiet interval).
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import healthcheck  # noqa: E402  (import after sys.path tweak, by design)


def stats_line(name, **fields):
    return json.dumps({"name": name, **fields})


def test_parse_stats_records_ignores_non_json_noise():
    log_text = "\n".join(
        [
            "Starting Entrypoint",
            stats_line("ruleset-techno1", size=0, enqueued=42),
            "",
            stats_line("output-techno1", processed=42, failed=0),
        ]
    )

    records = healthcheck.parse_stats_records(log_text)

    assert records == [
        {"name": "ruleset-techno1", "size": 0, "enqueued": 42},
        {"name": "output-techno1", "processed": 42, "failed": 0},
    ]


def test_build_intake_snapshot_pairs_queue_and_action_records():
    records = [
        {"name": "ruleset-techno1", "size": 3, "enqueued": 10},
        {"name": "output-techno1", "processed": 10, "failed": 0},
        {"name": "ruleset-techno2", "size": 0, "enqueued": 0},
        {"name": "output-techno2", "processed": 0, "failed": 0},
        {"name": "some-unrelated-object", "size": 999},
    ]

    snapshot = healthcheck.build_intake_snapshot(records)

    assert snapshot == {
        "techno1": {"queue_size": 3, "enqueued": 10, "processed": 10, "failed": 0},
        "techno2": {"queue_size": 0, "enqueued": 0, "processed": 0, "failed": 0},
    }


def test_healthy_intake_never_flagged_as_stalled():
    snapshot = {"techno1": {"queue_size": 0, "enqueued": 50, "processed": 50, "failed": 0}}

    state, stalled = healthcheck.update_stall_state(snapshot, previous_state={})

    assert stalled == []
    assert state["techno1"]["stalled_intervals"] == 0


def test_single_quiet_interval_is_not_enough_to_flag_a_stall():
    # No traffic at all (queue empty, nothing processed) must not be confused
    # with a stall: it's simply an idle intake.
    snapshot = {"techno1": {"queue_size": 0, "enqueued": 0, "processed": 0, "failed": 0}}

    state, stalled = healthcheck.update_stall_state(snapshot, previous_state={})

    assert stalled == []


def test_backlog_with_no_progress_is_flagged_after_consecutive_intervals():
    # This reproduces the reported bug: events keep arriving/queueing for the
    # intake (queue_size/enqueued > 0) but the output action processed
    # nothing during the interval - i.e. it is stuck.
    snapshot = {"techno1": {"queue_size": 4821, "enqueued": 120, "processed": 0, "failed": 0}}
    state = {}

    state, stalled = healthcheck.update_stall_state(snapshot, previous_state=state)
    assert stalled == []  # first bad interval: not yet flagged
    assert state["techno1"]["stalled_intervals"] == 1

    state, stalled = healthcheck.update_stall_state(snapshot, previous_state=state)
    assert stalled == []  # second bad interval: still within tolerance
    assert state["techno1"]["stalled_intervals"] == 2

    state, stalled = healthcheck.update_stall_state(snapshot, previous_state=state)
    assert stalled == ["techno1"]  # third consecutive bad interval: flagged
    assert state["techno1"]["stalled_intervals"] == 3


def test_progress_resets_the_stall_counter():
    stuck = {"techno1": {"queue_size": 4821, "enqueued": 120, "processed": 0, "failed": 0}}
    recovered = {"techno1": {"queue_size": 10, "enqueued": 120, "processed": 110, "failed": 0}}

    state, _ = healthcheck.update_stall_state(stuck, previous_state={})
    state, _ = healthcheck.update_stall_state(stuck, previous_state=state)
    assert state["techno1"]["stalled_intervals"] == 2

    state, stalled = healthcheck.update_stall_state(recovered, previous_state=state)

    assert stalled == []
    assert state["techno1"]["stalled_intervals"] == 0


def test_multiple_intakes_are_tracked_independently():
    snapshot = {
        "techno1": {"queue_size": 100, "enqueued": 100, "processed": 0, "failed": 0},
        "techno2": {"queue_size": 0, "enqueued": 5, "processed": 5, "failed": 0},
    }
    state = {}
    for _ in range(3):
        state, stalled = healthcheck.update_stall_state(snapshot, previous_state=state)

    assert stalled == ["techno1"]
    assert state["techno2"]["stalled_intervals"] == 0
