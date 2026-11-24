#!/usr/bin/env bash
# Legacy default entry for goodputai/sglang, used while the tested SHA has no
# .github/ci/public-unit.sh: runs pure-CPU Python unit tests for managed_host_mixin,
# kv_hints, and unified_cache / mem_cache in a single Python 3.12 job.
#
# ppu15-0.5.21 exclusions (and reasons):
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
#         (CUDA fixture modules)
set -euo pipefail

# Curated CPU-only unit tests covering our modified modules (managed_host_mixin,
# kv_hints) and existing unified_cache / mem_cache CPU unit tests.
MEM_CACHE_TEST_DIR=test/registered/unit/mem_cache
PPU15_TESTS=(
  # Managed Host & kv_hints (our modified modules)
  test_managed_confirm.py
  test_managed_host.py
  test_managed_0519_compat.py
  test_managed_device_prefetch_anchor.py
  test_managed_prefetch_contract.py
  test_managed_prefetch_reissue.py
  # Unified cache & mem_cache CPU unit tests
  test_unified_byte_accounting.py
  test_unified_byte_budget_sizing.py
  test_unified_capacity_memo.py
  test_unified_free_no_host_sync.py
  test_unified_hicache_regressions.py
  test_unified_mamba_views.py
  test_unified_mha_views.py
  test_unified_mla_views.py
  test_unified_npool_sweep.py
  test_unified_radix_hicache_dispatch.py
  test_unified_radix_lock_ref.py
  test_unified_swa_shared_virtual_ids.py
  test_unified_tri_pool.py
  test_hicache_non_managed_prefetch.py
  test_l2_transfer_write_back_context.py
  test_dsa_bf16_page_geometry.py
  test_dsa_hicache_restore_invalidation.py
)

# ppu-0.5.17-beta exclusions (on the CPU-only runner):
#   test_asymmetric_mha_pool.py: fused store_cache and tiled kernels require CUDA.
#   test_dsa_layer_split_broadcast.py: requires at least two GPUs.
#   test_hicache_load_back_timing.py: CUDA timing events.
#   test_hicache_nixl_storage.py: requires the external nixl wheel.
#   test_hicache_page_read_dma_cuda.py: CUDA page-read DMA.
#   test_hiradix_cache_unit.py: CUDA/AMD accelerator fixture.
#   test_mamba_unittest.py: CUDA tensors and accelerator-dependent cache fixtures.
#   test_managed_e2e.py: requires the companion dynamo_hicache wheel.
#   test_radix_cache_unit.py: uses GPU memory accounting, unavailable on torch.cpu.
#   test_session_unified_radix_cache.py: expects UnifiedRadixCache to have no ManagedHostMixin base.
#   test_store_cache_4d.py: requires CUDA Triton kernels.
#   test_swa_eviction_boundary.py: requires an accelerator for SWA cache fixtures.
#   test_swa_lock_release_lifecycle.py: requires an accelerator for SWA cache fixtures.
#   test_swa_unittest.py: requires an accelerator for SWA cache fixtures.
#   test_triton_kernel_layout.py: requires CUDA Triton kernels.
#   test_umbp_store.py: requires the external AMD/ROCm mori.umbp wheel.
#   test_unified_mla_gpu_parity.py: requires CUDA parity kernels.
#   test_unified_radix_cache_bench.py: requires an accelerator for benchmark fixtures.
#   test_unified_radix_cache_unittest.py: requires an accelerator for cache fixtures.
PPU17_TESTS=(
  test_asymmetric_mha_pool_host_unit.py
  test_decode_radix_lock_ref.py
  test_dllm_fdfo_kv_reuse.py
  test_dsa_layer_shard_utils.py
  test_dsa_pool_host_unit.py
  test_dsv4_ppu_c128_cleanup.py
  test_embedding_cache_controller.py
  test_evict_policy.py
  test_flashkda_strided_state_access.py
  test_full_loc_fast_path.py
  test_hicache_cp_storage_identity.py
  test_hicache_dcp_host_pool.py
  test_hicache_draft_pool_mirror.py
  test_hicache_file_lru_unit.py
  test_hicache_load_reservation_window.py
  test_hicache_mirror_release.py
  test_hicache_nixl_cleaner.py
  test_hicache_non_managed_prefetch.py
  test_hicache_numa_socket_local.py
  test_hicache_page_read_dma.py
  test_hicache_prefetch_consensus.py
  test_hicache_segmented_registration.py
  test_hicache_sidecar_hit_accounting.py
  test_hicache_staged_write_back_dispatch.py
  test_hicache_tp_write_load_consensus.py
  test_hiradix_pp_sync_drain.py
  test_hisparse_allocator.py
  test_hybrid_pool_assembler.py
  test_kda_fused_decode_strided_state.py
  test_layout_compat.py
  test_mamba_donated_alloc_ratio.py
  test_mamba_path_state_cap.py
  test_managed_confirm.py
  test_managed_host.py
  test_managed_sha256.py
  test_mem_cache_utils.py
  test_mem_pool_host.py
  test_minimax_sparse_pool_host_unit.py
  test_minimax_sparse_pool_pd_unit.py
  test_mmap_allocator.py
  test_mooncake_group_semantics.py
  test_mooncake_standalone_dummy_mamba.py
  test_mooncake_tenant_config.py
  test_multi_ended_allocator.py
  test_page_major_layout.py
  test_paged_free_segment.py
  test_pure_swa_chunk_cache.py
  test_quantized_kv_pool.py
  test_radix_cache_slru_accuracy.py
  test_radix_force_miss.py
  test_registry.py
  test_replayssm_ring_accounting.py
  test_session_token_share_unit.py
  test_streaming_session_unit.py
  test_swa_alloc_extend_page_estimation.py
  test_tree_core_registry.py
  test_umbp_host_allocator.py
  test_unified_mamba_views.py
  test_unified_mla_dense_block_table.py
  test_unified_mla_views.py
  test_unified_radix_hicache_dispatch.py
)

select_profile() {
  case "${SGLANG_CI_PROFILE:-}" in
    ppu15-0.5.21|ppu-0.5.17-beta)
      printf '%s\n' "$SGLANG_CI_PROFILE"
      ;;
    "")
      local prefetch="$MEM_CACHE_TEST_DIR/test_managed_prefetch_contract.py"
      local sha256="$MEM_CACHE_TEST_DIR/test_managed_sha256.py"
      if [[ -f "$prefetch" && ! -f "$sha256" ]]; then
        echo ppu15-0.5.21
      elif [[ -f "$sha256" && ! -f "$prefetch" ]]; then
        echo ppu-0.5.17-beta
      else
        echo "Cannot identify SGLang CI profile: expected exactly one of $prefetch and $sha256. Set SGLANG_CI_PROFILE to select a profile explicitly." >&2
        return 1
      fi
      ;;
    *)
      echo "Invalid SGLANG_CI_PROFILE '$SGLANG_CI_PROFILE': expected ppu15-0.5.21 or ppu-0.5.17-beta." >&2
      return 2
      ;;
  esac
}

checkout_requirements() {
  python3 - <<'PYTHON'
import re
import sys
import tomllib
from pathlib import Path

path = Path("python/pyproject.toml")
try:
    config = tomllib.loads(path.read_text(encoding="utf-8"))
except FileNotFoundError:
    sys.exit("pyproject 里没有 transformers 依赖声明：缺少 python/pyproject.toml")
except (OSError, UnicodeError, tomllib.TOMLDecodeError) as exc:
    sys.exit(f"无法读取 {path} 的依赖声明：{exc}")

requirements = {}
for requirement in config.get("project", {}).get("dependencies", []):
    name = re.match(r"[A-Za-z0-9][A-Za-z0-9._-]*", requirement.lstrip())
    if name:
        requirements[name.group().lower()] = requirement.strip()

if "transformers" not in requirements:
    sys.exit("pyproject 里没有 transformers 依赖声明：[project].dependencies")
if "xgrammar" not in requirements:
    print("pyproject 里没有 xgrammar 依赖声明，将安装不钉版本的 xgrammar", file=sys.stderr)
for name in ("transformers", "tokenizers", "xgrammar"):
    print(requirements.get(name, name))
PYTHON
}

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
    requirements=$(checkout_requirements)
    mapfile -t checkout_deps <<< "$requirements"
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
      datasets \
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
      "${checkout_deps[@]}" \
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

    profile=$(select_profile)
    case "$profile" in
      ppu15-0.5.21)
        selected_tests=("${PPU15_TESTS[@]}")
        export CUDA_VISIBLE_DEVICES=""
        ;;
      ppu-0.5.17-beta)
        selected_tests=("${PPU17_TESTS[@]}")
        # test_utils indexes CUDA_VISIBLE_DEVICES[0] when present. On the
        # CPU-only runner, an unset variable lets the port calculation use 0.
        unset CUDA_VISIBLE_DEVICES
        ;;
    esac

    tests=()
    for filename in "${selected_tests[@]}"; do
      test_path="$MEM_CACHE_TEST_DIR/$filename"
      if [[ ! -f "$test_path" ]]; then
        echo "SGLang CI profile $profile is missing required test file: $test_path" >&2
        exit 1
      fi
      tests+=("$test_path")
    done
    echo "Running ${#tests[@]} sglang CPU unit test files (profile $profile):"
    printf '  %s\n' "${tests[@]}"

    export PYTHONPATH="$PWD/python:$PWD/test/registered/unit/mem_cache${PYTHONPATH:+:$PYTHONPATH}"
    python3 -m pytest -v --noconftest -p no:cacheprovider "${tests[@]}"
    ;;
  *)
    echo "usage: $0 plan|setup <id>|run <id>|report" >&2
    exit 2
    ;;
esac
