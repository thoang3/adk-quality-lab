"""CLI: compute Cohen's kappa from gold labels vs latest rater results.

Usage:
    python -m adk_quality_lab.cli.kappa
"""

from __future__ import annotations

import logging

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


def main() -> None:
    from adk_quality_lab.calibration.kappa import compute_all_kappas
    from adk_quality_lab.datasets.loader import load_gold_cases

    gold = load_gold_cases()
    if not gold:
        logger.error("No gold cases found — run 'make eval CASE_SET=gold' first")
        return

    logger.info("Loaded %d gold cases", len(gold))

    # Try to load the latest rater results from the most recent eval run
    # For now, run deterministic raters against gold cases with placeholder responses
    from adk_quality_lab.datasets.schema import RaterResult

    # Placeholder: in production, load from BigQuery or Firestore
    rater_results: list[RaterResult] = []

    if not rater_results:
        logger.warning(
            "No rater results found. Run 'make eval CASE_SET=gold' to generate results, "
            "then re-run 'make kappa'."
        )
        print("\nTo compute κ:")
        print("  1. make eval CASE_SET=gold VARIANT=baseline")
        print("  2. make kappa")
        return

    kappas = compute_all_kappas(gold, rater_results)
    print(f"\n{'='*60}")
    print("Cohen's κ — LLM Judge Calibration Report")
    print(f"{'='*60}")
    for _rater_id, result in sorted(kappas.items()):
        print(f"  {result}")
    print(f"{'='*60}\n")

    failing = [r for r in kappas.values() if not r.meets_threshold]
    if failing:
        logger.warning(
            "%d rater(s) below κ=0.70 threshold — do NOT publish these numbers: %s",
            len(failing),
            [r.rater for r in failing],
        )
    else:
        logger.info("All raters meet κ ≥ 0.70 threshold — results publishable.")


if __name__ == "__main__":
    main()
