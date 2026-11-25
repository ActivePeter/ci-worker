#!/usr/bin/env bash
# Bridge the tested checkout's CPU stage onto the public worker entry contract.
set -euo pipefail
exec /usr/bin/python3 -I "$(dirname "$0")/../workflow.py" sglang "$@"
