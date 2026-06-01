"""Default app entry-point.

This file intentionally mirrors the upstream Travel Concierge root-agent path
for normal app behavior. Harness/eval-specific wiring is isolated in
`adk_quality_lab_wiring/agent_eval.py`.
"""
import pathlib
import sys

_wiring_dir = str(pathlib.Path(__file__).parent)
if _wiring_dir not in sys.path:
    sys.path.insert(0, _wiring_dir)

from travel_concierge.agent import root_agent as upstream_root_agent  # noqa: E402

root_agent = upstream_root_agent
