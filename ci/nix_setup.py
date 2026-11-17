"""Measure Nix environment realization using Nix 2.35.6's structured activity log.

Activity types come from NixOS/nix 2.35.6 logging.hh. Parallel intervals are
merged per category; category durations overlap and must never be added.
Only this runner's /nix/store is reused. No store is uploaded or restored.
"""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time

# https://github.com/NixOS/nix/blob/2.35.6/src/libutil/include/nix/util/logging.hh
ACTIVITIES = {101: "file_transfer", 105: "derivation_build", 108: "substitution"}


def union_seconds(intervals):
    end = total = 0.0
    for first, last in sorted(intervals):
        total += max(0.0, last - max(first, end))
        end = max(end, last)
    return total


def realize(source, output, label):
    started = time.monotonic()
    active, intervals, counts = {}, {name: [] for name in ACTIVITIES.values()}, {}
    command = ["nix", "print-dev-env", "--json", "--log-format", "internal-json", str(source)]
    events = output / (label + ".events.jsonl")
    with tempfile.TemporaryFile(mode="w+") as stdout, events.open("w") as trace:
        child = subprocess.Popen(command, stdout=stdout, stderr=subprocess.PIPE, text=True)
        for line in child.stderr:
            now = time.monotonic() - started
            if not line.startswith("@nix "):
                print(line, end="", flush=True)
                continue
            event = json.loads(line[5:])
            trace.write(json.dumps({"seconds": now, "event": event}) + "\n")
            action, ident = event.get("action"), event.get("id")
            if action == "start" and event.get("type") in ACTIVITIES:
                category = ACTIVITIES[event["type"]]
                active[ident] = (category, now)
                counts[category] = counts.get(category, 0) + 1
            elif action == "stop" and ident in active:
                category, first = active.pop(ident)
                intervals[category].append((first, now))
            if event.get("msg"):
                print(event["msg"], flush=True)
        rc = child.wait()
        seconds = time.monotonic() - started
        unfinished = len(active)
        for category, first in active.values():
            intervals[category].append((first, seconds))
        stdout.seek(0)
        data = stdout.read()
        (output / (label + ".stdout.json")).write_text(data)
    result = {"seconds": seconds, "returncode": rc, "activity_counts": counts,
              "activity_seconds": {k: union_seconds(v) for k, v in intervals.items()},
              "unfinished_activities": unfinished}
    if not rc:
        environment = json.loads(data)
        result["path"] = environment["variables"]["PATH"]["value"]
    return result


def main():
    source = Path(os.environ["NIX_SOURCE"]).resolve()
    output = Path(os.environ["NIX_EVIDENCE"])
    output.mkdir(parents=True, exist_ok=True)
    if not (source / "flake.lock").is_file():
        raise SystemExit("Nix runtime requires flake.lock in the tested SHA; update the branch from main")
    metrics = {"source_sha": subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip(),
               "nix": subprocess.check_output(["nix", "--version"], text=True).strip(),
               "install_seconds": (time.time_ns() - int(os.environ["NIX_INSTALL_STARTED_NS"])) / 1e9,
               "store_policy": "local machine only; official public dependency acquisition; no cross-runner cache"}
    metrics["first_realization"] = realize(source, output, "first-realization")
    if not metrics["first_realization"]["returncode"]:
        metrics["same_runner_repeat"] = realize(source, output, "same-runner-repeat")
    (output / "nix-timings.json").write_text(json.dumps(metrics, indent=2) + "\n")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a") as stream:
            stream.write("### Locked Nix environment\n\n| phase | wall seconds | substitution | derivation build | file transfer |\n|---|---:|---:|---:|---:|\n")
            for name in ("first_realization", "same_runner_repeat"):
                row = metrics.get(name)
                if row:
                    times = row["activity_seconds"]
                    stream.write(f"| {name} | {row['seconds']:.3f} | {times['substitution']:.3f} | {times['derivation_build']:.3f} | {times['file_transfer']:.3f} |\n")
            stream.write("\nActivity categories overlap; they are not additive. The repeat uses this same runner's local store. Fixed-output fetches can occur inside derivation builds.\n")
    return max(row["returncode"] for name, row in metrics.items()
               if name in ("first_realization", "same_runner_repeat"))


if __name__ == "__main__":
    raise SystemExit(main())
