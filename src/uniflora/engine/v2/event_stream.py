from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from uniflora.content.v2.investigation_schema import V2InvestigationPack
from uniflora.content.v2.static_roles import STATIC_ROLES_PACK_ID
from uniflora.engine.v2.commands import (
    ORIENTATION_ASSESSMENT_ID,
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
from uniflora.engine.v2.events import (
    V2ActionPerformedEvent,
    V2ActionProposedEvent,
    V2AssessmentConfirmedEvent,
    V2AssessmentDraftedEvent,
    V2CapacityPassedEvent,
    V2EvidenceExaminedEvent,
    V2InvestigationEvent,
    V2InvestigationInitializedEvent,
    V2PlayerJoinedEvent,
    V2PlayerMovedEvent,
    V2PositionCompletedEvent,
    V2PromotedFindingRegisteredEvent,
    V2ProposalSupportedEvent,
    V2QualityReviewSubmittedEvent,
    V2ReleasedRole,
    V2RoleAssignedEvent,
    V2RoleReleasedEvent,
)
from uniflora.engine.v2.kernel import (
    V2KernelResult,
    assign_role,
    begin_investigation,
    complete_position,
    confirm_assessment,
    draft_assessment,
    examine_evidence,
    initialize_investigation,
    join_investigation,
    move_player,
    pass_strategic_capacity,
    perform_action,
    propose_strategic_action,
    register_promoted_finding,
    release_role,
    submit_quality_review,
    support_strategic_action,
    view_strategic_board,
)
from uniflora.engine.v2.reducer import (
    V2ReplayError,
    apply_event,
    replay_events,
)
from uniflora.engine.v2.state import (
    V2InvestigationState,
    V2StochasticResolutionState,
    V2StrategicProposalState,
    V2StrategicResolutionState,
)
from uniflora.engine.v2.stochastic import V2RandomSource


def _require_nonblank(value: str, *, label: str) -> None:
    if not value.strip():
        raise ValueError(f"{label} must not be blank")


@dataclass(frozen=True, slots=True)
class V2InvestigationStream:
    stream_id: str
    events: tuple[V2InvestigationEvent, ...]
    state: V2InvestigationState

    def __post_init__(self) -> None:
        _require_nonblank(self.stream_id, label="stream ID")

        if not self.events:
            raise ValueError("an investigation stream must contain events")

        if not isinstance(
            self.events[0],
            V2InvestigationInitializedEvent,
        ):
            raise ValueError("an investigation stream must begin with initialization")

        for expected_sequence, event in enumerate(self.events):
            if event.stream_id != self.stream_id:
                raise ValueError("all investigation events must match the stream ID")

            if event.sequence != expected_sequence:
                raise ValueError(
                    f"expected event sequence {expected_sequence}, received {event.sequence}"
                )

        if self.state.revision != self.events[-1].sequence:
            raise ValueError("stream state revision must match the latest event sequence")


@dataclass(frozen=True, slots=True)
class V2RecordedCommandResult:
    accepted: bool
    code: str
    message: str
    stream: V2InvestigationStream
    event: V2InvestigationEvent | None


def initialize_event_stream(
    pack: V2InvestigationPack,
    player_ids: Iterable[str],
    *,
    stream_id: str,
) -> V2InvestigationStream:
    normalized_stream_id = stream_id.strip()
    _require_nonblank(normalized_stream_id, label="stream ID")

    kernel_state = initialize_investigation(pack, player_ids)
    event = V2InvestigationInitializedEvent(
        stream_id=normalized_stream_id,
        sequence=0,
        initial_state=kernel_state,
    )
    reduced_state = apply_event(None, event)

    if reduced_state != kernel_state:
        raise V2ReplayError("initialization event did not reproduce the kernel state")

    return V2InvestigationStream(
        stream_id=normalized_stream_id,
        events=(event,),
        state=reduced_state,
    )


def _execute_kernel_command(
    pack: V2InvestigationPack,
    state: V2InvestigationState,
    command: V2InvestigationCommand,
    *,
    random_source: V2RandomSource | None = None,
) -> V2KernelResult:
    if pack.pack.id == STATIC_ROLES_PACK_ID and not isinstance(
        command,
        (
            V2JoinInvestigationCommand,
            V2BeginInvestigationCommand,
            V2AssignRoleCommand,
            V2ViewStrategicBoardCommand,
        ),
    ):
        player = state.get_player(command.player_id)
        if player is not None and player.active_role_id is None:
            return V2KernelResult(
                accepted=False,
                code="role_required",
                message="Choose one permanent investigative role before taking part.",
                state=state,
            )

    if isinstance(command, V2JoinInvestigationCommand):
        return join_investigation(pack, state, player_id=command.player_id)

    if isinstance(command, V2BeginInvestigationCommand):
        return begin_investigation(
            pack,
            state,
            player_id=command.player_id,
        )

    if isinstance(command, V2AssignRoleCommand):
        return assign_role(
            pack,
            state,
            player_id=command.player_id,
            role_id=command.role_id,
            display_name=command.display_name,
            description=command.description,
        )

    if isinstance(command, V2ReleaseRoleCommand):
        return release_role(
            state,
            player_id=command.player_id,
        )

    if isinstance(command, V2MovePlayerCommand):
        return move_player(
            pack,
            state,
            player_id=command.player_id,
            location_id=command.location_id,
        )

    if isinstance(command, V2ExamineEvidenceCommand):
        return examine_evidence(
            pack,
            state,
            player_id=command.player_id,
            evidence_id=command.evidence_id,
        )

    if isinstance(command, V2PerformActionCommand):
        return perform_action(
            pack,
            state,
            player_id=command.player_id,
            action_id=command.action_id,
            random_source=random_source,
        )

    if isinstance(command, V2ViewStrategicBoardCommand):
        return view_strategic_board(
            pack, state, player_id=command.player_id
        )

    if isinstance(command, V2ProposeActionCommand):
        return propose_strategic_action(
            pack,
            state,
            player_id=command.player_id,
            action_id=command.action_id,
        )

    if isinstance(command, V2SupportActionCommand):
        return support_strategic_action(
            pack,
            state,
            player_id=command.player_id,
            proposal_id=command.proposal_id,
            random_source=random_source,
        )

    if isinstance(command, V2PassCapacityCommand):
        return pass_strategic_capacity(
            pack,
            state,
            player_id=command.player_id,
            random_source=random_source,
        )

    if isinstance(command, V2DraftAssessmentCommand):
        return draft_assessment(
            pack,
            state,
            player_id=command.player_id,
            assessment_id=command.assessment_id,
            statement=command.statement,
            evidence_ids=command.evidence_ids,
            tested_ordinary_explanation_ids=(command.tested_ordinary_explanation_ids),
            preserved_contradiction_ids=(command.preserved_contradiction_ids),
            documented_information_gap_ids=(command.documented_information_gap_ids),
            confidence=command.confidence,
            next_collection=command.next_collection,
            minority_view=command.minority_view,
        )

    if isinstance(command, V2ConfirmAssessmentCommand):
        return confirm_assessment(
            state,
            player_id=command.player_id,
            assessment_id=command.assessment_id,
        )

    if isinstance(command, V2RegisterPromotedFindingCommand):
        return register_promoted_finding(
            state,
            player_id=command.player_id,
            finding_id=command.finding_id,
            finding_revision=command.finding_revision,
            author_player_id=command.author_player_id,
        )

    if isinstance(command, V2SubmitQualityReviewCommand):
        return submit_quality_review(
            state,
            player_id=command.player_id,
            subject_kind=command.subject_kind,
            subject_id=command.subject_id,
            subject_revision=command.subject_revision,
            evidence_support=command.evidence_support,
            ordinary_alternatives=command.ordinary_alternatives,
            contradictions_preserved=command.contradictions_preserved,
            confidence_calibration=command.confidence_calibration,
            reproducibility=command.reproducibility,
            rationale=command.rationale,
        )

    if isinstance(command, V2CompletePositionCommand):
        return complete_position(
            pack,
            state,
            player_id=command.player_id,
            assessment_id=command.assessment_id,
        )

    raise TypeError(f"unsupported v2 investigation command: {type(command)!r}")


def _event_from_transition(
    stream: V2InvestigationStream,
    command: V2InvestigationCommand,
    updated_state: V2InvestigationState,
    *,
    stochastic_resolution: V2StochasticResolutionState | None = None,
    strategic_resolution: V2StrategicResolutionState | None = None,
    strategic_proposal: V2StrategicProposalState | None = None,
) -> V2InvestigationEvent:
    current = stream.state
    sequence = current.revision + 1
    common = {
        "stream_id": stream.stream_id,
        "sequence": sequence,
    }

    if isinstance(command, V2JoinInvestigationCommand):
        player = updated_state.get_player(command.player_id)
        if player is None:
            raise V2ReplayError("accepted player join lacks a recorded player")
        return V2PlayerJoinedEvent(**common, player=player)

    if isinstance(command, V2BeginInvestigationCommand):
        return V2PositionCompletedEvent(
            **common,
            player_id=command.player_id,
            position_id=current.current_position_id,
            assessment_id=ORIENTATION_ASSESSMENT_ID,
            next_position_id=updated_state.current_position_id,
            unlocked_location_ids=(
                updated_state.available_location_ids - current.available_location_ids
            ),
            unlocked_evidence_ids=(
                updated_state.available_evidence_ids - current.available_evidence_ids
            ),
            quality_seal=None,
            adaptation_selection=None,
        )

    if isinstance(command, V2AssignRoleCommand):
        return V2RoleAssignedEvent(
            **common,
            player_id=command.player_id,
            role_id=command.role_id,
            display_name=command.display_name,
            description=command.description,
        )

    if isinstance(command, V2ReleaseRoleCommand):
        player = current.get_player(command.player_id)

        if player is None or player.active_role_id is None:
            raise V2ReplayError("accepted role release lacks a recorded active role")

        return V2RoleReleasedEvent(
            **common,
            player_id=command.player_id,
            role_id=player.active_role_id,
        )

    if isinstance(command, V2MovePlayerCommand):
        player = current.get_player(command.player_id)

        if player is None:
            raise V2ReplayError("accepted player movement lacks a recorded player")

        return V2PlayerMovedEvent(
            **common,
            player_id=command.player_id,
            from_location_id=player.current_location_id,
            to_location_id=command.location_id,
        )

    if isinstance(command, V2ExamineEvidenceCommand):
        return V2EvidenceExaminedEvent(
            **common,
            player_id=command.player_id,
            evidence_id=command.evidence_id,
        )

    if isinstance(command, V2PerformActionCommand):
        return V2ActionPerformedEvent(
            **common,
            player_id=command.player_id,
            action_id=command.action_id,
            unlocked_evidence_ids=(
                updated_state.available_evidence_ids - current.available_evidence_ids
            ),
            tested_ordinary_explanation_ids=(
                updated_state.tested_ordinary_explanation_ids
                - current.tested_ordinary_explanation_ids
            ),
            preserved_contradiction_ids=(
                updated_state.preserved_contradiction_ids - current.preserved_contradiction_ids
            ),
            documented_information_gap_ids=(
                updated_state.documented_information_gap_ids
                - current.documented_information_gap_ids
            ),
            stochastic_resolution=stochastic_resolution,
            strategic_resolution=strategic_resolution,
        )

    if isinstance(command, V2ProposeActionCommand):
        if strategic_proposal is None or updated_state.strategic_board is None:
            raise V2ReplayError("accepted proposal lacks strategic state")
        return V2ActionProposedEvent(
            **common,
            player_id=command.player_id,
            proposal=strategic_proposal,
            board_after=updated_state.strategic_board,
            campaign_tracks_after=updated_state.campaign_tracks,
        )

    if isinstance(command, V2SupportActionCommand):
        if strategic_resolution is not None:
            return V2ActionPerformedEvent(
                **common,
                player_id=strategic_resolution.actor_player_id,
                action_id=strategic_resolution.action_id,
                unlocked_evidence_ids=(
                    updated_state.available_evidence_ids - current.available_evidence_ids
                ),
                tested_ordinary_explanation_ids=(
                    updated_state.tested_ordinary_explanation_ids
                    - current.tested_ordinary_explanation_ids
                ),
                preserved_contradiction_ids=(
                    updated_state.preserved_contradiction_ids
                    - current.preserved_contradiction_ids
                ),
                documented_information_gap_ids=(
                    updated_state.documented_information_gap_ids
                    - current.documented_information_gap_ids
                ),
                stochastic_resolution=stochastic_resolution,
                strategic_resolution=strategic_resolution,
            )
        if strategic_proposal is None or updated_state.strategic_board is None:
            raise V2ReplayError("accepted support lacks strategic state")
        return V2ProposalSupportedEvent(
            **common,
            player_id=command.player_id,
            proposal=strategic_proposal,
            board_after=updated_state.strategic_board,
            campaign_tracks_after=updated_state.campaign_tracks,
        )

    if isinstance(command, V2PassCapacityCommand):
        if strategic_resolution is None:
            raise V2ReplayError("accepted capacity pass lacks strategic resolution")
        return V2CapacityPassedEvent(
            **common,
            player_id=command.player_id,
            strategic_resolution=strategic_resolution,
        )

    if isinstance(command, V2ViewStrategicBoardCommand):
        raise V2ReplayError("read-only strategic board commands cannot produce events")

    if isinstance(command, V2DraftAssessmentCommand):
        assessment = updated_state.get_assessment(command.assessment_id)

        if assessment is None:
            raise V2ReplayError("accepted assessment draft lacks the recorded assessment")

        return V2AssessmentDraftedEvent(
            **common,
            assessment=assessment,
        )

    if isinstance(command, V2ConfirmAssessmentCommand):
        return V2AssessmentConfirmedEvent(
            **common,
            player_id=command.player_id,
            assessment_id=command.assessment_id,
        )

    if isinstance(command, V2RegisterPromotedFindingCommand):
        finding = updated_state.promoted_findings[-1]
        return V2PromotedFindingRegisteredEvent(
            **common,
            finding=finding,
        )

    if isinstance(command, V2SubmitQualityReviewCommand):
        review = updated_state.quality_reviews[-1]
        return V2QualityReviewSubmittedEvent(
            **common,
            review=review,
        )

    if isinstance(command, V2CompletePositionCommand):
        released_roles: list[V2ReleasedRole] = []

        for previous_player in current.players:
            updated_player = updated_state.get_player(previous_player.player_id)

            if updated_player is None:
                raise V2ReplayError("accepted position completion removed a player")

            if previous_player.active_role_id is not None and updated_player.active_role_id is None:
                released_roles.append(
                    V2ReleasedRole(
                        player_id=previous_player.player_id,
                        role_id=previous_player.active_role_id,
                    )
                )

        next_position_id = (
            updated_state.current_position_id
            if updated_state.current_position_id != current.current_position_id
            else None
        )

        return V2PositionCompletedEvent(
            **common,
            player_id=command.player_id,
            position_id=current.current_position_id,
            assessment_id=command.assessment_id,
            next_position_id=next_position_id,
            unlocked_location_ids=(
                updated_state.available_location_ids - current.available_location_ids
            ),
            unlocked_evidence_ids=(
                updated_state.available_evidence_ids - current.available_evidence_ids
            ),
            released_roles=tuple(released_roles),
            quality_seal=(
                updated_state.position_quality_seals[-1]
                if len(updated_state.position_quality_seals)
                > len(current.position_quality_seals)
                else None
            ),
            adaptation_selection=(
                updated_state.adaptation_selections[-1]
                if len(updated_state.adaptation_selections)
                > len(current.adaptation_selections)
                else None
            ),
            strategic_outcome=(
                updated_state.strategic_position_outcomes[-1]
                if len(updated_state.strategic_position_outcomes)
                > len(current.strategic_position_outcomes)
                else None
            ),
            campaign_tracks_after=updated_state.campaign_tracks,
            campaign_modifier_ids_after=updated_state.campaign_modifier_ids,
        )

    raise TypeError(f"unsupported v2 investigation command: {type(command)!r}")


def execute_command(
    pack: V2InvestigationPack,
    stream: V2InvestigationStream,
    command: V2InvestigationCommand,
    *,
    random_source: V2RandomSource | None = None,
) -> V2RecordedCommandResult:
    kernel_result = _execute_kernel_command(
        pack,
        stream.state,
        command,
        random_source=random_source,
    )

    if not kernel_result.accepted:
        return V2RecordedCommandResult(
            accepted=False,
            code=kernel_result.code,
            message=kernel_result.message,
            stream=stream,
            event=None,
        )

    if kernel_result.state == stream.state:
        return V2RecordedCommandResult(
            accepted=True,
            code=kernel_result.code,
            message=kernel_result.message,
            stream=stream,
            event=None,
        )

    event = _event_from_transition(
        stream,
        command,
        kernel_result.state,
        stochastic_resolution=kernel_result.stochastic_resolution,
        strategic_resolution=kernel_result.strategic_resolution,
        strategic_proposal=kernel_result.strategic_proposal,
    )
    reduced_state = apply_event(stream.state, event)

    if reduced_state != kernel_result.state:
        raise V2ReplayError(
            f"kernel transition for {event.event_type!r} diverged from event reduction"
        )

    updated_stream = V2InvestigationStream(
        stream_id=stream.stream_id,
        events=stream.events + (event,),
        state=reduced_state,
    )

    return V2RecordedCommandResult(
        accepted=True,
        code=kernel_result.code,
        message=kernel_result.message,
        stream=updated_stream,
        event=event,
    )


def verify_event_stream(
    stream: V2InvestigationStream,
) -> V2InvestigationState:
    replayed = replay_events(stream.events)

    if replayed != stream.state:
        raise V2ReplayError("event replay does not match the stream's current state")

    return replayed
