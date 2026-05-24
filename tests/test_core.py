"""Tests for adk_quality_lab package modules."""

from __future__ import annotations

import json
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Dataset schema + loader
# ---------------------------------------------------------------------------


def test_eval_case_schema() -> None:
    from adk_quality_lab.datasets.schema import EvalCase

    case = EvalCase(
        case_id="f1_001",
        category="F1",
        difficulty="easy",
        query="Find flights from SFO to LHR",
        fixture_hash="abc123",
        raters=["deterministic.row_count_match"],
    )
    assert case.case_id == "f1_001"
    assert case.category == "F1"
    assert case.gold_label is None


def test_eval_case_f2() -> None:
    from adk_quality_lab.datasets.schema import EvalCase

    case = EvalCase(
        case_id="f2_001",
        category="F2",
        difficulty="medium",
        query="Find cheapest JFK-LHR flight",
        fixture_hash="def456",
        raters=["groundedness.structured_value"],
        expected_values={"carrier": "AA", "price": "784.00"},
    )
    assert case.expected_values is not None
    assert case.expected_values["carrier"] == "AA"


def test_load_f1_cases() -> None:
    from adk_quality_lab.datasets.loader import load_cases

    path = Path(__file__).parent.parent / "datasets" / "f1_count_hallucination.jsonl"
    if not path.exists():
        pytest.skip("F1 dataset not yet captured")
    cases = load_cases(path)
    assert len(cases) > 0
    assert all(c.category == "F1" for c in cases)


def test_load_f2_cases() -> None:
    from adk_quality_lab.datasets.loader import load_cases

    path = Path(__file__).parent.parent / "datasets" / "f2_groundedness.jsonl"
    if not path.exists():
        pytest.skip("F2 dataset not yet captured")
    cases = load_cases(path)
    assert len(cases) > 0
    assert all(c.category == "F2" for c in cases)


def test_load_smoke_cases() -> None:
    from adk_quality_lab.datasets.loader import load_smoke_cases

    cases = load_smoke_cases(n=10)
    assert len(cases) <= 10


# ---------------------------------------------------------------------------
# Deterministic raters
# ---------------------------------------------------------------------------


def test_row_count_match_with_disclosure() -> None:
    from adk_quality_lab.datasets.schema import EvalCase
    from adk_quality_lab.raters.deterministic import row_count_match

    case = EvalCase(
        case_id="f1_test",
        category="F1",
        difficulty="easy",
        query="test",
        fixture_hash="h",
        raters=["deterministic.row_count_match"],
        expected_flight_count=118,
    )
    response = "Showing 20 of 118 — list truncated\n1. AA100\n2. BA200\n"
    result = row_count_match(case, response)
    assert result.passed is True
    assert result.rater == "deterministic.row_count_match"


def test_row_count_match_claim_mismatch() -> None:
    from adk_quality_lab.datasets.schema import EvalCase
    from adk_quality_lab.raters.deterministic import row_count_match

    case = EvalCase(
        case_id="f1_test2",
        category="F1",
        difficulty="easy",
        query="test",
        fixture_hash="h",
        raters=["deterministic.row_count_match"],
        expected_flight_count=95,
    )
    response = "I found 95 flights from JFK to LHR.\n1. AA100\n2. BA200\n"
    result = row_count_match(case, response)
    # Claimed 95 but expected_flight_count is 95 → should pass
    assert result.passed is True


def test_row_count_match_lie() -> None:
    from adk_quality_lab.datasets.schema import EvalCase
    from adk_quality_lab.raters.deterministic import row_count_match

    case = EvalCase(
        case_id="f1_test3",
        category="F1",
        difficulty="easy",
        query="test",
        fixture_hash="h",
        raters=["deterministic.row_count_match"],
        expected_flight_count=95,
    )
    response = "I found 118 flights from JFK to LHR.\n1. AA100\n2. BA200\n"
    result = row_count_match(case, response)
    # Claimed 118 but expected_flight_count is 95 → FAIL
    assert result.passed is False


def test_iata_membership_valid() -> None:
    from adk_quality_lab.datasets.schema import EvalCase
    from adk_quality_lab.raters.deterministic import iata_membership

    case = EvalCase(
        case_id="f2_test",
        category="F2",
        difficulty="easy",
        query="test",
        fixture_hash="h",
        raters=["deterministic.iata_membership"],
    )
    response = "I found AA100, BA284, DL402 for your journey."
    result = iata_membership(case, response)
    # AA, BA, DL are all valid IATA codes
    assert result.rater == "deterministic.iata_membership"


def test_numerical_equality_pass() -> None:
    from adk_quality_lab.datasets.schema import EvalCase
    from adk_quality_lab.raters.deterministic import numerical_equality

    case = EvalCase(
        case_id="f2_test2",
        category="F2",
        difficulty="easy",
        query="test",
        fixture_hash="h",
        raters=["deterministic.numerical_equality"],
        expected_values={"price": "784.00"},
    )
    response = "The cheapest flight is AA100 at $784.00 per person."
    result = numerical_equality(case, response)
    assert result.passed is True


def test_numerical_equality_fail_rounded() -> None:
    from adk_quality_lab.datasets.schema import EvalCase
    from adk_quality_lab.raters.deterministic import numerical_equality

    case = EvalCase(
        case_id="f2_test3",
        category="F2",
        difficulty="easy",
        query="test",
        fixture_hash="h",
        raters=["deterministic.numerical_equality"],
        expected_values={"price": "892.00"},
    )
    response = "The flight is $890 per person."  # Rounded — outside $1 tolerance
    result = numerical_equality(case, response)
    assert result.passed is False


# ---------------------------------------------------------------------------
# Groundedness rater
# ---------------------------------------------------------------------------


def test_structured_value_groundedness_pass() -> None:
    from adk_quality_lab.datasets.schema import EvalCase
    from adk_quality_lab.raters.groundedness import structured_value_groundedness

    case = EvalCase(
        case_id="f2_gnd",
        category="F2",
        difficulty="easy",
        query="test",
        fixture_hash="h",
        raters=["groundedness.structured_value"],
        expected_values={"carrier": "AA", "flight_number": "AA100", "price": "784.00"},
    )
    response = "The cheapest option is AA100 at $784.00."
    result = structured_value_groundedness(case, response)
    assert result.passed is True


def test_structured_value_groundedness_fail_wrong_flight() -> None:
    from adk_quality_lab.datasets.schema import EvalCase
    from adk_quality_lab.raters.groundedness import structured_value_groundedness

    case = EvalCase(
        case_id="f2_gnd2",
        category="F2",
        difficulty="easy",
        query="test",
        fixture_hash="h",
        raters=["groundedness.structured_value"],
        expected_values={"carrier": "BA", "flight_number": "BA284", "price": "892.00"},
    )
    # Tool returned BA284; agent mutated to BA285
    tool_payload = {
        "flights_search": [
            {
                "carrier": "BA",
                "flight_number": "BA284",
                "price_usd": 892.00,
                "origin": "JFK",
                "destination": "LHR",
            }
        ]
    }
    response = "I recommend BA285 at $892.00."
    result = structured_value_groundedness(case, response, tool_payload=tool_payload)
    assert result.passed is False


# ---------------------------------------------------------------------------
# Calibration
# ---------------------------------------------------------------------------


def test_bootstrap_ci_basic() -> None:
    from adk_quality_lab.calibration.bootstrap import bootstrap_ci

    scores = [1.0, 1.0, 0.0, 1.0, 0.0, 1.0, 1.0, 0.0, 1.0, 1.0]
    ci = bootstrap_ci(scores, n_resamples=100, seed=42)
    assert 0.0 <= ci.lower <= ci.mean <= ci.upper <= 1.0
    assert ci.n_samples == 10


def test_kappa_computation() -> None:
    from adk_quality_lab.calibration.kappa import compute_kappa
    from adk_quality_lab.datasets.schema import EvalCase, RaterResult

    gold = [
        EvalCase(
            case_id=f"f1_{i:03d}",
            category="F1",
            difficulty="easy",
            query="test",
            fixture_hash="h",
            raters=["llm_judge.truncation_disclosure"],
            gold_label=(i % 2 == 0),
        )
        for i in range(10)
    ]

    # Perfect agreement — κ should be 1.0
    rater_results = [
        RaterResult(
            case_id=f"f1_{i:03d}",
            rater="llm_judge.truncation_disclosure",
            passed=(i % 2 == 0),
            score=1.0 if (i % 2 == 0) else 0.0,
        )
        for i in range(10)
    ]

    result = compute_kappa(gold, rater_results, "llm_judge.truncation_disclosure")
    assert result.kappa == pytest.approx(1.0)
    assert result.meets_threshold is True
