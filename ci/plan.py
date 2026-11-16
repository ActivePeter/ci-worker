"""prepare: pick the entry script for the tested SHA, validate its plan, mark pending.

Entry = the SHA's own .github/ci/public-unit.sh when present (each branch owns
"how my unit runs"); otherwise ci-worker's legacy default for that repository.
Writes GitHub outputs: sha, kind, entry, jobs (matrix include JSON), report.
"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import status  # noqa: E402

TARGET_ENTRY = ".github/ci/public-unit.sh"
MAX_JOBS = 12


def normalize(plan):
    if plan.get("version") != 1:
        raise ValueError("plan.version must be 1")
    jobs, seen = [], set()
    for job in plan.get("jobs", []):
        ident = str(job.get("id", ""))
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,31}", ident) or ident in seen or ident == "report":
            raise ValueError(f"bad or duplicate job id {ident!r}")
        seen.add(ident)
        jobs.append({
            "id": ident,
            "timeout": max(1, min(int(job.get("timeout", 20)), 60)),
            "python": str(job.get("python", "")),
            "rust_cache": bool(job.get("rust_cache", False)),
            "fetch_depth": max(0, int(job.get("fetch_depth", 1))),
        })
    if not jobs or len(jobs) > MAX_JOBS:
        raise ValueError(f"plan must declare 1..{MAX_JOBS} jobs")
    return jobs, bool(plan.get("report", False))


def main():
    src, ciw = Path(os.environ["SRC"]), Path(os.environ["CIW"])
    repo, context = os.environ["REPO"], os.environ["CONTEXT"]
    sha = subprocess.check_output(["git", "-C", str(src), "rev-parse", "HEAD"], text=True).strip()
    out = open(os.environ["GITHUB_OUTPUT"], "a")
    out.write(f"sha={sha}\n")
    if (src / TARGET_ENTRY).is_file():
        kind, entry = "target", (src / TARGET_ENTRY).resolve()
    else:
        kind, entry = "legacy", (ciw / os.environ["DEFAULT_ENTRY"]).resolve()
    out.write(f"kind={kind}\nentry={entry}\n")
    out.flush()
    try:
        text = subprocess.check_output(["bash", str(entry), "plan"], cwd=src, text=True, timeout=120)
        jobs, report = normalize(json.loads(text))
    except Exception as error:
        print(f"::error::plan failed ({kind} entry {entry}): {error}")
        raise SystemExit(1)
    out.write(f"jobs={json.dumps(jobs, separators=(',', ':'))}\nreport={'true' if report else 'false'}\n")
    names = ", ".join(job["id"] for job in jobs)
    print(f"{kind} entry {entry}: {len(jobs)} jobs [{names}] report={report}")
    label = "legacy default · " if kind == "legacy" else ""
    status.post(repo, sha, "pending", context, f"{label}running {len(jobs)} jobs: {names}", status.run_url())


if __name__ == "__main__":
    main()
