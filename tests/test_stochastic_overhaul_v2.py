from __future__ import annotations

import json
from datetime import UTC, datetime

from uniflora.content.v2 import load_missing_interior_pack
from uniflora.engine.v2 import (
    V2ActionPerformedEvent,
    V2AssignRoleCommand,
    V2BeginInvestigationCommand,
    V2CompletePositionCommand,
    V2ConfirmAssessmentCommand,
    V2DraftAssessmentCommand,
    V2ExamineEvidenceCommand,
    V2PerformActionCommand,
    V2ReleaseRoleCommand,
    V2SessionView,
    deserialize_event,
    deserialize_state,
    execute_command,
    initialize_event_stream,
    replay_events,
    seal_event_stream,
    serialize_event,
    serialize_state,
    verify_event_stream,
)
from uniflora.engine.v2.delivery import completion_route_progress, relevant_actions
from uniflora.engine.v2.stochastic import V2SeededRandomSource
from uniflora.v2_activity_projection import build_v2_activity_snapshot


PLAYER = "discord:1001"
REVIEWER = "discord:1002"


def _accepted(pack, stream, command, random_source):
    result = execute_command(
        pack,
        stream,
        command,
        random_source=random_source,
    )
    assert result.accepted, (result.code, result.message)
    return result


def _run_receiver_diagnostic(seed: str = "receiver-seed"):
    pack = load_missing_interior_pack()
    stream = initialize_event_stream(
        pack,
        (PLAYER, REVIEWER),
        stream_id="stochastic-replay",
    )
    random_source = V2SeededRandomSource(seed)

    for command in (
        V2BeginInvestigationCommand(player_id=PLAYER),
        V2ExamineEvidenceCommand(player_id=PLAYER, evidence_id="radio_return"),
        V2AssignRoleCommand(
            player_id=PLAYER,
            role_id="instrument_operator",
            display_name="Night Receiver",
            description="Checks retained receiver behavior without treating it as a cause.",
        ),
    ):
        stream = _accepted(pack, stream, command, random_source).stream

    result = _accepted(
        pack,
        stream,
        V2PerformActionCommand(
            player_id=PLAYER,
            action_id="calibrate_radio_receiver",
        ),
        random_source,
    )
    return pack, result.stream, result


def _complete_environmental_route():
    pack = load_missing_interior_pack()
    stream = initialize_event_stream(
        pack,
        (PLAYER, REVIEWER),
        stream_id="environmental-route",
    )
    random_source = V2SeededRandomSource("environmental-route-seed")

    def go(command):
        nonlocal stream
        stream = _accepted(pack, stream, command, random_source).stream

    go(V2BeginInvestigationCommand(player_id=PLAYER))
    go(V2ExamineEvidenceCommand(player_id=PLAYER, evidence_id="optical_record"))
    go(V2ExamineEvidenceCommand(player_id=PLAYER, evidence_id="radio_return"))

    go(V2AssignRoleCommand(player_id=PLAYER, role_id="field_observer"))
    go(V2PerformActionCommand(player_id=PLAYER, action_id="inspect_optical_record"))
    go(V2ReleaseRoleCommand(player_id=PLAYER))

    go(V2AssignRoleCommand(player_id=PLAYER, role_id="atmospheric_analyst"))
    go(V2PerformActionCommand(player_id=PLAYER, action_id="request_weather_record"))
    go(V2ExamineEvidenceCommand(player_id=PLAYER, evidence_id="weather_record"))
    go(V2ReleaseRoleCommand(player_id=PLAYER))

    go(V2AssignRoleCommand(player_id=PLAYER, role_id="signal_correlator"))
    go(V2PerformActionCommand(player_id=PLAYER, action_id="compare_source_timing"))
    go(V2ReleaseRoleCommand(player_id=PLAYER))

    go(V2AssignRoleCommand(player_id=PLAYER, role_id="atmospheric_analyst"))
    go(
        V2PerformActionCommand(
            player_id=PLAYER,
            action_id="test_atmospheric_propagation",
        )
    )
    go(V2ReleaseRoleCommand(player_id=PLAYER))

    go(V2AssignRoleCommand(player_id=PLAYER, role_id="protocol_auditor"))
    go(
        V2PerformActionCommand(
            player_id=PLAYER,
            action_id="document_upper_atmosphere_gap",
        )
    )
    go(V2ReleaseRoleCommand(player_id=PLAYER))

    assessment_id = "boundary_event_assessment"
    go(
        V2DraftAssessmentCommand(
            player_id=PLAYER,
            assessment_id=assessment_id,
            statement=(
                "The retained records preserve a timing contradiction after an "
                "atmospheric test while upper-atmosphere conditions remain unavailable."
            ),
            evidence_ids=("optical_record", "radio_return", "weather_record"),
            tested_ordinary_explanation_ids=("atmospheric_propagation",),
            preserved_contradiction_ids=("optical_radio_timing_offset",),
            documented_information_gap_ids=("upper_atmosphere_conditions",),
            confidence="moderate",
            next_collection="Collect a synchronized upper-atmosphere profile.",
        )
    )
    go(V2ConfirmAssessmentCommand(player_id=REVIEWER, assessment_id=assessment_id))
    completion = _accepted(
        pack,
        stream,
        V2CompletePositionCommand(
            player_id=PLAYER,
            assessment_id=assessment_id,
        ),
        random_source,
    )
    return pack, completion.stream


def test_pack_defines_six_stochastic_facility_processes_and_alternative_routes() -> None:
    pack = load_missing_interior_pack()

    assert pack.pack.content_version == "2.0.0-strategic-overhaul"
    assert {process.id for process in pack.stochastic_processes} == {
        "boundary_signal_regime",
        "airspace_track_regime",
        "archive_provenance_regime",
        "holographic_phase_regime",
        "subsurface_mode_regime",
        "quantum_observer_regime",
    }
    for position in pack.positions:
        if position.ordinal == 0:
            continue
        assert len(position.completion.completion_routes) == 2
        assert all(route.required_action_ids for route in position.completion.completion_routes)


def test_seeded_resolution_is_reproducible_and_replays_without_rerolling() -> None:
    _, first_stream, first_result = _run_receiver_diagnostic("repeatable-seed")
    _, second_stream, second_result = _run_receiver_diagnostic("repeatable-seed")

    assert isinstance(first_result.event, V2ActionPerformedEvent)
    assert first_result.event.stochastic_resolution is not None
    assert first_result.event.stochastic_resolution == second_result.event.stochastic_resolution
    assert first_stream.state == second_stream.state

    encoded_event = serialize_event(first_result.event)
    assert deserialize_event(encoded_event) == first_result.event
    encoded_state = serialize_state(first_stream.state)
    assert deserialize_state(encoded_state) == first_stream.state
    assert replay_events(first_stream.events) == first_stream.state
    assert verify_event_stream(first_stream) == first_stream.state

    support = first_stream.state.get_stochastic_support("boundary_signal_regime")
    assert support is not None
    assert sum(item.basis_points for item in support.models) == 10_000


def test_environmental_route_completes_without_receiver_diagnostic() -> None:
    pack, stream = _complete_environmental_route()

    assert "boundary_event" in stream.state.completed_position_ids
    assert stream.state.current_position_id == "aeronautical_incident"
    assert "calibrate_radio_receiver" not in stream.state.completed_action_ids

    boundary = next(position for position in pack.positions if position.id == "boundary_event")
    environmental = next(
        route
        for route in boundary.completion.completion_routes
        if route.id == "environmental_route"
    )
    instrument = next(
        route
        for route in boundary.completion.completion_routes
        if route.id == "instrument_route"
    )
    assert completion_route_progress(environmental, stream.state)[0] is True
    assert completion_route_progress(instrument, stream.state)[0] is False


def test_activity_projection_exposes_observations_not_hidden_states_or_player_ids() -> None:
    pack, stream, _ = _run_receiver_diagnostic("activity-seed")
    envelopes = seal_event_stream(stream)
    session = V2SessionView(
        stream_id=stream.stream_id,
        state=stream.state,
        sequence=stream.state.revision,
        last_event_hash=envelopes[-1].event_hash,
    )

    snapshot = build_v2_activity_snapshot(
        pack,
        session,
        revision=7,
        previous_state_head_hash=None,
        updated_at=datetime(2026, 7, 27, 12, 0, tzinfo=UTC),
    )

    assert snapshot["schemaVersion"] == "2.4.0"
    assert snapshot["sequence"] == session.sequence
    assert snapshot["casePhase"] in {"establish", "perturb", "reconcile", "review"}
    assert snapshot["recentObservations"]
    assert snapshot["stochasticProcesses"]
    assert snapshot["actions"]
    assert snapshot["completionRoutes"]

    serialized = json.dumps(snapshot, sort_keys=True)
    assert PLAYER not in serialized
    assert REVIEWER not in serialized
    # Hidden state IDs are persisted for replay but must not enter the public snapshot.
    hidden_state_ids = {
        state.id
        for process in pack.stochastic_processes
        if not process.reveal_latent_state
        for state in process.states
    }
    assert not any(state_id in serialized for state_id in hidden_state_ids)


async def _runtime_command(runtime, text: str):
    response = await runtime.execute_public(player_id=PLAYER, text=text)
    assert response is not None
    assert response.code != "transport_error"
    return response


def test_public_runtime_executes_stochastic_capability_without_none_response(tmp_path) -> None:
    import asyncio

    from uniflora.v2_test_runtime import V2TestRuntime

    async def scenario() -> None:
        runtime = V2TestRuntime(
            tmp_path / "v2-runtime.sqlite3",
            stream_id="public-runtime-overhaul",
        )
        try:
            assert (await _runtime_command(runtime, "begin-investigation")).accepted
            assert (
                await _runtime_command(runtime, "examine-evidence radio_return")
            ).accepted
            role = await runtime.assign_public_role(
                player_id=PLAYER,
                role_id="instrument_operator",
                display_name="Receiver Steward",
            )
            assert role.accepted
            capability = await _runtime_command(
                runtime,
                "perform-action calibrate_radio_receiver",
            )
            assert capability.accepted
            assert capability.code == "capability_resolved"
            session = await runtime.session()
            assert "calibrate_radio_receiver" in session.state.completed_action_ids
            assert any(
                observation.action_id == "calibrate_radio_receiver"
                for observation in session.state.stochastic_observations
            )

            status = await runtime.public_status(player_id=PLAYER)
            assert status.sequence is not None and status.sequence >= 4

            status_text = status.to_text()
            assert (
                f"Actions 1/{len(relevant_actions(runtime.pack, session.state))}"
                in status_text
            )
            assert "Receiver Steward" in status_text
            assert "calibrate_radio_receiver" not in status_text
        finally:
            await runtime.close()

    asyncio.run(scenario())
