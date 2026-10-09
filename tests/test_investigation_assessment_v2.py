from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from uniflora.content.v2 import (
    V2InvestigationContentError,
    V2InvestigationPack,
    load_investigation_pack,
)
from uniflora.engine.v2 import (
    assign_role,
    complete_position,
    confirm_assessment,
    draft_assessment,
    examine_evidence,
    initialize_investigation,
    perform_action,
    release_role,
)
from uniflora.engine.v2.state import V2InvestigationState

FIXTURE_PATH = (
    Path(__file__).parent / "fixtures" / "v2" / "boundary_array_investigation" / "pack.yaml"
)


@pytest.fixture
def pack() -> V2InvestigationPack:
    return load_investigation_pack(FIXTURE_PATH)


def _fixture_payload() -> dict[str, Any]:
    payload = yaml.safe_load(FIXTURE_PATH.read_text(encoding="utf-8"))

    assert isinstance(payload, dict)

    return payload


def _write_pack(
    tmp_path: Path,
    payload: dict[str, Any],
) -> Path:
    path = tmp_path / "pack.yaml"
    path.write_text(
        yaml.safe_dump(payload, sort_keys=False),
        encoding="utf-8",
    )
    return path


def _complete_boundary_collection(
    pack: V2InvestigationPack,
) -> V2InvestigationState:
    state = initialize_investigation(pack, ["player_a", "player_b"])

    for evidence_id in ("optical_record", "radio_return"):
        result = examine_evidence(
            pack,
            state,
            player_id="player_a",
            evidence_id=evidence_id,
        )
        assert result.accepted is True
        state = result.state

    for action_id in (
        "inspect_optical_record",
        "inspect_radio_return",
        "compare_optical_radio_timing",
    ):
        result = perform_action(
            pack,
            state,
            player_id="player_a",
            action_id=action_id,
        )
        assert result.accepted is True
        state = result.state

    result = assign_role(
        pack,
        state,
        player_id="player_a",
        role_id="protocol_auditor",
    )
    assert result.accepted is True
    state = result.state

    result = perform_action(
        pack,
        state,
        player_id="player_a",
        action_id="request_weather_record",
    )
    assert result.accepted is True
    state = result.state

    result = release_role(
        state,
        player_id="player_a",
    )
    assert result.accepted is True
    state = result.state

    result = examine_evidence(
        pack,
        state,
        player_id="player_a",
        evidence_id="weather_record",
    )
    assert result.accepted is True
    state = result.state

    for action_id in (
        "test_atmospheric_propagation",
        "document_upper_atmosphere_gap",
    ):
        result = perform_action(
            pack,
            state,
            player_id="player_a",
            action_id=action_id,
        )
        assert result.accepted is True
        state = result.state

    return state


def _draft_complete_assessment(
    pack: V2InvestigationPack,
    state: V2InvestigationState,
):
    return draft_assessment(
        pack,
        state,
        player_id="player_a",
        assessment_id="boundary_assessment",
        statement=(
            "The optical, radio, and local environmental records converge on "
            "one event, but the timing conflict remains unresolved."
        ),
        evidence_ids=(
            "optical_record",
            "radio_return",
            "weather_record",
        ),
        tested_ordinary_explanation_ids=("atmospheric_propagation",),
        preserved_contradiction_ids=("optical_radio_timing_offset",),
        documented_information_gap_ids=("upper_atmosphere_conditions",),
        confidence="moderate",
        next_collection=("Retrieve independently calibrated upper-atmosphere measurements."),
        minority_view=(
            "A processing artifact remains possible until the receiver "
            "diagnostic is independently reviewed."
        ),
    )


def test_loads_position_completion_rules(
    pack: V2InvestigationPack,
) -> None:
    completion = pack.positions[0].completion

    assert completion.minimum_examined_source_classes == 3
    assert completion.minimum_confirmation_count == 1
    assert completion.required_completed_action_ids == (
        "compare_optical_radio_timing",
        "test_atmospheric_propagation",
        "document_upper_atmosphere_gap",
    )


def test_rejects_completion_rule_with_unknown_action(
    tmp_path: Path,
) -> None:
    payload = _fixture_payload()
    payload["positions"][0]["completion"]["required_completed_action_ids"] = ["missing_action"]

    path = _write_pack(tmp_path, payload)

    with pytest.raises(
        V2InvestigationContentError,
        match="completion requires unknown actions",
    ):
        load_investigation_pack(path)


def test_rejects_impossible_source_class_requirement(
    tmp_path: Path,
) -> None:
    payload = _fixture_payload()
    payload["positions"][0]["completion"]["minimum_examined_source_classes"] = 99

    path = _write_pack(tmp_path, payload)

    with pytest.raises(
        V2InvestigationContentError,
        match="but the pack defines only",
    ):
        load_investigation_pack(path)


def test_rejects_assessment_that_cites_unexamined_evidence(
    pack: V2InvestigationPack,
) -> None:
    state = initialize_investigation(pack, ["player_a", "player_b"])

    result = draft_assessment(
        pack,
        state,
        player_id="player_a",
        assessment_id="premature_assessment",
        statement="The available records appear related.",
        evidence_ids=("optical_record",),
    )

    assert result.accepted is False
    assert result.code == "assessment_evidence_unexamined"
    assert result.state is state


def test_drafts_structured_assessment_without_mutating_original(
    pack: V2InvestigationPack,
) -> None:
    state = _complete_boundary_collection(pack)

    drafted = _draft_complete_assessment(pack, state)

    assert drafted.accepted is True
    assert drafted.code == "assessment_drafted"
    assert drafted.state is not state
    assert state.assessments == ()

    assessment = drafted.state.get_assessment("boundary_assessment")

    assert assessment is not None
    assert assessment.status == "draft"
    assert assessment.confidence == "moderate"
    assert assessment.evidence_ids == {
        "optical_record",
        "radio_return",
        "weather_record",
    }
    assert assessment.preserved_contradiction_ids == {"optical_radio_timing_offset"}


def test_assessment_author_cannot_confirm_own_draft(
    pack: V2InvestigationPack,
) -> None:
    state = _complete_boundary_collection(pack)
    drafted = _draft_complete_assessment(pack, state)

    confirmed = confirm_assessment(
        drafted.state,
        player_id="player_a",
        assessment_id="boundary_assessment",
    )

    assert confirmed.accepted is False
    assert confirmed.code == "author_cannot_confirm"
    assert confirmed.state is drafted.state


def test_second_participant_confirms_assessment(
    pack: V2InvestigationPack,
) -> None:
    state = _complete_boundary_collection(pack)
    drafted = _draft_complete_assessment(pack, state)

    confirmed = confirm_assessment(
        drafted.state,
        player_id="player_b",
        assessment_id="boundary_assessment",
    )

    assert confirmed.accepted is True
    assert confirmed.code == "assessment_confirmed"

    assessment = confirmed.state.get_assessment("boundary_assessment")

    assert assessment is not None
    assert assessment.status == "confirmed"
    assert assessment.confirmed_by_player_ids == {"player_b"}


def test_rejects_position_completion_before_assessment_confirmation(
    pack: V2InvestigationPack,
) -> None:
    state = _complete_boundary_collection(pack)
    drafted = _draft_complete_assessment(pack, state)

    completed = complete_position(
        pack,
        drafted.state,
        player_id="player_b",
        assessment_id="boundary_assessment",
    )

    assert completed.accepted is False
    assert completed.code == "assessment_not_confirmed"
    assert completed.state is drafted.state


def test_confirmed_assessment_completes_position_and_releases_roles(
    pack: V2InvestigationPack,
) -> None:
    state = _complete_boundary_collection(pack)

    assigned = assign_role(
        pack,
        state,
        player_id="player_b",
        role_id="instrument_operator",
    )
    assert assigned.accepted is True

    drafted = _draft_complete_assessment(pack, assigned.state)
    confirmed = confirm_assessment(
        drafted.state,
        player_id="player_b",
        assessment_id="boundary_assessment",
    )
    completed = complete_position(
        pack,
        confirmed.state,
        player_id="player_b",
        assessment_id="boundary_assessment",
    )

    assert completed.accepted is True
    assert completed.code == "position_completed"
    assert completed.state.completed_position_ids == {"boundary_event"}

    player_b = completed.state.get_player("player_b")

    assert player_b is not None
    assert player_b.active_role_id is None
