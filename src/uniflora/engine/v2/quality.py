"""Exact-arithmetic review scoring shared by legacy and strategic v2 play.

The strategic overhaul keeps these review semantics deterministic; stochastic
and strategic events may change the record being reviewed, never the rubric.
"""

from __future__ import annotations

from collections.abc import Iterable
from fractions import Fraction
from statistics import median
from typing import Literal, Protocol

V2AdaptationBand = Literal["corrective", "baseline", "advanced"]
V2ReviewSubjectKind = Literal["finding", "assessment"]


class V2ScoredReview(Protocol):
    evidence_support: int
    ordinary_alternatives: int
    contradictions_preserved: int
    confidence_calibration: int
    reproducibility: int


def validate_rubric_score(value: int, *, label: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 2:
        raise ValueError(f"{label} must be an integer from 0 through 2")


def review_dimension_values(review: V2ScoredReview) -> tuple[int, ...]:
    return (
        review.evidence_support,
        review.ordinary_alternatives,
        review.contradictions_preserved,
        review.confidence_calibration,
        review.reproducibility,
    )


def subject_result(reviews: Iterable[V2ScoredReview]) -> Fraction:
    recorded = tuple(reviews)
    if not recorded:
        raise ValueError("at least one independent review is required")
    dimensions = zip(
        *(review_dimension_values(review) for review in recorded),
        strict=True,
    )
    return sum(
        (Fraction(median(values)) for values in dimensions),
        start=Fraction(),
    )


def position_result(subject_results: Iterable[Fraction]) -> Fraction:
    recorded = tuple(subject_results)
    if not recorded:
        raise ValueError("at least one reviewed subject is required")
    return Fraction(median(recorded))


def cumulative_result(
    sealed_results: Iterable[tuple[int, Fraction]],
) -> Fraction:
    recorded = tuple(sealed_results)
    if not recorded:
        raise ValueError("at least one sealed position result is required")
    weighted_sum = sum(
        (score * ordinal for ordinal, score in recorded),
        start=Fraction(),
    )
    return weighted_sum / sum(ordinal for ordinal, _score in recorded)


def adaptation_band(score: Fraction) -> V2AdaptationBand:
    if score <= 5:
        return "corrective"
    if score <= 8:
        return "baseline"
    return "advanced"


__all__ = [
    "V2AdaptationBand",
    "V2ReviewSubjectKind",
    "adaptation_band",
    "cumulative_result",
    "position_result",
    "subject_result",
    "validate_rubric_score",
]
