"""Harness/eval entry-point.

Keeps ADK Quality Lab variant wiring isolated from the default app entry-point
in `agent.py`.
"""

import pathlib
import sys

_wiring_dir = str(pathlib.Path(__file__).parent)
if _wiring_dir not in sys.path:
    sys.path.insert(0, _wiring_dir)

from tuned_prompts.planning_agent_arch_fix import planning_agent_arch_fix  # noqa: E402

root_agent = planning_agent_arch_fix
