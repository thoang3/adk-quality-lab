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


def load_range_fixture(case: Any) -> dict[str, Any] | None:
    """Load and merge per-date fixtures for a range case.

    Reads the fixture index to resolve (origin, dest, cabin, date) → hash
    for each date in [start_date, end_date] inclusive, then merges all
    best_flights / other_flights into a single synthetic fixture payload.
    Each flight record gets an extra 'outbound_date' field.

    Returns None if no fixtures are found.
    """
    from datetime import date, timedelta

    index_path = _FIXTURES_DIR.parent / "index.json"
    if not index_path.exists():
        logger.warning("Fixture index not found: %s", index_path)
        return None

    index: dict[str, Any] = json.loads(index_path.read_text())

    # Build reverse lookup: (origin, dest, cabin, date) → full_hash
    route_parts = (case.route or "").split("-")
    if len(route_parts) != 2:
        logger.warning("Cannot parse route for range case %s: %r", case.case_id, case.route)
        return None
    origin, destination = route_parts
    cabin = case.cabin or "economy"

    start = date.fromisoformat(case.start_date)
    end = date.fromisoformat(case.end_date)

    # Build (origin, dest, cabin, date) → full_hash from index
    lookup: dict[str, str] = {}
    for full_hash, meta in index.items():
        if (
            meta.get("origin") == origin
            and meta.get("destination") == destination
            and meta.get("cabin") == cabin
        ):
            lookup[meta["departure_date"]] = full_hash

    all_best: list[dict] = []
    all_other: list[dict] = []
    base_params: dict[str, Any] = {}

    cur = start
    while cur <= end:
        dep_str = cur.strftime("%Y-%m-%d")
        full_hash = lookup.get(dep_str)
        if full_hash:
            fixture = load_fixture(full_hash)
            if fixture:
                if not base_params:
                    base_params = fixture.get("search_parameters", {})
                # Tag each flight with the outbound_date
                for flight in fixture.get("best_flights", []):
                    flight = dict(flight)
                    flight["outbound_date"] = dep_str
                    all_best.append(flight)
                for flight in fixture.get("other_flights", []):
                    flight = dict(flight)
                    flight["outbound_date"] = dep_str
                    all_other.append(flight)
            else:
                logger.warning("Fixture missing for %s %s-%s %s", dep_str, origin, destination, cabin)
        else:
            logger.warning("No index entry for %s %s-%s %s", dep_str, origin, destination, cabin)
        cur += timedelta(days=1)

    if not all_best and not all_other:
        return None

    # Build synthetic merged fixture
    merged_params = dict(base_params)
    merged_params["outbound_date"] = case.start_date  # nominal start date
    merged_params["end_date"] = case.end_date          # trip end date for template injection
    merged_params["_total_flights"] = len(all_best) + len(all_other)
    return {
        "search_parameters": merged_params,
        "best_flights": all_best,
        "other_flights": all_other,
        "_range_merged": True,
        "_date_range": f"{case.start_date}/{case.end_date}",
        "_total_days": (end - start).days + 1,
    }


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
        if getattr(case, "search_type", None) == "range":
            tool_payload = load_range_fixture(case)
            if tool_payload is None:
                logger.warning("Range fixture load failed for case %s", case.case_id)
        else:
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


_LOCAL_RESULTS_DIR = Path(__file__).parent.parent / "runs"


def _persist_run(run: RunResult) -> None:
    """Persist a RunResult to Firestore AND a local JSONL file (both best-effort)."""
    import json

    # ── Local JSONL ────────────────────────────────────────────────────────────
    try:
        _LOCAL_RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        result_file = _LOCAL_RESULTS_DIR / "runs.jsonl"
        with result_file.open("a") as fh:
            fh.write(json.dumps(run.model_dump()) + "\n")
        logger.info("Saved run %s to %s", run.run_id, result_file)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Local persist failed: %s", exc)

    # ── Firestore ──────────────────────────────────────────────────────────────
    try:
        from adk_quality_lab.observability.firestore_writer import write_run_result  # noqa: PLC0415

        write_run_result(run.run_id, run.model_dump())
    except Exception as exc:  # noqa: BLE001
        logger.debug("Firestore persist skipped (set up GCP project to enable): %s", exc)


def fetch_last_run(n: int = 1) -> list[dict]:
    """Return the last *n* RunResult dicts from the local JSONL file."""
    import json

    result_file = _LOCAL_RESULTS_DIR / "runs.jsonl"
    if not result_file.exists():
        return []
    lines = [l for l in result_file.read_text().splitlines() if l.strip()]
    return [json.loads(l) for l in lines[-n:]]
