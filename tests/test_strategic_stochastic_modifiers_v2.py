from __future__ import annotations

from dataclasses import replace

from uniflora.content.v2 import load_missing_interior_pack
from uniflora.engine.v2 import (
    V2BeginInvestigationCommand,
    execute_command,
    initialize_event_stream,
)
from uniflora.engine.v2.state import V2StrategicConditionState
from uniflora.engine.v2.strategic import preview_strategic_state
from uniflora.engine.v2.stochastic import (
    V2SeededRandomSource,
    resolve_stochastic_action,
)

A = "discord:modifier-a"


def _position_one_state():
    pack = load_missing_interior_pack()
    stream = initialize_event_stream(pack, (A,), stream_id="modifier-test")
    begun = execute_command(
        pack,
        stream,
        V2BeginInvestigationCommand(player_id=A),
        random_source=V2SeededRandomSource("modifier-begin"),
    )
    assert begun.accepted
    state = begun.stream.state
    tracks, board = preview_strategic_state(pack, state)
    assert board is not None
    return pack, replace(
        state,
        campaign_tracks=tracks,
        strategic_board=board,
        serialization_schema=4,
    )


def test_emission_only_action_does_not_advance_latent_state() -> None:
    pack, state = _position_one_state()
    action = next(item for item in pack.actions if item.id == "inspect_optical_record")
    process = next(
        item for item in pack.stochastic_processes
        if item.id == action.stochastic_process_id
    )
    _, resolution, _ = resolve_stochastic_action(
        state,
        action,
        process,
        random_source=V2SeededRandomSource("emit-only"),
    )
    assert resolution.state_advanced is False
    assert resolution.transition_draw is None
    assert resolution.previous_state_id == resolution.next_state_id


def test_preparation_condition_changes_effective_weight_table_hash() -> None:
    pack, state = _position_one_state()
    action = next(
        item for item in pack.actions
        if item.id == "run_synchronized_reacquisition"
    )
    process = next(
        item for item in pack.stochastic_processes
        if item.id == action.stochastic_process_id
    )
    without, _, _ = resolve_stochastic_action(
        state,
        action,
        process,
        random_source=V2SeededRandomSource("same-draw"),
    )
    board = state.strategic_board
    assert board is not None
    prepared_board = replace(
        board,
        conditions=board.conditions
        + (
            V2StrategicConditionState(
                condition_id="raw_channels_quarantined",
                duration="position",
                created_round=board.round_index,
                expires_after_round=None,
            ),
        ),
    )
    prepared_state = replace(state, strategic_board=prepared_board)
    _, prepared_resolution, _ = resolve_stochastic_action(
        prepared_state,
        action,
        process,
        random_source=V2SeededRandomSource("same-draw"),
    )
    # First return value above is state; resolve again to retain resolution.
    _, unprepared_resolution, _ = resolve_stochastic_action(
        state,
        action,
        process,
        random_source=V2SeededRandomSource("same-draw"),
    )
    assert unprepared_resolution.state_advanced is True
    assert prepared_resolution.state_advanced is True
    assert unprepared_resolution.transition_draw is not None
    assert prepared_resolution.transition_draw is not None
    assert unprepared_resolution.weight_table_hash != prepared_resolution.weight_table_hash
