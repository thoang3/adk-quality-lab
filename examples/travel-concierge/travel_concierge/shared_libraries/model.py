# Copyright 2025 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Model configuration for Travel Concierge agents.

Provides a configurable model that supports Vertex AI Priority PayGo for
improved throughput (4M TPM baseline for Flash) without upfront commitment.

Priority PayGo adds HTTP headers to every Gemini request so they are routed
through a higher-priority shared pool. If demand exceeds the ramp limit,
requests gracefully fall back to Standard PayGo rates.

Toggle via environment variable:
    USE_PRIORITY_PAYGO=1  -> Priority PayGo (higher throughput, higher cost/token)
    USE_PRIORITY_PAYGO=0  -> Standard PayGo (default, lower cost/token)

Requires GOOGLE_CLOUD_LOCATION=global (Priority PayGo only supports global endpoint).

See: https://docs.cloud.google.com/vertex-ai/generative-ai/docs/priority-paygo
"""

import logging
import os

from google.adk.models.google_llm import Gemini

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "gemini-2.5-flash"


class PriorityPayGoGemini(Gemini):
    """Gemini model with Priority PayGo headers for better throughput.

    Injects X-Vertex-AI-LLM-Request-Type and X-Vertex-AI-LLM-Shared-Request-Type
    headers into every API request. These headers tell Vertex AI to route the
    request through the Priority PayGo pool, which starts at 4M TPM for Flash
    models (vs 2M TPM at Standard PayGo Tier 1).

    If the Priority pool is over capacity, the request is silently downgraded
    to Standard PayGo and charged at Standard rates — no errors, no failures.
    """

    # Forward-compatibility: newer ADK versions added use_interactions_api as a
    # Pydantic model field on Gemini. Declare it here so subclass attribute access
    # doesn't raise AttributeError when running on Agent Engine's newer ADK runtime.
    use_interactions_api: bool | None = None

    def _tracking_headers(self) -> dict[str, str]:
        headers = super()._tracking_headers()
        headers["X-Vertex-AI-LLM-Request-Type"] = "shared"
        headers["X-Vertex-AI-LLM-Shared-Request-Type"] = "priority"
        return headers


def get_model(model_name: str = DEFAULT_MODEL) -> str | PriorityPayGoGemini:
    """Factory function to create the appropriate model based on config.

    Args:
        model_name: The Gemini model identifier (e.g. "gemini-2.5-flash").

    Returns:
        A PriorityPayGoGemini instance if USE_PRIORITY_PAYGO=1 AND not running
        inside Vertex AI Agent Engine (where it manages routing itself),
        otherwise the plain model name string (Standard PayGo).

    Note:
        PriorityPayGoGemini is a Pydantic subclass of Gemini. When deploying via
        Agent Engine (deploy.py --create), the agent is pickled on the *local*
        machine where USE_PRIORITY_PAYGO=1 may be set. Agent Engine then unpickles
        it into a newer ADK runtime that has additional Pydantic fields (base_url,
        use_interactions_api, etc.) the subclass doesn't declare, causing
        AttributeError at runtime.

        AGENT_ENGINE_RUNTIME=1 is set in deploy.py env_vars so it's available
        *inside* Agent Engine at runtime, but it does NOT affect the local pickle.
        Therefore we also check SKIP_PRIORITY_PAYGO which is set by deploy.py
        *before* importing the agent (before pickling).
    """
    use_priority = os.getenv("USE_PRIORITY_PAYGO", "0").strip()

    # Two guards against pickling PriorityPayGoGemini into Agent Engine:
    # 1. AGENT_ENGINE_RUNTIME=1 — set inside Agent Engine at runtime
    # 2. SKIP_PRIORITY_PAYGO=1  — set by deploy.py locally before pickling
    skip = (
        os.getenv("AGENT_ENGINE_RUNTIME", "0") == "1"
        or os.getenv("SKIP_PRIORITY_PAYGO", "0") == "1"
    )

    if use_priority == "1" and not skip:
        location = os.getenv("GOOGLE_CLOUD_LOCATION", "")
        if location != "global":
            logger.warning(
                "⚠️ USE_PRIORITY_PAYGO=1 but GOOGLE_CLOUD_LOCATION=%r (expected 'global'). "
                "Priority PayGo requires the global endpoint — headers will be sent but "
                "may be ignored by regional endpoints.",
                location,
            )
        logger.info(
            "Priority PayGo ENABLED for model=%s "
            "(4M TPM Flash baseline, requires global endpoint)",
            model_name,
        )
        return PriorityPayGoGemini(model=model_name)

    if use_priority == "1" and skip:
        logger.info(
            "Priority PayGo skipped (Agent Engine deployment). Using plain model string."
        )

    return model_name


# Module-level constant for convenient import across all agent files.
# Usage: from travel_concierge.shared_libraries.model import MODEL
MODEL = get_model()
