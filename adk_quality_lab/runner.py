"""Parallel eval runner for ADK Quality Lab.

Runs eval cases against the Travel Concierge agent using
ThreadPoolExecutor (4 workers by default), aggregates rater results,
and persists to Firestore + BigQuery.

Note: ThreadPoolExecutor is used instead of ProcessPoolExecutor so that
arbitrary callables (closures, lambdas, ADK runners) can be passed as
agent_fn without pickling constraints.
"""

from __future__ import annotations

import concurrent.futures
import json
import logging
import os
import uuid
from pathlib import Path
from typing import Any

from adk_quality_lab.datasets.schema import Category, EvalCase, RaterResult, RunResult
from adk_quality_lab.raters.deterministic import run_deterministic_raters
from adk_quality_lab.raters.groundedness import run_groundedness_raters

logger = logging.getLogger(__name__)

_FIXTURES_DIR = Path(__file__).parent.parent / "datasets" / "fixtures" / "flights"
_EVAL_WORKERS = int(os.environ.get("EVAL_WORKERS", "4"))


# ---------------------------------------------------------------------------
# Fixture loading
# ---------------------------------------------------------------------------


def load_fixture(fixture_hash: str) -> dict[str, Any] | None:
    """Load a cached SerpAPI fixture by SHA256 hash (full or 24-char prefix).

    Supports both full 64-char SHA-256 filenames and the 24-char short prefix
    stored in JSONL dataset files by capture_fixtures.py.

    Returns None if fixture is not found (live API call would be needed).
    """
    # Try exact match first
    exact = _FIXTURES_DIR / f"{fixture_hash}.json"
    if exact.exists():
        return json.loads(exact.read_text())  # type: ignore[no-any-return]
    # Fall back to prefix glob (capture_fixtures stores 24-char prefixes)
    matches = sorted(_FIXTURES_DIR.glob(f"{fixture_hash}*.json"))
    if matches:
        return json.loads(matches[0].read_text())  # type: ignore[no-any-return]
    logger.warning("Fixture not found: %s", fixture_hash)
    return None


# ---------------------------------------------------------------------------
# Single-case runner (called in worker processes)
# ---------------------------------------------------------------------------


def run_single_case(
    case: EvalCase,
    agent_fn: Any,  # Callable[[str, dict], str] — query → agent_response
    use_fixture_cache: bool = True,
) -> list[RaterResult]:
    """Run a single eval case and return all rater results.

    Args:
        case: The eval case to run.
        agent_fn: Callable that takes (query, session_state) and returns agent response text.
        use_fixture_cache: If True, load tool payload from fixture cache instead of live API.

    Returns:
        List of RaterResult from all applicable raters.
    """
    tool_payload: dict[str, Any] | None = None
    if use_fixture_cache:
        tool_payload = load_fixture(case.fixture_hash)

    try:
        agent_response: str = agent_fn(case.query, tool_payload)
    except Exception as exc:
        logger.error("Agent call failed for case %s: %s", case.case_id, exc)
        # Return failed results for all raters
        return [
            RaterResult(
                case_id=case.case_id,
                rater=rater_id,
                passed=False,
                score=0.0,
                detail=f"Agent error: {exc}",
            )
            for rater_id in case.raters
        ]

    results: list[RaterResult] = []
    results.extend(run_deterministic_raters(case, agent_response, tool_payload))
    results.extend(run_groundedness_raters(case, agent_response, tool_payload))
    # LLM judge raters are run separately (expensive — not in parallel workers)

    return results


# ---------------------------------------------------------------------------
# Batch runner
# ---------------------------------------------------------------------------


def run_eval(
    cases: list[EvalCase],
    agent_fn: Any,
    variant: str = "baseline",
    surface: str | None = None,
    iteration: int | None = None,
    use_fixture_cache: bool = True,
    max_workers: int | None = None,
    run_id: str | None = None,
) -> RunResult:
    """Run a batch of eval cases in parallel and return aggregated results.

    Args:
        cases: Eval cases to run.
        agent_fn: Agent callable (query, tool_payload) → response.
        variant: 'baseline' or 'tuned'.
        surface: Optimizer surface being evaluated.
        iteration: Optimizer iteration number.
        use_fixture_cache: Whether to use SerpAPI fixture cache.
        max_workers: Override default worker count (EVAL_WORKERS env var).
        run_id: UUID for this run (auto-generated if not provided).

    Returns:
        RunResult with all rater results and aggregate scores.
    """
    run_id = run_id or str(uuid.uuid4())
    workers = max_workers or _EVAL_WORKERS

    logger.info(
        "Starting eval run %s: %d cases, variant=%s, workers=%d",
        run_id,
        len(cases),
        variant,
        workers,
    )

    all_results: list[RaterResult] = []

    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        future_to_case = {
            executor.submit(run_single_case, case, agent_fn, use_fixture_cache): case
            for case in cases
        }
        for future in concurrent.futures.as_completed(future_to_case):
            case = future_to_case[future]
            try:
                results = future.result()
                all_results.extend(results)
            except Exception as exc:
                logger.error("Worker failed for case %s: %s", case.case_id, exc)

    # Compute aggregate scores
    all_scores = [r.score for r in all_results]
    aggregate = sum(all_scores) / len(all_scores) if all_scores else 0.0

    category_scores: dict[Category, float] = {}
    for cat in ("F1", "F2"):
        cat_results = [r for r in all_results if r.case_id.lower().startswith(cat.lower())]
        if cat_results:
            category_scores[cat] = sum(r.score for r in cat_results) / len(cat_results)  # type: ignore[literal-required]

    run = RunResult(
        run_id=run_id,
        variant=variant,  # type: ignore[arg-type]
        surface=surface,
        iteration=iteration,
        cases=all_results,
        aggregate_score=aggregate,
        category_scores=category_scores,
    )

    logger.info(
        "Run %s complete: aggregate=%.3f category=%s",
        run_id,
        aggregate,
        category_scores,
    )

    # Persist to Firestore (non-blocking)
    _persist_run(run)

    return run


def _persist_run(run: RunResult) -> None:
    """Persist a RunResult to Firestore (best-effort)."""
    try:
        from adk_quality_lab.observability.firestore_writer import write_run_result  # noqa: PLC0415

        write_run_result(run.run_id, run.model_dump())
    except Exception as exc:  # noqa: BLE001
        logger.debug("Firestore persist skipped (set up GCP project to enable): %s", exc)
