"""CLI: run optimizer on a single surface.

Usage:
    python -m adk_quality_lab.cli.optimize --surface=planning --max-iters=20
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run ADK Quality Lab optimizer")
    parser.add_argument(
        "--surface",
        choices=["root", "planning", "tools"],
        default="planning",
        help="Instruction surface to optimize",
    )
    parser.add_argument("--max-iters", type=int, default=20)
    parser.add_argument("--example-dir", default="examples/travel-concierge")
    parser.add_argument("--output", default=None, help="Write TuningResult JSON to this file")
    args = parser.parse_args()

    from adk_quality_lab.datasets.loader import load_all_cases
    from adk_quality_lab.optimizer.instruction_tuner import tune_instruction

    cases = load_all_cases()
    logger.info("Loaded %d cases for optimization", len(cases))

    # Read the current instruction for the chosen surface
    base_instruction = _read_instruction(Path(args.example_dir), args.surface)
    logger.info("Base instruction (%d chars): %s...", len(base_instruction), base_instruction[:80])

    # Stub eval function — replace with real ADK runner
    def run_eval_fn(instruction: str, eval_cases: list) -> list:  # type: ignore[type-arg]
        logger.warning("Using stub eval fn — wire to real agent for production optimization")
        from adk_quality_lab.datasets.schema import RaterResult
        return [
            RaterResult(
                case_id=c.case_id,
                rater="stub",
                passed=True,
                score=0.5,
                detail="stub result",
            )
            for c in eval_cases
        ]

    result = tune_instruction(
        base_instruction=base_instruction,
        eval_set=cases,
        run_eval_fn=run_eval_fn,
        surface=args.surface,
        max_iters=args.max_iters,
    )

    print(f"\n{'='*60}")
    print(f"Surface:   {result.surface}")
    print(f"Baseline:  {result.baseline_score:.3f}")
    print(f"Final:     {result.final_score:.3f}")
    print(f"Delta:     {result.delta:+.3f}")
    print(f"Iters:     {len(result.history) - 1}")
    print(f"{'='*60}\n")

    # Save tuned instruction
    output_dir = Path(args.example_dir) / "adk_quality_lab_wiring" / "tuned_prompts"
    output_dir.mkdir(parents=True, exist_ok=True)
    tuned_path = output_dir / f"{args.surface}_final.txt"
    tuned_path.write_text(result.final_instruction)
    logger.info("Saved tuned instruction to %s", tuned_path)

    if args.output:
        history_data = [
            {
                "iteration": s.iteration,
                "score": s.score,
                "accepted": s.accepted,
                "rationale": s.rationale,
            }
            for s in result.history
        ]
        Path(args.output).write_text(json.dumps({"history": history_data}, indent=2))


def _read_instruction(example_dir: Path, surface: str) -> str:
    """Read the current instruction for a surface (stub — reads from tuned_prompts if available)."""
    tuned = example_dir / "adk_quality_lab_wiring" / "tuned_prompts" / f"{surface}_current.txt"
    if tuned.exists():
        return tuned.read_text()
    return f"[placeholder: {surface} instruction — to be read from agent.py]"


if __name__ == "__main__":
    main()
