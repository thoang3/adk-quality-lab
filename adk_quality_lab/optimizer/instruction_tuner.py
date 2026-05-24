"""Core instruction tuner: the Observe → Propose → Verify optimization loop.

Implements the algorithm from the challenge doc §5.3 with:
- Failure clustering (sentence-transformers + HDBSCAN)
- Meta-prompt proposer (gemini-2.5-pro via Vertex AI)
- No-regression acceptance gate (per-category, 1pp threshold)
- History tracking to suppress oscillation
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from typing import Any

from adk_quality_lab.datasets.schema import EvalCase, RaterResult

logger = logging.getLogger(__name__)


@dataclass
class Snapshot:
    """One accepted iteration of the tuning loop."""

    iteration: int
    instruction: str
    score: float
    category_scores: dict[str, float]
    run_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    accepted: bool = True
    rationale: str = ""


@dataclass
class TuningResult:
    """Final output of a tune_instruction() run."""

    final_instruction: str
    baseline_score: float
    final_score: float
    history: list[Snapshot]
    surface: str
    category_scores_final: dict[str, float]

    @property
    def delta(self) -> float:
        return self.final_score - self.baseline_score

    @property
    def converged(self) -> bool:
        return len(self.history) > 1 and self.history[-1].score == self.history[-2].score


# ---------------------------------------------------------------------------
# Scoring helper
# ---------------------------------------------------------------------------


def _compute_scores(
    results: list[RaterResult],
    target_categories: list[str],
) -> tuple[float, dict[str, float]]:
    """Compute aggregate and per-category pass rates."""
    all_scores = [r.score for r in results]
    aggregate = sum(all_scores) / len(all_scores) if all_scores else 0.0

    category_scores: dict[str, float] = {}
    for cat in ("F1", "F2"):
        cat_results = [r for r in results if r.case_id.startswith(cat.lower())]
        if cat_results:
            category_scores[cat] = sum(r.score for r in cat_results) / len(cat_results)

    return aggregate, category_scores


def _no_regression(
    baseline_scores: dict[str, float],
    candidate_scores: dict[str, float],
    threshold_pp: float,
) -> bool:
    """Return True if no per-category regression exceeds threshold_pp."""
    for cat, base in baseline_scores.items():
        cand = candidate_scores.get(cat, base)
        if base - cand > threshold_pp:
            logger.info(
                "Regression detected on %s: %.3f → %.3f (Δ=%.3f > %.3f threshold)",
                cat,
                base,
                cand,
                base - cand,
                threshold_pp,
            )
            return False
    return True


# ---------------------------------------------------------------------------
# Main tuning loop
# ---------------------------------------------------------------------------


def tune_instruction(
    base_instruction: str,
    eval_set: list[EvalCase],
    run_eval_fn: Any,  # Callable[[str, list[EvalCase]], list[RaterResult]]
    target_categories: list[str] | None = None,
    surface: str = "planning_agent",
    max_iters: int = 20,
    min_delta: float = 0.02,
    per_category_regression_pp: float = 0.01,
    k_candidates: int = 5,
) -> TuningResult:
    """Run the instruction tuning loop.

    Args:
        base_instruction: Starting instruction text.
        eval_set: Cases to evaluate on.
        run_eval_fn: Callable(instruction, cases) → list[RaterResult].
                     Runs the agent with the given instruction and returns scored results.
        target_categories: Filter eval to these categories (e.g. ['F1', 'F2']).
        surface: Which agent surface is being tuned.
        max_iters: Maximum optimization iterations.
        min_delta: Minimum aggregate improvement required to accept a candidate.
        per_category_regression_pp: Per-category regression tolerance (1pp = 0.01).
        k_candidates: Number of candidates to propose per iteration.

    Returns:
        TuningResult with the best instruction and full history.
    """
    from adk_quality_lab.optimizer.cluster import cluster_failures
    from adk_quality_lab.optimizer.meta_prompt import propose_edits

    if target_categories:
        eval_subset = [c for c in eval_set if c.category in target_categories]
    else:
        eval_subset = eval_set

    logger.info("Starting tuning on surface=%s with %d cases", surface, len(eval_subset))

    # Baseline evaluation
    baseline_results = run_eval_fn(base_instruction, eval_subset)
    baseline_score, baseline_cat_scores = _compute_scores(baseline_results, target_categories or [])
    logger.info("Baseline: aggregate=%.3f  category=%s", baseline_score, baseline_cat_scores)

    history: list[Snapshot] = [
        Snapshot(
            iteration=0,
            instruction=base_instruction,
            score=baseline_score,
            category_scores=baseline_cat_scores,
        )
    ]
    current_instruction = base_instruction
    current_score = baseline_score
    current_cat_scores = baseline_cat_scores

    for i in range(1, max_iters + 1):
        logger.info("Iteration %d/%d", i, max_iters)

        # 1. Identify failing cases
        failing_cases = [
            c
            for c, r in zip(eval_subset, baseline_results, strict=False)
            if hasattr(r, "passed") and not r.passed
        ]
        failing_results = [r for r in baseline_results if not r.passed]
        clusters = cluster_failures(failing_cases, failing_results)

        if not clusters:
            logger.info("No failing cases — converged after %d iterations", i - 1)
            break

        # 2. Propose K candidate edits
        history_dicts = [
            {"score": s.score, "rationale": s.rationale, "accepted": s.accepted}
            for s in history
        ]
        candidates = propose_edits(
            current_instruction,
            clusters,
            surface=surface,
            k=k_candidates,
            history=history_dicts,
        )

        # 3. Score each candidate
        best_candidate = current_instruction
        best_score = current_score
        best_cat_scores = current_cat_scores

        for candidate in candidates:
            results = run_eval_fn(candidate, eval_subset)
            score, cat_scores = _compute_scores(results, target_categories or [])
            logger.info("  Candidate score=%.3f  cat=%s", score, cat_scores)
            if score > best_score:
                best_score = score
                best_candidate = candidate
                best_cat_scores = cat_scores

        # 4. Accept gate: min_delta AND no per-category regression
        delta = best_score - current_score
        if (
            delta >= min_delta
            and _no_regression(current_cat_scores, best_cat_scores, per_category_regression_pp)
        ):
            logger.info(
                "Accepted: Δ=%.3f → aggregate=%.3f", delta, best_score
            )
            current_instruction = best_candidate
            current_score = best_score
            current_cat_scores = best_cat_scores
            history.append(
                Snapshot(
                    iteration=i,
                    instruction=current_instruction,
                    score=current_score,
                    category_scores=current_cat_scores,
                    accepted=True,
                    rationale=f"Δ={delta:.3f}",
                )
            )
        else:
            logger.info(
                "Rejected: Δ=%.3f < min_delta=%.3f or regression detected", delta, min_delta
            )
            history.append(
                Snapshot(
                    iteration=i,
                    instruction=best_candidate,
                    score=best_score,
                    category_scores=best_cat_scores,
                    accepted=False,
                    rationale=f"Δ={delta:.3f} < threshold or regression",
                )
            )
            break  # converged or stuck

    return TuningResult(
        final_instruction=current_instruction,
        baseline_score=baseline_score,
        final_score=current_score,
        history=history,
        surface=surface,
        category_scores_final=current_cat_scores,
    )
