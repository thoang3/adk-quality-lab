"""ADK entry point for `adk run adk_quality_lab_wiring/playground`.

Exposes root_agent pointing at the json_code_block variant by default.
Override by setting PLAYGROUND_VARIANT env var to one of:
  markdown_table | json_code_block | json_passthrough

Session state is seeded automatically on the first turn via a
before_agent_callback so `adk run` works without --replay.
"""

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from google.adk.agents import Agent
from google.adk.agents.callback_context import CallbackContext
from google.genai.types import Content

# ---------------------------------------------------------------------------
# Seed session state (user_profile, _time, etc.) on first agent turn so that
# ROOT_AGENT_INSTR template variables are always populated.
# ---------------------------------------------------------------------------

_PROFILE_PATH = Path(__file__).parent.parent / "profiles" / "demo_rich_portfolio.json"


def _seed_state_callback(callback_context: CallbackContext) -> Optional[Content]:
    """Inject profile state into session on first turn only."""
    state = callback_context.state
    if state.get("_state_seeded"):
        return None  # already done

    if _PROFILE_PATH.exists():
        raw = _PROFILE_PATH.read_text()
        fixed = re.sub(r",(\s*[}\]])", r"\1", raw)  # strip trailing commas
        data = json.loads(fixed)
        profile_state = data.get("state", data)
        for k, v in profile_state.items():
            state[k] = v

    state.setdefault("_time", datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"))
    state["_state_seeded"] = True
    return None  # let the agent run normally


# ---------------------------------------------------------------------------
# Select variant
# ---------------------------------------------------------------------------

_variant = os.getenv("PLAYGROUND_VARIANT", "json_code_block")

if _variant == "markdown_table":
    from adk_quality_lab_wiring.playground.agent_variants_minimal_cash_markdown_table import (
        root_agent_minimal_cash as _base_agent,
    )
elif _variant == "json_passthrough":
    from adk_quality_lab_wiring.playground.agent_variants_minimal_cash_json_passthrough import (
        root_agent_minimal_cash as _base_agent,
    )
else:
    from adk_quality_lab_wiring.playground.agent_variants_minimal_cash_json_code_block import (
        root_agent_minimal_cash as _base_agent,
    )

# Attach the seed callback to the root agent's before_agent_callback.
# _base_agent is an Agent instance; we patch its callback slot directly.
_base_agent.before_agent_callback = _seed_state_callback

root_agent = _base_agent

__all__ = ["root_agent"]
