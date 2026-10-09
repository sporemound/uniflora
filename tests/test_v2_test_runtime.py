from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from uniflora.engine.v2 import V2SQLiteEventStore
from uniflora.v2_test_runtime import (
    ClosedV2TestRuntimeError,
    UnknownV2TestIdentityError,
    V2TestRuntime,
)


@pytest.mark.asyncio
async def test_auto_creates_the_canonical_stream_with_fixed_identities(
    tmp_path: Path,
) -> None:
    runtime = V2TestRuntime(tmp_path / "v2.sqlite3", stream_id="discord-test-v2")
    try:
        session = await runtime.session()

        assert session.stream_id == "discord-test-v2"
        assert session.sequence == 0
        assert session.state.pack_id == "missing_interior"
        assert session.state.current_position_id == "network_orientation"
        assert len(session.state.available_location_ids) == 6
        assert {player.player_id for player in session.state.players} == {
            "test:investigator-a",
            "test:reviewer-b",
        }
        assert runtime.identities == ("investigator-a", "reviewer-b")
    finally:
        await runtime.close()


@pytest.mark.asyncio
async def test_live_stream_uses_separate_store_and_real_initial_identity(
    tmp_path: Path,
) -> None:
    test_runtime = V2TestRuntime(tmp_path / "test.sqlite3", stream_id="discord-test")
    live_runtime = V2TestRuntime(
        tmp_path / "live.sqlite3", stream_id="discord-live",
        initial_player_ids=("discord:111111111111111111",),
    )
    try:
        assert {player.player_id for player in (await live_runtime.session()).state.players} == {
            "discord:111111111111111111",
        }
        result = await live_runtime.execute_public(
            player_id="discord:111111111111111111", text="begin-investigation",
        )
        assert result.accepted is True
        assert (await live_runtime.session()).state.current_position_id == "boundary_event"
        assert (await test_runtime.session()).state.current_position_id == "network_orientation"
    finally:
        await live_runtime.close()
        await test_runtime.close()


@pytest.mark.asyncio
async def test_live_role_choice_lists_canonical_roles_and_persists_title(
    tmp_path: Path,
) -> None:
    runtime = V2TestRuntime(
        tmp_path / "live.sqlite3", stream_id="discord-live",
        initial_player_ids=("discord:111111111111111111",),
    )
    try:
        begun = await runtime.execute_public(
            player_id="discord:111111111111111111", text="begin-investigation",
        )
        assert begun.accepted
        choices = await runtime.available_public_roles("field")
        assert any(role_id == "field_observer" for role_id, _label in choices)

        assigned = await runtime.assign_public_role(
            player_id="discord:111111111111111111",
            role_id="field_observer",
            display_name="Field Analyst",
        )
        assert assigned.accepted
        player = (await runtime.session()).state.get_player("discord:111111111111111111")
        assert player is not None
        assert player.active_role_id == "field_observer"
        assert player.active_role_display_name == "Field Analyst"
    finally:
        await runtime.close()


@pytest.mark.asyncio
async def test_auto_creation_is_idempotent_across_runtime_restarts(
    tmp_path: Path,
) -> None:
    database = tmp_path / "v2.sqlite3"
    first = V2TestRuntime(database, stream_id="stable-stream")
    initial = await first.session()
    await first.close()

    second = V2TestRuntime(database, stream_id="stable-stream")
    try:
        restored = await second.session()
        assert restored.sequence == initial.sequence == 0
        assert restored.last_event_hash == initial.last_event_hash
    finally:
        await second.close()

    with V2SQLiteEventStore(database) as store:
        assert len(store.load_event_envelopes("stable-stream")) == 1


@pytest.mark.asyncio
async def test_position_zero_begins_once_without_quality_scoring(
    tmp_path: Path,
) -> None:
    runtime = V2TestRuntime(tmp_path / "v2.sqlite3", stream_id="orientation-stream")
    try:
        begun = await runtime.execute(
            identity="investigator-a",
            text="begin-investigation",
        )
        duplicate = await runtime.execute(
            identity="investigator-a",
            text="begin-investigation",
        )
        session = await runtime.session()

        assert begun.accepted is True
        assert begun.code == "investigation_begun"
        assert duplicate.accepted is False
        assert duplicate.code == "orientation_unavailable"
        assert session.state.current_position_id == "boundary_event"
        assert session.state.completed_position_ids == {"network_orientation"}
        assert session.state.position_quality_seals == ()
        assert session.state.adaptation_selections == ()
    finally:
        await runtime.close()


@pytest.mark.asyncio
async def test_execute_loads_the_current_sequence_internally(
    tmp_path: Path,
) -> None:
    runtime = V2TestRuntime(tmp_path / "v2.sqlite3", stream_id="sequence-stream")
    try:
        assigned = await runtime.execute(
            identity="investigator-a",
            text="assign-role instrument_operator",
        )
        released = await runtime.execute(
            identity="investigator-a",
            text="release-role",
        )

        assert assigned.accepted is True
        assert assigned.code == "role_assigned"
        assert assigned.sequence == 1
        assert released.accepted is True
        assert released.code == "role_released"
        assert released.sequence == 2
        assert (await runtime.session()).sequence == 2
    finally:
        await runtime.close()


@pytest.mark.asyncio
async def test_unknown_identity_is_rejected_before_engine_mutation(
    tmp_path: Path,
) -> None:
    database = tmp_path / "v2.sqlite3"
    runtime = V2TestRuntime(database, stream_id="identity-stream")
    try:
        initial = await runtime.session()
        with pytest.raises(
            UnknownV2TestIdentityError,
            match="investigator-a, reviewer-b",
        ):
            await runtime.execute(
                identity="intruder",
                text="assign-role instrument_operator",
            )
        assert (await runtime.session()).sequence == initial.sequence
    finally:
        await runtime.close()

    with V2SQLiteEventStore(database) as store:
        assert store.latest_sequence("identity-stream") == 0


@pytest.mark.asyncio
async def test_concurrent_commands_are_serialized_without_sequence_conflict(
    tmp_path: Path,
) -> None:
    runtime = V2TestRuntime(tmp_path / "v2.sqlite3", stream_id="concurrent-stream")
    try:
        investigator, reviewer = await asyncio.gather(
            runtime.execute(
                identity="investigator-a",
                text="assign-role instrument_operator",
            ),
            runtime.execute(
                identity="reviewer-b",
                text="assign-role atmospheric_analyst",
            ),
        )

        assert investigator.accepted is True
        assert reviewer.accepted is True
        assert {investigator.sequence, reviewer.sequence} == {1, 2}
        assert (await runtime.session()).sequence == 2
    finally:
        await runtime.close()


@pytest.mark.asyncio
async def test_documented_sole_tester_sequence_completes_position_one(
    tmp_path: Path,
) -> None:
    runtime = V2TestRuntime(tmp_path / "v2.sqlite3", stream_id="guide-stream")
    investigator_commands = (
        "assign-role field_observer",
        "examine-evidence optical_record",
        "perform-action inspect_optical_record",
        "release-role",
        "assign-role instrument_operator",
        "examine-evidence radio_return",
        "perform-action calibrate_radio_receiver",
        "examine-evidence receiver_diagnostic",
        "release-role",
        "assign-role atmospheric_analyst",
        "perform-action request_weather_record",
        "examine-evidence weather_record",
        "release-role",
        "assign-role signal_correlator",
        "perform-action compare_source_timing",
        "release-role",
        "assign-role atmospheric_analyst",
        "perform-action test_atmospheric_propagation",
        "release-role",
        "assign-role protocol_auditor",
        "perform-action document_upper_atmosphere_gap",
        (
            'draft-assessment boundary_assessment --statement "The records support a '
            "bounded timing anomaly without establishing distance, size, composition, "
            'or identity." --evidence optical_record,radio_return,weather_record '
            "--ordinary atmospheric_propagation --contradictions "
            "optical_radio_timing_offset --gaps upper_atmosphere_conditions "
            '--confidence moderate --next-collection "Obtain regional '
            'upper-atmosphere observations."'
        ),
    )

    try:
        orientation = await runtime.execute(
            identity="investigator-a",
            text="begin-investigation",
        )
        assert orientation.accepted is True
        assert orientation.code == "investigation_begun"
        for command in investigator_commands:
            result = await runtime.execute(
                identity="investigator-a",
                text=command,
            )
            assert result.accepted is True, (command, result.code, result.to_text())

        confirmation = await runtime.execute(
            identity="reviewer-b",
            text="confirm-assessment boundary_assessment",
        )
        completion = await runtime.execute(
            identity="investigator-a",
            text="complete-position boundary_assessment",
        )
        session = await runtime.session()

        assert confirmation.accepted is True
        assert completion.accepted is True
        assert session.state.current_position_id == "aeronautical_incident"
        assert "boundary_event" in session.state.completed_position_ids
    finally:
        await runtime.close()


@pytest.mark.asyncio
async def test_close_is_idempotent_and_prevents_further_work(tmp_path: Path) -> None:
    runtime = V2TestRuntime(tmp_path / "v2.sqlite3", stream_id="closed-stream")
    await runtime.close()
    await runtime.close()

    with pytest.raises(ClosedV2TestRuntimeError, match="runtime is closed"):
        await runtime.status()
