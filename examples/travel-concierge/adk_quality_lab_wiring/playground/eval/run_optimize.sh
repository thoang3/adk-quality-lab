#!/usr/bin/env bash
# run_optimize.sh — Run adk optimize on the markdown_table planning variant.
#
# Uses a flat single-agent wrapper (optimize_agent/) so GEPA rewrites the
# planning instruction directly rather than the root concierge routing prompt.
#
# After optimization, copy the printed instruction back into:
#   adk_quality_lab_wiring/playground/agent_variants_minimal_cash_markdown_table.py
# and re-run:
#   bash adk_quality_lab_wiring/playground/eval/run_sim_eval.sh markdown_table
# to confirm the score improves.
#
# Usage:
#   cd examples/travel-concierge
#   bash adk_quality_lab_wiring/playground/eval/run_optimize.sh
#
# Prerequisites:
#   - GOOGLE_CLOUD_PROJECT set
#   - gcloud auth application-default login
#   - Run from the examples/travel-concierge/ directory
#
# Known limitation (Python 3.14.0):
#   GEPA crashes on iteration 2+ with:
#     TypeError: type NoneType doesn't define __round__ method
#   Root cause: same Python 3.14 aiohttp SSL RecursionError that blocks
#   json_code_block eval — the SSL crash leaves eval_metric_result.score=None,
#   and local_eval_sampler.py calls round(None, 2).
#   Workaround: run on Python <= 3.13.

set -euo pipefail

AGENT_DIR="adk_quality_lab_wiring/playground/optimize_agent"
SAMPLER_CONFIG="adk_quality_lab_wiring/playground/eval/sampler_config.json"
RUN_DIR="/tmp/adk_optimize_$(date -u +%Y%m%dT%H%M%SZ)"

mkdir -p "${RUN_DIR}"

echo ""
echo "========================================"
echo " adk optimize — markdown_table planning variant"
echo " Run dir: ${RUN_DIR}"
echo "========================================"
echo ""

# PLAYGROUND_VARIANT is not needed here — optimize_agent/__init__.py directly
# imports the markdown_table instruction without going through agent.py.
adk optimize "${AGENT_DIR}" \
  --sampler_config_file_path "${SAMPLER_CONFIG}" \
  --print_detailed_results \
  2>&1 | tee "${RUN_DIR}/optimize.log"

echo ""
echo "Full log: ${RUN_DIR}/optimize.log"
echo ""
echo "Next steps:"
echo "  1. Copy the 'Optimized root agent instructions' block above."
echo "  2. Replace PLANNING_AGENT_INSTR_MINIMAL_RENDER_FLIGHTS in:"
echo "       adk_quality_lab_wiring/playground/agent_variants_minimal_cash_markdown_table.py"
echo "  3. Re-run eval to confirm improvement:"
echo "       bash adk_quality_lab_wiring/playground/eval/run_sim_eval.sh markdown_table"
