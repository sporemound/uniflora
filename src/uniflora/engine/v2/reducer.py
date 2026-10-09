from __future__ import annotations

from collections.abc import Iterable
from dataclasses import replace

from uniflora.engine.v2.commands import (
    ORIENTATION_ASSESSMENT_ID,
    ORIENTATION_POSITION_ID,
)
from uniflora.engine.v2.events import (
    V2ActionPerformedEvent,
    V2ActionProposedEvent,
    V2CapacityPassedEvent,
    V2ProposalSupportedEvent,
    V2AssessmentConfirmedEvent,
    V2AssessmentDraftedEvent,
    V2EvidenceExaminedEvent,
    V2InvestigationEvent,
    V2InvestigationInitializedEvent,
    V2PlayerJoinedEvent,
    V2PlayerMovedEvent,
    V2PositionCompletedEvent,
    V2PromotedFindingRegisteredEvent,
    V2QualityReviewSubmittedEvent,
    V2RoleAssignedEvent,
    V2RoleReleasedEvent,
)
from uniflora.engine.v2.stochastic import apply_stochastic_resolution
from uniflora.engine.v2.strategic import apply_recorded_strategic_resolution
from uniflora.engine.v2.state import (
    V2AssessmentState,
    V2InvestigationState,
    V2PlayerState,
)


class V2ReplayError(ValueError):
    """Raised when an event stream cannot be reduced deterministically."""


def _require_state(
    state: V2InvestigationState | None,
    event: V2InvestigationEvent,
) -> V2InvestigationState:
    if state is None:
        raise V2ReplayError(f"event {event.event_type!r} cannot occur before initialization")

    expected_sequence = state.revision + 1

    if event.sequence != expected_sequence:
        raise V2ReplayError(
            f"event sequence {event.sequence} does not follow state revision {state.revision}"
        )

    return state


def _require_player(
    state: V2InvestigationState,
    player_id: str,
) -> V2PlayerState:
    player = state.get_player(player_id)

    if player is None:
        raise V2ReplayError(f"event references unknown player {player_id!r}")

    return player


def _replace_player(
    state: V2InvestigationState,
    updated_player: V2PlayerState,
    *,
    revision: int,
) -> V2InvestigationState:
    players = tuple(
        updated_player if player.player_id == updated_player.player_id else player
        for player in state.players
    )

    return replace(
        state,
        players=players,
        revision=revision,
    )


def _replace_assessment(
    state: V2InvestigationState,
    updated_assessment: V2AssessmentState,
    *,
    revision: int,
) -> V2InvestigationState:
    assessments = tuple(
        updated_assessment if assessment.id == updated_assessment.id else assessment
        for assessment in state.assessments
    )

    return replace(
        state,
        assessments=assessments,
        revision=revision,
    )


def apply_event(
    state: V2InvestigationState | None,
    event: V2InvestigationEvent,
) -> V2InvestigationState:
    if isinstance(event, V2InvestigationInitializedEvent):
        if state is not None:
            raise V2ReplayError("investigation initialization must be the first event")

        return event.initial_state

    current = _require_state(state, event)

    if isinstance(event, V2PlayerJoinedEvent):
        if current.get_player(event.player.player_id) is not None:
            raise V2ReplayError(f"player {event.player.player_id!r} joined more than once")
        if event.player.current_location_id not in current.available_location_ids:
            raise V2ReplayError(
                f"joined player occupies unavailable location {event.player.current_location_id!r}"
            )
        return replace(
            current,
            players=current.players + (event.player,),
            revision=event.sequence,
            serialization_schema=max(current.serialization_schema, 2),
        )

    if isinstance(event, V2RoleAssignedEvent):
        player = _require_player(current, event.player_id)

        if player.active_role_id is not None:
            raise V2ReplayError(
                f"player {player.player_id!r} already holds role {player.active_role_id!r}"
            )

        return _replace_player(
            current,
            replace(
                player,
                active_role_id=event.role_id,
                active_role_display_name=event.display_name,
                active_role_description=event.description,
            ),
            revision=event.sequence,
        )

    if isinstance(event, V2RoleReleasedEvent):
        player = _require_player(current, event.player_id)

        if player.active_role_id != event.role_id:
            raise V2ReplayError(
                f"player {player.player_id!r} does not hold recorded role {event.role_id!r}"
            )

        return _replace_player(
            current,
            replace(
                player,
                active_role_id=None,
                active_role_display_name=None,
                active_role_description=None,
            ),
            revision=event.sequence,
        )

    if isinstance(event, V2PlayerMovedEvent):
        player = _require_player(current, event.player_id)

        if player.current_location_id != event.from_location_id:
            raise V2ReplayError(
                f"player {player.player_id!r} is not at recorded origin {event.from_location_id!r}"
            )

        if event.to_location_id not in current.available_location_ids:
            raise V2ReplayError(f"destination {event.to_location_id!r} is not available")

        return _replace_player(
            current,
            replace(
                player,
                current_location_id=event.to_location_id,
            ),
            revision=event.sequence,
        )

    if isinstance(event, V2EvidenceExaminedEvent):
        _require_player(current, event.player_id)

        if event.evidence_id not in current.available_evidence_ids:
            raise V2ReplayError(f"evidence {event.evidence_id!r} is not available")

        if event.evidence_id in current.examined_evidence_ids:
            raise V2ReplayError(f"evidence {event.evidence_id!r} was already examined")

        return replace(
            current,
            examined_evidence_ids=(current.examined_evidence_ids | {event.evidence_id}),
            revision=event.sequence,
        )

    if isinstance(event, V2ActionPerformedEvent):
        _require_player(current, event.player_id)
        replay_state = current
        if event.stochastic_resolution is not None:
            replay_state = apply_stochastic_resolution(
                replay_state,
                event.stochastic_resolution,
                sequence=event.sequence,
            )

        replay_state = replace(
            replay_state,
            available_evidence_ids=(
                replay_state.available_evidence_ids | event.unlocked_evidence_ids
            ),
            completed_action_ids=(replay_state.completed_action_ids | {event.action_id}),
            tested_ordinary_explanation_ids=(
                replay_state.tested_ordinary_explanation_ids
                | event.tested_ordinary_explanation_ids
            ),
            preserved_contradiction_ids=(
                replay_state.preserved_contradiction_ids | event.preserved_contradiction_ids
            ),
            documented_information_gap_ids=(
                replay_state.documented_information_gap_ids
                | event.documented_information_gap_ids
            ),
            revision=event.sequence,
        )
        if event.strategic_resolution is not None:
            replay_state = apply_recorded_strategic_resolution(
                replay_state,
                event.strategic_resolution,
                sequence=event.sequence,
            )
        return replay_state

    if isinstance(event, V2ActionProposedEvent):
        _require_player(current, event.player_id)
        return replace(
            current,
            campaign_tracks=event.campaign_tracks_after,
            strategic_board=event.board_after,
            revision=event.sequence,
            serialization_schema=4,
        )

    if isinstance(event, V2ProposalSupportedEvent):
        _require_player(current, event.player_id)
        return replace(
            current,
            campaign_tracks=event.campaign_tracks_after,
            strategic_board=event.board_after,
            revision=event.sequence,
            serialization_schema=4,
        )

    if isinstance(event, V2CapacityPassedEvent):
        _require_player(current, event.player_id)
        return apply_recorded_strategic_resolution(
            current,
            event.strategic_resolution,
            sequence=event.sequence,
        )

    if isinstance(event, V2AssessmentDraftedEvent):
        if current.get_assessment(event.assessment.id) is not None:
            raise V2ReplayError(f"assessment {event.assessment.id!r} already exists")

        return replace(
            current,
            assessments=current.assessments + (event.assessment,),
            revision=event.sequence,
        )

    if isinstance(event, V2AssessmentConfirmedEvent):
        _require_player(current, event.player_id)
        assessment = current.get_assessment(event.assessment_id)

        if assessment is None:
            raise V2ReplayError(f"assessment {event.assessment_id!r} does not exist")

        if assessment.author_player_id == event.player_id:
            raise V2ReplayError("assessment authors cannot confirm their own assessment")

        if event.player_id in assessment.confirmed_by_player_ids:
            raise V2ReplayError(
                f"player {event.player_id!r} already confirmed assessment {event.assessment_id!r}"
            )

        updated_assessment = replace(
            assessment,
            status="confirmed",
            confirmed_by_player_ids=(assessment.confirmed_by_player_ids | {event.player_id}),
        )

        return _replace_assessment(
            current,
            updated_assessment,
            revision=event.sequence,
        )

    if isinstance(event, V2PromotedFindingRegisteredEvent):
        _require_player(current, event.finding.author_player_id)
        key = (event.finding.finding_id, event.finding.revision)
        if any(
            (finding.finding_id, finding.revision) == key for finding in current.promoted_findings
        ):
            raise V2ReplayError("promoted finding revision is already registered")
        return replace(
            current,
            promoted_findings=current.promoted_findings + (event.finding,),
            revision=event.sequence,
            serialization_schema=2,
        )

    if isinstance(event, V2QualityReviewSubmittedEvent):
        _require_player(current, event.review.reviewer_player_id)
        _require_player(current, event.review.author_player_id)
        key = (
            event.review.subject_kind,
            event.review.subject_id,
            event.review.subject_revision,
            event.review.reviewer_player_id,
        )
        if any(
            (
                review.subject_kind,
                review.subject_id,
                review.subject_revision,
                review.reviewer_player_id,
            )
            == key
            for review in current.quality_reviews
        ):
            raise V2ReplayError("reviewer already scored this exact subject revision")
        return replace(
            current,
            quality_reviews=current.quality_reviews + (event.review,),
            revision=event.sequence,
            serialization_schema=2,
        )

    if isinstance(event, V2PositionCompletedEvent):
        _require_player(current, event.player_id)

        if event.position_id != current.current_position_id:
            raise V2ReplayError(
                f"position completion records {event.position_id!r}, but the "
                f"current position is {current.current_position_id!r}"
            )

        orientation_completion = (
            event.position_id == ORIENTATION_POSITION_ID
            and event.assessment_id == ORIENTATION_ASSESSMENT_ID
            and event.quality_seal is None
            and event.adaptation_selection is None
        )
        if (
            not orientation_completion
            and current.get_assessment(event.assessment_id) is None
        ):
            raise V2ReplayError(f"assessment {event.assessment_id!r} does not exist")

        if event.position_id in current.completed_position_ids:
            raise V2ReplayError(f"position {event.position_id!r} is already completed")

        released_by_player = {
            released.player_id: released.role_id for released in event.released_roles
        }

        players: list[V2PlayerState] = []

        for player in current.players:
            recorded_role = released_by_player.get(player.player_id)

            if recorded_role is None:
                players.append(player)
                continue

            if player.active_role_id != recorded_role:
                raise V2ReplayError(
                    f"player {player.player_id!r} does not hold recorded "
                    f"released role {recorded_role!r}"
                )

            players.append(replace(player, active_role_id=None))

        next_position_id = (
            event.next_position_id
            if event.next_position_id is not None
            else current.current_position_id
        )

        return replace(
            current,
            current_position_id=next_position_id,
            available_location_ids=(current.available_location_ids | event.unlocked_location_ids),
            available_evidence_ids=(current.available_evidence_ids | event.unlocked_evidence_ids),
            players=tuple(players),
            completed_position_ids=(current.completed_position_ids | {event.position_id}),
            position_quality_seals=(
                current.position_quality_seals
                + ((event.quality_seal,) if event.quality_seal is not None else ())
            ),
            adaptation_selections=(
                current.adaptation_selections
                + ((event.adaptation_selection,) if event.adaptation_selection is not None else ())
            ),
            campaign_tracks=(
                event.campaign_tracks_after
                if event.strategic_outcome is not None
                else current.campaign_tracks
            ),
            strategic_board=(None if event.strategic_outcome is not None else current.strategic_board),
            strategic_position_outcomes=(
                current.strategic_position_outcomes
                + ((event.strategic_outcome,) if event.strategic_outcome is not None else ())
            ),
            campaign_modifier_ids=(
                event.campaign_modifier_ids_after
                if event.strategic_outcome is not None
                else current.campaign_modifier_ids
            ),
            revision=event.sequence,
            serialization_schema=(
                4
                if event.strategic_outcome is not None
                else 2
                if event.quality_seal is not None or event.adaptation_selection is not None
                else current.serialization_schema
            ),
        )

    raise TypeError(f"unsupported v2 investigation event: {type(event)!r}")


def replay_events(
    events: Iterable[V2InvestigationEvent],
) -> V2InvestigationState:
    recorded = tuple(events)

    if not recorded:
        raise V2ReplayError("an event stream must contain at least one event")

    stream_id = recorded[0].stream_id
    state: V2InvestigationState | None = None

    for expected_sequence, event in enumerate(recorded):
        if event.stream_id != stream_id:
            raise V2ReplayError("all events in a stream must use the same stream ID")

        if event.sequence != expected_sequence:
            raise V2ReplayError(
                f"expected event sequence {expected_sequence}, received {event.sequence}"
            )

        state = apply_event(state, event)

    if state is None:
        raise V2ReplayError("event replay did not produce a state")

    return state
