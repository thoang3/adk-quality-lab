"""Entry-point for `adk optimize` / `adk eval`.

NOT imported at package load time.  The eval harness (agent_runner.py) adds
adk_quality_lab_wiring/ to sys.path before loading, so bare-name imports
(`from tuned_prompts...`, `from tools...`) work correctly here.

TODO (adk-optimize): when resuming the optimizer effort, the final_response
ground-truth in train_eval_set.evalset.json should be a JSON array of flight
objects serialised from the FlightInfo Pydantic schema so the LLM judge can
do a structured comparison.
"""
import pathlib
import sys

_wiring_dir = str(pathlib.Path(__file__).parent)
if _wiring_dir not in sys.path:
    sys.path.insert(0, _wiring_dir)

from tuned_prompts.planning_agent_v2 import planning_agent_v2  # noqa: E402

root_agent = planning_agent_v2
