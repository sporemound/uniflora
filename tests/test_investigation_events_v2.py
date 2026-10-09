from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from uniflora.content.v2 import (
    V2InvestigationPack,
    load_investigation_pack,
)
from uniflora.content.v2.investigation_schema import (
    V2LocationDefinition,
)
from uniflora.engine.v2 import (
    V2ActionPerformedEvent,
    V2AssignRoleCommand,
    V2CompletePositionCommand,
    V2ConfirmAssessmentCommand,
    V2DraftAssessmentCommand,
    V2EvidenceExaminedEvent,
    V2ExamineEvidenceCommand,
    V2InvestigationInitializedEvent,
    V2MovePlayerCommand,
    V2PerformActionCommand,
    V2PlayerMovedEvent,
    V2PositionCompletedEvent,
    V2ReleaseRoleCommand,
    V2ReplayError,
    V2RoleAssignedEvent,
    V2RoleReleasedEvent,
    execute_command,
    initialize_event_stream,
    replay_events,
    verify_event_stream,
)

FIXTURE_PATH = (
    Path(__file__).parent / "fixtures" / "v2" / "boundary_array_investigation" / "pack.yaml"
)


@pytest.fixture
def pack() -> V2InvestigationPack:
    return load_investigation_pack(FIXTURE_PATH)


def _accepted(pack, stream, command):
    result = execute_command(pack, stream, command)

    assert result.accepted is True
    assert result.event is not None

    return result.stream


def _collect_boundary_evidence(pack, stream):
    for evidence_id in ("optical_record", "radio_return"):
        stream = _accepted(
            pack,
            stream,
            V2ExamineEvidenceCommand(
                player_id="player_a",
                evidence_id=evidence_id,
            ),
        )

    for action_id in (
        "inspect_optical_record",
        "inspect_radio_return",
        "compare_optical_radio_timing",
    ):
        stream = _accepted(
            pack,
            stream,
            V2PerformActionCommand(
                player_id="player_a",
                action_id=action_id,
            ),
        )

    stream = _accepted(
        pack,
        stream,
        V2AssignRoleCommand(
            player_id="player_a",
            role_id="protocol_auditor",
        ),
    )
    stream = _accepted(
        pack,
        stream,
        V2PerformActionCommand(
            player_id="player_a",
            action_id="request_weather_record",
        ),
    )
    stream = _accepted(
        pack,
        stream,
        V2ReleaseRoleCommand(player_id="player_a"),
    )
    stream = _accepted(
        pack,
        stream,
        V2ExamineEvidenceCommand(
            player_id="player_a",
            evidence_id="weather_record",
        ),
    )

    for action_id in (
        "test_atmospheric_propagation",
        "document_upper_atmosphere_gap",
    ):
        stream = _accepted(
            pack,
            stream,
            V2PerformActionCommand(
                player_id="player_a",
                action_id=action_id,
            ),
        )

    return stream


def _assessment_command() -> V2DraftAssessmentCommand:
    return V2DraftAssessmentCommand(
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


def test_initialization_event_replays_exact_state(
    pack: V2InvestigationPack,
) -> None:
    stream = initialize_event_stream(
        pack,
        ["player_a", "player_b"],
        stream_id="boundary_session",
    )

    assert len(stream.events) == 1
    assert isinstance(
        stream.events[0],
        V2InvestigationInitializedEvent,
    )
    assert stream.events[0].sequence == 0
    assert stream.state.revision == 0
    assert replay_events(stream.events) == stream.state
    assert verify_event_stream(stream) == stream.state


def test_rejected_command_does_not_append_event(
    pack: V2InvestigationPack,
) -> None:
    stream = initialize_event_stream(
        pack,
        ["player_a"],
        stream_id="boundary_session",
    )

    result = execute_command(
        pack,
        stream,
        V2AssignRoleCommand(
            player_id="player_a",
            role_id="missing_role",
        ),
    )

    assert result.accepted is False
    assert result.code == "unknown_role"
    assert result.event is None
    assert result.stream is stream
    assert len(stream.events) == 1


def test_role_events_are_append_only_and_replayable(
    pack: V2InvestigationPack,
) -> None:
    stream = initialize_event_stream(
        pack,
        ["player_a"],
        stream_id="boundary_session",
    )
    stream = _accepted(
        pack,
        stream,
        V2AssignRoleCommand(
            player_id="player_a",
            role_id="instrument_operator",
        ),
    )
    stream = _accepted(
        pack,
        stream,
        V2ReleaseRoleCommand(player_id="player_a"),
    )

    assert isinstance(stream.events[1], V2RoleAssignedEvent)
    assert isinstance(stream.events[2], V2RoleReleasedEvent)
    assert stream.events[2].role_id == "instrument_operator"
    assert stream.state.revision == 2
    assert replay_events(stream.events) == stream.state


def test_player_movement_is_recorded_with_origin_and_destination(
    pack: V2InvestigationPack,
) -> None:
    remote = V2LocationDefinition(
        id="remote_archive",
        name="Remote Archive",
        description="A second synthetic location used for replay testing.",
    )
    position = pack.positions[0].model_copy(
        update={
            "initially_available_location_ids": (
                "boundary_array",
                "remote_archive",
            )
        }
    )
    extended_pack = pack.model_copy(
        update={
            "locations": pack.locations + (remote,),
            "positions": (position,),
        }
    )
    stream = initialize_event_stream(
        extended_pack,
        ["player_a"],
        stream_id="movement_session",
    )

    result = execute_command(
        extended_pack,
        stream,
        V2MovePlayerCommand(
            player_id="player_a",
            location_id="remote_archive",
        ),
    )

    assert result.accepted is True
    assert isinstance(result.event, V2PlayerMovedEvent)
    assert result.event.from_location_id == "boundary_array"
    assert result.event.to_location_id == "remote_archive"
    assert replay_events(result.stream.events) == result.stream.state


def test_action_event_records_only_new_effects(
    pack: V2InvestigationPack,
) -> None:
    stream = initialize_event_stream(
        pack,
        ["player_a"],
        stream_id="boundary_session",
    )
    stream = _accepted(
        pack,
        stream,
        V2ExamineEvidenceCommand(
            player_id="player_a",
            evidence_id="optical_record",
        ),
    )
    result = execute_command(
        pack,
        stream,
        V2PerformActionCommand(
            player_id="player_a",
            action_id="inspect_optical_record",
        ),
    )

    assert result.accepted is True
    assert isinstance(result.stream.events[1], V2EvidenceExaminedEvent)
    assert isinstance(result.event, V2ActionPerformedEvent)
    assert result.event.action_id == "inspect_optical_record"
    assert result.event.unlocked_evidence_ids == set()
    assert replay_events(result.stream.events) == result.stream.state


def test_weather_action_event_records_unlocked_evidence(
    pack: V2InvestigationPack,
) -> None:
    stream = initialize_event_stream(
        pack,
        ["player_a"],
        stream_id="boundary_session",
    )
    stream = _accepted(
        pack,
        stream,
        V2AssignRoleCommand(
            player_id="player_a",
            role_id="protocol_auditor",
        ),
    )
    result = execute_command(
        pack,
        stream,
        V2PerformActionCommand(
            player_id="player_a",
            action_id="request_weather_record",
        ),
    )

    assert result.accepted is True
    assert isinstance(result.event, V2ActionPerformedEvent)
    assert result.event.unlocked_evidence_ids == {"weather_record"}
    assert replay_events(result.stream.events) == result.stream.state


def test_assessment_draft_and_confirmation_replay(
    pack: V2InvestigationPack,
) -> None:
    stream = initialize_event_stream(
        pack,
        ["player_a", "player_b"],
        stream_id="assessment_session",
    )
    stream = _collect_boundary_evidence(pack, stream)
    stream = _accepted(pack, stream, _assessment_command())
    stream = _accepted(
        pack,
        stream,
        V2ConfirmAssessmentCommand(
            player_id="player_b",
            assessment_id="boundary_assessment",
        ),
    )

    assessment = stream.state.get_assessment("boundary_assessment")

    assert assessment is not None
    assert assessment.status == "confirmed"
    assert assessment.confirmed_by_player_ids == {"player_b"}
    assert replay_events(stream.events) == stream.state


def test_position_completion_event_records_released_roles(
    pack: V2InvestigationPack,
) -> None:
    stream = initialize_event_stream(
        pack,
        ["player_a", "player_b"],
        stream_id="completion_session",
    )
    stream = _collect_boundary_evidence(pack, stream)
    stream = _accepted(
        pack,
        stream,
        V2AssignRoleCommand(
            player_id="player_b",
            role_id="instrument_operator",
        ),
    )
    stream = _accepted(pack, stream, _assessment_command())
    stream = _accepted(
        pack,
        stream,
        V2ConfirmAssessmentCommand(
            player_id="player_b",
            assessment_id="boundary_assessment",
        ),
    )
    result = execute_command(
        pack,
        stream,
        V2CompletePositionCommand(
            player_id="player_b",
            assessment_id="boundary_assessment",
        ),
    )

    assert result.accepted is True
    assert isinstance(result.event, V2PositionCompletedEvent)
    assert tuple(
        (released.player_id, released.role_id) for released in result.event.released_roles
    ) == (("player_b", "instrument_operator"),)
    assert replay_events(result.stream.events) == result.stream.state

    player_b = result.stream.state.get_player("player_b")

    assert player_b is not None
    assert player_b.active_role_id is None


def test_replay_rejects_sequence_gap(
    pack: V2InvestigationPack,
) -> None:
    stream = initialize_event_stream(
        pack,
        ["player_a"],
        stream_id="boundary_session",
    )
    stream = _accepted(
        pack,
        stream,
        V2AssignRoleCommand(
            player_id="player_a",
            role_id="instrument_operator",
        ),
    )
    broken_event = replace(stream.events[1], sequence=2)

    with pytest.raises(V2ReplayError, match="expected event sequence 1"):
        replay_events((stream.events[0], broken_event))


def test_replay_rejects_mixed_stream_ids(
    pack: V2InvestigationPack,
) -> None:
    stream = initialize_event_stream(
        pack,
        ["player_a"],
        stream_id="boundary_session",
    )
    stream = _accepted(
        pack,
        stream,
        V2AssignRoleCommand(
            player_id="player_a",
            role_id="instrument_operator",
        ),
    )
    broken_event = replace(stream.events[1], stream_id="other_session")

    with pytest.raises(V2ReplayError, match="same stream ID"):
        replay_events((stream.events[0], broken_event))
