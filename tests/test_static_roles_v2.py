from __future__ import annotations

from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path

import pytest

from uniflora.content.v2 import (
    V2InvestigationPack,
    load_missing_interior_pack,
    load_missing_interior_static_pack,
)
from uniflora.content.v2.static_roles import (
    LEGACY_FUNCTION_TO_STATIC_ROLE,
    STATIC_ROLES_PACK_ID,
)
from uniflora.engine.v2.application import (
    V2ApplicationError,
    V2PersistentInvestigationService,
    V2SessionView,
)
from uniflora.engine.v2.commands import (
    V2AssignRoleCommand,
    V2BeginInvestigationCommand,
    V2ExamineEvidenceCommand,
    V2PerformActionCommand,
    V2ReleaseRoleCommand,
)
from uniflora.engine.v2.delivery import guided_suggestions, next_requirement
from uniflora.engine.v2.event_stream import (
    execute_command,
    initialize_event_stream,
    verify_event_stream,
)
from uniflora.engine.v2.kernel import release_role
from uniflora.engine.v2.persistence import V2SQLiteEventStore
from uniflora.engine.v2.rendering import render_session_view
from uniflora.v2_activity_projection import build_v2_activity_snapshot
from uniflora.v2_test_runtime import V2TestRuntime


@pytest.fixture(scope="module")
def packs() -> tuple[V2InvestigationPack, V2InvestigationPack]:
    return load_missing_interior_pack(), load_missing_interior_static_pack()


def test_static_pack_maps_every_function_and_action_gate(
    packs: tuple[V2InvestigationPack, V2InvestigationPack],
) -> None:
    legacy, static = packs
    assert legacy.pack.id == "missing_interior"
    assert legacy.pack.content_version == "2.0.0-strategic-overhaul"
    assert len(legacy.roles) == 38

    assert static.pack.id == STATIC_ROLES_PACK_ID
    assert static.pack.content_version == "2.1.0-static-roles"
    assert {role.id for role in static.roles} == {
        "evidence_investigator",
        "systems_analyst",
        "independent_reviewer",
    }
    assert all(role.scope == "arc" and not role.allowed_location_ids for role in static.roles)
    assert all(not role.allow_player_defined_name for role in static.roles)
    assert set(LEGACY_FUNCTION_TO_STATIC_ROLE) == {role.id for role in legacy.roles}

    static_actions = {action.id: action for action in static.actions}
    counts: Counter[str] = Counter()
    roles_by_position: dict[str, set[str]] = defaultdict(set)
    for original in legacy.actions:
        mapped = static_actions[original.id]
        expected = tuple(
            dict.fromkeys(
                LEGACY_FUNCTION_TO_STATIC_ROLE[role_id]
                for role_id in original.prerequisites.required_role_ids
            )
        )
        assert mapped.prerequisites.required_role_ids == expected
        assert mapped.title == original.title
        assert mapped.description == original.description
        counts.update(expected)
        roles_by_position[original.position_id].update(expected)

    assert counts == {
        "evidence_investigator": 22,
        "systems_analyst": 21,
        "independent_reviewer": 20,
    }
    assert len(roles_by_position) == 6
    assert all(roles == {role.id for role in static.roles} for roles in roles_by_position.values())


def test_permanent_role_is_chosen_once_and_survives_position_transition(
    packs: tuple[V2InvestigationPack, V2InvestigationPack],
) -> None:
    _, pack = packs
    stream = initialize_event_stream(pack, ["web:alice", "web:bob"], stream_id="static-test")
    suggestions = guided_suggestions(pack, stream.state, "web:alice")
    assert {item.command for item in suggestions} == {
        "assign-role evidence_investigator",
        "assign-role systems_analyst",
        "assign-role independent_reviewer",
    }
    assert "Choose one permanent investigative role" in next_requirement(
        pack, stream.state, "web:alice"
    )

    before_role = execute_command(
        pack,
        stream,
        V2ExamineEvidenceCommand(player_id="web:alice", evidence_id="optical_record"),
    )
    assert not before_role.accepted
    assert before_role.code == "role_required"

    chosen = execute_command(
        pack,
        stream,
        V2AssignRoleCommand(player_id="web:alice", role_id="evidence_investigator"),
    )
    assert chosen.accepted
    stream = chosen.stream
    assert stream.state.get_player("web:alice").active_role_id == "evidence_investigator"

    released = execute_command(pack, stream, V2ReleaseRoleCommand(player_id="web:alice"))
    assert not released.accepted
    assert released.code == "permanent_role"
    assert released.stream is stream
    assert not release_role(stream.state, player_id="web:alice").accepted

    changed = execute_command(
        pack,
        stream,
        V2AssignRoleCommand(player_id="web:alice", role_id="systems_analyst"),
    )
    assert not changed.accepted
    assert changed.code == "role_already_assigned"
    assert changed.stream is stream

    begun = execute_command(pack, stream, V2BeginInvestigationCommand(player_id="web:alice"))
    assert begun.accepted
    assert begun.stream.state.current_position_id == "boundary_event"
    assert begun.stream.state.get_player("web:alice").active_role_id == "evidence_investigator"
    assert verify_event_stream(begun.stream) == begun.stream.state
    assert all(
        item.command != "release-role" and not item.command.startswith("assign-role")
        for item in guided_suggestions(pack, begun.stream.state, "web:alice")
    )


def test_legacy_stream_keeps_temporary_role_events(
    packs: tuple[V2InvestigationPack, V2InvestigationPack],
) -> None:
    legacy, _ = packs
    stream = initialize_event_stream(legacy, ["discord:old"], stream_id="legacy-test")
    chosen = execute_command(
        legacy,
        stream,
        V2AssignRoleCommand(player_id="discord:old", role_id="field_observer"),
    )
    assert chosen.accepted
    released = execute_command(
        legacy,
        chosen.stream,
        V2ReleaseRoleCommand(player_id="discord:old"),
    )
    assert released.accepted
    assert released.stream.state.get_player("discord:old").active_role_id is None
    assert verify_event_stream(released.stream) == released.stream.state


def test_default_status_selects_web_participant_over_test_seat(
    packs: tuple[V2InvestigationPack, V2InvestigationPack],
) -> None:
    _, pack = packs
    stream = initialize_event_stream(pack, ["test:seat", "web:alice"], stream_id="web-status")
    chosen = execute_command(
        pack,
        stream,
        V2AssignRoleCommand(player_id="web:alice", role_id="systems_analyst"),
    )
    assert chosen.accepted
    view = V2SessionView(
        stream_id=chosen.stream.stream_id,
        state=chosen.stream.state,
        sequence=chosen.stream.state.revision,
        last_event_hash="test-event-hash",
    )
    text = render_session_view(view, pack=pack).to_text()
    assert "Systems Analyst" in text
    assert "Choose one permanent investigative role" not in text


def test_action_gate_uses_permanent_role(
    packs: tuple[V2InvestigationPack, V2InvestigationPack],
) -> None:
    _, pack = packs
    stream = initialize_event_stream(pack, ["web:inv", "web:analyst"], stream_id="role-gate")
    for player_id, role_id in (
        ("web:inv", "evidence_investigator"),
        ("web:analyst", "systems_analyst"),
    ):
        assigned = execute_command(
            pack,
            stream,
            V2AssignRoleCommand(player_id=player_id, role_id=role_id),
        )
        assert assigned.accepted
        stream = assigned.stream

    started = execute_command(pack, stream, V2BeginInvestigationCommand(player_id="web:inv"))
    assert started.accepted
    examined = execute_command(
        pack,
        started.stream,
        V2ExamineEvidenceCommand(player_id="web:inv", evidence_id="optical_record"),
    )
    assert examined.accepted

    wrong_role = execute_command(
        pack,
        examined.stream,
        V2PerformActionCommand(player_id="web:analyst", action_id="inspect_optical_record"),
    )
    assert not wrong_role.accepted
    assert wrong_role.code == "required_role_missing"
    assert wrong_role.stream is examined.stream

    correct_role = execute_command(
        pack,
        examined.stream,
        V2PerformActionCommand(player_id="web:inv", action_id="inspect_optical_record"),
    )
    assert correct_role.accepted
    assert verify_event_stream(correct_role.stream) == correct_role.stream.state


def test_pack_id_keeps_legacy_and_static_streams_separate(
    tmp_path: Path,
    packs: tuple[V2InvestigationPack, V2InvestigationPack],
) -> None:
    legacy, static = packs
    with V2SQLiteEventStore(tmp_path / "role-streams.sqlite3") as store:
        static_service = V2PersistentInvestigationService(static, store)
        created = static_service.create_session("web-stream", ["web:alice"])
        assert created.session.state.pack_id == STATIC_ROLES_PACK_ID
        assert static_service.load_session("web-stream") == created.session

        legacy_service = V2PersistentInvestigationService(legacy, store)
        with pytest.raises(V2ApplicationError, match="stream belongs to pack"):
            legacy_service.load_session("web-stream")


@pytest.mark.asyncio
async def test_first_web_player_can_choose_role_and_publish_projection(
    packs: tuple[V2InvestigationPack, V2InvestigationPack],
) -> None:
    _, pack = packs
    player_id = "web:participant_" + "a" * 24
    runtime = V2TestRuntime(
        ":memory:",
        stream_id="web-live",
        initial_player_ids=(),
        pack=pack,
    )
    try:
        first_status = await runtime.public_status(player_id=player_id)
        assert first_status.accepted
        assert "Choose one permanent investigative role" in first_status.payload.to_text()
        session = await runtime.session()
        assert session.sequence == 0
        assert tuple(player.player_id for player in session.state.players) == (player_id,)

        commands = await runtime.available_public_commands(player_id=player_id)
        assert {command for command, _ in commands} == {
            "assign-role evidence_investigator",
            "assign-role systems_analyst",
            "assign-role independent_reviewer",
        }
        chosen = await runtime.execute_public(
            player_id=player_id,
            text="assign-role evidence_investigator",
        )
        assert chosen.accepted
        assert chosen.code == "role_assigned"
        assert (await runtime.session()).state.get_player(player_id).active_role_id == (
            "evidence_investigator"
        )

        snapshot = build_v2_activity_snapshot(
            pack,
            await runtime.session(),
            revision=1,
            previous_state_head_hash=None,
            updated_at=datetime(2026, 10, 8, tzinfo=UTC),
            environment="live",
        )
        assert snapshot["contentVersion"] == "2.1.0-static-roles"
        assert snapshot["environment"] == "live"
        assert snapshot["assignments"]
        assert player_id not in str(snapshot)

        released = await runtime.execute_public(player_id=player_id, text="release-role")
        assert not released.accepted
        assert released.code == "permanent_role"
    finally:
        await runtime.close()
