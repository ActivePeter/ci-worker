"""Run a target entry inside its locked Nix shell, and retain the phase wall time."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time

source, entry, phase, *args = sys.argv[1:]
started = time.monotonic()
result = subprocess.run(["nix", "develop", "--offline", source, "--command", "bash", entry, phase, *args])
output = Path(os.environ["CI_OUT"])
output.mkdir(parents=True, exist_ok=True)
(output / (phase + "-timing.json")).write_text(json.dumps({
    "phase": phase, "seconds": time.monotonic() - started, "returncode": result.returncode,
    "runtime": "nix", "source_sha": os.environ["CI_REF_SHA"]}) + "\n")
raise SystemExit(result.returncode)
