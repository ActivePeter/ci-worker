"""report: the only writer of the final ci/public-worker/<name> status.

success iff prepare succeeded, every planned job left a `success` marker and the
optional entry `report` step passed. The description names every red job.
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import status  # noqa: E402


def main():
    repo, context, sha = os.environ["REPO"], os.environ["CONTEXT"], os.environ.get("SHA", "")
    kind = os.environ.get("KIND", "")
    label = "legacy default · " if kind == "legacy" else ""
    jobs = json.loads(os.environ.get("JOBS") or "[]")
    results = {}
    if os.environ["PREPARE_RESULT"] != "success":
        state, description = "failure", f"{label}prepare/plan failed"
    else:
        ci_in = Path(os.environ["CI_IN"])
        for job in jobs:
            marker = ci_in / f"job-{job['id']}" / ".ci-job-status"
            results[job["id"]] = marker.read_text().strip() if marker.is_file() else "missing"
        report_rc = os.environ.get("REPORT_RC", "")
        if report_rc not in ("", "0"):
            results["report"] = f"failure(rc={report_rc})"
        red = [k for k, v in results.items() if v != "success"]
        ok = len(jobs) - len([k for k in red if k != "report"])
        if not red:
            state, description = "success", f"{label}{ok}/{len(jobs)} jobs ok"
        elif all(results[k] == "cancelled" for k in red):
            state, description = "error", f"{label}cancelled: {', '.join(red)}"
        else:
            state, description = "failure", f"{label}red: {', '.join(red)} ({ok}/{len(jobs)} ok)"
    lines = [f"### {context}: {state}", "", description, "", "| job | result |", "|---|---|"]
    lines += [f"| {k} | {v} |" for k, v in results.items()]
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        Path(os.environ["GITHUB_STEP_SUMMARY"]).open("a").write("\n".join(lines) + "\n")
    print("\n".join(lines))
    if sha:
        status.post(repo, sha, state, context, description, status.run_url())
    else:
        print("::error::no tested SHA resolved; cannot post status")
    return 0 if state == "success" else 1


if __name__ == "__main__":
    sys.exit(main())
