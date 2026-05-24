"""Meta-prompt proposer: generates candidate instruction edits via Vertex AI.

Calls gemini-2.5-pro with the proposer_v1.txt template to generate
K candidate instruction rewrites targeting a specific failure cluster.
"""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any

from adk_quality_lab.optimizer.cluster import FailureCluster

logger = logging.getLogger(__name__)

_PROPOSER_PROMPT_PATH = Path(__file__).parent.parent / "raters" / "prompts" / "proposer_v1.txt"


def _load_proposer_template() -> str:
    return _PROPOSER_PROMPT_PATH.read_text()


def _call_vertex_proposer(prompt: str) -> list[dict[str, Any]]:
    """Call Vertex AI to propose candidate instruction edits."""
    import vertexai  # type: ignore[import-untyped]
    from vertexai.generative_models import GenerativeModel  # type: ignore[import-untyped]

    project = os.environ.get("GOOGLE_CLOUD_PROJECT", "adk-quality-lab-tung")
    location = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")

    vertexai.init(project=project, location=location)
    model = GenerativeModel("gemini-2.5-pro")

    response = model.generate_content(
        prompt,
        generation_config={"temperature": 0.7},
    )

    raw = response.text.strip()
    # Strip markdown fences
    if raw.startswith("```"):
        raw = re.sub(r"^```[a-z]*\n?", "", raw)
        raw = re.sub(r"\n?```$", "", raw)

    return json.loads(raw)  # type: ignore[no-any-return]


def propose_edits(
    current_instruction: str,
    clusters: list[FailureCluster],
    surface: str,
    k: int = 5,
    history: list[dict[str, Any]] | None = None,
) -> list[str]:
    """Propose K candidate instruction replacements.

    Args:
        current_instruction: The instruction text to be improved.
        clusters: Failure clusters from cluster_failures().
        surface: Which surface is being tuned ('root_agent', 'planning_agent', 'tool_description').
        k: Number of candidate edits to propose.
        history: Previous accepted/rejected edit snapshots (for oscillation suppression).

    Returns:
        List of k instruction strings (complete replacements).
    """
    if not clusters:
        logger.warning("No failure clusters — nothing to propose edits for")
        return [current_instruction]

    template = _load_proposer_template()

    # Use the top cluster's failure mode
    top_cluster = clusters[0]
    failure_mode = top_cluster.failure_mode or "general_quality"

    # Format cluster exemplars
    exemplar_texts = top_cluster.exemplar_texts(n=3)
    cluster_exemplars = "\n".join(
        f"{i + 1}. Query: {q}" for i, q in enumerate(exemplar_texts)
    )

    # Format edit history
    if history:
        history_lines = []
        for snap in history[-5:]:  # last 5 snapshots
            status = "ACCEPTED" if snap.get("accepted") else "REJECTED"
            history_lines.append(
                f"[{status}] score={snap.get('score', '?'):.3f} "
                f"rationale={snap.get('rationale', 'N/A')}"
            )
        edit_history = "\n".join(history_lines)
    else:
        edit_history = "None yet."

    prompt = template.format(
        current_instruction=current_instruction,
        failure_mode=failure_mode,
        surface=surface,
        cluster_exemplars=cluster_exemplars,
        edit_history=edit_history,
        k=k,
    )

    try:
        candidates = _call_vertex_proposer(prompt)
        return [c["instruction"] for c in candidates[:k]]
    except Exception as exc:
        logger.error("Proposer call failed: %s", exc)
        return [current_instruction]
