from __future__ import annotations

from dataclasses import replace

from uniflora.content.v2 import load_missing_interior_pack
from uniflora.engine.v2 import (
    V2ActionPerformedEvent,
    V2AssignRoleCommand,
    V2BeginInvestigationCommand,
    V2ExamineEvidenceCommand,
    V2PassCapacityCommand,
    V2PerformActionCommand,
    V2ProposeActionCommand,
    V2ReleaseRoleCommand,
    V2SupportActionCommand,
    V2ViewStrategicBoardCommand,
    deserialize_event,
    deserialize_state,
    execute_command,
    initialize_event_stream,
    replay_events,
    serialize_event,
    serialize_state,
)
from uniflora.engine.v2.stochastic import V2SeededRandomSource

A = "discord:strategic-a"
B = "discord:strategic-b"
C = "discord:strategic-c"


class CountingRandom:
    def __init__(self) -> None:
        self.calls: list[tuple[int, str]] = []

    def randbelow(self, upper_bound: int, *, context: str) -> int:
        self.calls.append((upper_bound, context))
        return 0


def accepted(pack, stream, command, source):
    result = execute_command(pack, stream, command, random_source=source)
    assert result.accepted, (result.code, result.message)
    return result


def setup_position_one(seed: str = "strategic"):
    pack = load_missing_interior_pack()
    source = V2SeededRandomSource(seed)
    stream = initialize_event_stream(pack, (A, B, C), stream_id=f"stream-{seed}")
    stream = accepted(pack, stream, V2BeginInvestigationCommand(player_id=A), source).stream
    stream = accepted(
        pack, stream, V2ExamineEvidenceCommand(player_id=A, evidence_id="optical_record"), source
    ).stream
    stream = accepted(
        pack, stream, V2ExamineEvidenceCommand(player_id=A, evidence_id="radio_return"), source
    ).stream
    return pack, source, stream


def resolve_opening_round(pack, source, stream):
    stream = accepted(pack, stream, V2AssignRoleCommand(player_id=A, role_id="field_observer"), source).stream
    first = accepted(
        pack, stream, V2PerformActionCommand(player_id=A, action_id="inspect_optical_record"), source
    )
    stream = first.stream
    stream = accepted(pack, stream, V2AssignRoleCommand(player_id=B, role_id="atmospheric_analyst"), source).stream
    second = accepted(
        pack, stream, V2PerformActionCommand(player_id=B, action_id="request_weather_record"), source
    )
    stream = second.stream
    stream = accepted(pack, stream, V2AssignRoleCommand(player_id=C, role_id="instrument_operator"), source).stream
    third = accepted(
        pack, stream, V2PerformActionCommand(player_id=C, action_id="calibrate_radio_receiver"), source
    )
    return first, second, third


def test_board_preview_is_read_only_and_lazy_bootstrap_records_one_action_event() -> None:
    pack, source, stream = setup_position_one("preview")
    before = stream
    result = accepted(pack, stream, V2ViewStrategicBoardCommand(player_id=A), source)
    assert result.event is None
    assert result.stream == before
    assert result.stream.state.strategic_board is None
    assert "capacity 3/3" in result.message

    stream = accepted(pack, stream, V2AssignRoleCommand(player_id=A, role_id="field_observer"), source).stream
    action = accepted(
        pack, stream, V2PerformActionCommand(player_id=A, action_id="inspect_optical_record"), source
    )
    assert isinstance(action.event, V2ActionPerformedEvent)
    assert action.event.strategic_resolution is not None
    assert action.stream.state.serialization_schema == 4
    assert action.stream.state.strategic_board is not None
    assert action.stream.state.strategic_board.capacity_remaining == 2
    assert action.stream.state.campaign_tracks


def test_round_closure_records_exactly_one_natural_drift_and_replays() -> None:
    pack, source, stream = setup_position_one("round-close")
    first, second, third = resolve_opening_round(pack, source, stream)

    assert first.event.strategic_resolution.natural_drift is None
    assert second.event.strategic_resolution.natural_drift is None
    assert third.event.strategic_resolution.natural_drift is not None
    board = third.stream.state.strategic_board
    assert board is not None
    assert board.round_index == 2
    assert board.capacity_remaining == 3
    assert all(player.operation_count == 0 for player in board.players)
    assert replay_events(third.stream.events) == third.stream.state
    assert deserialize_state(serialize_state(third.stream.state)) == third.stream.state
    assert deserialize_event(serialize_event(third.event)) == third.event


def test_rejected_major_action_is_side_effect_free_and_draws_no_randomness() -> None:
    pack, _, stream = setup_position_one("rejected")
    source = CountingRandom()
    stream = accepted(pack, stream, V2AssignRoleCommand(player_id=A, role_id="signal_correlator"), source).stream
    before = stream
    result = execute_command(
        pack,
        stream,
        V2PerformActionCommand(player_id=A, action_id="run_synchronized_reacquisition"),
        random_source=source,
    )
    assert not result.accepted
    assert result.code == "major_action_requires_proposal"
    assert result.event is None
    assert result.stream == before
    assert source.calls == []


def test_major_operation_requires_independent_support_and_resolves_atomically() -> None:
    pack, source, stream = setup_position_one("proposal")
    _, _, third = resolve_opening_round(pack, source, stream)
    stream = third.stream
    assert stream.state.strategic_board is not None
    assert stream.state.strategic_board.round_index == 2

    stream = accepted(pack, stream, V2ReleaseRoleCommand(player_id=A), source).stream
    stream = accepted(pack, stream, V2AssignRoleCommand(player_id=A, role_id="signal_correlator"), source).stream
    proposal_result = accepted(
        pack,
        stream,
        V2ProposeActionCommand(player_id=A, action_id="run_synchronized_reacquisition"),
        source,
    )
    stream = proposal_result.stream
    proposal_id = proposal_result.event.proposal.proposal_id

    self_support = execute_command(
        pack, stream, V2SupportActionCommand(player_id=A, proposal_id=proposal_id), random_source=source
    )
    assert not self_support.accepted
    assert self_support.code == "self_support_forbidden"
    assert self_support.stream == stream

    resolved = accepted(
        pack, stream, V2SupportActionCommand(player_id=B, proposal_id=proposal_id), source
    )
    assert isinstance(resolved.event, V2ActionPerformedEvent)
    assert resolved.code == "major_action_resolved"
    assert resolved.event.action_id == "run_synchronized_reacquisition"
    assert resolved.event.stochastic_resolution is not None
    assert resolved.event.stochastic_resolution.state_advanced is True
    assert resolved.event.stochastic_resolution.transition_draw is not None
    strategic = resolved.event.strategic_resolution
    assert strategic is not None
    assert strategic.proposal_id == proposal_id
    assert strategic.supporter_player_ids == frozenset({B})
    assert resolved.stream.state.strategic_board.get_proposal(proposal_id) is None
    assert replay_events(resolved.stream.events) == resolved.stream.state


def test_legacy_schema_three_stream_bootstraps_without_retroactive_capacity_cost() -> None:
    pack = load_missing_interior_pack()
    legacy_pack = pack.model_copy(update={"schema_version": 2, "strategic": None})
    source = V2SeededRandomSource("legacy")
    stream = initialize_event_stream(legacy_pack, (A, B), stream_id="legacy-bootstrap")
    for command in (
        V2BeginInvestigationCommand(player_id=A),
        V2ExamineEvidenceCommand(player_id=A, evidence_id="optical_record"),
        V2ExamineEvidenceCommand(player_id=A, evidence_id="radio_return"),
        V2AssignRoleCommand(player_id=A, role_id="field_observer"),
        V2PerformActionCommand(player_id=A, action_id="inspect_optical_record"),
        V2ReleaseRoleCommand(player_id=A),
        V2AssignRoleCommand(player_id=A, role_id="instrument_operator"),
    ):
        stream = accepted(legacy_pack, stream, command, source).stream
    assert stream.state.strategic_board is None
    legacy_revision = stream.state.revision

    result = accepted(
        pack, stream, V2PerformActionCommand(player_id=A, action_id="calibrate_radio_receiver"), source
    )
    assert result.stream.state.revision == legacy_revision + 1
    assert result.event.strategic_resolution is not None
    board = result.stream.state.strategic_board
    assert board is not None
    assert board.capacity_remaining == 2
    assert board.get_player(A).operation_count == 1
    assert replay_events(result.stream.events) == result.stream.state
