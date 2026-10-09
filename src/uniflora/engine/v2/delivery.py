from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from uniflora.content.v2.investigation_schema import (
    V2InvestigationActionDefinition,
    V2InvestigationPack,
    V2InvestigationPositionDefinition,
)
from uniflora.content.v2.static_roles import STATIC_ROLES_PACK_ID
from uniflora.engine.v2.commands import (
    V2AssignRoleCommand,
    V2BeginInvestigationCommand,
    V2CompletePositionCommand,
    V2ConfirmAssessmentCommand,
    V2DraftAssessmentCommand,
    V2ExamineEvidenceCommand,
    V2InvestigationCommand,
    V2JoinInvestigationCommand,
    V2MovePlayerCommand,
    V2PassCapacityCommand,
    V2PerformActionCommand,
    V2ProposeActionCommand,
    V2RegisterPromotedFindingCommand,
    V2ReleaseRoleCommand,
    V2SubmitQualityReviewCommand,
    V2SupportActionCommand,
    V2ViewStrategicBoardCommand,
)
from uniflora.engine.v2.state import V2InvestigationState, V2PlayerState
from uniflora.engine.v2.strategic import (
    action_profile,
    board_text,
    preview_strategic_state,
)

V2SuggestionKind = Literal["ready", "review", "blocked"]


@dataclass(frozen=True, slots=True)
class V2GuidedSuggestion:
    label: str
    command: str
    reason: str
    kind: V2SuggestionKind = "ready"


@dataclass(frozen=True, slots=True)
class V2DeliveryMessage:
    summary: str
    details: tuple[str, ...] = ()


def _position(
    pack: V2InvestigationPack,
    state: V2InvestigationState,
) -> V2InvestigationPositionDefinition:
    position = next(
        (item for item in pack.positions if item.id == state.current_position_id),
        None,
    )
    if position is None:
        raise ValueError(f"unknown current position {state.current_position_id!r}")
    return position


def _player(state: V2InvestigationState, player_id: str) -> V2PlayerState | None:
    return state.get_player(player_id)


def _selected_action_ids(
    pack: V2InvestigationPack,
    state: V2InvestigationState,
) -> frozenset[str]:
    position = _position(pack, state)
    completion = position.completion
    if completion.completion_routes:
        selected = {
            action_id
            for route in completion.completion_routes
            for action_id in (*route.required_action_ids, *route.candidate_action_ids)
        }
    else:
        selected = set(completion.required_completed_action_ids)

    if position.adaptation is not None:
        selection = state.get_adaptation_selection(position.id)
        band = selection.band if selection is not None else "baseline"
        variant = getattr(position.adaptation, band)
        if variant.required_action_id is not None:
            selected.add(variant.required_action_id)
        selected.update(variant.optional_action_ids)

    # Strategic actions are intentionally broader than completion-route actions.
    # Preparation and commitment choices must remain visible even when they are
    # optional and do not gate campaign completion.
    if pack.strategic is not None:
        selected.update(
            action.id
            for action in pack.actions
            if action.position_id == position.id and action.strategic is not None
        )

    actions_by_id = {action.id: action for action in pack.actions}
    changed = True
    while changed:
        changed = False
        for action_id in tuple(selected):
            action = actions_by_id.get(action_id)
            if action is None:
                continue
            before = len(selected)
            selected.update(action.prerequisites.required_completed_action_ids)
            selected.update(action.prerequisites.candidate_completed_action_ids)
            changed = changed or len(selected) != before

    return frozenset(selected)


def relevant_actions(
    pack: V2InvestigationPack,
    state: V2InvestigationState,
) -> tuple[V2InvestigationActionDefinition, ...]:
    selected = _selected_action_ids(pack, state)
    return tuple(action for action in pack.actions if action.id in selected)


def relevant_evidence_ids(
    pack: V2InvestigationPack,
    state: V2InvestigationState,
) -> frozenset[str]:
    position = _position(pack, state)
    evidence_ids = set(position.available_evidence_ids_on_entry)
    for action in relevant_actions(pack, state):
        evidence_ids.update(action.prerequisites.required_examined_evidence_ids)
        evidence_ids.update(action.prerequisites.candidate_examined_evidence_ids)
        evidence_ids.update(action.effects.unlock_evidence_ids)
    return frozenset(evidence_ids)


def _find_unlocking_action(
    pack: V2InvestigationPack,
    state: V2InvestigationState,
    evidence_id: str,
) -> V2InvestigationActionDefinition | None:
    relevant = {action.id for action in relevant_actions(pack, state)}
    return next(
        (
            action
            for action in pack.actions
            if action.id in relevant
            and evidence_id in action.effects.unlock_evidence_ids
        ),
        None,
    )



def _role_allows_location(
    pack: V2InvestigationPack,
    player: V2PlayerState,
    location_id: str,
) -> bool:
    if player.active_role_id is None:
        return True
    role = next((item for item in pack.roles if item.id == player.active_role_id), None)
    return (
        role is None
        or not role.allowed_location_ids
        or location_id in role.allowed_location_ids
    )


def _move_or_release(
    pack: V2InvestigationPack,
    player: V2PlayerState,
    location_id: str,
    *,
    reason: str,
) -> V2GuidedSuggestion:
    if not _role_allows_location(pack, player, location_id):
        return V2GuidedSuggestion(
            label=f"Release {player.active_role_id}",
            command="release-role",
            reason=f"The active function does not permit movement to {location_id}; {reason}",
        )
    return V2GuidedSuggestion(
        label=f"Move to {location_id}",
        command=f"move {location_id}",
        reason=reason,
    )

def _effective_stochastic_observation_count(
    pack: V2InvestigationPack,
    state: V2InvestigationState,
    process_ids: object,
) -> int:
    """Mirror the kernel's pre-overhaul completed-action compatibility rule."""

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


def action_context_blockers(
    pack: V2InvestigationPack,
    action: V2InvestigationActionDefinition,
    state: V2InvestigationState,
) -> tuple[str, ...]:
    """Return spoiler-safe prerequisite blockers for one capability."""

    blockers: list[str] = []
    for required_action_id in action.prerequisites.required_completed_action_ids:
        if required_action_id not in state.completed_action_ids:
            blockers.append(f"action:{required_action_id}")
    for evidence_id in action.prerequisites.required_examined_evidence_ids:
        if evidence_id not in state.examined_evidence_ids:
            blockers.append(f"evidence:{evidence_id}")

    completed_candidates = len(
        set(action.prerequisites.candidate_completed_action_ids)
        & state.completed_action_ids
    )
    if completed_candidates < action.prerequisites.minimum_completed_action_count:
        blockers.append(
            "action-choice:"
            f"{completed_candidates}/"
            f"{action.prerequisites.minimum_completed_action_count}"
        )

    examined_candidates = len(
        set(action.prerequisites.candidate_examined_evidence_ids)
        & state.examined_evidence_ids
    )
    if examined_candidates < action.prerequisites.minimum_examined_evidence_count:
        blockers.append(
            "evidence-choice:"
            f"{examined_candidates}/"
            f"{action.prerequisites.minimum_examined_evidence_count}"
        )

    observations = _effective_stochastic_observation_count(
        pack,
        state,
        action.prerequisites.required_stochastic_process_ids,
    )
    if observations < action.prerequisites.minimum_stochastic_observation_count:
        blockers.append(
            "observation-choice:"
            f"{observations}/"
            f"{action.prerequisites.minimum_stochastic_observation_count}"
        )
    return tuple(blockers)


def _first_step_for_action(
    pack: V2InvestigationPack,
    state: V2InvestigationState,
    player: V2PlayerState,
    action: V2InvestigationActionDefinition,
    *,
    seen: frozenset[str] = frozenset(),
) -> V2GuidedSuggestion | None:
    if action.id in seen or (
        action.id in state.completed_action_ids and not action.repeatable
    ):
        return None

    required_roles = tuple(action.prerequisites.required_role_ids)
    if (
        pack.pack.id == STATIC_ROLES_PACK_ID
        and required_roles
        and player.active_role_id not in required_roles
    ):
        return None

    next_seen = seen | {action.id}
    actions_by_id = {item.id: item for item in pack.actions}
    evidence_by_id = {item.id: item for item in pack.evidence_sources}

    for required_action_id in action.prerequisites.required_completed_action_ids:
        if required_action_id in state.completed_action_ids:
            continue
        prerequisite = actions_by_id.get(required_action_id)
        if prerequisite is not None:
            step = _first_step_for_action(
                pack,
                state,
                player,
                prerequisite,
                seen=next_seen,
            )
            if step is not None:
                return step

    completed_candidates = len(
        set(action.prerequisites.candidate_completed_action_ids)
        & state.completed_action_ids
    )
    if completed_candidates < action.prerequisites.minimum_completed_action_count:
        for candidate_id in action.prerequisites.candidate_completed_action_ids:
            if candidate_id in state.completed_action_ids:
                continue
            prerequisite = actions_by_id.get(candidate_id)
            if prerequisite is None:
                continue
            step = _first_step_for_action(
                pack,
                state,
                player,
                prerequisite,
                seen=next_seen,
            )
            if step is not None:
                return step

    for evidence_id in action.prerequisites.required_examined_evidence_ids:
        if evidence_id in state.examined_evidence_ids:
            continue

        if evidence_id not in state.available_evidence_ids:
            unlocker = _find_unlocking_action(pack, state, evidence_id)
            if unlocker is not None:
                step = _first_step_for_action(
                    pack,
                    state,
                    player,
                    unlocker,
                    seen=next_seen,
                )
                if step is not None:
                    return step
            continue

        evidence = evidence_by_id.get(evidence_id)
        if evidence is None:
            continue
        if player.current_location_id != evidence.origin_location_id:
            if evidence.origin_location_id in state.available_location_ids:
                return _move_or_release(
                    pack,
                    player,
                    evidence.origin_location_id,
                    reason=f"{evidence.name} must be examined there.",
                )
            continue
        return V2GuidedSuggestion(
            label=f"Examine {evidence.name}",
            command=f"examine-evidence {evidence.id}",
            reason=f"Required before {action.title}.",
        )

    examined_candidates = len(
        set(action.prerequisites.candidate_examined_evidence_ids)
        & state.examined_evidence_ids
    )
    if examined_candidates < action.prerequisites.minimum_examined_evidence_count:
        for evidence_id in action.prerequisites.candidate_examined_evidence_ids:
            if evidence_id in state.examined_evidence_ids:
                continue
            if evidence_id not in state.available_evidence_ids:
                unlocker = _find_unlocking_action(pack, state, evidence_id)
                if unlocker is not None:
                    step = _first_step_for_action(
                        pack,
                        state,
                        player,
                        unlocker,
                        seen=next_seen,
                    )
                    if step is not None:
                        return step
                continue
            evidence = evidence_by_id.get(evidence_id)
            if evidence is None:
                continue
            if player.current_location_id != evidence.origin_location_id:
                if evidence.origin_location_id in state.available_location_ids:
                    return _move_or_release(
                        pack,
                        player,
                        evidence.origin_location_id,
                        reason=(
                            f"Choose {action.prerequisites.minimum_examined_evidence_count} "
                            f"supporting record(s) before {action.title}."
                        ),
                    )
                continue
            return V2GuidedSuggestion(
                label=f"Examine {evidence.name}",
                command=f"examine-evidence {evidence.id}",
                reason=(
                    f"Choose {action.prerequisites.minimum_examined_evidence_count} "
                    f"supporting record(s) before {action.title}."
                ),
            )

    if (
        _effective_stochastic_observation_count(
            pack,
            state,
            action.prerequisites.required_stochastic_process_ids,
        )
        < action.prerequisites.minimum_stochastic_observation_count
    ):
        for candidate in relevant_actions(pack, state):
            if candidate.id in state.completed_action_ids:
                continue
            if candidate.stochastic_process_id not in (
                action.prerequisites.required_stochastic_process_ids
            ):
                continue
            step = _first_step_for_action(
                pack,
                state,
                player,
                candidate,
                seen=next_seen,
            )
            if step is not None:
                return step

    if player.current_location_id != action.location_id:
        if action.location_id in state.available_location_ids:
            return _move_or_release(
                pack,
                player,
                action.location_id,
                reason=f"{action.title} is performed there.",
            )
        return None

    if required_roles and player.active_role_id not in required_roles:
        if player.active_role_id is not None:
            return V2GuidedSuggestion(
                label=f"Release {player.active_role_id}",
                command="release-role",
                reason=f"A different function is required for {action.title}.",
            )
        role_id = required_roles[0]
        role = next((item for item in pack.roles if item.id == role_id), None)
        role_name = role.name if role is not None else role_id
        return V2GuidedSuggestion(
            label=f"Assume {role_name}",
            command=f"assign-role {role_id}",
            reason=f"Required for {action.title}.",
        )

    if pack.pack.id == STATIC_ROLES_PACK_ID and action_context_blockers(pack, action, state):
        return None

    if pack.strategic is not None:
        profile = action_profile(action)
        if profile.supporter_count > 0:
            _, board = preview_strategic_state(pack, state)
            proposal = (
                next(
                    (
                        item
                        for item in board.proposals
                        if item.action_id == action.id and item.status == "active"
                    ),
                    None,
                )
                if board is not None
                else None
            )
            if proposal is not None:
                if (
                    proposal.proposer_player_id != player.player_id
                    and player.player_id not in proposal.supporter_player_ids
                ):
                    return V2GuidedSuggestion(
                        label=f"Support {action.title}",
                        command=f"support-action {proposal.proposal_id}",
                        reason=(
                            "An independent participant must support this major "
                            "operation before it resolves."
                        ),
                    )
                return None
            return V2GuidedSuggestion(
                label=f"Propose {action.title}",
                command=f"propose-action {action.id}",
                reason=(
                    f"Major operation: costs {profile.capacity_cost} capacity and "
                    f"requires {profile.supporter_count} independent supporter(s)."
                ),
            )

    return V2GuidedSuggestion(
        label=action.title,
        command=f"perform-action {action.id}",
        reason=action.description,
    )


def completion_route_progress(route: object, state: V2InvestigationState) -> tuple[bool, str]:
    required_action_ids = set(getattr(route, "required_action_ids", ()))
    candidate_action_ids = set(getattr(route, "candidate_action_ids", ()))
    minimum_candidates = int(getattr(route, "minimum_completed_action_count", 0))
    process_ids = tuple(getattr(route, "required_stochastic_process_ids", ()))
    minimum_observations = int(getattr(route, "minimum_stochastic_observation_count", 0))
    missing = required_action_ids - state.completed_action_ids
    candidate_count = len(candidate_action_ids & state.completed_action_ids)
    observation_count = sum(
        state.stochastic_observation_count(process_id) for process_id in process_ids
    )
    satisfied = (
        not missing
        and candidate_count >= minimum_candidates
        and observation_count >= minimum_observations
    )
    details: list[str] = []
    if missing:
        details.append(f"{len(missing)} core capability/capabilities remain")
    if minimum_candidates:
        details.append(f"{candidate_count}/{minimum_candidates} route choices")
    if minimum_observations:
        details.append(f"{observation_count}/{minimum_observations} recorded observations")
    return satisfied, "; ".join(details) or "route requirements met"


def _completion_action_gate(pack: V2InvestigationPack, state: V2InvestigationState) -> bool:
    position = _position(pack, state)
    completion = position.completion
    if completion.completion_routes:
        return any(
            completion_route_progress(route, state)[0]
            for route in completion.completion_routes
        )
    return set(completion.required_completed_action_ids) <= state.completed_action_ids


def _ready_to_draft_assessment(
    pack: V2InvestigationPack,
    state: V2InvestigationState,
) -> bool:
    position = _position(pack, state)
    completion = position.completion
    if not _completion_action_gate(pack, state):
        return False
    if not (
        set(completion.required_tested_ordinary_explanation_ids)
        <= state.tested_ordinary_explanation_ids
    ):
        return False
    if not (
        set(completion.required_preserved_contradiction_ids)
        <= state.preserved_contradiction_ids
    ):
        return False
    if not (
        set(completion.required_documented_information_gap_ids)
        <= state.documented_information_gap_ids
    ):
        return False
    evidence_by_id = {item.id: item for item in pack.evidence_sources}
    source_classes = {
        evidence_by_id[evidence_id].source_class
        for evidence_id in state.examined_evidence_ids
        if evidence_id in evidence_by_id
    }
    return len(source_classes) >= completion.minimum_examined_source_classes


def _assessment_can_complete(
    pack: V2InvestigationPack,
    state: V2InvestigationState,
    assessment: object,
) -> bool:
    position = _position(pack, state)
    completion = position.completion

    if position.id in state.completed_position_ids:
        return False
    if getattr(assessment, "status", None) != "confirmed":
        return False
    if (
        len(getattr(assessment, "confirmed_by_player_ids", frozenset()))
        < completion.minimum_confirmation_count
    ):
        return False

    selection = state.get_adaptation_selection(position.id)
    if (
        selection is not None
        and selection.band == "corrective"
        and position.adaptation is not None
        and position.adaptation.corrective.required_action_id is not None
        and position.adaptation.corrective.required_action_id
        not in state.completed_action_ids
    ):
        return False

    if not _completion_action_gate(pack, state):
        return False
    if not (
        set(completion.required_tested_ordinary_explanation_ids)
        <= state.tested_ordinary_explanation_ids
    ):
        return False
    if not (
        set(completion.required_preserved_contradiction_ids)
        <= state.preserved_contradiction_ids
    ):
        return False
    if not (
        set(completion.required_documented_information_gap_ids)
        <= state.documented_information_gap_ids
    ):
        return False

    assessment_evidence = getattr(assessment, "evidence_ids", frozenset())
    if not (
        set(completion.required_tested_ordinary_explanation_ids)
        <= getattr(assessment, "tested_ordinary_explanation_ids", frozenset())
    ):
        return False
    if not (
        set(completion.required_preserved_contradiction_ids)
        <= getattr(assessment, "preserved_contradiction_ids", frozenset())
    ):
        return False
    if not (
        set(completion.required_documented_information_gap_ids)
        <= getattr(assessment, "documented_information_gap_ids", frozenset())
    ):
        return False

    entry_evidence = set(position.available_evidence_ids_on_entry)
    if entry_evidence and not entry_evidence.intersection(assessment_evidence):
        return False

    evidence_by_id = {item.id: item for item in pack.evidence_sources}
    source_classes = {
        evidence_by_id[evidence_id].source_class
        for evidence_id in assessment_evidence
        if evidence_id in evidence_by_id
    }
    if len(source_classes) < completion.minimum_examined_source_classes:
        return False

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
        for subject_kind, subject_id, subject_revision in subject_keys:
            if not any(
                review.subject_kind == subject_kind
                and review.subject_id == subject_id
                and review.subject_revision == subject_revision
                for review in position_reviews
            ):
                return False

    return True


def _assessment_suggestions(
    pack: V2InvestigationPack,
    state: V2InvestigationState,
    player: V2PlayerState,
) -> tuple[V2GuidedSuggestion, ...]:
    suggestions: list[V2GuidedSuggestion] = []

    for assessment in state.assessments:
        if (
            assessment.status == "draft"
            and assessment.author_player_id != player.player_id
            and player.player_id not in assessment.confirmed_by_player_ids
        ):
            suggestions.append(
                V2GuidedSuggestion(
                    label=f"Confirm assessment {assessment.id}",
                    command=f"confirm-assessment {assessment.id}",
                    reason="Independent confirmation is required.",
                )
            )

    position = _position(pack, state)
    for assessment in state.assessments:
        if not _assessment_can_complete(pack, state, assessment):
            continue
        suggestions.append(
            V2GuidedSuggestion(
                label=f"Complete {position.title}",
                command=f"complete-position {assessment.id}",
                reason="The confirmed assessment can be checked against completion rules.",
            )
        )

    return tuple(suggestions)


def guided_suggestions(
    pack: V2InvestigationPack,
    state: V2InvestigationState,
    player_id: str,
    current: str = "",
    *,
    limit: int = 25,
) -> tuple[V2GuidedSuggestion, ...]:
    player = _player(state, player_id)
    if player is None:
        return ()

    position = _position(pack, state)
    suggestions: list[V2GuidedSuggestion] = []

    if pack.pack.id == STATIC_ROLES_PACK_ID and player.active_role_id is None:
        suggestions.extend(
            V2GuidedSuggestion(
                label=f"Choose {role.name}",
                command=f"assign-role {role.id}",
                reason="This role remains yours throughout the campaign.",
            )
            for role in pack.roles
        )
        return tuple(
            suggestion for suggestion in suggestions
            if not current or current.casefold() in suggestion.label.casefold()
        )[:limit]

    if position.id == "network_orientation":
        suggestions.append(
            V2GuidedSuggestion(
                label="Begin the investigation",
                command="begin-investigation",
                reason="Complete Position 0 and open Position 1.",
            )
        )
    else:
        for action in relevant_actions(pack, state):
            step = _first_step_for_action(pack, state, player, action)
            if step is not None:
                suggestions.append(step)

        evidence_by_id = {item.id: item for item in pack.evidence_sources}
        for evidence_id in sorted(relevant_evidence_ids(pack, state)):
            if evidence_id not in state.examined_evidence_ids:
                continue
            evidence = evidence_by_id.get(evidence_id)
            if evidence is None or evidence.origin_location_id != player.current_location_id:
                continue
            suggestions.append(
                V2GuidedSuggestion(
                    label=f"Reopen {evidence.name}",
                    command=f"examine-evidence {evidence.id}",
                    reason="Review the complete source record without advancing the sequence.",
                    kind="review",
                )
            )

        suggestions.extend(_assessment_suggestions(pack, state, player))

    deduplicated: list[V2GuidedSuggestion] = []
    seen_commands: set[str] = set()
    query = current.strip().casefold()
    for suggestion in suggestions:
        if suggestion.command in seen_commands:
            continue
        if query and not (
            query in suggestion.label.casefold()
            or query in suggestion.command.casefold()
            or query in suggestion.reason.casefold()
        ):
            continue
        seen_commands.add(suggestion.command)
        deduplicated.append(suggestion)
        if len(deduplicated) >= limit:
            break

    return tuple(deduplicated)


def next_requirement(
    pack: V2InvestigationPack,
    state: V2InvestigationState,
    player_id: str | None = None,
) -> str:
    selected_player_id = player_id
    if selected_player_id is None:
        selected_player_id = next(
            (
                player.player_id
                for player in state.players
                if player.player_id.startswith(("discord:", "web:"))
            ),
            state.players[0].player_id if state.players else None,
        )

    position = _position(pack, state)
    if position.id in state.completed_position_ids:
        return "The investigation is complete; review the distributed record."
    if selected_player_id is not None and pack.pack.id == STATIC_ROLES_PACK_ID:
        selected_player = state.get_player(selected_player_id)
        if selected_player is not None and selected_player.active_role_id is None:
            return "Choose one permanent investigative role before taking part."
    if not state.assessments and _ready_to_draft_assessment(pack, state):
        return "Draft an assessment from the examined source classes and recorded tests."

    if selected_player_id is not None:
        suggestions = guided_suggestions(
            pack,
            state,
            selected_player_id,
            limit=25,
        )
        suggestion = next(
            (
                item
                for item in suggestions
                if item.kind != "review"
            ),
            None,
        )
        if suggestion is not None:
            return f"{suggestion.label}. Use `{suggestion.command}`."

    if not state.assessments:
        return "Choose an investigation route, examine its sources, and resolve its capabilities."
    return "Review the current assessment and completion requirements."


def _bullet_block(title: str, values: tuple[str, ...]) -> str | None:
    if not values:
        return None
    return title + "\n" + "\n".join(f"• {item}" for item in values)


def render_evidence(
    pack: V2InvestigationPack,
    state: V2InvestigationState,
    player_id: str,
    evidence_id: str,
    *,
    reopened: bool,
) -> V2DeliveryMessage:
    source = next((item for item in pack.evidence_sources if item.id == evidence_id), None)
    if source is None:
        return V2DeliveryMessage(summary=f"Evidence {evidence_id}")

    instrument = next(
        (item for item in pack.instruments if item.id == source.instrument_id),
        None,
    )
    metadata = (
        f"Evidence ID: `{source.id}`",
        f"Source class: `{source.source_class}`",
        f"Origin: `{source.origin_location_id}`",
        "Instrument: "
        + (instrument.name if instrument is not None else source.instrument_id or "not specified"),
        f"Record type: `{source.raw_or_derived}`",
    )

    sections = [
        *metadata,
        f"Provenance\n{source.provenance}",
        f"Uncertainty\n{source.uncertainty}",
        _bullet_block("Supported conclusions", source.supported_conclusions),
        _bullet_block("Limitations", source.limitations),
        _bullet_block("Processing history", source.processing_history),
        _bullet_block("Not established by this source", source.unsupported_extrapolations),
    ]

    requirement = next_requirement(pack, state, player_id)
    sections.append(f"Next useful step\n{requirement}")

    sections.append(
        "Review note: this source was already in the record; no new event was added."
        if reopened
        else "Progress note: this source was added to the examined evidence record."
    )

    return V2DeliveryMessage(
        summary=f"{source.name} — {'reopened' if reopened else 'examined'}",
        details=tuple(item for item in sections if item is not None),
    )


def render_action(
    pack: V2InvestigationPack,
    before: V2InvestigationState,
    after: V2InvestigationState,
    player_id: str,
    action_id: str,
) -> V2DeliveryMessage:
    action = next((item for item in pack.actions if item.id == action_id), None)
    if action is None:
        return V2DeliveryMessage(summary=f"Action {action_id} completed")

    evidence_by_id = {item.id: item for item in pack.evidence_sources}
    explanation_by_id = {item.id: item for item in pack.ordinary_explanations}
    contradiction_by_id = {item.id: item for item in pack.contradictions}
    gap_by_id = {item.id: item for item in pack.information_gaps}

    unlocked = after.available_evidence_ids - before.available_evidence_ids
    explanations = (
        after.tested_ordinary_explanation_ids - before.tested_ordinary_explanation_ids
    )
    contradictions = (
        after.preserved_contradiction_ids - before.preserved_contradiction_ids
    )
    gaps = after.documented_information_gap_ids - before.documented_information_gap_ids

    sections: list[str | None] = [action.description]
    new_observations = after.stochastic_observations[len(before.stochastic_observations) :]
    if new_observations:
        observation = new_observations[-1]
        observation_lines = [observation.public_summary]
        if observation.measurements:
            observation_lines.extend(
                "• "
                + f"{item.key.replace('_', ' ')}: {item.value}"
                + (f" {item.unit}" if item.unit else "")
                + (f" ({item.uncertainty})" if item.uncertainty else "")
                for item in observation.measurements
            )
        support = after.get_stochastic_support(observation.process_id)
        if support is not None:
            observation_lines.append("Working model support — not a conclusion")
            observation_lines.extend(
                f"• {item.model_id.replace('_', ' ')}: {item.basis_points / 100:.1f}%"
                for item in sorted(
                    support.models,
                    key=lambda candidate: (-candidate.basis_points, candidate.model_id),
                )
            )
        sections.append("Observed result\n" + "\n".join(observation_lines))
    if unlocked:
        sections.append(
            "Unlocked evidence\n"
            + "\n".join(
                f"• {evidence_by_id[item].name} (`{item}`)"
                if item in evidence_by_id
                else f"• `{item}`"
                for item in sorted(unlocked)
            )
        )
    if explanations:
        sections.append(
            "Ordinary explanations tested\n"
            + "\n".join(
                f"• {explanation_by_id[item].title} (`{item}`)"
                if item in explanation_by_id
                else f"• `{item}`"
                for item in sorted(explanations)
            )
        )
    if contradictions:
        sections.append(
            "Contradictions preserved\n"
            + "\n".join(
                f"• {contradiction_by_id[item].title} (`{item}`)"
                if item in contradiction_by_id
                else f"• `{item}`"
                for item in sorted(contradictions)
            )
        )
    if gaps:
        sections.append(
            "Information gaps documented\n"
            + "\n".join(
                f"• {gap_by_id[item].title} (`{item}`)"
                if item in gap_by_id
                else f"• `{item}`"
                for item in sorted(gaps)
            )
        )

    suggestion = guided_suggestions(pack, after, player_id, limit=1)
    if suggestion:
        sections.append(
            f"Next useful step\n`{suggestion[0].command}` — {suggestion[0].reason}"
        )

    return V2DeliveryMessage(
        summary=action.title,
        details=tuple(item for item in sections if item is not None),
    )


def render_role(
    pack: V2InvestigationPack,
    state: V2InvestigationState,
    player_id: str,
    role_id: str,
) -> V2DeliveryMessage:
    role = next((item for item in pack.roles if item.id == role_id), None)
    if role is None:
        return V2DeliveryMessage(summary=f"Role {role_id} assigned")

    player = state.get_player(player_id)
    public_name = (
        getattr(player, "active_role_display_name", None)
        if player is not None
        else None
    )
    capabilities = tuple(
        action
        for action in relevant_actions(pack, state)
        if role.id in action.prerequisites.required_role_ids
        and action.id not in state.completed_action_ids
    )
    details: list[str] = [
        role.description,
        f"Scope: `{role.scope}`",
        "Allowed locations: "
        + (
            ", ".join(f"`{item}`" for item in role.allowed_location_ids)
            or "current investigation network"
        ),
    ]
    if public_name:
        details.insert(0, f"Public title: {public_name}")
    if capabilities:
        details.append(
            "Current capabilities\n"
            + "\n".join(
                f"• {action.title} — `perform-action {action.id}`"
                for action in capabilities
            )
        )
    suggestion = guided_suggestions(pack, state, player_id, limit=1)
    if suggestion:
        details.append(
            f"Next useful step\n`{suggestion[0].command}` — {suggestion[0].reason}"
        )
    return V2DeliveryMessage(
        summary=f"Role assigned — {public_name or role.name}",
        details=tuple(details),
    )


def _assessment_template(
    pack: V2InvestigationPack,
    state: V2InvestigationState,
) -> str:
    position = _position(pack, state)
    completion = position.completion
    evidence = ",".join(sorted(state.examined_evidence_ids)) or "evidence_id"
    ordinary = ",".join(completion.required_tested_ordinary_explanation_ids)
    contradictions = ",".join(completion.required_preserved_contradiction_ids)
    gaps = ",".join(completion.required_documented_information_gap_ids)
    parts = [
        f"draft-assessment {position.id}_assessment",
        '--statement "State only what the examined records support."',
        f"--evidence {evidence}",
    ]
    if ordinary:
        parts.append(f"--ordinary {ordinary}")
    if contradictions:
        parts.append(f"--contradictions {contradictions}")
    if gaps:
        parts.append(f"--gaps {gaps}")
    parts.extend(
        (
            "--confidence moderate",
            '--next-collection "Name the most useful missing observation."',
        )
    )
    return " ".join(parts)


def build_position_guide(
    pack: V2InvestigationPack,
    state: V2InvestigationState,
    player_id: str,
) -> str:
    position = _position(pack, state)
    evidence_by_id = {item.id: item for item in pack.evidence_sources}
    lines = [f"**Position {position.ordinal} — {position.title}**"]

    if position.fixed_opening is not None:
        lines.extend(("", position.fixed_opening.prologue))
    else:
        selection = state.get_adaptation_selection(position.id)
        if selection is not None and position.adaptation is not None:
            variant = getattr(position.adaptation, selection.band)
            lines.extend(("", variant.prologue))

    if pack.strategic is not None and position.id != "network_orientation":
        lines.extend(("", "**Strategic board**", board_text(pack, state)))

    lines.extend(("", "**Evidence record**"))
    for evidence_id in sorted(relevant_evidence_ids(pack, state)):
        evidence = evidence_by_id.get(evidence_id)
        name = evidence.name if evidence is not None else evidence_id
        if evidence_id in state.examined_evidence_ids:
            mark = "✓ examined"
        elif evidence_id in state.available_evidence_ids:
            mark = "○ available"
        else:
            mark = "◇ locked"
        lines.append(f"• {mark} — {name} (`{evidence_id}`)")

    completion = position.completion
    if completion.completion_routes:
        lines.extend(("", "**Investigation routes — complete any one**"))
        for route in completion.completion_routes:
            satisfied, progress = completion_route_progress(route, state)
            mark = "✓" if satisfied else "○"
            lines.append(f"• {mark} **{route.title}** — {route.description}")
            lines.append(f"  {progress}")

    lines.extend(("", "**Capabilities**"))
    for action in relevant_actions(pack, state):
        if action.id in state.completed_action_ids:
            mark = "✓ resolved"
        else:
            mark = (
                "○ available"
                if not action_context_blockers(pack, action, state)
                else "◇ developing"
            )
        process_note = " · variable observation" if action.stochastic_process_id else ""
        strategic_note = ""
        if pack.strategic is not None:
            profile = action_profile(action)
            strategic_note = f" · {profile.capacity_cost} capacity"
            if profile.coordination_cost:
                strategic_note += f" · {profile.coordination_cost} coordination"
            if profile.supporter_count:
                strategic_note += f" · propose + {profile.supporter_count} supporter(s)"
        lines.append(
            f"• {mark} — {action.title} (`{action.id}`)"
            f"{process_note}{strategic_note}"
        )

    position_process_ids = {
        process_id
        for route in completion.completion_routes
        for process_id in route.required_stochastic_process_ids
    }
    recent_observations = [
        item for item in state.stochastic_observations if item.process_id in position_process_ids
    ][-3:]
    if recent_observations:
        lines.extend(("", "**Recent observed results**"))
        for observation in recent_observations:
            lines.append(
                f"• sequence {observation.sequence} · {observation.public_summary}"
            )

    lines.extend(("", "**Completion record**"))
    for label, required, completed in (
        (
            "ordinary explanation",
            completion.required_tested_ordinary_explanation_ids,
            state.tested_ordinary_explanation_ids,
        ),
        (
            "contradiction",
            completion.required_preserved_contradiction_ids,
            state.preserved_contradiction_ids,
        ),
        (
            "information gap",
            completion.required_documented_information_gap_ids,
            state.documented_information_gap_ids,
        ),
    ):
        for item_id in required:
            mark = "✓" if item_id in completed else "○"
            lines.append(f"• {mark} {label}: `{item_id}`")

    if state.assessments:
        lines.extend(("", "**Assessments**"))
        for assessment in state.assessments:
            lines.append(
                f"• `{assessment.id}` — {assessment.status}; "
                f"{len(assessment.confirmed_by_player_ids)} confirmation(s)"
            )

    suggestions = guided_suggestions(pack, state, player_id, limit=1)
    lines.extend(("", "**Recommended next step**"))
    if not state.assessments and _ready_to_draft_assessment(pack, state):
        lines.extend(
            (
                "Draft the position assessment.",
                "Copy and edit this template:",
                f"`{_assessment_template(pack, state)}`",
            )
        )
    elif suggestions:
        suggestion = suggestions[0]
        lines.extend(
            (
                suggestion.label,
                f"`{suggestion.command}`",
                suggestion.reason,
            )
        )
    elif not state.assessments:
        lines.append("Continue one investigation route; not every capability is required.")
    else:
        lines.append("Review the current assessment and completion checks.")

    return "\n".join(lines)


def _render_rejection(
    pack: V2InvestigationPack,
    state: V2InvestigationState,
    player_id: str,
    message: str,
) -> V2DeliveryMessage:
    details: list[str] = []
    suggestions = guided_suggestions(pack, state, player_id, limit=1)
    if suggestions:
        suggestion = suggestions[0]
        details.append(
            f"Next valid step\n`{suggestion.command}` — {suggestion.reason}"
        )
    return V2DeliveryMessage(summary=message, details=tuple(details))


def render_command_delivery(
    pack: V2InvestigationPack,
    before: V2InvestigationState,
    after: V2InvestigationState,
    command: V2InvestigationCommand,
    *,
    accepted: bool,
    code: str,
    message: str,
) -> V2DeliveryMessage:
    player_id = getattr(command, "player_id", "")
    if not accepted:
        return _render_rejection(pack, after, player_id, message)

    if isinstance(command, V2ExamineEvidenceCommand):
        return render_evidence(
            pack,
            after,
            player_id,
            command.evidence_id,
            reopened=(code == "evidence_reopened" or before == after),
        )

    if isinstance(command, V2PerformActionCommand):
        return render_action(pack, before, after, player_id, command.action_id)

    if isinstance(command, V2ViewStrategicBoardCommand):
        return V2DeliveryMessage(
            summary="Strategic board",
            details=(board_text(pack, after),),
        )

    if isinstance(command, V2ProposeActionCommand):
        proposal = (
            after.strategic_board.proposals[-1]
            if after.strategic_board is not None and after.strategic_board.proposals
            else None
        )
        support = (
            f"Use `support-action {proposal.proposal_id}` from an independent "
            "participant."
            if proposal is not None
            else "Independent support is required."
        )
        return V2DeliveryMessage(
            summary=f"Major operation proposed — {command.action_id}",
            details=(support, board_text(pack, after)),
        )

    if isinstance(command, V2SupportActionCommand):
        return V2DeliveryMessage(
            summary=message,
            details=(board_text(pack, after),),
        )

    if isinstance(command, V2PassCapacityCommand):
        return V2DeliveryMessage(
            summary=message,
            details=(board_text(pack, after),),
        )

    if isinstance(command, V2AssignRoleCommand):
        return render_role(pack, after, player_id, command.role_id)

    if isinstance(command, V2MovePlayerCommand):
        suggestion = guided_suggestions(pack, after, player_id, limit=1)
        details = (
            f"Next useful step\n`{suggestion[0].command}` — {suggestion[0].reason}",
        ) if suggestion else ()
        return V2DeliveryMessage(
            summary=f"Arrived at {command.location_id}",
            details=details,
        )

    if isinstance(command, V2ReleaseRoleCommand):
        suggestion = guided_suggestions(pack, after, player_id, limit=1)
        details = (
            f"Next useful step\n`{suggestion[0].command}` — {suggestion[0].reason}",
        ) if suggestion else ()
        return V2DeliveryMessage(summary="Role released", details=details)

    if isinstance(command, (V2BeginInvestigationCommand, V2CompletePositionCommand)):
        return V2DeliveryMessage(
            summary=message,
            details=(build_position_guide(pack, after, player_id),),
        )

    if isinstance(command, V2DraftAssessmentCommand):
        return V2DeliveryMessage(
            summary=f"Assessment drafted — {command.assessment_id}",
            details=(
                command.statement,
                "Independent confirmation is now required.",
            ),
        )

    if isinstance(command, V2ConfirmAssessmentCommand):
        suggestion = guided_suggestions(pack, after, player_id, limit=1)
        details = (
            f"Next useful step\n`{suggestion[0].command}` — {suggestion[0].reason}",
        ) if suggestion else ()
        return V2DeliveryMessage(
            summary=f"Assessment confirmed — {command.assessment_id}",
            details=details,
        )

    if isinstance(command, V2JoinInvestigationCommand):
        return V2DeliveryMessage(
            summary="Joined the shared investigation",
            details=(next_requirement(pack, after, player_id),),
        )

    if isinstance(command, V2RegisterPromotedFindingCommand):
        return V2DeliveryMessage(
            summary=(
                f"Finding registered — {command.finding_id} "
                f"revision {command.finding_revision}"
            ),
        )

    if isinstance(command, V2SubmitQualityReviewCommand):
        return V2DeliveryMessage(
            summary=f"Quality review recorded — {command.subject_id}",
            details=(command.rationale,),
        )

    return V2DeliveryMessage(summary=message)


__all__ = [
    "V2DeliveryMessage",
    "V2GuidedSuggestion",
    "build_position_guide",
    "guided_suggestions",
    "next_requirement",
    "relevant_actions",
    "relevant_evidence_ids",
    "render_command_delivery",
    "render_evidence",
]
