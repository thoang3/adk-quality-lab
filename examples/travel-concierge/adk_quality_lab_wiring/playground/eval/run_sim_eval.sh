#!/usr/bin/env bash
# run_sim_eval.sh — Run ADK user simulation eval for all 3 playground variants.
#
# Usage:
#   bash eval/run_sim_eval.sh [markdown_table|json_code_block|json_passthrough|all]
#
# Prerequisites:
#   - `adk` CLI installed (google-adk >= 1.18.0)
#   - GOOGLE_CLOUD_PROJECT set (Vertex GenAI Eval Service)
#   - ADC configured: `gcloud auth application-default login`
#   - Run from the examples/travel-concierge/ directory

set -euo pipefail

VARIANT="${1:-all}"
AGENT_DIR="adk_quality_lab_wiring/playground"
EVAL_DIR="${AGENT_DIR}/eval"
CONFIG="${EVAL_DIR}/eval_config.json"
SCENARIOS="${EVAL_DIR}/scenarios_cash_flight.json"
RESULTS_DIR="${EVAL_DIR}/results"
RUN_TS="$(date -u +%Y%m%dT%H%M%SZ)"

mkdir -p "${RESULTS_DIR}"

run_variant() {
  local v="$1"
  local session_file="${EVAL_DIR}/session_input_${v}.json"
  local eval_set_id="cash_sim_${v}"
  local log_file="${RESULTS_DIR}/${RUN_TS}_${v}.log"

  echo ""
  echo "========================================"
  echo " Variant: ${v}  |  Run: ${RUN_TS}"
  echo " Log: ${log_file}"
  echo "========================================"

  export PLAYGROUND_VARIANT="${v}"

  # 1. Create the eval set (idempotent — ignore error if already exists)
  adk eval_set create "${AGENT_DIR}" "${eval_set_id}" 2>/dev/null || true

  # 2. Populate it with the shared conversation scenarios
  adk eval_set add_eval_case \
    "${AGENT_DIR}" \
    "${eval_set_id}" \
    --scenarios_file "${SCENARIOS}" \
    --session_input_file "${session_file}"

  # 3. Run the evaluation — tee to timestamped log AND latest symlink
  adk eval \
    "${AGENT_DIR}" \
    --config_file_path "${CONFIG}" \
    "${eval_set_id}" \
    --print_detailed_results \
  2>&1 | tee "${log_file}"

  # Keep a "latest" copy for quick reference
  cp "${log_file}" "${RESULTS_DIR}/latest_${v}.log"

  echo ""
  echo "--- SUMMARY: ${v} ---"
  grep -E "Tests passed|Tests failed|Overall Eval Status|Metric:" "${log_file}" || true
  echo "Full log: ${log_file}"
}

case "$VARIANT" in
  all)
    run_variant markdown_table
    run_variant json_code_block
    run_variant json_passthrough
    ;;
  markdown_table|json_code_block|json_passthrough)
    run_variant "$VARIANT"
    ;;
  *)
    echo "Unknown variant: $VARIANT"
    echo "Usage: $0 [markdown_table|json_code_block|json_passthrough|all]"
    exit 1
    ;;
esac
