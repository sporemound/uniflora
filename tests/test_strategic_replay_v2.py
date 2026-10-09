from __future__ import annotations

from uniflora.content.v2 import load_missing_interior_pack
from uniflora.engine.v2 import (
    V2AssignRoleCommand,
    V2BeginInvestigationCommand,
    V2ExamineEvidenceCommand,
    V2PerformActionCommand,
    deserialize_event,
    deserialize_state,
    execute_command,
    initialize_event_stream,
    replay_events,
    serialize_event,
    serialize_state,
    verify_event_stream,
)
from uniflora.engine.v2.stochastic import V2SeededRandomSource

A = "discord:replay-a"
B = "discord:replay-b"


def test_schema_four_action_and_natural_drift_replay_exactly() -> None:
    pack = load_missing_interior_pack()
    source = V2SeededRandomSource("schema-four-replay")
    stream = initialize_event_stream(pack, (A, B), stream_id="schema-four-replay")
    for command in (
        V2BeginInvestigationCommand(player_id=A),
        V2ExamineEvidenceCommand(player_id=A, evidence_id="optical_record"),
        V2AssignRoleCommand(player_id=A, role_id="field_observer"),
        V2PerformActionCommand(player_id=A, action_id="inspect_optical_record"),
        V2AssignRoleCommand(player_id=B, role_id="atmospheric_analyst"),
        V2PerformActionCommand(player_id=B, action_id="request_weather_record"),
        V2PerformActionCommand(player_id=A, action_id="inspect_optical_record"),
    ):
        result = execute_command(pack, stream, command, random_source=source)
        if not result.accepted and result.code == "action_already_completed":
            continue
        assert result.accepted, (result.code, result.message)
        stream = result.stream
    verify_event_stream(stream)
    assert replay_events(stream.events) == stream.state
    assert deserialize_state(serialize_state(stream.state)) == stream.state
    for event in stream.events:
        assert deserialize_event(serialize_event(event)) == event
