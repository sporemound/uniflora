from __future__ import annotations

import hashlib
from dataclasses import dataclass, fields, is_dataclass, replace
from typing import Iterable

from uniflora.content.v2.investigation_schema import (
    V2InvestigationActionDefinition,
    V2InvestigationPack,
    V2StrategicActionEffectsDefinition,
    V2StrategicActionProfileDefinition,
    V2StrategicConditionGrantDefinition,
    V2StrategicDeltaDefinition,
    V2StrategicPositionDefinition,
)
from uniflora.engine.v2.serialization import canonical_json_bytes
from uniflora.engine.v2.state import (
    V2InvestigationState,
    V2StrategicBoardState,
    V2StrategicConditionState,
    V2StrategicPlayerRoundState,
    V2StrategicPositionOutcomeState,
    V2StrategicProposalState,
    V2StrategicResolutionState,
    V2StrategicResourceState,
    V2StrategicTrackState,
)
from uniflora.engine.v2.stochastic import (
    V2RandomSource,
    resolve_natural_drift,
)


class V2StrategicRuleError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True, slots=True)
class V2StrategicPreparedAction:
    sequence: int
    action_id: str
    actor_player_id: str
    profile: V2StrategicActionProfileDefinition
    state: V2InvestigationState
    board_before_hash: str
    capacity_cost: int
    coordination_cost: int
    supporter_player_ids: frozenset[str]
    proposal_id: str | None


@dataclass(frozen=True, slots=True)
class V2StrategicSupportResult:
    state: V2InvestigationState
    proposal: V2StrategicProposalState
    threshold_reached: bool


_DEFAULT_CLASS_BY_ACTION_TYPE = {
    "inspect": "observe",
    "calibrate": "prepare",
    "request": "coordinate",
    "compare": "reconcile",
    "test_explanation": "probe",
    "document_gap": "secure",
}

_CONTROLLED_ASSET_BY_POSITION = {
    "boundary_event": "verified_clock_handoff",
    "aeronautical_incident": "independent_track_geometry",
    "archive_convergence": "provenance_dependency_map",
    "holographic_reconstruction": "registered_phase_reference",
    "subsurface_resonance": "multiphysics_station_alignment",
    "quantum_state": "basis_calibration_ledger",
}

_CRITICAL_LIABILITY_BY_POSITION = {
    "boundary_event": "receiver_baseline_disputed",
    "aeronautical_incident": "airspace_source_conflict",
    "archive_convergence": "archive_dependency_contaminated",
    "holographic_reconstruction": "phase_reference_overfit",
    "subsurface_resonance": "station_coverage_fragmented",
    "quantum_state": "observer_basis_unresolved",
}


def _clamp(value: int, minimum: int, maximum: int) -> int:
    return max(minimum, min(maximum, value))


def _position_rules(
    pack: V2InvestigationPack,
    position_id: str,
) -> V2StrategicPositionDefinition | None:
    if pack.strategic is None:
        return None
    return next(
        (item for item in pack.strategic.positions if item.position_id == position_id),
        None,
    )


def strategic_enabled(pack: V2InvestigationPack, state: V2InvestigationState) -> bool:
    return pack.strategic is not None and _position_rules(pack, state.current_position_id) is not None


def default_action_profile(
    action: V2InvestigationActionDefinition,
) -> V2StrategicActionProfileDefinition:
    strategic_class = _DEFAULT_CLASS_BY_ACTION_TYPE[action.action_type]
    campaign_deltas: tuple[V2StrategicDeltaDefinition, ...] = ()
    position_deltas: tuple[V2StrategicDeltaDefinition, ...] = ()
    conditions: tuple[V2StrategicConditionGrantDefinition, ...] = ()
    if action.action_type == "document_gap":
        campaign_deltas = (
            V2StrategicDeltaDefinition(target_id="case_integrity", amount=1),
        )
    elif action.action_type == "request":
        position_deltas = (
            V2StrategicDeltaDefinition(target_id="coordination", amount=1),
        )
    elif action.action_type == "test_explanation":
        position_deltas = (
            V2StrategicDeltaDefinition(target_id="escalation", amount=1),
        )
    elif action.action_type == "calibrate":
        conditions = (
            V2StrategicConditionGrantDefinition(
                id=f"prepared_{action.id}",
                duration="position",
            ),
        )
    stochastic_mode = "emit_only" if action.stochastic_process_id is not None else "none"
    return V2StrategicActionProfileDefinition(
        strategic_class=strategic_class,  # type: ignore[arg-type]
        capacity_cost=1,
        stochastic_mode=stochastic_mode,
        deterministic_effects=V2StrategicActionEffectsDefinition(
            campaign_track_deltas=campaign_deltas,
            position_track_deltas=position_deltas,
            add_conditions=conditions,
        ),
    )


def action_profile(
    action: V2InvestigationActionDefinition,
) -> V2StrategicActionProfileDefinition:
    return action.strategic or default_action_profile(action)


def _campaign_tracks(
    pack: V2InvestigationPack,
    state: V2InvestigationState,
) -> tuple[V2StrategicTrackState, ...]:
    if state.campaign_tracks:
        return state.campaign_tracks
    if pack.strategic is None:
        return ()
    return tuple(
        V2StrategicTrackState(
            track_id=item.id,
            value=item.initial,
            minimum=item.minimum,
            maximum=item.maximum,
        )
        for item in pack.strategic.campaign_tracks
    )


def _initial_board(
    pack: V2InvestigationPack,
    state: V2InvestigationState,
) -> V2StrategicBoardState:
    rules = _position_rules(pack, state.current_position_id)
    if rules is None:
        raise V2StrategicRuleError(
            "strategic_rules_unavailable",
            f"Position {state.current_position_id!r} has no strategic rules.",
        )
    resource = rules.local_resource
    return V2StrategicBoardState(
        position_id=rules.position_id,
        round_index=1,
        max_rounds=rules.max_rounds,
        capacity_remaining=rules.capacity_per_round,
        capacity_per_round=rules.capacity_per_round,
        coordination=0,
        coordination_maximum=rules.coordination_maximum,
        escalation=0,
        escalation_maximum=rules.escalation_maximum,
        local_resource=V2StrategicResourceState(
            resource_id=resource.id,
            title=resource.title,
            value=resource.initial,
            minimum=resource.minimum,
            maximum=resource.maximum,
        ),
        conditions=tuple(
            V2StrategicConditionState(
                condition_id=modifier_id,
                duration="campaign",
                created_round=1,
                expires_after_round=None,
            )
            for modifier_id in sorted(state.campaign_modifier_ids)
        ),
        players=tuple(
            V2StrategicPlayerRoundState(player_id=player.player_id)
            for player in state.players
        ),
    )


def preview_strategic_state(
    pack: V2InvestigationPack,
    state: V2InvestigationState,
) -> tuple[tuple[V2StrategicTrackState, ...], V2StrategicBoardState | None]:
    if not strategic_enabled(pack, state):
        return state.campaign_tracks, state.strategic_board
    tracks = _campaign_tracks(pack, state)
    board = state.strategic_board
    if board is None or board.position_id != state.current_position_id:
        board = _initial_board(pack, state)
    return tracks, board


def _canonical_state_value(value: object) -> object:
    """Convert frozen state dataclasses to canonical JSON-compatible values."""

    if is_dataclass(value) and not isinstance(value, type):
        return {
            item.name: _canonical_state_value(getattr(value, item.name))
            for item in fields(value)
        }
    if isinstance(value, (tuple, list)):
        return [_canonical_state_value(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return [_canonical_state_value(item) for item in sorted(value)]
    if isinstance(value, dict):
        return {str(key): _canonical_state_value(item) for key, item in value.items()}
    return value


def _board_hash(
    board: V2StrategicBoardState,
    campaign_tracks: tuple[V2StrategicTrackState, ...],
) -> str:
    payload = {
        "board": _canonical_state_value(board),
        "campaignTracks": _canonical_state_value(campaign_tracks),
    }
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def action_definition_hash(action: V2InvestigationActionDefinition) -> str:
    return hashlib.sha256(
        canonical_json_bytes(
            {
                "action": action.model_dump(mode="json", by_alias=True),
                "profile": action_profile(action).model_dump(mode="json", by_alias=True),
            }
        )
    ).hexdigest()


def _replace_track(
    tracks: tuple[V2StrategicTrackState, ...],
    track_id: str,
    delta: int,
) -> tuple[V2StrategicTrackState, ...]:
    found = False
    result: list[V2StrategicTrackState] = []
    for item in tracks:
        if item.track_id == track_id:
            result.append(
                replace(
                    item,
                    value=_clamp(item.value + delta, item.minimum, item.maximum),
                )
            )
            found = True
        else:
            result.append(item)
    if not found:
        raise V2StrategicRuleError(
            "unknown_campaign_track",
            f"Strategic effect references unknown campaign track {track_id!r}.",
        )
    return tuple(result)


def _replace_board_player(
    board: V2StrategicBoardState,
    updated: V2StrategicPlayerRoundState,
) -> V2StrategicBoardState:
    values = tuple(
        updated if item.player_id == updated.player_id else item for item in board.players
    )
    if not any(item.player_id == updated.player_id for item in board.players):
        values += (updated,)
    return replace(board, players=values)


def _apply_conditions(
    board: V2StrategicBoardState,
    effects: V2StrategicActionEffectsDefinition,
) -> V2StrategicBoardState:
    removed = set(effects.remove_condition_ids)
    existing = {
        item.condition_id: item
        for item in board.conditions
        if item.condition_id not in removed
    }
    for grant in effects.add_conditions:
        expires = None
        if grant.duration == "round":
            expires = board.round_index
        elif grant.duration == "next_round":
            expires = min(board.max_rounds, board.round_index + 1)
        existing[grant.id] = V2StrategicConditionState(
            condition_id=grant.id,
            duration=grant.duration,
            created_round=board.round_index,
            expires_after_round=expires,
        )
    return replace(board, conditions=tuple(existing[key] for key in sorted(existing)))


def _apply_effects(
    board: V2StrategicBoardState,
    tracks: tuple[V2StrategicTrackState, ...],
    effects: V2StrategicActionEffectsDefinition,
) -> tuple[V2StrategicBoardState, tuple[V2StrategicTrackState, ...]]:
    updated_tracks = tracks
    for delta in effects.campaign_track_deltas:
        updated_tracks = _replace_track(updated_tracks, delta.target_id, delta.amount)

    coordination = board.coordination
    escalation = board.escalation
    for delta in effects.position_track_deltas:
        if delta.target_id == "coordination":
            coordination = _clamp(
                coordination + delta.amount,
                0,
                board.coordination_maximum,
            )
        elif delta.target_id == "escalation":
            escalation = _clamp(
                escalation + delta.amount,
                0,
                board.escalation_maximum,
            )
        else:
            raise V2StrategicRuleError(
                "unknown_position_track",
                f"Unknown strategic position track {delta.target_id!r}.",
            )

    local = board.local_resource
    for delta in effects.resource_deltas:
        if delta.target_id == "coordination":
            coordination = _clamp(
                coordination + delta.amount,
                0,
                board.coordination_maximum,
            )
        elif delta.target_id == "escalation":
            escalation = _clamp(
                escalation + delta.amount,
                0,
                board.escalation_maximum,
            )
        elif delta.target_id == local.resource_id:
            local = replace(
                local,
                value=_clamp(local.value + delta.amount, local.minimum, local.maximum),
            )
        else:
            raise V2StrategicRuleError(
                "unknown_local_resource",
                f"Unknown local resource {delta.target_id!r}.",
            )

    updated_board = replace(
        board,
        coordination=coordination,
        escalation=escalation,
        local_resource=local,
    )
    updated_board = _apply_conditions(updated_board, effects)
    return updated_board, updated_tracks


def prepare_strategic_action(
    pack: V2InvestigationPack,
    state: V2InvestigationState,
    action: V2InvestigationActionDefinition,
    *,
    player_id: str,
    supporter_player_ids: Iterable[str] = (),
    proposal_id: str | None = None,
    proposal_authorized: bool = False,
) -> V2StrategicPreparedAction | None:
    if not strategic_enabled(pack, state):
        return None
    if pack.strategic is None:
        raise AssertionError("strategic rules disappeared")
    tracks, board = preview_strategic_state(pack, state)
    if board is None:
        return None
    if board.forced_review:
        raise V2StrategicRuleError(
            "position_in_forced_review",
            "The position has exhausted its operation rounds and is awaiting review.",
        )
    profile = action_profile(action)
    supporters = frozenset(item.strip() for item in supporter_player_ids if item.strip())
    if profile.supporter_count and not proposal_authorized:
        raise V2StrategicRuleError(
            "major_action_requires_proposal",
            f"Action {action.id!r} requires propose-action and independent support.",
        )
    if len(supporters) < profile.supporter_count:
        raise V2StrategicRuleError(
            "insufficient_independent_support",
            f"Action {action.id!r} requires {profile.supporter_count} independent supporter(s).",
        )
    if player_id in supporters:
        raise V2StrategicRuleError(
            "self_support_forbidden",
            "A proposal author cannot support their own operation.",
        )

    round_player = board.get_player(player_id) or V2StrategicPlayerRoundState(
        player_id=player_id
    )
    if round_player.operation_count >= pack.strategic.max_operations_per_player_per_round:
        raise V2StrategicRuleError(
            "player_round_operation_limit",
            "This participant has resolved the maximum operations for the current round.",
        )
    surcharge = (
        pack.strategic.second_operation_surcharge
        if round_player.operation_count >= 1
        else 0
    )
    capacity_cost = profile.capacity_cost + surcharge
    if capacity_cost > board.capacity_remaining:
        raise V2StrategicRuleError(
            "insufficient_operation_capacity",
            f"Action {action.id!r} costs {capacity_cost} capacity; "
            f"only {board.capacity_remaining} remains.",
        )
    if profile.coordination_cost > board.coordination:
        raise V2StrategicRuleError(
            "insufficient_coordination",
            f"Action {action.id!r} costs {profile.coordination_cost} Coordination; "
            f"only {board.coordination} is available.",
        )

    player = state.get_player(player_id)
    if player is None:
        raise V2StrategicRuleError(
            "unknown_player",
            f"Player {player_id!r} is not part of the investigation.",
        )
    board_hash = _board_hash(board, tracks)
    board = replace(
        board,
        capacity_remaining=board.capacity_remaining - capacity_cost,
        coordination=board.coordination - profile.coordination_cost,
    )
    first_operation = round_player.operation_count == 0
    updated_round_player = replace(
        round_player,
        operation_count=round_player.operation_count + 1,
        locked_role_id=player.active_role_id,
    )
    board = _replace_board_player(board, updated_round_player)
    if first_operation:
        board = replace(
            board,
            coordination=min(board.coordination_maximum, board.coordination + 1),
        )
    board, tracks = _apply_effects(board, tracks, profile.deterministic_effects)
    if proposal_id is not None:
        board = replace(
            board,
            proposals=tuple(item for item in board.proposals if item.proposal_id != proposal_id),
        )

    interim = replace(
        state,
        campaign_tracks=tracks,
        strategic_board=board,
        serialization_schema=4,
    )
    return V2StrategicPreparedAction(
        sequence=state.revision + 1,
        action_id=action.id,
        actor_player_id=player_id,
        profile=profile,
        state=interim,
        board_before_hash=board_hash,
        capacity_cost=capacity_cost,
        coordination_cost=profile.coordination_cost,
        supporter_player_ids=supporters,
        proposal_id=proposal_id,
    )


def _expire_for_round_close(
    board: V2StrategicBoardState,
) -> tuple[V2StrategicConditionState, ...]:
    return tuple(
        item
        for item in board.conditions
        if item.duration in {"position", "campaign"}
        or (
            item.expires_after_round is not None
            and item.expires_after_round > board.round_index
        )
    )


def _apply_round_thresholds(
    board: V2StrategicBoardState,
    tracks: tuple[V2StrategicTrackState, ...],
) -> tuple[V2StrategicBoardState, tuple[V2StrategicTrackState, ...]]:
    updated = tracks
    if board.escalation >= max(1, board.escalation_maximum - 1):
        updated = _replace_track(updated, "case_integrity", -1)
        updated = _replace_track(updated, "institutional_trust", -1)
    if board.local_resource.value == board.local_resource.minimum:
        updated = _replace_track(updated, "case_integrity", -1)
    return board, updated


def finalize_strategic_action(
    pack: V2InvestigationPack,
    state: V2InvestigationState,
    prepared: V2StrategicPreparedAction,
    *,
    random_source: V2RandomSource | None = None,
) -> tuple[V2InvestigationState, V2StrategicResolutionState]:
    board = state.strategic_board
    if board is None:
        raise V2StrategicRuleError(
            "strategic_board_unavailable",
            "The strategic board disappeared during action resolution.",
        )
    tracks = state.campaign_tracks
    drift = None
    updated = state
    if board.capacity_remaining == 0:
        board, tracks = _apply_round_thresholds(board, tracks)
        rules = _position_rules(pack, board.position_id)
        if rules is None:
            raise V2StrategicRuleError(
                "strategic_rules_unavailable",
                f"Position {board.position_id!r} has no strategic rules.",
            )
        if rules.natural_drift_process_id is not None:
            process = next(
                (
                    item
                    for item in pack.stochastic_processes
                    if item.id == rules.natural_drift_process_id
                ),
                None,
            )
            if process is None:
                raise V2StrategicRuleError(
                    "stochastic_process_unavailable",
                    f"Natural drift process {rules.natural_drift_process_id!r} is unavailable.",
                )
            updated, drift = resolve_natural_drift(
                replace(
                    updated,
                    campaign_tracks=tracks,
                    strategic_board=board,
                    revision=prepared.sequence,
                    serialization_schema=4,
                ),
                process,
                random_source=random_source,
                context=(
                    f"{state.pack_id}|{prepared.sequence}|{board.position_id}|"
                    f"round:{board.round_index}"
                ),
            )
        conditions = _expire_for_round_close(board)
        if board.round_index >= board.max_rounds:
            board = replace(
                board,
                capacity_remaining=0,
                conditions=conditions,
                proposals=(),
                forced_review=True,
            )
        else:
            board = replace(
                board,
                round_index=board.round_index + 1,
                capacity_remaining=board.capacity_per_round,
                conditions=conditions,
                players=tuple(
                    V2StrategicPlayerRoundState(player_id=item.player_id)
                    for item in board.players
                ),
                proposals=(),
            )
    updated = replace(
        updated,
        campaign_tracks=tracks,
        strategic_board=board,
        revision=prepared.sequence,
        serialization_schema=4,
    )
    resolution = V2StrategicResolutionState(
        action_id=prepared.action_id,
        actor_player_id=prepared.actor_player_id,
        capacity_cost=prepared.capacity_cost,
        coordination_cost=prepared.coordination_cost,
        board_before_hash=prepared.board_before_hash,
        board_after=board,
        campaign_tracks_after=tracks,
        supporter_player_ids=prepared.supporter_player_ids,
        proposal_id=prepared.proposal_id,
        natural_drift=drift,
    )
    return updated, resolution


def bind_resolution_identity(
    resolution: V2StrategicResolutionState,
    *,
    action_id: str,
    actor_player_id: str,
) -> V2StrategicResolutionState:
    return replace(
        resolution,
        action_id=action_id,
        actor_player_id=actor_player_id,
    )


def propose_action(
    pack: V2InvestigationPack,
    state: V2InvestigationState,
    action: V2InvestigationActionDefinition,
    *,
    player_id: str,
) -> tuple[V2InvestigationState, V2StrategicProposalState]:
    if not strategic_enabled(pack, state):
        raise V2StrategicRuleError(
            "strategic_rules_unavailable",
            "Major-operation proposals are unavailable in this position.",
        )
    if pack.strategic is None:
        raise AssertionError("strategic rules disappeared")
    profile = action_profile(action)
    if profile.supporter_count < 1:
        raise V2StrategicRuleError(
            "action_does_not_require_proposal",
            f"Action {action.id!r} does not require independent support.",
        )
    tracks, board = preview_strategic_state(pack, state)
    if board is None:
        raise AssertionError("strategic board unavailable")
    if any(
        item.action_id == action.id and item.status == "active"
        for item in board.proposals
    ):
        raise V2StrategicRuleError(
            "action_already_proposed",
            f"Action {action.id!r} already has an active proposal this round.",
        )
    active_for_player = sum(
        item.proposer_player_id == player_id and item.status == "active"
        for item in board.proposals
    )
    if active_for_player >= pack.strategic.maximum_active_proposals_per_player:
        raise V2StrategicRuleError(
            "proposal_limit_reached",
            "This participant already has the maximum active proposals.",
        )
    digest = hashlib.sha256(
        f"{state.pack_id}|{state.current_position_id}|{board.round_index}|"
        f"{state.revision + 1}|{player_id}|{action.id}".encode()
    ).hexdigest()[:12]
    proposal = V2StrategicProposalState(
        proposal_id=f"proposal_{digest}",
        action_id=action.id,
        proposer_player_id=player_id,
        round_index=board.round_index,
        required_supporter_count=profile.supporter_count,
        supporter_player_ids=frozenset(),
        definition_hash=action_definition_hash(action),
    )
    board = replace(board, proposals=board.proposals + (proposal,))
    return (
        replace(
            state,
            campaign_tracks=tracks,
            strategic_board=board,
            revision=state.revision + 1,
            serialization_schema=4,
        ),
        proposal,
    )


def register_support(
    pack: V2InvestigationPack,
    state: V2InvestigationState,
    *,
    player_id: str,
    proposal_id: str,
) -> V2StrategicSupportResult:
    if not strategic_enabled(pack, state):
        raise V2StrategicRuleError(
            "strategic_rules_unavailable",
            "Major-operation support is unavailable in this position.",
        )
    tracks, board = preview_strategic_state(pack, state)
    if board is None:
        raise AssertionError("strategic board unavailable")
    proposal = board.get_proposal(proposal_id)
    if proposal is None or proposal.status != "active":
        raise V2StrategicRuleError(
            "unknown_proposal",
            f"Active proposal {proposal_id!r} was not found.",
        )
    if proposal.round_index != board.round_index:
        raise V2StrategicRuleError(
            "proposal_expired",
            "The proposal belongs to an earlier round.",
        )
    if proposal.proposer_player_id == player_id:
        raise V2StrategicRuleError(
            "self_support_forbidden",
            "A proposal author cannot support their own operation.",
        )
    if player_id in proposal.supporter_player_ids:
        raise V2StrategicRuleError(
            "proposal_already_supported",
            "This participant already supported the proposal.",
        )
    round_player = board.get_player(player_id) or V2StrategicPlayerRoundState(
        player_id=player_id
    )
    if round_player.supported_proposal_ids:
        raise V2StrategicRuleError(
            "support_limit_reached",
            "A participant may support one major proposal per round.",
        )
    updated_proposal = replace(
        proposal,
        supporter_player_ids=proposal.supporter_player_ids | {player_id},
    )
    updated_round_player = replace(
        round_player,
        supported_proposal_ids=round_player.supported_proposal_ids | {proposal_id},
    )
    board = _replace_board_player(board, updated_round_player)
    board = replace(
        board,
        proposals=tuple(
            updated_proposal if item.proposal_id == proposal_id else item
            for item in board.proposals
        ),
    )
    threshold = (
        len(updated_proposal.supporter_player_ids)
        >= updated_proposal.required_supporter_count
    )
    # A non-threshold support is an event of its own. Threshold support is folded
    # into the action event and does not first consume a separate sequence.
    updated_state = replace(
        state,
        campaign_tracks=tracks,
        strategic_board=board,
        serialization_schema=4,
        revision=(state.revision if threshold else state.revision + 1),
    )
    return V2StrategicSupportResult(
        state=updated_state,
        proposal=updated_proposal,
        threshold_reached=threshold,
    )


def pass_capacity(
    pack: V2InvestigationPack,
    state: V2InvestigationState,
    *,
    player_id: str,
    random_source: V2RandomSource | None = None,
) -> tuple[V2InvestigationState, V2StrategicResolutionState]:
    if not strategic_enabled(pack, state):
        raise V2StrategicRuleError(
            "strategic_rules_unavailable",
            "There is no strategic round to pass.",
        )
    tracks, board = preview_strategic_state(pack, state)
    if board is None:
        raise AssertionError("strategic board unavailable")
    if board.forced_review:
        raise V2StrategicRuleError(
            "position_in_forced_review",
            "The position is already awaiting review.",
        )
    if board.capacity_remaining > 1:
        distinct_actors = sum(item.operation_count > 0 for item in board.players)
        if distinct_actors < 2:
            raise V2StrategicRuleError(
                "pass_requires_independent_participation",
                "Passing more than one remaining capacity requires two participants "
                "to have acted in the current round.",
            )
    board_hash = _board_hash(board, tracks)
    cost = board.capacity_remaining
    board = replace(board, capacity_remaining=0)
    prepared = V2StrategicPreparedAction(
        sequence=state.revision + 1,
        action_id="pass_capacity",
        actor_player_id=player_id,
        profile=V2StrategicActionProfileDefinition(
            strategic_class="coordinate",
            capacity_cost=cost,
            stochastic_mode="none",
        ),
        state=replace(
            state,
            campaign_tracks=tracks,
            strategic_board=board,
            serialization_schema=4,
        ),
        board_before_hash=board_hash,
        capacity_cost=cost,
        coordination_cost=0,
        supporter_player_ids=frozenset(),
        proposal_id=None,
    )
    updated, resolution = finalize_strategic_action(
        pack,
        prepared.state,
        prepared,
        random_source=random_source,
    )
    return updated, resolution


def apply_recorded_strategic_resolution(
    state: V2InvestigationState,
    resolution: V2StrategicResolutionState,
    *,
    sequence: int,
) -> V2InvestigationState:
    updated = state
    if resolution.natural_drift is not None:
        from uniflora.engine.v2.stochastic import apply_natural_drift

        updated = apply_natural_drift(
            updated,
            resolution.natural_drift,
            sequence=sequence,
        )
    return replace(
        updated,
        campaign_tracks=resolution.campaign_tracks_after,
        strategic_board=resolution.board_after,
        revision=sequence,
        serialization_schema=4,
    )


def grade_current_position(
    pack: V2InvestigationPack,
    state: V2InvestigationState,
) -> tuple[
    V2StrategicPositionOutcomeState | None,
    tuple[V2StrategicTrackState, ...],
    frozenset[str],
]:
    if not strategic_enabled(pack, state):
        return None, state.campaign_tracks, state.campaign_modifier_ids
    rules = _position_rules(pack, state.current_position_id)
    tracks, board = preview_strategic_state(pack, state)
    if rules is None or board is None:
        return None, tracks, state.campaign_modifier_ids
    integrity = next(item.value for item in tracks if item.track_id == "case_integrity")
    trust = next(item.value for item in tracks if item.track_id == "institutional_trust")
    if (
        integrity <= 1
        or trust <= 1
        or board.escalation >= board.escalation_maximum
    ):
        grade = "critical"
    elif board.forced_review:
        grade = "incomplete"
    elif (
        integrity >= rules.controlled_integrity_minimum
        and trust >= rules.controlled_trust_minimum
        and board.escalation <= rules.controlled_escalation_maximum
    ):
        grade = "controlled"
    else:
        grade = "compromised"
    assets: tuple[str, ...] = ()
    liabilities: tuple[str, ...] = ()
    modifiers = set(state.campaign_modifier_ids)
    if grade == "controlled":
        asset = _CONTROLLED_ASSET_BY_POSITION.get(state.current_position_id)
        if asset:
            assets = (asset,)
            modifiers.add(asset)
    elif grade == "critical":
        liability = _CRITICAL_LIABILITY_BY_POSITION.get(state.current_position_id)
        if liability:
            liabilities = (liability,)
            modifiers.add(liability)
    outcome = V2StrategicPositionOutcomeState(
        position_id=state.current_position_id,
        grade=grade,  # type: ignore[arg-type]
        round_index=board.round_index,
        case_integrity=integrity,
        institutional_trust=trust,
        escalation=board.escalation,
        asset_ids=assets,
        liability_ids=liabilities,
    )
    return outcome, tracks, frozenset(modifiers)


def board_text(pack: V2InvestigationPack, state: V2InvestigationState) -> str:
    tracks, board = preview_strategic_state(pack, state)
    if board is None:
        return "No strategic board is active in the current position."
    track_by_id = {item.track_id: item for item in tracks}
    integrity = track_by_id["case_integrity"]
    trust = track_by_id["institutional_trust"]
    conditions = ", ".join(item.condition_id.replace("_", " ") for item in board.conditions)
    proposal_lines = [
        (
            f"• `{item.proposal_id}` — `{item.action_id}` · "
            f"{len(item.supporter_player_ids)}/{item.required_supporter_count} supporters"
        )
        for item in board.proposals
    ]
    lines = [
        f"**Round {board.round_index}/{board.max_rounds} · capacity "
        f"{board.capacity_remaining}/{board.capacity_per_round}**",
        (
            f"Campaign — integrity {integrity.value}/{integrity.maximum} · "
            f"trust {trust.value}/{trust.maximum}"
        ),
        (
            f"Position — coordination {board.coordination}/{board.coordination_maximum} · "
            f"escalation {board.escalation}/{board.escalation_maximum} · "
            f"{board.local_resource.title.lower()} "
            f"{board.local_resource.value}/{board.local_resource.maximum}"
        ),
        f"Conditions — {conditions or 'none'}",
    ]
    if board.forced_review:
        lines.append("Status — forced review; no operation capacity remains")
    if proposal_lines:
        lines.extend(("Major proposals", *proposal_lines))
    return "\n".join(lines)


__all__ = [
    "V2StrategicPreparedAction",
    "V2StrategicRuleError",
    "V2StrategicSupportResult",
    "action_definition_hash",
    "action_profile",
    "apply_recorded_strategic_resolution",
    "bind_resolution_identity",
    "board_text",
    "default_action_profile",
    "finalize_strategic_action",
    "grade_current_position",
    "pass_capacity",
    "prepare_strategic_action",
    "preview_strategic_state",
    "propose_action",
    "register_support",
    "strategic_enabled",
]
