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
MAX_JOBS = 32


def normalize(plan):
    if plan.get("version") != 1:
        raise ValueError("plan.version must be 1")
    jobs, seen, suites = [], set(), set()
    for job in plan.get("jobs", []):
        ident = str(job.get("id", ""))
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,31}", ident) or ident in seen or ident == "report":
            raise ValueError(f"bad or duplicate job id {ident!r}")
        seen.add(ident)
        verification = job.get("verification")
        if verification is not None:
            if (not isinstance(verification, dict) or set(verification) != {"namespace", "suite"}
                    or not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", str(verification["namespace"]))
                    or not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,31}", str(verification["suite"]))
                    or verification["suite"] in suites or not job.get("shared") or not plan.get("report")):
                raise ValueError(f"invalid verification plan for {ident!r}")
            suites.add(verification["suite"])
        jobs.append({
            "id": ident,
            "timeout": max(1, min(int(job.get("timeout", 20)), 60)),
            "python": str(job.get("python", "")),
            "shared": bool(job.get("shared", False)),
            "verification": verification,
            "rust_cache": bool(job.get("rust_cache", False)),
            "go": bool(job.get("go", False)),
            "go_version": str(job.get("go_version", "")),
            "node": str(job.get("node", "")),
            "pnpm": str(job.get("pnpm", "")),
            "fetch_depth": max(0, int(job.get("fetch_depth", 1))),
        })
    if not jobs or len(jobs) > MAX_JOBS:
        raise ValueError(f"plan must declare 1..{MAX_JOBS} jobs")
    if any(job["shared"] for job in jobs) and plan.get("shared") is None:
        raise ValueError("shared consumers require a shared preparation job")
    return jobs, bool(plan.get("report", False))


def matrix_order(repo, jobs):
    if repo != "goodputai/test":
        return jobs
    return sorted(jobs, key=lambda job: not job["id"].startswith("nix-cpu-chain-"))


def normalize_shared(plan):
    record = plan.get("shared")
    if record is None:
        return None
    if not isinstance(record, dict) or set(record) - {"id", "timeout", "fetch_depth"}:
        raise ValueError("shared must declare only id, timeout and fetch_depth")
    shared = normalize({"version": 1, "jobs": [record]})[0][0]
    if any(str(job.get("id", "")) == shared["id"] for job in plan.get("jobs", [])):
        raise ValueError("shared preparation id must differ from matrix job ids")
    return {name: shared[name] for name in ("id", "timeout", "fetch_depth")}


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
        plan = json.loads(text)
        jobs, report = normalize(plan)
        shared = normalize_shared(plan)
    except Exception as error:
        print(f"::error::plan failed ({kind} entry {entry}): {error}")
        raise SystemExit(1)
    ordered_jobs = matrix_order(repo, jobs)
    out.write(f"jobs={json.dumps(ordered_jobs, separators=(',', ':'))}\nreport={'true' if report else 'false'}\n")
    report_jobs = ([shared] if shared else []) + jobs
    out.write(f"shared={json.dumps(shared, separators=(',', ':')) if shared else ''}\n")
    out.write(f"report_jobs={json.dumps(report_jobs, separators=(',', ':'))}\n")
    names = ", ".join(job["id"] for job in report_jobs)
    print(f"{kind} entry {entry}: {len(jobs)} jobs [{names}] report={report}")
    label = "legacy default · " if kind == "legacy" else ""
    status.post(repo, sha, "pending", context, f"{label}running {len(jobs)} jobs: {names}", status.run_url())


if __name__ == "__main__":
    main()
