"""Cohen's κ computation for LLM-judge calibration.

Compares judge predictions against human gold labels.
Acceptance threshold: κ ≥ 0.7 before publishing any judge-derived number.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from adk_quality_lab.datasets.schema import EvalCase, RaterResult

logger = logging.getLogger(__name__)


@dataclass
class KappaResult:
    """Cohen's κ result for a single rater."""

    rater: str
    kappa: float
    n_total: int
    n_agreed: int
    po: float  # observed agreement
    pe: float  # expected agreement
    category: str | None = None

    @property
    def meets_threshold(self) -> bool:
        """Whether κ meets the publication threshold (≥ 0.70)."""
        return self.kappa >= 0.70

    def __str__(self) -> str:
        status = "✓ PASS" if self.meets_threshold else "✗ FAIL (below 0.70 threshold)"
        return (
            f"κ={self.kappa:.3f} [{status}] "
            f"(n={self.n_total}, Po={self.po:.3f}, Pe={self.pe:.3f}) "
            f"rater={self.rater}"
        )


def compute_kappa(
    gold_cases: list[EvalCase],
    rater_results: list[RaterResult],
    rater_id: str,
) -> KappaResult:
    """Compute Cohen's κ for a rater against human gold labels.

    Args:
        gold_cases: EvalCase instances with gold_label set.
        rater_results: RaterResult instances from the rater under evaluation.
        rater_id: The rater identifier to evaluate (e.g. 'llm_judge.truncation_disclosure').

    Returns:
        KappaResult with κ and supporting statistics.
    """
    # Build lookup: case_id → gold_label
    gold_map: dict[str, bool] = {
        c.case_id: c.gold_label
        for c in gold_cases
        if c.gold_label is not None
    }

    # Build lookup: case_id → rater prediction
    pred_map: dict[str, bool] = {
        r.case_id: r.passed
        for r in rater_results
        if r.rater == rater_id
    }

    # Intersect on case_ids with both labels
    common = set(gold_map.keys()) & set(pred_map.keys())
    if not common:
        logger.warning("No overlapping cases between gold and rater %s", rater_id)
        return KappaResult(
            rater=rater_id,
            kappa=0.0,
            n_total=0,
            n_agreed=0,
            po=0.0,
            pe=0.0,
        )

    n = len(common)
    agreed = sum(1 for cid in common if gold_map[cid] == pred_map[cid])
    po = agreed / n  # observed agreement

    # Expected agreement (Pe) for binary classification
    # P(both say True) + P(both say False)
    gold_pos = sum(1 for cid in common if gold_map[cid]) / n
    pred_pos = sum(1 for cid in common if pred_map[cid]) / n
    pe = (gold_pos * pred_pos) + ((1 - gold_pos) * (1 - pred_pos))

    if pe == 1.0:
        kappa = 0.0  # degenerate case
    else:
        kappa = (po - pe) / (1.0 - pe)

    return KappaResult(
        rater=rater_id,
        kappa=kappa,
        n_total=n,
        n_agreed=agreed,
        po=po,
        pe=pe,
    )


def compute_all_kappas(
    gold_cases: list[EvalCase],
    rater_results: list[RaterResult],
) -> dict[str, KappaResult]:
    """Compute κ for every unique rater present in rater_results."""
    rater_ids = {r.rater for r in rater_results}
    return {
        rater_id: compute_kappa(gold_cases, rater_results, rater_id)
        for rater_id in rater_ids
    }
