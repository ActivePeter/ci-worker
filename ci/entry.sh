#!/usr/bin/env bash
# Select test's environment; keep the entry and exact-ID report unchanged.
set -euo pipefail
mode="${TEST_UNIT_SETUP:-legacy}"
case "$mode" in
  legacy|nix) ;;
  *) echo "unknown TEST_UNIT_SETUP: $mode (expected legacy or nix)" >&2; exit 2 ;;
esac
phase="$1"
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
  if python3 --version; then echo 'host Python mutation was not effective' >&2; exit 2; fi
  printf '%s\n' 'rustc absent; host Python exits 93' > "$CI_OUT/host-poison.txt"
fi
if [[ "$mode" == nix ]]; then
  opts=(--extra-experimental-features 'nix-command flakes')
  develop=(nix "${opts[@]}" develop --no-update-lock-file --no-write-lock-file .#default)
  if [[ "$phase" == setup ]]; then
    # Fresh runner store, then the same realized environment on this machine.
    /usr/bin/time -f '%e' -o "$CI_OUT/local-store-cold.seconds" \
      "${develop[@]}" --command bash "$ENTRY" "$@"
    /usr/bin/time -f '%e' -o "$CI_OUT/local-store-hot.seconds" \
      "${develop[@]}" --command true
    exit 0
  fi
  # Time only execution inside the realized environment, excluding evaluation.
  exec "${develop[@]}" --command /usr/bin/time -f '%e' \
    -o "$CI_OUT/test-execution.seconds" bash "$ENTRY" "$@"
fi
exec /usr/bin/time -f '%e' -o "$CI_OUT/legacy-$phase.seconds" bash "$ENTRY" "$@"
