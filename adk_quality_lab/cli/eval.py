"""CLI: run eval harness.

Usage:
    python -m adk_quality_lab.cli.eval --case-set=both --variant=baseline
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run ADK Quality Lab eval harness")
    parser.add_argument(
        "--case-set",
        choices=["f1", "f2", "both", "smoke", "gold", "tail"],
        default="smoke",
        help="Which case set to evaluate",
    )
    parser.add_argument(
        "--variant",
        choices=["baseline", "arch_fix"],
        default="baseline",
        help=(
            "Planning variants currently active for audit:\n"
            "  baseline — control variant\n"
            "  arch_fix — lazy-load/SSE-inject architecture (Condition D)\n"
            "All other historical planning variants are deferred for now."
        ),
    )
    parser.add_argument(
        "--example-dir",
        default="examples/travel-concierge",
        help="Path to vendored Travel Concierge example",
    )
    parser.add_argument(
        "--use-fixture-cache",
        action="store_true",
        default=True,
        help="Load SerpAPI responses from fixture cache (default: True)",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Write run result JSON to this file (optional)",
    )
    parser.add_argument(
        "--surface",
        choices=["root", "planning", "inspiration"],
        default="root",
        help="Which agent surface to target",
    )
    parser.add_argument(
        "--stub",
        action="store_true",
        default=False,
        help="Use stub agent (for CI / smoke tests without API keys)",
    )
    parser.add_argument(
        "--case-id",
        default=None,
        help="Run a single case by ID (e.g. f1_005). Overrides --case-set.",
    )
    args = parser.parse_args()

    from adk_quality_lab.datasets.loader import (
        load_all_cases,
        load_gold_cases,
        load_smoke_cases,
    )

    logger.info("Loading cases for case-set=%s", args.case_set)
    if args.case_set == "f1":
        cases = load_all_cases(category="F1")
    elif args.case_set == "f2":
        cases = load_all_cases(category="F2")
    elif args.case_set == "both":
        cases = load_all_cases()
    elif args.case_set == "smoke":
        cases = load_smoke_cases(n=30)
    elif args.case_set == "gold":
        cases = load_gold_cases()
    elif args.case_set == "tail":
        cases = load_all_cases(include_tail=True)
        cases = [c for c in cases if getattr(c, "search_type", None) == "range"]
    else:
        cases = []

    if args.case_id:
        cases = [c for c in cases if c.case_id == args.case_id]
        if not cases:
            # case_id may not be in the default case_set — load all and filter
            cases = [c for c in load_all_cases(include_tail=True) if c.case_id == args.case_id]
        if not cases:
            logger.error("case-id %r not found in any dataset", args.case_id)
            sys.exit(1)
        logger.info("Single-case mode: %s", args.case_id)

    logger.info("Loaded %d cases", len(cases))

    # Build agent function
    example_dir = Path(args.example_dir)
    sys.path.insert(0, str(example_dir))

    # Apply firebase stub before importing travel_concierge
    _patch_firebase(example_dir)

    from adk_quality_lab.runner import run_eval  # noqa: PLC0415
    from adk_quality_lab.tools.agent_runner import build_agent_fn  # noqa: PLC0415

    agent_fn = build_agent_fn(
        example_dir=example_dir,
        surface=args.surface,
        variant=args.variant,
        use_stub=args.stub,
    )

    run = run_eval(
        cases=cases,
        agent_fn=agent_fn,
        variant=args.variant,
        surface=args.surface,
        use_fixture_cache=args.use_fixture_cache,
    )

    logger.info(
        "Run %s complete: aggregate=%.3f category=%s",
        run.run_id,
        run.aggregate_score,
        run.category_scores,
    )

    if args.output:
        Path(args.output).write_text(json.dumps(run.model_dump(), indent=2))
        logger.info("Wrote run result to %s", args.output)

    # Print summary
    print(f"\n{'='*60}")
    print(f"Run ID:    {run.run_id}")
    print(f"Variant:   {run.variant}")
    print(f"Cases:     {len(run.cases)}")
    print(f"Aggregate: {run.aggregate_score:.3f}")
    for cat, score in run.category_scores.items():
        print(f"  {cat}:    {score:.3f}")
    print(f"{'='*60}\n")


def _patch_firebase(example_dir: Path) -> None:
    """Patch firebase stub before travel_concierge imports."""
    import sys
    wiring = example_dir / "adk_quality_lab_wiring"
    if str(wiring.parent) not in sys.path:
        sys.path.insert(0, str(wiring.parent))
    try:
        import adk_quality_lab_wiring.firebase_stub as stub  # noqa: PLC0415
        sys.modules["travel_concierge.shared_libraries.firebase"] = stub  # type: ignore[assignment]
    except ImportError:
        pass


if __name__ == "__main__":
    main()
