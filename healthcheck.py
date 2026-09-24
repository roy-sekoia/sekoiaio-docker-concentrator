#!/usr/bin/env python3
"""Detect stalled rsyslog output actions and self-heal the container.

Context
-------
The Sekoia.io Forwarder (this concentrator) can silently stop relaying logs
for one or more intakes while the `rsyslogd` process itself keeps running
(container stays `Up`). This has been observed under sustained load and
matches known upstream rsyslog issues where an `omfwd`/GnuTLS output worker
thread gets stuck (e.g. rsyslog/rsyslog#1533, #5539). Because the process
never exits/crashes, Docker's `restart: always` policy never triggers, and
the only recovery today is a manual `docker restart` of the container.

This script inspects rsyslog's `impstats` JSON log (enabled in rsyslog.conf,
written to /var/log/rsyslog-stats.log) to detect intakes whose output action
has stopped making progress (`processed == 0`) while their queue still holds
or receives events (backlog present). If the same intake is stalled for
several consecutive stats intervals in a row, it is considered stuck and,
unless running with --dry-run, the script terminates rsyslogd (PID 1) so
that Docker's restart policy brings the container back to a healthy state -
automating the manual restart that operators currently have to perform.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import sys

DEFAULT_STATS_FILE = "/var/log/rsyslog-stats.log"
DEFAULT_STATE_FILE = "/var/spool/rsyslog/.healthcheck_state.json"
# Number of consecutive "backlog but no progress" intervals required before
# an intake is considered stalled. impstats reports every 300s by default,
# so 3 intervals (~15 minutes) gives enough tolerance to avoid false
# positives from a momentary hiccup while still recovering quickly.
DEFAULT_STALL_THRESHOLD = 3
# Tail size (in bytes) read from the stats file. impstats logs one JSON
# object per monitored item per interval; reading the last chunk is enough
# to cover the latest reporting interval for a reasonably sized fleet of
# intakes without having to parse the whole (rotated) log file.
DEFAULT_TAIL_BYTES = 512 * 1024


def parse_stats_records(log_text: str) -> list[dict]:
    """Parse impstats JSON lines, silently skipping any non-JSON noise."""
    records = []
    for line in log_text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return records


def build_intake_snapshot(records: list[dict]) -> dict[str, dict]:
    """Pair per-intake queue (`ruleset-<name>`) and action (`output-<name>`)
    impstats records together, keyed by intake name."""
    snapshot: dict[str, dict] = {}
    for rec in records:
        name = rec.get("name", "")
        if name.startswith("ruleset-"):
            intake = name[len("ruleset-") :]
            entry = snapshot.setdefault(intake, {})
            entry["queue_size"] = rec.get("size", 0)
            entry["enqueued"] = rec.get("enqueued", 0)
        elif name.startswith("output-"):
            intake = name[len("output-") :]
            entry = snapshot.setdefault(intake, {})
            entry["processed"] = rec.get("processed", 0)
            entry["failed"] = rec.get("failed", 0)
    return snapshot


def update_stall_state(
    snapshot: dict[str, dict],
    previous_state: dict[str, dict],
    stall_threshold: int = DEFAULT_STALL_THRESHOLD,
) -> tuple[dict[str, dict], list[str]]:
    """Update the per-intake stall counters and return the intakes that have
    been stuck for `stall_threshold` consecutive intervals."""
    new_state: dict[str, dict] = {}
    stalled = []
    for intake, stats in snapshot.items():
        previous_count = previous_state.get(intake, {}).get("stalled_intervals", 0)
        backlog_present = stats.get("queue_size", 0) > 0 or stats.get("enqueued", 0) > 0
        no_progress = stats.get("processed", 0) == 0
        count = previous_count + 1 if (backlog_present and no_progress) else 0
        new_state[intake] = {"stalled_intervals": count}
        if count >= stall_threshold:
            stalled.append(intake)
    return new_state, stalled


def _read_tail(path: str, max_bytes: int) -> str:
    if not os.path.exists(path):
        return ""
    with open(path, "rb") as f:
        f.seek(0, os.SEEK_END)
        size = f.tell()
        f.seek(max(0, size - max_bytes))
        return f.read().decode("utf-8", errors="replace")


def _load_state(path: str) -> dict:
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _save_state(path: str, state: dict) -> None:
    try:
        with open(path, "w") as f:
            json.dump(state, f)
    except OSError:
        pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stats-file", default=DEFAULT_STATS_FILE)
    parser.add_argument("--state-file", default=DEFAULT_STATE_FILE)
    parser.add_argument("--stall-threshold", type=int, default=DEFAULT_STALL_THRESHOLD)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report stalled intakes without restarting rsyslogd.",
    )
    args = parser.parse_args(argv)

    log_text = _read_tail(args.stats_file, DEFAULT_TAIL_BYTES)
    records = parse_stats_records(log_text)
    snapshot = build_intake_snapshot(records)

    previous_state = _load_state(args.state_file)
    new_state, stalled = update_stall_state(snapshot, previous_state, args.stall_threshold)
    _save_state(args.state_file, new_state)

    if not stalled:
        return 0

    print(
        "healthcheck: the following intake(s) appear stuck (backlog present, "
        f"no events forwarded for {args.stall_threshold} consecutive intervals): "
        + ", ".join(sorted(stalled)),
        file=sys.stderr,
    )

    if not args.dry_run:
        print("healthcheck: restarting rsyslogd to restore log forwarding", file=sys.stderr)
        try:
            os.kill(1, signal.SIGTERM)
        except OSError as exc:
            print(f"healthcheck: failed to signal PID 1: {exc}", file=sys.stderr)

    return 1


if __name__ == "__main__":
    sys.exit(main())
