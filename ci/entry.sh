#!/usr/bin/env bash
# Test environment selection and mutation; the target owns setup and execution.
set -euo pipefail
mode="${TEST_UNIT_SETUP:-legacy}"
case "$mode" in
  legacy|nix) ;;
  *) echo "unknown TEST_UNIT_SETUP: $mode (expected legacy or nix)" >&2; exit 2 ;;
esac
: "${ENTRY:?missing target or fallback entry}"
if [[ "$mode" == nix && ( "${CI_ENTRY_KIND:-}" != target || ! -f nix/ci.sh ) ]]; then
  echo 'TEST_UNIT_SETUP=nix requires the tested target entry and its nix/ci.sh; legacy fallback cannot run Nix' >&2
  exit 2
fi
entry_bash=$(command -v bash)
mkdir -p "$CI_OUT"
if [[ "${TEST_UNIT_POISON_HOST:-0}" == 1 ]]; then
  poison="${RUNNER_TEMP:-$CI_OUT}/testkit-host-poison"
  mkdir -p "$poison"
  for name in python python3; do
    printf '%s\n' '#!/bin/sh' 'echo "host Python was deliberately replaced" >&2' 'exit 93' > "$poison/$name"
    chmod +x "$poison/$name"
  done
  clean_path="$poison"
  IFS=: read -ra components <<< "$PATH"
  for dir in "${components[@]}"; do
    if [[ -n "$dir" && ! -x "$dir/rustc" ]]; then clean_path+=":$dir"; fi
  done
  export PATH="$clean_path" PYTHONPATH="$poison" PYTHONHOME="$poison"
  if command -v rustc; then echo 'host rustc was not removed' >&2; exit 2; fi
  if python3 --version; then python_rc=0; else python_rc=$?; fi
  if [[ "$python_rc" != 93 ]]; then echo 'host Python mutation did not exit 93' >&2; exit 2; fi
  printf '%s\n' 'rustc absent; host Python exits 93' > "$CI_OUT/host-poison.txt"
fi
exec "$entry_bash" "$ENTRY" "$@"
