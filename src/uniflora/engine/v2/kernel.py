from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, replace
from fractions import Fraction
from typing import Literal

from uniflora.content.v2.investigation_schema import (
    V2EvidenceSourceDefinition,
    V2InvestigationActionDefinition,
    V2InvestigationPack,
    V2InvestigationPositionDefinition,
    V2RoleDefinition,
)
from uniflora.content.v2.player_roles import (
    V2PlayerRoleError,
    create_player_role_assignment,
)
from uniflora.content.v2.static_roles import STATIC_ROLES_PACK_ID
from uniflora.engine.v2.commands import ORIENTATION_POSITION_ID
from uniflora.engine.v2.quality import (
    adaptation_band,
    cumulative_result,
    position_result,
    subject_result,
)
from uniflora.engine.v2.state import (
    V2AdaptationSelectionState,
    V2AssessmentState,
    V2InvestigationState,
    V2PlayerState,
    V2PositionQualitySealState,
    V2PromotedFindingState,
    V2QualityReviewState,
    V2StochasticResolutionState,
    V2StrategicProposalState,
    V2StrategicResolutionState,
)
from uniflora.engine.v2.stochastic import (
    V2RandomSource,
    resolve_stochastic_action,
)
from uniflora.engine.v2.strategic import (
    V2StrategicRuleError,
    action_definition_hash,
    board_text,
    finalize_strategic_action,
    grade_current_position,
    pass_capacity,
    prepare_strategic_action,
    propose_action,
    register_support,
)


@dataclass(frozen=True, slots=True)
class V2KernelResult:
    accepted: bool
    code: str
    message: str
    state: V2InvestigationState
    stochastic_resolution: V2StochasticResolutionState | None = None
    strategic_resolution: V2StrategicResolutionState | None = None
    strategic_proposal: V2StrategicProposalState | None = None


def _reject(
    state: V2InvestigationState,
    *,
    code: str,
    message: str,
) -> V2KernelResult:
    return V2KernelResult(
        accepted=False,
        code=code,
        message=message,
        state=state,
    )


def _accept(
    state: V2InvestigationState,
    *,
    code: str,
    message: str,
    stochastic_resolution: V2StochasticResolutionState | None = None,
    strategic_resolution: V2StrategicResolutionState | None = None,
    strategic_proposal: V2StrategicProposalState | None = None,
) -> V2KernelResult:
    return V2KernelResult(
        accepted=True,
        code=code,
        message=message,
        state=state,
        stochastic_resolution=stochastic_resolution,
        strategic_resolution=strategic_resolution,
        strategic_proposal=strategic_proposal,
    )


def _position(
    pack: V2InvestigationPack,
    position_id: str,
) -> V2InvestigationPositionDefinition | None:
    return next(
        (position for position in pack.positions if position.id == position_id),
        None,
    )


def _role(
    pack: V2InvestigationPack,
    role_id: str,
) -> V2RoleDefinition | None:
    return next(
        (role for role in pack.roles if role.id == role_id),
        None,
    )


def _evidence(
    pack: V2InvestigationPack,
    evidence_id: str,
) -> V2EvidenceSourceDefinition | None:
    return next(
        (source for source in pack.evidence_sources if source.id == evidence_id),
        None,
    )


def _action(
    pack: V2InvestigationPack,
    action_id: str,
) -> V2InvestigationActionDefinition | None:
    return next(
        (action for action in pack.actions if action.id == action_id),
        None,
    )


def _stochastic_process(pack: V2InvestigationPack, process_id: str):
    return next(
        (process for process in pack.stochastic_processes if process.id == process_id),
        None,
    )


def _effective_stochastic_observation_count(
    pack: V2InvestigationPack,
    state: V2InvestigationState,
    process_ids: object,
) -> int:
    """Count recorded observations plus pre-overhaul completed-action credits."""

    required_process_ids = frozenset(str(item) for item in process_ids)

    recorded = tuple(
        observation
        for observation in state.stochastic_observations
        if observation.process_id in required_process_ids
    )
    recorded_action_ids = frozenset(
        observation.action_id for observation in recorded
    )

    legacy_action_ids = frozenset(
        action.id
        for action in pack.actions
        if action.id in state.completed_action_ids
        and action.stochastic_process_id in required_process_ids
        and action.id not in recorded_action_ids
    )

    return len(recorded) + len(legacy_action_ids)


def _replace_player(
    state: V2InvestigationState,
    updated_player: V2PlayerState,
) -> V2InvestigationState:
    players = tuple(
        updated_player if player.player_id == updated_player.player_id else player
        for player in state.players
    )

    return replace(
        state,
        players=players,
        revision=state.revision + 1,
    )


def initialize_investigation(
    pack: V2InvestigationPack,
    player_ids: Iterable[str],
) -> V2InvestigationState:
    normalized_player_ids = tuple(player_id.strip() for player_id in player_ids)

    if not normalized_player_ids:
        raise ValueError("at least one player is required to initialize an investigation")

    if any(not player_id for player_id in normalized_player_ids):
        raise ValueError("player IDs must not be blank")

    if len(normalized_player_ids) != len(set(normalized_player_ids)):
        raise ValueError("player IDs must be unique")

    initial_position = _position(
        pack,
        pack.pack.initial_position_id,
    )

    if initial_position is None:
        raise ValueError("pack initial position is unavailable after validation")

    available_locations = frozenset(initial_position.initially_available_location_ids)

    players = tuple(
        V2PlayerState(
            player_id=player_id,
            current_location_id=initial_position.focus_location_id,
        )
        for player_id in normalized_player_ids
    )

    available_evidence = frozenset(
        source.id for source in pack.evidence_sources if source.initially_available
    ) | frozenset(initial_position.available_evidence_ids_on_entry)

    return V2InvestigationState(
        pack_id=pack.pack.id,
        current_position_id=initial_position.id,
        available_location_ids=available_locations,
        players=players,
        available_evidence_ids=available_evidence,
    )


def join_investigation(
    pack: V2InvestigationPack,
    state: V2InvestigationState,
    *,
    player_id: str,
) -> V2KernelResult:
    normalized = player_id.strip()
    if not normalized:
        return _reject(state, code="invalid_player", message="Player ID must not be blank.")
    if state.get_player(normalized) is not None:
        return _reject(
            state,
            code="player_already_joined",
            message=f"Player {normalized!r} is already part of this investigation.",
        )
    position = _position(pack, state.current_position_id)
    if position is None:
        return _reject(state, code="unknown_position", message="Current position is unavailable.")
    player = V2PlayerState(
        player_id=normalized,
        current_location_id=position.focus_location_id,
    )
    return _accept(
        replace(
            state,
            players=state.players + (player,),
            revision=state.revision + 1,
            serialization_schema=max(state.serialization_schema, 2),
        ),
        code="player_joined",
        message=(
            f"Player {normalized!r} joined the investigation "
            f"at {position.focus_location_id!r}."
        ),
    )


def begin_investigation(
    pack: V2InvestigationPack,
    state: V2InvestigationState,
    *,
    player_id: str,
) -> V2KernelResult:
    """Complete the unscored Position 0 orientation and expose Position 1."""

    if state.get_player(player_id) is None:
        return _reject(
            state,
            code="unknown_player",
            message=f"Player {player_id!r} is not part of this investigation.",
        )

    position = _position(pack, state.current_position_id)
    if (
        position is None
        or position.id != ORIENTATION_POSITION_ID
        or position.ordinal != 0
    ):
        return _reject(
            state,
            code="orientation_unavailable",
            message="Position 0 orientation is not the current shared state.",
        )

    next_position = (
        _position(pack, position.next_position_id)
        if position.next_position_id is not None
        else None
    )
    if next_position is None or next_position.ordinal != 1:
        return _reject(
            state,
            code="orientation_target_unavailable",
            message="Position 0 does not resolve to an available Position 1.",
        )

    updated_state = replace(
        state,
        current_position_id=next_position.id,
        available_location_ids=(
            state.available_location_ids
            | frozenset(next_position.initially_available_location_ids)
        ),
        available_evidence_ids=(
            state.available_evidence_ids
            | frozenset(next_position.available_evidence_ids_on_entry)
        ),
        completed_position_ids=state.completed_position_ids | {position.id},
        revision=state.revision + 1,
        serialization_schema=2,
    )
    return _accept(
        updated_state,
        code="investigation_begun",
        message=(
            f"Player {player_id!r} completed Position 0 orientation and "
            f"opened Position 1: {next_position.title}."
        ),
    )


def assign_role(
    pack: V2InvestigationPack,
    state: V2InvestigationState,
    *,
    player_id: str,
    role_id: str,
    display_name: str | None = None,
    description: str | None = None,
) -> V2KernelResult:
    player = state.get_player(player_id)

    if player is None:
        return _reject(
            state,
            code="unknown_player",
            message=f"Player {player_id!r} is not part of this investigation.",
        )

    role = _role(pack, role_id)

    if role is None:
        return _reject(
            state,
            code="unknown_role",
            message=f"Role {role_id!r} is not defined.",
        )

    if player.active_role_id is not None:
        return _reject(
            state,
            code="role_already_assigned",
            message=(f"Player {player_id!r} already holds role {player.active_role_id!r}."),
        )

    if role.allowed_location_ids and player.current_location_id not in role.allowed_location_ids:
        return _reject(
            state,
            code="role_location_not_allowed",
            message=(
                f"Role {role_id!r} cannot be assigned at location {player.current_location_id!r}."
            ),
        )

    if display_name is not None and not role.allow_player_defined_name:
        return _reject(
            state,
            code="custom_role_name_disallowed",
            message="This function does not permit a custom public title.",
        )
    if description is not None and not role.allow_player_defined_description:
        return _reject(
            state,
            code="custom_role_description_disallowed",
            message="This function does not permit a custom public description.",
        )
    if description is not None and display_name is None:
        return _reject(
            state,
            code="invalid_player_defined_role",
            message="A custom description requires a custom public title.",
        )
    if display_name is not None:
        try:
            assignment = create_player_role_assignment(
                pack,
                identity=player_id,
                canonical_role_id=role.id,
                display_name=display_name,
                description=description,
                position_id=state.current_position_id,
                current_location_id=player.current_location_id,
            )
        except V2PlayerRoleError as exc:
            return _reject(
                state,
                code="invalid_player_defined_role",
                message=str(exc),
            )
        display_name = assignment.display_name
        description = assignment.description
    updated_state = _replace_player(
        state,
        replace(
            player,
            active_role_id=role.id,
            active_role_display_name=display_name,
            active_role_description=description,
        ),
    )

    return _accept(
        updated_state,
        code="role_assigned",
        message=f"Player {player_id!r} assumed role {role.id!r}.",
    )


def release_role(
    state: V2InvestigationState,
    *,
    player_id: str,
) -> V2KernelResult:
    player = state.get_player(player_id)

    if player is None:
        return _reject(
            state,
            code="unknown_player",
            message=f"Player {player_id!r} is not part of this investigation.",
        )

    if player.active_role_id is None:
        return _reject(
            state,
            code="no_active_role",
            message=f"Player {player_id!r} has no active role.",
        )

    if state.pack_id == STATIC_ROLES_PACK_ID:
        return _reject(
            state,
            code="permanent_role",
            message="Your investigative role is fixed for the entire campaign.",
        )

    released_role = player.active_role_id

    updated_state = _replace_player(
        state,
        replace(
            player,
            active_role_id=None,
            active_role_display_name=None,
            active_role_description=None,
        ),
    )

    return _accept(
        updated_state,
        code="role_released",
        message=(f"Player {player_id!r} released role {released_role!r}."),
    )


def move_player(
    pack: V2InvestigationPack,
    state: V2InvestigationState,
    *,
    player_id: str,
    location_id: str,
) -> V2KernelResult:
    player = state.get_player(player_id)

    if player is None:
        return _reject(
            state,
            code="unknown_player",
            message=f"Player {player_id!r} is not part of this investigation.",
        )

    known_locations = {location.id for location in pack.locations}

    if location_id not in known_locations:
        return _reject(
            state,
            code="unknown_location",
            message=f"Location {location_id!r} is not defined.",
        )

    if location_id not in state.available_location_ids:
        return _reject(
            state,
            code="location_unavailable",
            message=f"Location {location_id!r} is not currently available.",
        )

    if player.current_location_id == location_id:
        return _reject(
            state,
            code="already_at_location",
            message=f"Player {player_id!r} is already at {location_id!r}.",
        )

    if player.active_role_id is not None:
        role = _role(pack, player.active_role_id)

        if (
            role is not None
            and role.allowed_location_ids
            and location_id not in role.allowed_location_ids
        ):
            return _reject(
                state,
                code="role_location_not_allowed",
                message=(f"Role {role.id!r} does not permit movement to {location_id!r}."),
            )

    updated_state = _replace_player(
        state,
        replace(
            player,
            current_location_id=location_id,
        ),
    )

    return _accept(
        updated_state,
        code="player_moved",
        message=f"Player {player_id!r} moved to {location_id!r}.",
    )


def examine_evidence(
    pack: V2InvestigationPack,
    state: V2InvestigationState,
    *,
    player_id: str,
    evidence_id: str,
) -> V2KernelResult:
    player = state.get_player(player_id)

    if player is None:
        return _reject(
            state,
            code="unknown_player",
            message=f"Player {player_id!r} is not part of this investigation.",
        )

    source = _evidence(pack, evidence_id)

    if source is None:
        return _reject(
            state,
            code="unknown_evidence",
            message=f"Evidence source {evidence_id!r} is not defined.",
        )

    if evidence_id not in state.available_evidence_ids:
        return _reject(
            state,
            code="evidence_unavailable",
            message=f"Evidence source {evidence_id!r} is not available.",
        )

    if player.current_location_id != source.origin_location_id:
        return _reject(
            state,
            code="wrong_location",
            message=(
                f"Evidence source {evidence_id!r} must be examined at "
                f"{source.origin_location_id!r}."
            ),
        )

    if evidence_id in state.examined_evidence_ids:
        return _accept(
            state,
            code="evidence_reopened",
            message=(
                f"Player {player_id!r} reopened evidence {evidence_id!r}. "
                "The source remains in the record and no new event was added."
            ),
        )

    updated_state = replace(
        state,
        examined_evidence_ids=state.examined_evidence_ids | {evidence_id},
        revision=state.revision + 1,
    )

    return _accept(
        updated_state,
        code="evidence_examined",
        message=(f"Player {player_id!r} examined evidence {evidence_id!r}."),
    )


def perform_action(
    pack: V2InvestigationPack,
    state: V2InvestigationState,
    *,
    player_id: str,
    action_id: str,
    random_source: V2RandomSource | None = None,
    supporter_player_ids: Iterable[str] = (),
    proposal_id: str | None = None,
    proposal_authorized: bool = False,
) -> V2KernelResult:
    player = state.get_player(player_id)

    if player is None:
        return _reject(
            state,
            code="unknown_player",
            message=f"Player {player_id!r} is not part of this investigation.",
        )

    action = _action(pack, action_id)

    if action is None:
        return _reject(
            state,
            code="unknown_action",
            message=f"Action {action_id!r} is not defined.",
        )

    if action.position_id is not None and action.position_id != state.current_position_id:
        return _reject(
            state,
            code="action_not_current_position",
            message=(
                f"Action {action.id!r} belongs to position {action.position_id!r}, "
                f"not current position {state.current_position_id!r}."
            ),
        )

    position = _position(pack, state.current_position_id)
    if position is not None and position.adaptation is not None:
        selection = state.get_adaptation_selection(position.id)
        selected_band = selection.band if selection is not None else "baseline"
        restricted_by_band = {
            band: {
                *getattr(position.adaptation, band).optional_action_ids,
                *(
                    (getattr(position.adaptation, band).required_action_id,)
                    if getattr(position.adaptation, band).required_action_id is not None
                    else ()
                ),
            }
            for band in ("corrective", "baseline", "advanced")
        }
        allowed = restricted_by_band[selected_band]
        restricted = set().union(*restricted_by_band.values())
        if action.id in restricted and action.id not in allowed:
            return _reject(
                state,
                code="action_not_selected_for_adaptation",
                message=f"Action {action.id!r} is not available in this scenario.",
            )

    if action.id in state.completed_action_ids and not action.repeatable:
        return _reject(
            state,
            code="action_already_completed",
            message=f"Action {action.id!r} was already completed.",
        )

    if player.current_location_id != action.location_id:
        return _reject(
            state,
            code="wrong_location",
            message=(f"Action {action.id!r} must be performed at {action.location_id!r}."),
        )

    required_roles = set(action.prerequisites.required_role_ids)

    if required_roles and player.active_role_id not in required_roles:
        return _reject(
            state,
            code="required_role_missing",
            message=(
                f"Action {action.id!r} requires one of these roles: "
                + ", ".join(sorted(required_roles))
            ),
        )

    missing_evidence = (
        set(action.prerequisites.required_examined_evidence_ids) - state.examined_evidence_ids
    )

    if missing_evidence:
        return _reject(
            state,
            code="required_evidence_missing",
            message=(
                f"Action {action.id!r} requires examined evidence: "
                + ", ".join(sorted(missing_evidence))
            ),
        )

    candidate_evidence = set(
        action.prerequisites.candidate_examined_evidence_ids
    ) & state.examined_evidence_ids
    if (
        len(candidate_evidence)
        < action.prerequisites.minimum_examined_evidence_count
    ):
        return _reject(
            state,
            code="insufficient_evidence_context",
            message=(
                f"Action {action.id!r} requires at least "
                f"{action.prerequisites.minimum_examined_evidence_count} examined "
                "record(s) from: "
                + ", ".join(
                    sorted(action.prerequisites.candidate_examined_evidence_ids)
                )
            ),
        )

    missing_actions = (
        set(action.prerequisites.required_completed_action_ids) - state.completed_action_ids
    )

    if missing_actions:
        return _reject(
            state,
            code="required_action_missing",
            message=(
                f"Action {action.id!r} requires completed actions: "
                + ", ".join(sorted(missing_actions))
            ),
        )

    candidate_actions = set(
        action.prerequisites.candidate_completed_action_ids
    ) & state.completed_action_ids
    if (
        len(candidate_actions)
        < action.prerequisites.minimum_completed_action_count
    ):
        return _reject(
            state,
            code="insufficient_action_context",
            message=(
                f"Action {action.id!r} requires at least "
                f"{action.prerequisites.minimum_completed_action_count} completed "
                "capability/capabilities from: "
                + ", ".join(
                    sorted(action.prerequisites.candidate_completed_action_ids)
                )
            ),
        )

    process_observations = _effective_stochastic_observation_count(
        pack,
        state,
        action.prerequisites.required_stochastic_process_ids,
    )
    if (
        process_observations
        < action.prerequisites.minimum_stochastic_observation_count
    ):
        return _reject(
            state,
            code="insufficient_stochastic_context",
            message=(
                f"Action {action.id!r} requires at least "
                f"{action.prerequisites.minimum_stochastic_observation_count} "
                "recorded stochastic observation(s) across: "
                + ", ".join(
                    sorted(action.prerequisites.required_stochastic_process_ids)
                )
            ),
        )

    try:
        strategic_prepared = prepare_strategic_action(
            pack,
            state,
            action,
            player_id=player_id,
            supporter_player_ids=supporter_player_ids,
            proposal_id=proposal_id,
            proposal_authorized=proposal_authorized,
        )
    except V2StrategicRuleError as error:
        return _reject(state, code=error.code, message=error.message)

    strategic_base_state = strategic_prepared.state if strategic_prepared is not None else state
    stochastic_resolution: V2StochasticResolutionState | None = None
    stochastic_unlocks: frozenset[str] = frozenset()
    stochastic_state = strategic_base_state
    if action.stochastic_process_id is not None:
        process = _stochastic_process(pack, action.stochastic_process_id)
        if process is None:
            return _reject(
                state,
                code="stochastic_process_unavailable",
                message=(
                    f"Action {action.id!r} references unavailable stochastic process "
                    f"{action.stochastic_process_id!r}."
                ),
            )
        stochastic_state, stochastic_resolution, stochastic_unlocks = (
            resolve_stochastic_action(
                strategic_base_state,
                action,
                process,
                random_source=random_source,
            )
        )

    updated_state = replace(
        stochastic_state,
        available_evidence_ids=(
            stochastic_state.available_evidence_ids
            | set(action.effects.unlock_evidence_ids)
            | set(stochastic_unlocks)
        ),
        completed_action_ids=stochastic_state.completed_action_ids | {action.id},
        tested_ordinary_explanation_ids=(
            stochastic_state.tested_ordinary_explanation_ids
            | set(action.effects.mark_ordinary_explanation_tested_ids)
        ),
        preserved_contradiction_ids=(
            stochastic_state.preserved_contradiction_ids
            | set(action.effects.preserve_contradiction_ids)
        ),
        documented_information_gap_ids=(
            stochastic_state.documented_information_gap_ids
            | set(action.effects.document_information_gap_ids)
        ),
        revision=state.revision + 1,
    )

    strategic_resolution: V2StrategicResolutionState | None = None
    if strategic_prepared is not None:
        try:
            updated_state, strategic_resolution = finalize_strategic_action(
                pack,
                updated_state,
                strategic_prepared,
                random_source=random_source,
            )
        except V2StrategicRuleError as error:
            return _reject(state, code=error.code, message=error.message)

    message = f"Player {player_id!r} completed capability {action.id!r}."
    if stochastic_resolution is not None:
        message += f" Observed result: {stochastic_resolution.public_summary}"
    return _accept(
        updated_state,
        code="capability_resolved" if stochastic_resolution is not None else "action_completed",
        message=message,
        stochastic_resolution=stochastic_resolution,
        strategic_resolution=strategic_resolution,
    )


def view_strategic_board(
    pack: V2InvestigationPack,
    state: V2InvestigationState,
    *,
    player_id: str,
) -> V2KernelResult:
    if state.get_player(player_id) is None:
        return _reject(
            state, code="unknown_player",
            message=f"Player {player_id!r} is not part of this investigation."
        )
    return _accept(
        state,
        code="strategic_board_viewed",
        message=board_text(pack, state),
    )


def propose_strategic_action(
    pack: V2InvestigationPack,
    state: V2InvestigationState,
    *,
    player_id: str,
    action_id: str,
) -> V2KernelResult:
    if state.get_player(player_id) is None:
        return _reject(
            state, code="unknown_player",
            message=f"Player {player_id!r} is not part of this investigation."
        )
    action = _action(pack, action_id)
    if action is None:
        return _reject(
            state, code="unknown_action", message=f"Action {action_id!r} is not defined."
        )
    if action.position_id != state.current_position_id:
        return _reject(
            state,
            code="action_not_current_position",
            message=f"Action {action.id!r} is not part of the current position.",
        )
    try:
        updated, proposal = propose_action(
            pack, state, action, player_id=player_id
        )
    except V2StrategicRuleError as error:
        return _reject(state, code=error.code, message=error.message)
    return _accept(
        updated,
        code="major_action_proposed",
        message=(
            f"Player {player_id!r} proposed {action.id!r} as `{proposal.proposal_id}`. "
            f"It requires {proposal.required_supporter_count} independent supporter(s)."
        ),
        strategic_proposal=proposal,
    )


def support_strategic_action(
    pack: V2InvestigationPack,
    state: V2InvestigationState,
    *,
    player_id: str,
    proposal_id: str,
    random_source: V2RandomSource | None = None,
) -> V2KernelResult:
    if state.get_player(player_id) is None:
        return _reject(
            state, code="unknown_player",
            message=f"Player {player_id!r} is not part of this investigation."
        )
    try:
        support = register_support(
            pack, state, player_id=player_id, proposal_id=proposal_id
        )
    except V2StrategicRuleError as error:
        return _reject(state, code=error.code, message=error.message)
    if not support.threshold_reached:
        return _accept(
            support.state,
            code="major_action_supported",
            message=(
                f"Player {player_id!r} supported `{proposal_id}` "
                f"({len(support.proposal.supporter_player_ids)}/"
                f"{support.proposal.required_supporter_count})."
            ),
            strategic_proposal=support.proposal,
        )
    action = _action(pack, support.proposal.action_id)
    if action is None or action_definition_hash(action) != support.proposal.definition_hash:
        return _reject(
            state,
            code="proposal_definition_changed",
            message="The proposed action definition changed; open a new proposal.",
        )
    result = perform_action(
        pack,
        support.state,
        player_id=support.proposal.proposer_player_id,
        action_id=action.id,
        random_source=random_source,
        supporter_player_ids=support.proposal.supporter_player_ids,
        proposal_id=support.proposal.proposal_id,
        proposal_authorized=True,
    )
    if not result.accepted:
        return _reject(state, code=result.code, message=result.message)
    return replace(
        result,
        code="major_action_resolved",
        message=(
            f"Player {player_id!r} supplied the threshold support for "
            f"`{proposal_id}`. {result.message}"
        ),
    )


def pass_strategic_capacity(
    pack: V2InvestigationPack,
    state: V2InvestigationState,
    *,
    player_id: str,
    random_source: V2RandomSource | None = None,
) -> V2KernelResult:
    if state.get_player(player_id) is None:
        return _reject(
            state, code="unknown_player",
            message=f"Player {player_id!r} is not part of this investigation."
        )
    try:
        updated, resolution = pass_capacity(
            pack, state, player_id=player_id, random_source=random_source
        )
    except V2StrategicRuleError as error:
        return _reject(state, code=error.code, message=error.message)
    return _accept(
        updated,
        code="round_capacity_passed",
        message=f"Player {player_id!r} passed the remaining operation capacity.",
        strategic_resolution=resolution,
    )


def _normalize_ids(values: Iterable[str]) -> frozenset[str]:
    normalized = frozenset(value.strip() for value in values)

    if any(not value for value in normalized):
        raise ValueError("identifier collections must not contain blank values")

    return normalized


def draft_assessment(
    pack: V2InvestigationPack,
    state: V2InvestigationState,
    *,
    player_id: str,
    assessment_id: str,
    statement: str,
    evidence_ids: Iterable[str],
    tested_ordinary_explanation_ids: Iterable[str] = (),
    preserved_contradiction_ids: Iterable[str] = (),
    documented_information_gap_ids: Iterable[str] = (),
    confidence: Literal["low", "moderate", "high"] = "low",
    next_collection: str = "No next collection specified.",
    minority_view: str | None = None,
) -> V2KernelResult:
    player = state.get_player(player_id)

    if player is None:
        return _reject(
            state,
            code="unknown_player",
            message=f"Player {player_id!r} is not part of this investigation.",
        )

    normalized_assessment_id = assessment_id.strip()
    normalized_statement = statement.strip()
    normalized_next_collection = next_collection.strip()
    normalized_minority_view = minority_view.strip() if minority_view is not None else None

    if not normalized_assessment_id:
        return _reject(
            state,
            code="invalid_assessment",
            message="Assessment ID must not be blank.",
        )

    if state.get_assessment(normalized_assessment_id) is not None:
        return _reject(
            state,
            code="assessment_id_exists",
            message=f"Assessment {normalized_assessment_id!r} already exists.",
        )

    if not normalized_statement or not normalized_next_collection:
        return _reject(
            state,
            code="invalid_assessment",
            message="Assessment statement and next collection must not be blank.",
        )

    if normalized_minority_view == "":
        return _reject(
            state,
            code="invalid_assessment",
            message="Minority view must be omitted or nonblank.",
        )

    try:
        cited_evidence = _normalize_ids(evidence_ids)
        cited_explanations = _normalize_ids(tested_ordinary_explanation_ids)
        cited_contradictions = _normalize_ids(preserved_contradiction_ids)
        cited_gaps = _normalize_ids(documented_information_gap_ids)
    except ValueError as exc:
        return _reject(
            state,
            code="invalid_assessment",
            message=str(exc),
        )

    if not cited_evidence:
        return _reject(
            state,
            code="assessment_evidence_required",
            message="An assessment must cite at least one examined evidence source.",
        )

    known_evidence = {source.id for source in pack.evidence_sources}
    unknown_evidence = cited_evidence - known_evidence
    if unknown_evidence:
        return _reject(
            state,
            code="unknown_assessment_evidence",
            message=("Assessment cites unknown evidence: " + ", ".join(sorted(unknown_evidence))),
        )

    unexamined_evidence = cited_evidence - state.examined_evidence_ids
    if unexamined_evidence:
        return _reject(
            state,
            code="assessment_evidence_unexamined",
            message=(
                "Assessment cites unexamined evidence: " + ", ".join(sorted(unexamined_evidence))
            ),
        )

    missing_explanations = cited_explanations - state.tested_ordinary_explanation_ids
    if missing_explanations:
        return _reject(
            state,
            code="assessment_explanation_untested",
            message=(
                "Assessment cites untested ordinary explanations: "
                + ", ".join(sorted(missing_explanations))
            ),
        )

    missing_contradictions = cited_contradictions - state.preserved_contradiction_ids
    if missing_contradictions:
        return _reject(
            state,
            code="assessment_contradiction_unpreserved",
            message=(
                "Assessment cites unpreserved contradictions: "
                + ", ".join(sorted(missing_contradictions))
            ),
        )

    missing_gaps = cited_gaps - state.documented_information_gap_ids
    if missing_gaps:
        return _reject(
            state,
            code="assessment_gap_undocumented",
            message=(
                "Assessment cites undocumented information gaps: " + ", ".join(sorted(missing_gaps))
            ),
        )

    assessment = V2AssessmentState(
        id=normalized_assessment_id,
        author_player_id=player_id,
        statement=normalized_statement,
        evidence_ids=cited_evidence,
        tested_ordinary_explanation_ids=cited_explanations,
        preserved_contradiction_ids=cited_contradictions,
        documented_information_gap_ids=cited_gaps,
        confidence=confidence,
        next_collection=normalized_next_collection,
        minority_view=normalized_minority_view,
    )

    updated_state = replace(
        state,
        assessments=state.assessments + (assessment,),
        revision=state.revision + 1,
    )

    return _accept(
        updated_state,
        code="assessment_drafted",
        message=(f"Player {player_id!r} drafted assessment {normalized_assessment_id!r}."),
    )


def confirm_assessment(
    state: V2InvestigationState,
    *,
    player_id: str,
    assessment_id: str,
) -> V2KernelResult:
    player = state.get_player(player_id)

    if player is None:
        return _reject(
            state,
            code="unknown_player",
            message=f"Player {player_id!r} is not part of this investigation.",
        )

    assessment = state.get_assessment(assessment_id)

    if assessment is None:
        return _reject(
            state,
            code="unknown_assessment",
            message=f"Assessment {assessment_id!r} is not defined.",
        )

    if assessment.author_player_id == player_id:
        return _reject(
            state,
            code="author_cannot_confirm",
            message="Assessment authors cannot confirm their own assessment.",
        )

    if player_id in assessment.confirmed_by_player_ids:
        return _reject(
            state,
            code="assessment_already_confirmed",
            message=(f"Player {player_id!r} already confirmed assessment {assessment_id!r}."),
        )

    updated_assessment = replace(
        assessment,
        status="confirmed",
        confirmed_by_player_ids=(assessment.confirmed_by_player_ids | {player_id}),
    )
    updated_assessments = tuple(
        updated_assessment if item.id == assessment.id else item for item in state.assessments
    )
    updated_state = replace(
        state,
        assessments=updated_assessments,
        revision=state.revision + 1,
    )

    return _accept(
        updated_state,
        code="assessment_confirmed",
        message=(f"Player {player_id!r} confirmed assessment {assessment_id!r}."),
    )


def register_promoted_finding(
    state: V2InvestigationState,
    *,
    player_id: str,
    finding_id: str,
    finding_revision: int,
    author_player_id: str,
) -> V2KernelResult:
    if state.get_player(player_id) is None:
        return _reject(
            state,
            code="unknown_player",
            message=f"Player {player_id!r} is not part of this investigation.",
        )
    if state.get_player(author_player_id) is None:
        return _reject(
            state,
            code="unknown_finding_author",
            message=f"Finding author {author_player_id!r} is not part of this investigation.",
        )
    if any(finding.finding_id == finding_id for finding in state.promoted_findings):
        return _reject(
            state,
            code="finding_already_registered",
            message=f"Finding {finding_id!r} already has a registered promoted revision.",
        )
    finding = V2PromotedFindingState(
        finding_id=finding_id,
        revision=finding_revision,
        position_id=state.current_position_id,
        author_player_id=author_player_id,
    )
    return _accept(
        replace(
            state,
            promoted_findings=state.promoted_findings + (finding,),
            revision=state.revision + 1,
            serialization_schema=2,
        ),
        code="promoted_finding_registered",
        message=f"Promoted finding {finding_id!r} revision {finding_revision} was registered.",
    )


def submit_quality_review(
    state: V2InvestigationState,
    *,
    player_id: str,
    subject_kind: Literal["finding", "assessment"],
    subject_id: str,
    subject_revision: int,
    evidence_support: int,
    ordinary_alternatives: int,
    contradictions_preserved: int,
    confidence_calibration: int,
    reproducibility: int,
    rationale: str,
) -> V2KernelResult:
    if state.get_player(player_id) is None:
        return _reject(
            state,
            code="unknown_player",
            message=f"Player {player_id!r} is not part of this investigation.",
        )

    if subject_kind == "assessment":
        assessment = state.get_assessment(subject_id)
        if assessment is None or subject_revision != 1:
            return _reject(
                state,
                code="unknown_subject_revision",
                message="The exact assessment revision is not available for review.",
            )
        if assessment.status != "confirmed":
            return _reject(
                state,
                code="assessment_not_confirmed",
                message="Only a confirmed final assessment can receive a quality review.",
            )
        author_player_id = assessment.author_player_id
        position_id = state.current_position_id
    else:
        finding = next(
            (
                item
                for item in state.promoted_findings
                if item.finding_id == subject_id and item.revision == subject_revision
            ),
            None,
        )
        if finding is None:
            return _reject(
                state,
                code="unknown_subject_revision",
                message="The exact promoted finding revision is not registered.",
            )
        author_player_id = finding.author_player_id
        position_id = finding.position_id

    if position_id != state.current_position_id:
        return _reject(
            state,
            code="review_position_sealed",
            message="Reviews cannot change a completed position.",
        )
    if author_player_id == player_id:
        return _reject(
            state,
            code="author_cannot_review",
            message="Authors cannot review their own work.",
        )
    if any(
        review.subject_kind == subject_kind
        and review.subject_id == subject_id
        and review.subject_revision == subject_revision
        and review.reviewer_player_id == player_id
        for review in state.quality_reviews
    ):
        return _reject(
            state,
            code="quality_review_immutable",
            message="This reviewer already scored the exact subject revision.",
        )

    review = V2QualityReviewState(
        subject_kind=subject_kind,
        subject_id=subject_id,
        subject_revision=subject_revision,
        position_id=position_id,
        author_player_id=author_player_id,
        reviewer_player_id=player_id,
        evidence_support=evidence_support,
        ordinary_alternatives=ordinary_alternatives,
        contradictions_preserved=contradictions_preserved,
        confidence_calibration=confidence_calibration,
        reproducibility=reproducibility,
        rationale=rationale.strip(),
    )
    return _accept(
        replace(
            state,
            quality_reviews=state.quality_reviews + (review,),
            revision=state.revision + 1,
            serialization_schema=2,
        ),
        code="quality_review_submitted",
        message="Peer review recorded for the exact immutable revision.",
    )


def complete_position(
    pack: V2InvestigationPack,
    state: V2InvestigationState,
    *,
    player_id: str,
    assessment_id: str,
) -> V2KernelResult:
    player = state.get_player(player_id)

    if player is None:
        return _reject(
            state,
            code="unknown_player",
            message=f"Player {player_id!r} is not part of this investigation.",
        )

    position = _position(pack, state.current_position_id)

    if position is None:
        return _reject(
            state,
            code="unknown_position",
            message=(f"Current position {state.current_position_id!r} is not defined."),
        )

    if position.id in state.completed_position_ids:
        return _reject(
            state,
            code="position_already_completed",
            message=f"Position {position.id!r} is already completed.",
        )

    assessment = state.get_assessment(assessment_id)

    if assessment is None:
        return _reject(
            state,
            code="unknown_assessment",
            message=f"Assessment {assessment_id!r} is not defined.",
        )

    completion = position.completion

    if assessment.status != "confirmed":
        return _reject(
            state,
            code="assessment_not_confirmed",
            message=f"Assessment {assessment.id!r} is not confirmed.",
        )

    selection = state.get_adaptation_selection(position.id)
    if (
        selection is not None
        and selection.band == "corrective"
        and position.adaptation is not None
        and position.adaptation.corrective.required_action_id is not None
        and position.adaptation.corrective.required_action_id not in state.completed_action_ids
    ):
        return _reject(
            state,
            code="corrective_reconciliation_incomplete",
            message=(
                "Position completion requires the guided reconciliation task: "
                f"{position.adaptation.corrective.required_action_id}"
            ),
        )

    if len(assessment.confirmed_by_player_ids) < completion.minimum_confirmation_count:
        return _reject(
            state,
            code="insufficient_assessment_confirmations",
            message=(
                f"Assessment {assessment.id!r} requires at least "
                f"{completion.minimum_confirmation_count} independent "
                "confirmation(s)."
            ),
        )

    if completion.completion_routes:
        satisfied_route = None
        route_failures: list[str] = []
        for route in completion.completion_routes:
            missing_required = set(route.required_action_ids) - state.completed_action_ids
            completed_candidates = len(
                set(route.candidate_action_ids) & state.completed_action_ids
            )
            process_observations = _effective_stochastic_observation_count(
                pack,
                state,
                route.required_stochastic_process_ids,
            )
            if (
                not missing_required
                and completed_candidates >= route.minimum_completed_action_count
                and process_observations >= route.minimum_stochastic_observation_count
            ):
                satisfied_route = route
                break
            route_failures.append(
                f"{route.title}: {len(missing_required)} required capability/capabilities missing; "
                f"{completed_candidates}/{route.minimum_completed_action_count} route options; "
                f"{process_observations}/{route.minimum_stochastic_observation_count} observations"
            )
        if satisfied_route is None:
            return _reject(
                state,
                code="position_routes_incomplete",
                message="Complete one investigation route. " + " | ".join(route_failures),
            )
    else:
        missing_actions = set(completion.required_completed_action_ids) - state.completed_action_ids
        if missing_actions:
            return _reject(
                state,
                code="position_actions_incomplete",
                message=(
                    "Position completion requires actions: "
                    + ", ".join(sorted(missing_actions))
                ),
            )

    missing_explanations = (
        set(completion.required_tested_ordinary_explanation_ids)
        - state.tested_ordinary_explanation_ids
    )
    if missing_explanations:
        return _reject(
            state,
            code="position_explanations_untested",
            message=(
                "Position completion requires tested ordinary explanations: "
                + ", ".join(sorted(missing_explanations))
            ),
        )

    missing_contradictions = (
        set(completion.required_preserved_contradiction_ids) - state.preserved_contradiction_ids
    )
    if missing_contradictions:
        return _reject(
            state,
            code="position_contradictions_unpreserved",
            message=(
                "Position completion requires preserved contradictions: "
                + ", ".join(sorted(missing_contradictions))
            ),
        )

    missing_gaps = (
        set(completion.required_documented_information_gap_ids)
        - state.documented_information_gap_ids
    )
    if missing_gaps:
        return _reject(
            state,
            code="position_gaps_undocumented",
            message=(
                "Position completion requires documented information gaps: "
                + ", ".join(sorted(missing_gaps))
            ),
        )

    assessment_missing_explanations = (
        set(completion.required_tested_ordinary_explanation_ids)
        - assessment.tested_ordinary_explanation_ids
    )
    if assessment_missing_explanations:
        return _reject(
            state,
            code="assessment_missing_explanations",
            message=(
                "Assessment omits required tested explanations: "
                + ", ".join(sorted(assessment_missing_explanations))
            ),
        )

    assessment_missing_contradictions = (
        set(completion.required_preserved_contradiction_ids)
        - assessment.preserved_contradiction_ids
    )
    if assessment_missing_contradictions:
        return _reject(
            state,
            code="assessment_missing_contradictions",
            message=(
                "Assessment omits required contradictions: "
                + ", ".join(sorted(assessment_missing_contradictions))
            ),
        )

    assessment_missing_gaps = (
        set(completion.required_documented_information_gap_ids)
        - assessment.documented_information_gap_ids
    )
    if assessment_missing_gaps:
        return _reject(
            state,
            code="assessment_missing_gaps",
            message=(
                "Assessment omits required information gaps: "
                + ", ".join(sorted(assessment_missing_gaps))
            ),
        )

    position_entry_evidence = set(position.available_evidence_ids_on_entry)
    if position_entry_evidence and not position_entry_evidence.intersection(
        assessment.evidence_ids
    ):
        return _reject(
            state,
            code="assessment_missing_position_evidence",
            message=(
                f"Assessment {assessment.id!r} does not cite evidence made "
                f"available for position {position.id!r}."
            ),
        )

    evidence_by_id = {source.id: source for source in pack.evidence_sources}
    source_classes = {
        evidence_by_id[evidence_id].source_class
        for evidence_id in assessment.evidence_ids
        if evidence_id in evidence_by_id
    }

    if len(source_classes) < completion.minimum_examined_source_classes:
        return _reject(
            state,
            code="insufficient_source_classes",
            message=(
                f"Assessment cites {len(source_classes)} source class(es); "
                f"{completion.minimum_examined_source_classes} required."
            ),
        )

    role_by_id = {role.id: role for role in pack.roles}
    released_players = tuple(
        replace(member, active_role_id=None)
        if (
            member.active_role_id is not None
            and member.active_role_id in role_by_id
            and role_by_id[member.active_role_id].scope == "position"
        )
        else member
        for member in state.players
    )

    next_position = (
        _position(pack, position.next_position_id)
        if position.next_position_id is not None
        else None
    )

    if position.next_position_id is not None and next_position is None:
        return _reject(
            state,
            code="unknown_next_position",
            message=(
                f"Position {position.id!r} advances to undefined position "
                f"{position.next_position_id!r}."
            ),
        )

    next_position_id = next_position.id if next_position is not None else position.id
    unlocked_location_ids = (
        frozenset(next_position.initially_available_location_ids)
        if next_position is not None
        else frozenset()
    )
    unlocked_evidence_ids = (
        frozenset(next_position.available_evidence_ids_on_entry)
        if next_position is not None
        else frozenset()
    )

    position_reviews = tuple(
        review for review in state.quality_reviews if review.position_id == position.id
    )
    if position_reviews:
        subject_keys = [
            ("finding", finding.finding_id, finding.revision)
            for finding in state.promoted_findings
            if finding.position_id == position.id
        ]
        subject_keys.append(("assessment", assessment.id, 1))
        results: list[Fraction] = []
        for subject_kind, subject_id, subject_revision in subject_keys:
            reviews = tuple(
                review
                for review in position_reviews
                if review.subject_kind == subject_kind
                and review.subject_id == subject_id
                and review.subject_revision == subject_revision
            )
            if not reviews:
                return _reject(
                    state,
                    code="quality_review_incomplete",
                    message=(
                        "Every promoted finding and the final assessment require "
                        "an independent rubric review before quality can be sealed."
                    ),
                )
            results.append(subject_result(reviews))
        exact_position_score = position_result(results)
        quality_seal = V2PositionQualitySealState(
            position_id=position.id,
            position_ordinal=position.ordinal,
            score_numerator=exact_position_score.numerator,
            score_denominator=exact_position_score.denominator,
            reviewed_subject_count=len(results),
            baseline_fallback=False,
        )
    else:
        quality_seal = V2PositionQualitySealState(
            position_id=position.id,
            position_ordinal=position.ordinal,
            score_numerator=None,
            score_denominator=None,
            reviewed_subject_count=0,
            baseline_fallback=True,
        )

    graded_seals = [
        (seal.position_ordinal, seal.score)
        for seal in (*state.position_quality_seals, quality_seal)
        if seal.score is not None
    ]
    selected_band = (
        adaptation_band(
            cumulative_result(
                (ordinal, score) for ordinal, score in graded_seals if score is not None
            )
        )
        if graded_seals
        else "baseline"
    )
    target_id = next_position.id if next_position is not None else "ending"
    if next_position is not None and next_position.adaptation is not None:
        variant = getattr(next_position.adaptation, selected_band)
        presentation_id = variant.presentation_id
        unlocked_evidence_ids |= frozenset(variant.unlock_evidence_ids)
    elif next_position is None and pack.endings is not None:
        presentation_id = getattr(pack.endings, selected_band).presentation_id
    else:
        presentation_id = f"{target_id}_baseline"
        selected_band = "baseline"
    adaptation_selection = V2AdaptationSelectionState(
        target_id=target_id,
        presentation_id=presentation_id,
        band=selected_band,
    )

    strategic_outcome, strategic_tracks, strategic_modifiers = grade_current_position(
        pack, state
    )

    updated_state = replace(
        state,
        current_position_id=next_position_id,
        available_location_ids=(state.available_location_ids | unlocked_location_ids),
        available_evidence_ids=(state.available_evidence_ids | unlocked_evidence_ids),
        players=released_players,
        completed_position_ids=state.completed_position_ids | {position.id},
        position_quality_seals=state.position_quality_seals + (quality_seal,),
        adaptation_selections=state.adaptation_selections + (adaptation_selection,),
        campaign_tracks=strategic_tracks,
        strategic_board=None,
        strategic_position_outcomes=(
            state.strategic_position_outcomes
            + ((strategic_outcome,) if strategic_outcome is not None else ())
        ),
        campaign_modifier_ids=strategic_modifiers,
        revision=state.revision + 1,
        serialization_schema=(4 if strategic_outcome is not None else 2),
    )

    if next_position is None:
        message = (
            f"Player {player_id!r} completed final position {position.id!r} "
            f"using assessment {assessment.id!r}."
        )
    else:
        message = (
            f"Player {player_id!r} completed position {position.id!r} "
            f"and advanced to {next_position.id!r} using assessment "
            f"{assessment.id!r}."
        )

    return _accept(
        updated_state,
        code="position_completed",
        message=message,
    )
