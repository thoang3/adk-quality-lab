"""Pydantic v2 schema for ADK Quality Lab evaluation cases and results."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Difficulty = Literal["easy", "medium", "hard"]
Category = Literal["F1", "F2"]


class EvalCase(BaseModel):
    """A single evaluation case for the ADK Quality Lab harness."""

    case_id: str
    """Unique identifier, e.g. 'f1_001'."""

    category: Category
    """'F1' (count hallucination) or 'F2' (tool-call groundedness)."""

    difficulty: Difficulty
    """'easy' | 'medium' | 'hard'."""

    query: str
    """Natural-language user query sent to the agent."""

    fixture_hash: str
    """SHA256 of canonical_query JSON → datasets/fixtures/flights/<hash>.json."""

    raters: list[str]
    """List of rater identifiers, e.g.
    ['deterministic.row_count_match', 'llm_judge.completeness'].
    """

    # F1-specific
    expected_flight_count: int | None = None
    """SerpAPI result count for this fixture (F1 only)."""

    # F2-specific
    expected_values: dict[str, str] | None = None
    """Verbatim values that must appear in agent response,
    e.g. {'carrier': 'AA', 'price': '1234.00'}.
    """

    # Search context (used to augment the query if it lacks a date)
    route: str | None = None
    """IATA route string, e.g. 'JFK-LHR'."""

    cabin: str | None = None
    """Cabin class, e.g. 'economy' | 'business'."""

    departure_date: str | None = None
    """ISO date string, e.g. '2026-06-07'."""

    # Range search fields (used by tail_flights.jsonl hard cases)
    start_date: str | None = None
    """ISO date of range start, e.g. '2026-07-01' (range cases only)."""

    end_date: str | None = None
    """ISO date of range end, e.g. '2026-07-07' (range cases only)."""

    search_type: str | None = None
    """'single' (default) or 'range' — drives multi-fixture merge in runner."""

    expected_baseline_behaviour: str | None = None
    """Human description of expected failure mode (tail cases)."""

    # Gold label (only present in datasets/gold/*.jsonl)
    gold_label: bool | None = None
    """True = pass, False = fail, None = unlabeled."""

    gold_label_rationale: str | None = None
    """Human rationale for the gold label."""


class RaterResult(BaseModel):
    """Result from a single rater on a single case."""

    case_id: str
    rater: str
    passed: bool
    score: float = Field(ge=0.0, le=1.0)
    detail: str | None = None


class RunResult(BaseModel):
    """Aggregate result for a full eval run."""

    run_id: str
    """UUID, persisted to BigQuery."""

    variant: Literal["baseline", "markdown", "json_block", "prompt_tuning_v1", "structured_output", "prompt_tuning_v2", "arch_fix"]

    surface: str | None = None
    """'root' | 'planning' | 'tools' | None."""

    iteration: int | None = None
    """Optimizer iteration number."""

    cases: list[RaterResult]

    aggregate_score: float

    category_scores: dict[Category, float]
