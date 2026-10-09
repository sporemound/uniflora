from __future__ import annotations

from dataclasses import replace

from uniflora.content.v2 import load_missing_interior_pack
from uniflora.engine.v2 import (
    V2AssignRoleCommand,
    V2BeginInvestigationCommand,
    V2ExamineEvidenceCommand,
    V2PassCapacityCommand,
    V2PerformActionCommand,
    V2ProposeActionCommand,
    V2SupportActionCommand,
    execute_command,
    initialize_event_stream,
)
from uniflora.engine.v2.stochastic import V2SeededRandomSource

A = "discord:proposal-a"
B = "discord:proposal-b"
C = "discord:proposal-c"


def _accepted(pack, stream, command, source):
    result = execute_command(pack, stream, command, random_source=source)
    assert result.accepted, (result.code, result.message)
    return result


def _setup(seed: str = "proposal"):
    pack = load_missing_interior_pack()
    source = V2SeededRandomSource(seed)
    stream = initialize_event_stream(pack, (A, B, C), stream_id=f"proposal-{seed}")
    for command in (
        V2BeginInvestigationCommand(player_id=A),
        V2ExamineEvidenceCommand(player_id=A, evidence_id="optical_record"),
        V2ExamineEvidenceCommand(player_id=A, evidence_id="radio_return"),
        V2AssignRoleCommand(player_id=A, role_id="signal_correlator"),
        V2AssignRoleCommand(player_id=B, role_id="protocol_auditor"),
        V2PerformActionCommand(player_id=B, action_id="preserve_raw_channel_snapshot"),
    ):
        stream = _accepted(pack, stream, command, source).stream
    return pack, source, stream


def _pack_with_two_supporters(pack):
    actions = []
    for action in pack.actions:
        if action.id == "run_synchronized_reacquisition":
            actions.append(
                action.model_copy(
                    update={
                        "strategic": action.strategic.model_copy(
                            update={"supporter_count": 2}
                        )
                    }
                )
            )
        else:
            actions.append(action)
    return pack.model_copy(update={"actions": tuple(actions)})


def test_duplicate_support_is_rejected_and_threshold_resolution_is_atomic() -> None:
    pack, source, stream = _setup("two-supporters")
    pack = _pack_with_two_supporters(pack)
    proposal = _accepted(
        pack,
        stream,
        V2ProposeActionCommand(
            player_id=A,
            action_id="run_synchronized_reacquisition",
        ),
        source,
    )
    stream = proposal.stream
    proposal_id = proposal.event.proposal.proposal_id

    duplicate_proposal = execute_command(
        pack,
        stream,
        V2ProposeActionCommand(
            player_id=C,
            action_id="run_synchronized_reacquisition",
        ),
        random_source=source,
    )
    assert not duplicate_proposal.accepted
    assert duplicate_proposal.code == "action_already_proposed"
    assert duplicate_proposal.stream == stream

    first = _accepted(
        pack,
        stream,
        V2SupportActionCommand(player_id=B, proposal_id=proposal_id),
        source,
    )
    assert first.code == "major_action_supported"
    assert first.event.proposal.supporter_player_ids == frozenset({B})
    stream = first.stream

    duplicate = execute_command(
        pack,
        stream,
        V2SupportActionCommand(player_id=B, proposal_id=proposal_id),
        random_source=source,
    )
    assert not duplicate.accepted
    assert duplicate.code == "proposal_already_supported"
    assert duplicate.event is None
    assert duplicate.stream == stream

    threshold = _accepted(
        pack,
        stream,
        V2SupportActionCommand(player_id=C, proposal_id=proposal_id),
        source,
    )
    assert threshold.code == "major_action_resolved"
    assert threshold.event.action_id == "run_synchronized_reacquisition"
    assert threshold.event.strategic_resolution.supporter_player_ids == frozenset({B, C})
    assert threshold.stream.state.revision == stream.state.revision + 1


def test_definition_change_rejects_stale_proposal_without_side_effects() -> None:
    pack, source, stream = _setup("definition-change")
    proposal = _accepted(
        pack,
        stream,
        V2ProposeActionCommand(
            player_id=A,
            action_id="run_synchronized_reacquisition",
        ),
        source,
    )
    stream = proposal.stream
    proposal_id = proposal.event.proposal.proposal_id

    actions = []
    for action in pack.actions:
        if action.id == "run_synchronized_reacquisition":
            actions.append(
                action.model_copy(
                    update={
                        "strategic": action.strategic.model_copy(
                            update={"capacity_cost": 1}
                        )
                    }
                )
            )
        else:
            actions.append(action)
    changed_pack = pack.model_copy(update={"actions": tuple(actions)})
    result = execute_command(
        changed_pack,
        stream,
        V2SupportActionCommand(player_id=B, proposal_id=proposal_id),
        random_source=source,
    )
    assert not result.accepted
    assert result.code == "proposal_definition_changed"
    assert result.event is None
    assert result.stream == stream


def test_proposals_expire_when_round_closes_and_pass_requires_participation() -> None:
    pack, source, stream = _setup("expiry")
    proposal = _accepted(
        pack,
        stream,
        V2ProposeActionCommand(
            player_id=A,
            action_id="run_synchronized_reacquisition",
        ),
        source,
    )
    stream = proposal.stream
    proposal_id = proposal.event.proposal.proposal_id
    board = stream.state.strategic_board
    assert board is not None and board.capacity_remaining == 2

    # B is the only actor so far; passing more than one capacity is rejected.
    rejected = execute_command(
        pack,
        stream,
        V2PassCapacityCommand(player_id=A),
        random_source=source,
    )
    assert not rejected.accepted
    assert rejected.code == "pass_requires_independent_participation"
    assert rejected.stream == stream

    # C performs one ordinary operation. B and C have now acted, leaving one
    # capacity that a third participant can pass to close the round.
    stream = _accepted(
        pack,
        stream,
        V2AssignRoleCommand(player_id=C, role_id="field_observer"),
        source,
    ).stream
    stream = _accepted(
        pack,
        stream,
        V2PerformActionCommand(player_id=C, action_id="inspect_optical_record"),
        source,
    ).stream
    board = stream.state.strategic_board
    assert board is not None and board.capacity_remaining == 1
    closed = _accepted(
        pack,
        stream,
        V2PassCapacityCommand(player_id=A),
        source,
    )
    board = closed.stream.state.strategic_board
    assert board is not None and board.round_index == 2
    assert board.get_proposal(proposal_id) is None
