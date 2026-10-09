from __future__ import annotations

import pytest

from uniflora.orientation import OrientationIntent, classify_orientation


@pytest.mark.parametrize(
    "message",
    (
        "Mara wakes up and gets their bearings.",
        "Mara: She wakes and tries to get her bearings.",
        "Mara looks around.",
        "Mara surveys the area.",
        "Mara tries to understand where she is.",
        "Mara takes in the surroundings.",
    ),
)
def test_generic_atmospheric_orientation_stays_local(message: str) -> None:
    assert classify_orientation(message) is OrientationIntent.LOCAL


@pytest.mark.parametrize(
    "message",
    (
        "Give us a recap.",
        "Please provide an orientation summary.",
        "Show the map overview.",
        "What is the confirmed public state?",
        "Please give an accessibility summary.",
    ),
)
def test_explicit_summary_requests_are_distinct(message: str) -> None:
    assert classify_orientation(message) is OrientationIntent.EXPLICIT_SUMMARY


@pytest.mark.parametrize(
    "message",
    (
        "She looks around for the damaged pathway.",
        "They survey the area for risk to the water reserve.",
        "He takes in the surroundings, focusing on northern capacity.",
    ),
)
def test_targeted_inquiry_is_not_reduced_to_generic_orientation(message: str) -> None:
    assert classify_orientation(message) is OrientationIntent.TARGETED_INQUIRY


def test_unrelated_action_is_not_orientation() -> None:
    assert classify_orientation("Mara waits quietly.") is OrientationIntent.NONE


def test_position_vocabulary_can_mark_a_specific_inquiry() -> None:
    assert (
        classify_orientation(
            "Mara looks around for spores.",
            additional_targeted_terms=frozenset({"spores"}),
        )
        is OrientationIntent.TARGETED_INQUIRY
    )
