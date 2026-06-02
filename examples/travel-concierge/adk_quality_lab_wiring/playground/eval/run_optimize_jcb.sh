#!/usr/bin/env bash
# run_optimize_jcb.sh — Run adk optimize on the json_code_block planning variant.
#
# Targets train cases bb5cc9cb (LAX→NRT duration chain) and 93d715cc
# (LAX→NRT metric gap) — both are multi-turn scenarios with score potential.
#
# After optimization, copy the printed instruction back into:
#   adk_quality_lab_wiring/playground/agent_variants_minimal_cash_json_code_block.py
# and re-run:
#   bash adk_quality_lab_wiring/playground/eval/run_sim_eval.sh json_code_block
# to confirm the score improves.
#
# Usage:
#   cd examples/travel-concierge
#   source /path/to/.venv-313/bin/activate
#   bash adk_quality_lab_wiring/playground/eval/run_optimize_jcb.sh
#
# Prerequisites:
#   - Python 3.13 venv with google-adk[eval] + gepa installed
#   - local_eval_sampler.py patched (score or 0.0 guard — ADK bug #5115)
#   - GOOGLE_CLOUD_PROJECT set + gcloud auth

set -euo pipefail

AGENT_DIR="adk_quality_lab_wiring/playground/optimize_agent_jcb"
SAMPLER_CONFIG="adk_quality_lab_wiring/playground/eval/sampler_config_jcb.json"
RUN_DIR="/tmp/adk_optimize_jcb_$(date -u +%Y%m%dT%H%M%SZ)"

mkdir -p "${RUN_DIR}"

echo ""
echo "========================================"
echo " adk optimize — json_code_block planning variant"
echo " Train cases: bb5cc9cb (LAX→NRT chain) + 93d715cc (LAX→NRT metric gap)"
echo " Run dir: ${RUN_DIR}"
echo "========================================"
echo ""

adk optimize "${AGENT_DIR}" \
  --sampler_config_file_path "${SAMPLER_CONFIG}" \
  --print_detailed_results \
  2>&1 | tee "${RUN_DIR}/optimize.log"

echo ""
echo "Full log: ${RUN_DIR}/optimize.log"
echo ""
echo "Next steps:"
echo "  1. Copy the 'Optimized root agent instructions' block above."
echo "  2. Replace PLANNING_AGENT_INSTR_MINIMAL_CASH_JSON_CODE_BLOCK in:"
echo "       adk_quality_lab_wiring/playground/agent_variants_minimal_cash_json_code_block.py"
echo "  3. Re-run eval to confirm improvement:"
echo "       bash adk_quality_lab_wiring/playground/eval/run_sim_eval.sh json_code_block"
