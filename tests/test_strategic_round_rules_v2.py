from __future__ import annotations

from uniflora.content.v2 import load_missing_interior_pack
from uniflora.engine.v2 import (
    V2AssignRoleCommand,
    V2BeginInvestigationCommand,
    V2ExamineEvidenceCommand,
    V2PerformActionCommand,
    V2ReleaseRoleCommand,
    execute_command,
    initialize_event_stream,
)
from uniflora.engine.v2.stochastic import V2SeededRandomSource

A = "discord:round-a"
B = "discord:round-b"


def _run(pack, stream, command, source):
    result = execute_command(pack, stream, command, random_source=source)
    assert result.accepted, (result.code, result.message)
    return result


def test_first_and_second_operation_costs_and_round_reset() -> None:
    pack = load_missing_interior_pack()
    source = V2SeededRandomSource("round-cost")
    stream = initialize_event_stream(pack, (A, B), stream_id="round-cost")
    for command in (
        V2BeginInvestigationCommand(player_id=A),
        V2ExamineEvidenceCommand(player_id=A, evidence_id="optical_record"),
        V2ExamineEvidenceCommand(player_id=A, evidence_id="radio_return"),
        V2AssignRoleCommand(player_id=A, role_id="field_observer"),
    ):
        stream = _run(pack, stream, command, source).stream

    first = _run(
        pack,
        stream,
        V2PerformActionCommand(player_id=A, action_id="inspect_optical_record"),
        source,
    )
    assert first.event.strategic_resolution.capacity_cost == 1
    board = first.stream.state.strategic_board
    assert board is not None
    assert board.capacity_remaining == 2
    assert board.coordination == 1

    stream = _run(pack, first.stream, V2ReleaseRoleCommand(player_id=A), source).stream
    stream = _run(
        pack,
        stream,
        V2AssignRoleCommand(player_id=A, role_id="signal_correlator"),
        source,
    ).stream
    second = _run(
        pack,
        stream,
        V2PerformActionCommand(player_id=A, action_id="compare_source_timing"),
        source,
    )
    assert second.event.strategic_resolution.capacity_cost == 2
    assert second.event.strategic_resolution.natural_drift is not None
    board = second.stream.state.strategic_board
    assert board is not None
    assert board.round_index == 2
    assert board.capacity_remaining == 3
    assert board.get_player(A).operation_count == 0


def test_distinct_first_actors_build_coordination_without_exceeding_bound() -> None:
    pack = load_missing_interior_pack()
    source = V2SeededRandomSource("round-coordination")
    stream = initialize_event_stream(pack, (A, B), stream_id="round-coordination")
    for command in (
        V2BeginInvestigationCommand(player_id=A),
        V2ExamineEvidenceCommand(player_id=A, evidence_id="optical_record"),
        V2AssignRoleCommand(player_id=A, role_id="field_observer"),
        V2AssignRoleCommand(player_id=B, role_id="atmospheric_analyst"),
        V2PerformActionCommand(player_id=A, action_id="inspect_optical_record"),
        V2PerformActionCommand(player_id=B, action_id="request_weather_record"),
    ):
        stream = _run(pack, stream, command, source).stream
    board = stream.state.strategic_board
    assert board is not None
    # Two distinct first operations contribute two points; the request action
    # also contributes one deterministic coordination point, capped at maximum.
    assert board.coordination == board.coordination_maximum == 3
