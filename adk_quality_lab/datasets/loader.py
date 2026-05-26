"""JSONL dataset loader for ADK Quality Lab eval cases."""

from __future__ import annotations

import json
from pathlib import Path

from adk_quality_lab.datasets.schema import Category, EvalCase

# Default datasets directory (relative to package root)
_DATASETS_DIR = Path(__file__).parent.parent.parent / "datasets"


def load_cases(
    path: str | Path,
    category: Category | None = None,
) -> list[EvalCase]:
    """Load EvalCase records from a JSONL file.

    Args:
        path: Path to the .jsonl file.
        category: Optional filter — only return cases matching this category.

    Returns:
        List of EvalCase instances.
    """
    cases: list[EvalCase] = []
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            raw = json.loads(line)
            case = EvalCase.model_validate(raw)
            if category is None or case.category == category:
                cases.append(case)
    return cases


def load_all_cases(
    category: Category | None = None,
    include_adversarial: bool = False,
    include_tail: bool = False,
) -> list[EvalCase]:
    """Load cases from the canonical datasets directory.

    Loads f1_count_hallucination.jsonl and f2_groundedness.jsonl (and
    adversarial files when include_adversarial=True, tail_flights.jsonl
    when include_tail=True).

    Args:
        category: Optional filter by category.
        include_adversarial: Whether to include adversarial cases.
        include_tail: Whether to include hard tail cases (range search).

    Returns:
        Combined list of EvalCase instances.
    """
    files = [
        _DATASETS_DIR / "f1_count_hallucination.jsonl",
        _DATASETS_DIR / "f2_groundedness.jsonl",
    ]
    if include_adversarial:
        files += [
            _DATASETS_DIR / "f1_adversarial.jsonl",
            _DATASETS_DIR / "f2_adversarial.jsonl",
        ]
    if include_tail:
        tail_path = _DATASETS_DIR / "tail_flights.jsonl"
        if tail_path.exists():
            files.append(tail_path)

    all_cases: list[EvalCase] = []
    for path in files:
        if path.exists():
            all_cases.extend(load_cases(path, category=category))
    return all_cases


def load_smoke_cases(n: int = 30) -> list[EvalCase]:
    """Load a deterministic smoke subset (first n cases across F1+F2).

    Used in CI to keep the PR check under 5 minutes with no live API calls.
    """
    all_cases = load_all_cases()
    # Interleave F1 and F2 for balanced smoke coverage
    f1 = [c for c in all_cases if c.category == "F1"]
    f2 = [c for c in all_cases if c.category == "F2"]
    interleaved: list[EvalCase] = []
    for a, b in zip(f1, f2, strict=False):
        interleaved.extend([a, b])
    # Append remainder
    shorter, longer = (f1, f2) if len(f1) < len(f2) else (f2, f1)
    interleaved.extend(longer[len(shorter) :])
    return interleaved[:n]


def load_gold_cases(category: Category | None = None) -> list[EvalCase]:
    """Load hand-labeled gold cases from datasets/gold/."""
    gold_dir = _DATASETS_DIR / "gold"
    files = [gold_dir / "f1_gold.jsonl", gold_dir / "f2_gold.jsonl"]
    cases: list[EvalCase] = []
    for path in files:
        if path.exists():
            cases.extend(load_cases(path, category=category))
    return cases
