from __future__ import annotations

from dataclasses import replace
from fractions import Fraction

import pytest

from uniflora.content.v2 import load_missing_interior_pack
from uniflora.content.v2.investigation_schema import V2InvestigationPack
from uniflora.engine.v2.events import V2QualityReviewSubmittedEvent
from uniflora.engine.v2.kernel import (
    complete_position,
    initialize_investigation,
    submit_quality_review,
)
from uniflora.engine.v2.quality import (
    adaptation_band,
    cumulative_result,
    position_result,
    subject_result,
)
from uniflora.engine.v2.serialization import deserialize_event, serialize_event
from uniflora.engine.v2.state import (
    V2AssessmentState,
    V2QualityReviewState,
)


def _pack() -> V2InvestigationPack:
    variant = {
        "prologue": "A public presentation without a tier label.",
        "guidance": ["Use the resolved public mechanics."],
    }
    return V2InvestigationPack.model_validate(
        {
            "schema_version": 2,
            "pack": {
                "id": "quality_test",
                "title": "Quality Test",
                "content_version": "1",
                "initial_position_id": "position_one",
            },
            "locations": [
                {"id": "room_one", "name": "One", "description": "First room."},
                {"id": "room_two", "name": "Two", "description": "Second room."},
            ],
            "positions": [
                {
                    "id": "position_one",
                    "ordinal": 1,
                    "title": "One",
                    "focus_location_id": "room_one",
                    "next_position_id": "position_two",
                    "initially_available_location_ids": ["room_one"],
                    "fixed_opening": {
                        **variant,
                        "presentation_id": "position_one_fixed",
                    },
                },
                {
                    "id": "position_two",
                    "ordinal": 2,
                    "title": "Two",
                    "focus_location_id": "room_two",
                    "next_position_id": None,
                    "initially_available_location_ids": ["room_two"],
                    "adaptation": {
                        "corrective": {
                            **variant,
                            "presentation_id": "position_two_corrective",
                            "required_action_id": "guided_reconciliation",
                        },
                        "baseline": {
                            **variant,
                            "presentation_id": "position_two_baseline",
                        },
                        "advanced": {
                            **variant,
                            "presentation_id": "position_two_advanced",
                            "optional_action_ids": ["optional_sensitivity"],
                        },
                    },
                },
            ],
            "actions": [
                {
                    "id": "guided_reconciliation",
                    "title": "Guided reconciliation",
                    "description": "Required only on the resolved corrective path.",
                    "action_type": "compare",
                    "location_id": "room_two",
                },
                {
                    "id": "optional_sensitivity",
                    "title": "Optional sensitivity",
                    "description": "Optional and advanced only.",
                    "action_type": "compare",
                    "location_id": "room_two",
                },
            ],
            "endings": {
                band: {
                    "presentation_id": f"ending_{band}",
                    "prose": "The same core conclusion, differently constrained.",
                }
                for band in ("corrective", "baseline", "advanced")
            },
        }
    )


def _review(scores: tuple[int, int, int, int, int]) -> V2QualityReviewState:
    return V2QualityReviewState(
        subject_kind="assessment",
        subject_id="final",
        subject_revision=1,
        position_id="position_one",
        author_player_id="author",
        reviewer_player_id="reviewer",
        evidence_support=scores[0],
        ordinary_alternatives=scores[1],
        contradictions_preserved=scores[2],
        confidence_calibration=scores[3],
        reproducibility=scores[4],
        rationale="Exact-revision rationale.",
    )


def test_exact_medians_weighting_and_threshold_boundaries() -> None:
    low = _review((0, 1, 1, 2, 2))
    high = replace(
        low,
        reviewer_player_id="reviewer_two",
        evidence_support=2,
        ordinary_alternatives=2,
    )
    assert subject_result((low, high)) == Fraction(15, 2)
    assert position_result((Fraction(7), Fraction(8))) == Fraction(15, 2)
    assert cumulative_result(((1, Fraction(5)), (2, Fraction(10)))) == Fraction(25, 3)
    assert adaptation_band(Fraction(5)) == "corrective"
    assert adaptation_band(Fraction(6)) == "baseline"
    assert adaptation_band(Fraction(8)) == "baseline"
    assert adaptation_band(Fraction(9)) == "advanced"


def test_review_rejects_self_review_and_duplicate_exact_revision() -> None:
    state = initialize_investigation(_pack(), ("author", "reviewer"))
    state = replace(
        state,
        assessments=(
            V2AssessmentState(
                id="final",
                author_player_id="author",
                statement="A bounded conclusion.",
                status="confirmed",
                confirmed_by_player_ids=frozenset({"reviewer"}),
            ),
        ),
    )
    self_review = submit_quality_review(
        state,
        player_id="author",
        subject_kind="assessment",
        subject_id="final",
        subject_revision=1,
        evidence_support=1,
        ordinary_alternatives=1,
        contradictions_preserved=1,
        confidence_calibration=1,
        reproducibility=1,
        rationale="Not independent.",
    )
    assert not self_review.accepted
    assert self_review.code == "author_cannot_review"

    first = submit_quality_review(
        state,
        player_id="reviewer",
        subject_kind="assessment",
        subject_id="final",
        subject_revision=1,
        evidence_support=2,
        ordinary_alternatives=2,
        contradictions_preserved=2,
        confidence_calibration=2,
        reproducibility=1,
        rationale="Independent and reproducible.",
    )
    assert first.accepted
    duplicate = submit_quality_review(
        first.state,
        player_id="reviewer",
        subject_kind="assessment",
        subject_id="final",
        subject_revision=1,
        evidence_support=0,
        ordinary_alternatives=0,
        contradictions_preserved=0,
        confidence_calibration=0,
        reproducibility=0,
        rationale="Attempted rewrite.",
    )
    assert not duplicate.accepted
    assert duplicate.code == "quality_review_immutable"


@pytest.mark.parametrize(
    ("scores", "presentation_id"),
    [
        ((1, 1, 1, 1, 1), "position_two_corrective"),
        ((2, 1, 1, 1, 1), "position_two_baseline"),
        ((2, 2, 2, 2, 1), "position_two_advanced"),
    ],
)
def test_completion_seals_quality_and_resolves_next_opening(
    scores: tuple[int, int, int, int, int],
    presentation_id: str,
) -> None:
    pack = _pack()
    state = initialize_investigation(pack, ("author", "reviewer"))
    state = replace(
        state,
        assessments=(
            V2AssessmentState(
                id="final",
                author_player_id="author",
                statement="A bounded conclusion.",
                status="confirmed",
                confirmed_by_player_ids=frozenset({"reviewer"}),
            ),
        ),
        quality_reviews=(_review(scores),),
    )
    completed = complete_position(
        pack,
        state,
        player_id="reviewer",
        assessment_id="final",
    )
    assert completed.accepted
    assert completed.state.position_quality_seals[0].score == sum(scores)
    assert completed.state.adaptation_selections[0].presentation_id == presentation_id


def test_quality_review_event_round_trips_canonically() -> None:
    event = V2QualityReviewSubmittedEvent(
        stream_id="quality-stream",
        sequence=1,
        review=_review((2, 1, 2, 1, 2)),
    )
    assert deserialize_event(serialize_event(event)) == event


def test_canonical_pack_contains_all_fifteen_openings_and_three_endings() -> None:
    pack = load_missing_interior_pack()

    adaptive_positions = tuple(
        position
        for position in pack.positions
        if position.adaptation is not None
    )

    assert len(adaptive_positions) == 5

    presentations = {
        variant.presentation_id
        for position in adaptive_positions
        for variant in (
            position.adaptation.corrective,
            position.adaptation.baseline,
            position.adaptation.advanced,
        )
    }
    assert len(presentations) == 15
    assert all(
        position.adaptation is not None
        and position.adaptation.corrective.required_action_id is not None
        and position.adaptation.advanced.optional_action_ids
        for position in adaptive_positions
    )
    assert pack.endings is not None
    assert {
        pack.endings.corrective.presentation_id,
        pack.endings.baseline.presentation_id,
        pack.endings.advanced.presentation_id,
    } == {
        "missing_interior_corrective_ending",
        "missing_interior_baseline_ending",
        "missing_interior_advanced_ending",
    }
