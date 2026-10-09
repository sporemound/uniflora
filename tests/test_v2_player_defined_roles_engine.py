from dataclasses import replace
from pathlib import Path

from uniflora.content.v2 import load_investigation_pack
from uniflora.engine.v2.event_stream import (
    execute_command,
    initialize_event_stream,
)
from uniflora.engine.v2.events import V2RoleAssignedEvent
from uniflora.engine.v2.integrity import seal_event_stream, verify_event_envelopes
from uniflora.engine.v2.kernel import perform_action
from uniflora.engine.v2.parsing import parse_user_command
from uniflora.engine.v2.reducer import replay_events
from uniflora.engine.v2.rendering import render_session_view
from uniflora.engine.v2.serialization import (
    deserialize_event,
    deserialize_state,
    serialize_event,
    serialize_state,
)
from uniflora.engine.v2.application import V2SessionView


PACK_PATH = (
    Path(__file__).parents[1]
    / "src"
    / "uniflora"
    / "content"
    / "v2"
    / "packs"
    / "missing_interior"
    / "pack.yaml"
)


def _pack():
    return load_investigation_pack(PACK_PATH)


def test_custom_role_runs_through_parser_kernel_event_and_replay() -> None:
    pack = _pack()
    stream = initialize_event_stream(
        pack,
        ("test:investigator-a",),
        stream_id="custom-role-test",
    )
    command = parse_user_command(
        'assign-role field_observer --name "Night Watcher" '
        '--description "Tracks the optical record"',
        player_id="test:investigator-a",
    )

    result = execute_command(pack, stream, command)

    assert result.accepted
    assert result.event is not None
    player = result.stream.state.get_player("test:investigator-a")
    assert player is not None
    assert player.active_role_id == "field_observer"
    assert player.active_role_display_name == "Night Watcher"
    assert player.active_role_description == "Tracks the optical record"
    assert replay_events(result.stream.events) == result.stream.state


def test_friendly_role_set_alias_and_role_clear() -> None:
    set_command = parse_user_command(
        'role set signal_correlator as "Night Radio Listener" '
        '--description "Compares timing"',
        player_id="test:investigator-a",
    )
    assert set_command.role_id == "signal_correlator"
    assert set_command.display_name == "Night Radio Listener"
    assert set_command.description == "Compares timing"

    clear_command = parse_user_command(
        "role clear",
        player_id="test:investigator-a",
    )
    assert type(clear_command).__name__ == "V2ReleaseRoleCommand"


def test_custom_role_still_uses_canonical_action_gate() -> None:
    pack = _pack()
    stream = initialize_event_stream(
        pack,
        ("test:investigator-a",),
        stream_id="canonical-gate-test",
    )
    command = parse_user_command(
        'assign-role field_observer --name "Sky Recorder"',
        player_id="test:investigator-a",
    )
    assigned = execute_command(pack, stream, command)
    assert assigned.accepted

    state = replace(
        assigned.stream.state,
        current_position_id="boundary_event",
        available_evidence_ids=(
            assigned.stream.state.available_evidence_ids | {"optical_record"}
        ),
        examined_evidence_ids=frozenset({"optical_record"}),
    )
    action = perform_action(
        pack,
        state,
        player_id="test:investigator-a",
        action_id="inspect_optical_record",
    )
    assert action.accepted


def test_custom_role_round_trips_state_event_and_hash_chain() -> None:
    pack = _pack()
    stream = initialize_event_stream(
        pack,
        ("test:investigator-a",),
        stream_id="serialization-test",
    )
    command = parse_user_command(
        'assign-role field_observer --name "Sky Recorder"',
        player_id="test:investigator-a",
    )
    assigned = execute_command(pack, stream, command)
    assert assigned.accepted
    assert assigned.event is not None

    assert deserialize_event(serialize_event(assigned.event)) == assigned.event
    assert deserialize_state(serialize_state(assigned.stream.state)) == assigned.stream.state

    envelopes = seal_event_stream(assigned.stream)
    assert verify_event_envelopes(envelopes) == assigned.stream.state


def test_legacy_role_event_serialization_remains_byte_compatible() -> None:
    event = V2RoleAssignedEvent(
        stream_id="legacy",
        sequence=1,
        player_id="test:investigator-a",
        role_id="field_observer",
    )
    assert serialize_event(event) == (
        b'{"event_type":"role_assigned","payload":{"player_id":'
        b'"test:investigator-a","role_id":"field_observer"},'
        b'"schema_version":2,"sequence":1,"stream_id":"legacy"}'
    )


def test_status_renders_public_title_and_canonical_function() -> None:
    pack = _pack()
    stream = initialize_event_stream(
        pack,
        ("test:investigator-a",),
        stream_id="render-test",
    )
    assigned = execute_command(
        pack,
        stream,
        parse_user_command(
            'assign-role field_observer --name "Sky Recorder"',
            player_id="test:investigator-a",
        ),
    )
    assert assigned.accepted
    response = render_session_view(
        V2SessionView(
            stream_id=assigned.stream.stream_id,
            state=assigned.stream.state,
            sequence=assigned.stream.state.revision,
            last_event_hash="0" * 64,
        )
    )
    assert "Sky Recorder (function: field_observer)" in response.to_text()


def test_mentions_are_rejected_without_state_change() -> None:
    pack = _pack()
    stream = initialize_event_stream(
        pack,
        ("test:investigator-a",),
        stream_id="moderation-test",
    )
    result = execute_command(
        pack,
        stream,
        parse_user_command(
            'assign-role field_observer --name "@everyone observer"',
            player_id="test:investigator-a",
        ),
    )
    assert not result.accepted
    assert result.code == "invalid_player_defined_role"
    assert result.stream == stream


def test_persistent_service_restores_custom_role(tmp_path: Path) -> None:
    from uniflora.engine.v2.application import V2PersistentInvestigationService
    from uniflora.engine.v2.persistence import V2SQLiteEventStore

    pack = _pack()
    with V2SQLiteEventStore(tmp_path / "custom-roles.sqlite3") as store:
        service = V2PersistentInvestigationService(pack, store)
        created = service.create_session("persistent-custom-role", ["player_a"])
        command = parse_user_command(
            'role set field_observer as "Sky Recorder" '
            '--description "Maintains the visible record"',
            player_id="player_a",
        )
        assigned = service.execute(
            "persistent-custom-role",
            command,
            expected_sequence=created.session.sequence,
        )
        assert assigned.accepted

        restored = service.load_session("persistent-custom-role")
        player = restored.state.get_player("player_a")
        assert player is not None
        assert player.active_role_id == "field_observer"
        assert player.active_role_display_name == "Sky Recorder"
        assert player.active_role_description == "Maintains the visible record"


def test_role_release_clears_player_defined_text() -> None:
    pack = _pack()
    stream = initialize_event_stream(
        pack,
        ("test:investigator-a",),
        stream_id="release-test",
    )
    assigned = execute_command(
        pack,
        stream,
        parse_user_command(
            'role set field_observer as "Sky Recorder"',
            player_id="test:investigator-a",
        ),
    )
    assert assigned.accepted

    released = execute_command(
        pack,
        assigned.stream,
        parse_user_command(
            "role clear",
            player_id="test:investigator-a",
        ),
    )
    assert released.accepted
    player = released.stream.state.get_player("test:investigator-a")
    assert player is not None
    assert player.active_role_id is None
    assert player.active_role_display_name is None
    assert player.active_role_description is None


def test_ordinary_role_state_keeps_legacy_player_shape() -> None:
    pack = _pack()
    stream = initialize_event_stream(
        pack,
        ("test:investigator-a",),
        stream_id="legacy-state-shape",
    )
    assigned = execute_command(
        pack,
        stream,
        parse_user_command(
            "assign-role field_observer",
            player_id="test:investigator-a",
        ),
    )
    data = serialize_state(assigned.stream.state)
    assert b"active_role_display_name" not in data
    assert b"active_role_description" not in data
