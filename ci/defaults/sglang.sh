#!/usr/bin/env bash
# Legacy default entry for goodputai/sglang, used while the tested SHA has no
# .github/ci/public-unit.sh: runs pure-CPU Python unit tests for managed_host_mixin,
# kv_hints, and unified_cache / mem_cache in a single Python 3.12 job.
#
# Explicitly excluded tests (and reasons):
#   GPU / torch.cuda required:
#     - test/registered/unit/mem_cache/test_unified_handout_zeroing.py
#         (all tests require CUDA / torch.cuda.is_available())
#     - test/registered/unit/mem_cache/test_unified_mla_block_table.py
#         (register_cuda_ci; all tests require CUDA)
#     - test/registered/unit/mem_cache/test_unified_mla_gpu_parity.py
#         (register_cuda_ci; GPU parity checks require CUDA)
#     - test/registered/unit/mem_cache/test_unified_radix_cache_bench.py
#         (register_cuda_ci; GPU benchmark)
#     - test/registered/unit/mem_cache/test_unified_radix_cache_unittest.py
#         (register_cuda_ci; cache fixtures require CUDA)
#     - test/registered/unit/mem_cache/test_unified_swa_tail_allocation.py
#         (register_cuda_ci; allocates device="cuda" tensors)
#   Companion / Rust / distributed-init required (outside pure-Python CPU unit scope):
#     - test/registered/unit/mem_cache/test_managed_e2e.py
#         (requires companion dynamo_hicache wheel from goodputai/dynamo)
#     - test/registered/unit/mem_cache/test_managed_rank_sharded_draft.py
#         (test_the_dspark_worker_marks_its_isolated_draft fails without PP group init on ppu15-0.5.21)
#     - test/registered/unit/mem_cache/test_rust_tree_core*.py
#     - test/registered/unit/mem_cache/test_rust_unified_radix_cache*.py
#         (require prebuilt Rust tree-core extension)
#     - test/registered/unit/mem_cache/test_unified_cache_linker.py
#     - test/registered/unit/mem_cache/test_unified_hicache_strided_state.py
#     - test/registered/unit/mem_cache/test_unified_radix_allocation_eviction.py
#         (import sglang.test.test_utils -> datasets / CUDA fixture modules)
set -euo pipefail

# Curated CPU-only unit tests covering our modified modules (managed_host_mixin,
# kv_hints) and existing unified_cache / mem_cache CPU unit tests.
CANDIDATE_TESTS=(
  # Managed Host & kv_hints (our modified modules)
  test/registered/unit/mem_cache/test_managed_confirm.py
  test/registered/unit/mem_cache/test_managed_host.py
  test/registered/unit/mem_cache/test_managed_0519_compat.py
  test/registered/unit/mem_cache/test_managed_device_prefetch_anchor.py
  test/registered/unit/mem_cache/test_managed_prefetch_contract.py
  test/registered/unit/mem_cache/test_managed_prefetch_reissue.py
  # Unified cache & mem_cache CPU unit tests
  test/registered/unit/mem_cache/test_unified_byte_accounting.py
  test/registered/unit/mem_cache/test_unified_byte_budget_sizing.py
  test/registered/unit/mem_cache/test_unified_capacity_memo.py
  test/registered/unit/mem_cache/test_unified_free_no_host_sync.py
  test/registered/unit/mem_cache/test_unified_hicache_regressions.py
  test/registered/unit/mem_cache/test_unified_mamba_views.py
  test/registered/unit/mem_cache/test_unified_mha_views.py
  test/registered/unit/mem_cache/test_unified_mla_views.py
  test/registered/unit/mem_cache/test_unified_npool_sweep.py
  test/registered/unit/mem_cache/test_unified_radix_hicache_dispatch.py
  test/registered/unit/mem_cache/test_unified_radix_lock_ref.py
  test/registered/unit/mem_cache/test_unified_swa_shared_virtual_ids.py
  test/registered/unit/mem_cache/test_unified_tri_pool.py
  test/registered/unit/mem_cache/test_hicache_non_managed_prefetch.py
  test/registered/unit/mem_cache/test_l2_transfer_write_back_context.py
  test/registered/unit/mem_cache/test_dsa_bf16_page_geometry.py
  test/registered/unit/mem_cache/test_dsa_hicache_restore_invalidation.py
)

pip_install() {
  if command -v uv >/dev/null 2>&1; then
    uv pip install --python "$(command -v python3)" "$@"
  else
    python3 -m pip install --disable-pip-version-check "$@"
  fi
}

case "${1:-}" in
  plan)
    cat <<'JSON'
{"version": 1, "report": false, "jobs": [
  {"id": "cpu-unit", "timeout": 20, "python": "3.12"}
]}
JSON
    ;;
  setup)
    [ "${2:-}" = "cpu-unit" ] || { echo "unknown job ${2:-}" >&2; exit 2; }
    # libssl-dev (-lcrypto) and ninja-build are required by
    # sglang.srt.mem_cache.cpp_utils.native_hash JIT compilation on Linux CPU.
    sudo apt-get update -qq
    sudo apt-get install -y -qq libssl-dev ninja-build
    # CPU-only PyTorch wheels avoid multi-GB CUDA downloads on hosted CPU runners.
    pip_install --index-url https://download.pytorch.org/whl/cpu torch torchvision
    # Minimal runtime + test dependencies needed to import sglang.srt.mem_cache
    # and sglang.srt.managers.scheduler / kv_hints on CPU.
    pip_install \
      pytest \
      triton \
      ninja \
      setuptools \
      numpy \
      scipy \
      einops \
      psutil \
      pydantic \
      pyzmq \
      orjson \
      msgspec \
      msgpack \
      packaging \
      requests \
      prometheus-client \
      aiohttp \
      httpx \
      httpx-sse \
      fastapi \
      uvicorn \
      uvloop \
      transformers \
      tokenizers \
      huggingface-hub \
      safetensors \
      sentencepiece \
      tiktoken \
      pillow \
      pybase64 \
      setproctitle \
      compressed-tensors \
      gguf \
      dill \
      loguru \
      PyYAML \
      opentelemetry-api \
      opentelemetry-sdk \
      opentelemetry-exporter-otlp \
      ipython \
      partial-json-parser \
      python-multipart \
      openai \
      redis \
      nvidia-ml-py
    ;;
  run)
    [ "${2:-}" = "cpu-unit" ] || { echo "unknown job ${2:-}" >&2; exit 2; }
    # If managed_host_mixin exists on this branch (e.g. ppu15-0.5.21), require
    # test_managed_confirm.py to be present so it can never be silently skipped.
    if [ -f python/sglang/srt/mem_cache/unified_cache/managed_host_mixin.py ] \
      && [ ! -f test/registered/unit/mem_cache/test_managed_confirm.py ]; then
      echo "managed_host_mixin.py is present but test_managed_confirm.py is missing" >&2
      exit 1
    fi

    tests=()
    for t in "${CANDIDATE_TESTS[@]}"; do
      if [ -f "$t" ]; then
        tests+=("$t")
      fi
    done
    if [ "${#tests[@]}" -eq 0 ]; then
      echo "no CPU unit test files found in checkout" >&2
      exit 1
    fi
    echo "Running ${#tests[@]} sglang CPU unit test files:"
    printf '  %s\n' "${tests[@]}"

    export CUDA_VISIBLE_DEVICES=""
    export PYTHONPATH="$PWD/python:$PWD/test/registered/unit/mem_cache${PYTHONPATH:+:$PYTHONPATH}"
    python3 -m pytest -v --noconftest -p no:cacheprovider "${tests[@]}"
    ;;
  *)
    echo "usage: $0 plan|setup <id>|run <id>|report" >&2
    exit 2
    ;;
esac
