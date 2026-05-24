"""LLM-as-judge rater using Vertex AI gemini-2.5-pro.

Calibrated against human gold labels. κ must be ≥ 0.7 before publishing results.
Prompt template is versioned — never delete prior versions, always append.
"""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any

from adk_quality_lab.datasets.schema import EvalCase, RaterResult

logger = logging.getLogger(__name__)

_PROMPTS_DIR = Path(__file__).parent / "prompts"

# Judge model — separate from agent under test to avoid self-grading bias
_JUDGE_MODEL = "gemini-2.5-pro"

# Prompt version used for this run (increment when rubric changes)
JUDGE_PROMPT_VERSION = "v1"


def _load_prompt(version: str = "v1") -> str:
    path = _PROMPTS_DIR / f"judge_{version}.txt"
    return path.read_text()


def _call_vertex(prompt: str) -> dict[str, Any]:
    """Call Vertex AI and return the parsed JSON response from the judge."""
    import vertexai
    from vertexai.generative_models import GenerativeModel

    project = os.environ.get("GOOGLE_CLOUD_PROJECT", "adk-quality-lab-tung")
    location = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")

    vertexai.init(project=project, location=location)
    model = GenerativeModel(_JUDGE_MODEL)

    response = model.generate_content(
        prompt,
        generation_config={
            "temperature": 0.0,
            "response_mime_type": "application/json",
        },
    )

    raw = response.text.strip()
    # Strip markdown fences if present
    if raw.startswith("```"):
        raw = re.sub(r"^```[a-z]*\n?", "", raw)
        raw = re.sub(r"\n?```$", "", raw)
    return json.loads(raw)  # type: ignore[no-any-return]


def judge(
    case: EvalCase,
    agent_response: str,
    tool_payload: dict[str, Any] | None = None,
    criterion: str = "completeness",
    prompt_version: str = "v1",
) -> RaterResult:
    """Run the LLM judge on a single case.

    Args:
        case: The eval case.
        agent_response: The agent's textual response.
        tool_payload: Raw SerpAPI payload the agent received (for grounding check).
        criterion: Rubric criterion to evaluate (F1 or F2 sub-criterion).
        prompt_version: Which prompt version to use.

    Returns:
        RaterResult with passed, score, and rationale from the judge.
    """
    rater_id = f"llm_judge.{criterion}"
    template = _load_prompt(prompt_version)

    # Truncate tool payload to ~4000 tokens (rough approximation: 4 chars/token)
    payload_str = json.dumps(tool_payload, indent=2) if tool_payload else "N/A"
    if len(payload_str) > 16000:
        payload_str = payload_str[:16000] + "\n... [truncated]"

    prompt = template.format(
        criterion=criterion,
        query=case.query,
        tool_payload=payload_str,
        agent_response=agent_response,
    )

    try:
        result = _call_vertex(prompt)
        passed = bool(result.get("passed", False))
        score = float(result.get("score", 0.0))
        rationale = str(result.get("rationale", ""))
    except Exception as exc:
        logger.error("LLM judge failed for %s: %s", case.case_id, exc)
        return RaterResult(
            case_id=case.case_id,
            rater=rater_id,
            passed=False,
            score=0.0,
            detail=f"Judge error: {exc}",
        )

    return RaterResult(
        case_id=case.case_id,
        rater=rater_id,
        passed=passed,
        score=score,
        detail=rationale,
    )


def truncation_disclosure(
    case: EvalCase,
    agent_response: str,
    tool_payload: dict[str, Any] | None = None,
) -> RaterResult:
    """Judge whether the agent properly discloses truncation (F1 criterion)."""
    return judge(case, agent_response, tool_payload, criterion="truncation_disclosure")


def completeness(
    case: EvalCase,
    agent_response: str,
    tool_payload: dict[str, Any] | None = None,
) -> RaterResult:
    """Judge response completeness (F1 sub-criterion)."""
    return judge(case, agent_response, tool_payload, criterion="completeness")


def value_groundedness(
    case: EvalCase,
    agent_response: str,
    tool_payload: dict[str, Any] | None = None,
) -> RaterResult:
    """Judge whether cited values are grounded in the tool payload (F2 criterion)."""
    return judge(case, agent_response, tool_payload, criterion="value_groundedness")


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

_RATER_REGISTRY = {
    "llm_judge.truncation_disclosure": truncation_disclosure,
    "llm_judge.completeness": completeness,
    "llm_judge.value_groundedness": value_groundedness,
}


def run_llm_raters(
    case: EvalCase,
    agent_response: str,
    tool_payload: dict[str, Any] | None = None,
) -> list[RaterResult]:
    """Run all LLM-judge raters declared in the case."""
    results: list[RaterResult] = []
    for rater_id in case.raters:
        if rater_id in _RATER_REGISTRY:
            fn = _RATER_REGISTRY[rater_id]
            results.append(fn(case, agent_response, tool_payload))
    return results
