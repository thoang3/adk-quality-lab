"""Eval-harness GenerateContentConfig presets.

Re-exports everything from ``travel_concierge.shared_libraries.types`` so that
eval-wiring code can simply do::

    from adk_quality_lab_wiring import types

and get both the upstream ``json_response_config`` *and* our eval-specific
presets (``markdown_default_config``, ``json_deterministic_config``, etc.).
"""

from __future__ import annotations

from google.genai import types as _genai_types

# Re-export upstream types so this module is a drop-in for
# ``travel_concierge.shared_libraries.types`` in eval-wiring imports.
from travel_concierge.shared_libraries.types import *  # noqa: F401, F403
from travel_concierge.shared_libraries.types import json_response_config

# ---------------------------------------------------------------------------
# Eval-harness config presets (not present in upstream types.py)
# ---------------------------------------------------------------------------

# Alias for clarity; backward-compat with code that used json_response_config.
json_default_config = json_response_config.model_copy(deep=True)

json_deterministic_config = _genai_types.GenerateContentConfig(
    response_mime_type="application/json",
    temperature=0,
    top_p=1.0,
    top_k=1,
)

markdown_default_config = _genai_types.GenerateContentConfig(
    temperature=0.1,
    top_p=0.5,
)

markdown_deterministic_config = _genai_types.GenerateContentConfig(
    temperature=0,
    top_p=1.0,
    top_k=1,
)
