#!/usr/bin/env bash
# Legacy default entry for goodputai/sglang, used while the tested SHA has no
# .github/ci/public-unit.sh: runs CPU unit tests for managed_host_mixin,
# kv_hints, and unified_cache / mem_cache in a single Python 3.12 job.
#
set -euo pipefail

MEM_CACHE_TEST_DIR=test/registered/unit/mem_cache

# ppu15-0.5.21 exclusions (on the CPU-only runner):
#   test_asymmetric_mha_pool.py: fused store_cache and tiled kernels require CUDA.
#   test_decode_retraction_backup.py: GPU device pools and CUDA-backed transfer fixtures.
#   test_dsa_layer_split_broadcast.py: requires at least two GPUs.
#   test_hicache_load_back_timing.py: CUDA timing events.
#   test_hicache_nixl_storage.py: requires the external nixl wheel.
#   test_mamba_unittest.py: CUDA and accelerator-dependent cache fixtures.
#   test_managed_e2e.py: requires the companion dynamo_hicache wheel.
#   test_p2a_provider_contract.py: requires native P2A leader, provider and hash artifacts.
#   test_rust_tree_core.py: requires the Rust tree-core extension.
#   test_rust_tree_core_errors.py: requires building the Rust tree-core extension.
#   test_rust_tree_core_integration.py: requires cargo and the Rust tree-core extension.
#   test_rust_unified_radix_cache_bench.py: requires the Rust tree-core extension.
#   test_rust_unified_radix_cache_unittest.py: requires the Rust tree-core extension.
#   test_swa_unittest.py: accelerator-dependent SWA fixtures.
#   test_umbp_store.py: imports the external mori.umbp wheel at collection.
#   test_unified_handout_zeroing.py: CUDA memory fixtures.
#   test_unified_mla_block_table.py: CUDA MLA kernels.
#   test_unified_mla_gpu_parity.py: CUDA parity kernels.
#   test_unified_radix_cache_bench.py: accelerator-dependent benchmark.
#   test_unified_radix_cache_unittest.py: accelerator-dependent unified cache fixtures.
#   test_unified_swa_tail_allocation.py: allocates CUDA tensors.
PPU15_TESTS=(
  test_0519_storage_codec_compat.py
  test_asymmetric_mha_pool_host_unit.py
  test_buffer_mode_sidecar.py
  test_decode_radix_lock_ref.py
  test_dllm_fdfo_kv_reuse.py
  test_dsa_bf16_page_geometry.py
  test_dsa_hicache_restore_invalidation.py
  test_dsa_layer_shard_utils.py
  test_dsa_page_geometry.py
  test_dsa_pool_host_unit.py
  test_dsv4_c4_state_lifecycle.py
  test_dsv4_compress_write_pad.py
  test_dsv4_compressed_pools.py
  test_dsv4_hicache_l2.py
  test_dsv4_unified_fp8_pool.py
  test_embedding_cache_controller.py
  test_evict_policy.py
  test_flashkda_strided_state_access.py
  test_free_kv_row_coalesce.py
  test_full_loc_fast_path.py
  test_hicache_auto_size.py
  test_hicache_copy_rounds.py
  test_hicache_dcp_host_pool.py
  test_hicache_file_lru_unit.py
  test_hicache_host_register.py
  test_hicache_nixl_cleaner.py
  test_hicache_non_managed_prefetch.py
  test_hicache_pp_sync_drain.py
  test_hicache_staged_write_back_dispatch.py
  test_hisparse_allocator.py
  test_hisparse_max_token_pool_size.py
  test_hisparse_slot_translation.py
  test_host_memory.py
  test_hybrid_pool_assembler.py
  test_inkling_sconv_strided_conv_state.py
  test_kda_fused_decode_strided_state.py
  test_kv_index_translator.py
  test_l2_transfer_write_back_context.py
  test_layout_compat.py
  test_linker_pool_assembler.py
  test_lmcache_component_cursors.py
  test_mamba_donated_alloc_ratio.py
  test_mamba_path_state_cap.py
  test_mamba_state_transfer_buffers.py
  test_managed_0519_compat.py
  test_managed_confirm.py
  test_managed_device_prefetch_anchor.py
  test_managed_host.py
  test_managed_prefetch_contract.py
  test_managed_prefetch_reissue.py
  test_managed_rank_sharded_draft.py
  test_mem_cache_utils.py
  test_mem_pool_host.py
  test_minimax_sparse_pool_host_unit.py
  test_minimax_sparse_pool_pd_unit.py
  test_mla_host_dedup_primitives.py
  test_mmap_allocator.py
  test_mooncake_group_semantics.py
  test_mooncake_ssd_offload_path.py
  test_mooncake_standalone_dummy_mamba.py
  test_mooncake_store_config.py
  test_mooncake_tenant_config.py
  test_multi_ended_allocator.py
  test_mxfp8_mha_pool_host_unit.py
  test_mxfp8_scale_transfer_buffers.py
  test_npu_mamba_async_layout.py
  test_page_interleave_shard.py
  test_page_major_layout.py
  test_paged_allocator_lazy_release.py
  test_paged_free_segment.py
  test_pd_envelope_transfer_layout.py
  test_pp_prefetch_ticket.py
  test_prefill_memory_budget.py
  test_pure_swa_chunk_cache.py
  test_pure_swa_radix_cache.py
  test_qsa_kv_pool.py
  test_quantized_kv_pool.py
  test_radix_cache_slru_accuracy.py
  test_radix_cache_unit.py
  test_radix_force_miss.py
  test_registry.py
  test_replayssm_ring_accounting.py
  test_retraction_mamba_backup.py
  test_session_token_share_unit.py
  test_session_unified_radix_cache.py
  test_storage_prefetch_lifecycle.py
  test_streaming_session_unit.py
  test_swa_alloc_extend_page_estimation.py
  test_swa_cpu_copy_filter.py
  test_swa_eviction_interval.py
  test_swa_locked_full_recover_unified.py
  test_swa_pool_v_head_dim.py
  test_swa_ring_page_return.py
  test_tlru_eviction_policy.py
  test_tree_core_registry.py
  test_umbp_direct_linker_rank_keys.py
  test_umbp_host_allocator.py
  test_unified_byte_accounting.py
  test_unified_byte_budget_sizing.py
  test_unified_cache_linker.py
  test_unified_capacity_memo.py
  test_unified_free_no_host_sync.py
  test_unified_hicache_regressions.py
  test_unified_hicache_strided_state.py
  test_unified_mamba_views.py
  test_unified_mha_views.py
  test_unified_mla_views.py
  test_unified_npool_sweep.py
  test_unified_radix_allocation_eviction.py
  test_unified_radix_hicache_dispatch.py
  test_unified_radix_lock_ref.py
  test_unified_swa_shared_virtual_ids.py
  test_unified_tri_pool.py
  test_uno_allocation_sizing.py
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
#   test_store_cache_4d.py: requires CUDA Triton kernels.
#   test_swa_eviction_boundary.py: requires an accelerator for SWA cache fixtures.
#   test_swa_lock_release_lifecycle.py: requires an accelerator for SWA cache fixtures.
#   test_swa_unittest.py: requires an accelerator for SWA cache fixtures.
#   test_triton_kernel_layout.py: requires CUDA Triton kernels.
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
  test_radix_cache_unit.py
  test_radix_cache_slru_accuracy.py
  test_radix_force_miss.py
  test_registry.py
  test_replayssm_ring_accounting.py
  test_session_token_share_unit.py
  test_session_unified_radix_cache.py
  test_streaming_session_unit.py
  test_swa_alloc_extend_page_estimation.py
  test_tree_core_registry.py
  test_umbp_host_allocator.py
  test_umbp_store.py
  test_unified_mamba_views.py
  test_unified_mla_dense_block_table.py
  test_unified_mla_views.py
  test_unified_radix_hicache_dispatch.py
)

select_profile() {
  case "${SGLANG_CI_BASE_REF:-}" in
    ppu15-0.5.21|ppu-0.5.17-beta)
      printf '%s\n' "$SGLANG_CI_BASE_REF"
      return
      ;;
    "") ;;
    *)
      printf "Unsupported SGLang CI base_ref '%s'; expected ppu15-0.5.21 or ppu-0.5.17-beta.\n" "$SGLANG_CI_BASE_REF" >&2
      return 2
      ;;
  esac
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
        echo "Cannot identify SGLang CI profile: expected exactly one of $prefetch and $sha256. For local runs only, set SGLANG_CI_PROFILE to select a profile explicitly." >&2
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
    sys.exit("缺少 python/pyproject.toml，无法读取 torch、transformers 和 xgrammar 依赖声明")
except (OSError, UnicodeError, tomllib.TOMLDecodeError) as exc:
    sys.exit(f"无法读取 {path} 的依赖声明：{exc}")

packages = ("torch", "torchvision", "transformers", "tokenizers", "xgrammar")
requirements = {name: [] for name in packages}
for requirement in config.get("project", {}).get("dependencies", []):
    requirement = requirement.strip()
    match = re.match(r"[A-Za-z0-9][A-Za-z0-9._-]*", requirement)
    if match and (name := match.group().lower()) in requirements:
        requirements[name].append(requirement)

for name in ("torch", "transformers", "xgrammar"):
    if not requirements[name]:
        sys.exit(f"pyproject 里没有 {name} 依赖声明：[project].dependencies")

# Preserve every PEP 508 requirement, including multiple declarations with
# complementary environment markers. The installer evaluates the markers.
for name in packages:
    # tokenizers on the beta branch is resolved to the last verified fallback
    # only when the checkout has no declaration of its own.
    fallback = "tokenizers==0.22.2" if name == "tokenizers" else name
    for requirement in requirements[name] or [fallback]:
        print(f"{name}\t{requirement}")
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
    torch_deps=()
    checkout_deps=()
    while IFS=$'\t' read -r package requirement; do
      case "$package" in
        torch|torchvision) torch_deps+=("$requirement") ;;
        *) checkout_deps+=("$requirement") ;;
      esac
    done <<< "$requirements"
    # libssl-dev (-lcrypto) and ninja-build are required by
    # sglang.srt.mem_cache.cpp_utils.native_hash JIT compilation on Linux CPU.
    sudo apt-get update -qq
    sudo apt-get install -y -qq libssl-dev ninja-build
    constraints="$(dirname "${BASH_SOURCE[0]}")/sglang-constraints.txt"
    # Solve torchvision together with the checkout's exact torch against the CPU index.
    pip_install --constraint "$constraints" --index-url https://download.pytorch.org/whl/cpu "${torch_deps[@]}"
    # Minimal runtime + test dependencies needed to import sglang.srt.mem_cache
    # and sglang.srt.managers.scheduler / kv_hints on CPU.
    pip_install --constraint "$constraints" --constraint <(printf '%s\n' "${torch_deps[@]}") \
      pytest \
      parameterized \
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
    profile=$(select_profile)
    deselect=(
      # GPU memory accounting is unavailable on torch.cpu for either profile.
      --deselect "$MEM_CACHE_TEST_DIR/test_radix_cache_unit.py::TestRadixCache::test_memory_allocated"
    )
    case "$profile" in
      ppu15-0.5.21)
        selected_tests=("${PPU15_TESTS[@]}")
        # Keep CPU fixtures on the Python tree even if a test builds the Rust extension.
        export SGLANG_UNIFIED_RADIX_TREE_CORE_BACKEND=python
        deselect+=(
          # Branch fixtures reference a missing indexer attribute and an unpublished memory namespace.
          --deselect "$MEM_CACHE_TEST_DIR/test_hicache_host_register.py::TestHiCacheHostRegister::test_dsa_page_layouts_with_draft_use_page_registration_granularity"
          --deselect "$MEM_CACHE_TEST_DIR/test_linker_pool_assembler.py::TestHybridDevicePoolAssembler::test_linker_requires_packed_draft"
          # This worker fixture needs an initialized pipeline group.
          --deselect "$MEM_CACHE_TEST_DIR/test_managed_rank_sharded_draft.py::TestTheDraftDeclaresItsSharding::test_the_dspark_worker_marks_its_isolated_draft"
        )
        ;;
      ppu-0.5.17-beta)
        selected_tests=("${PPU17_TESTS[@]}")
        deselect+=(
          # The AST assertion predates the branch's ManagedHostMixin base.
          --deselect "$MEM_CACHE_TEST_DIR/test_session_unified_radix_cache.py::TestSessionCacheOwnership::test_only_unified_radix_cache_owns_session_ref_tracker"
        )
        ;;
    esac

    # The hosted runner is CPU-only. test_utils indexes CUDA_VISIBLE_DEVICES[0]
    # when the variable is present; unset lets its port calculation default to 0.
    unset CUDA_VISIBLE_DEVICES

    tests=()
    missing_tests=()
    for filename in "${selected_tests[@]}"; do
      test_path="$MEM_CACHE_TEST_DIR/$filename"
      if [[ -f "$test_path" ]]; then
        tests+=("$test_path")
      else
        missing_tests+=("$test_path")
      fi
    done
    if (( ${#missing_tests[@]} )); then
      printf 'PR 落后 base 分支 %s，请 rebase\n' "$profile" >&2
      printf '  %s\n' "${missing_tests[@]}" >&2
      exit 1
    fi
    echo "Running ${#tests[@]} sglang CPU unit test files (profile $profile):"
    printf '  %s\n' "${tests[@]}"

    export PYTHONPATH="$PWD/python:$PWD/test/registered/unit/mem_cache${PYTHONPATH:+:$PYTHONPATH}"
    # Keep node IDs checkout-relative even when pytest finds config under test/.
    python3 -m pytest -v --rootdir="$PWD" --noconftest -p no:cacheprovider "${deselect[@]}" "${tests[@]}"
    ;;
  *)
    echo "usage: $0 plan|setup <id>|run <id>|report" >&2
    exit 2
    ;;
esac
