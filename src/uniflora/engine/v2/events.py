from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from uniflora.engine.v2.state import (
    V2AdaptationSelectionState,
    V2AssessmentState,
    V2InvestigationState,
    V2PositionQualitySealState,
    V2PlayerState,
    V2PromotedFindingState,
    V2QualityReviewState,
    V2StochasticResolutionState,
    V2StrategicBoardState,
    V2StrategicPositionOutcomeState,
    V2StrategicProposalState,
    V2StrategicResolutionState,
    V2StrategicTrackState,
)


def _require_nonblank(value: str, *, label: str) -> None:
    if not value.strip():
        raise ValueError(f"{label} must not be blank")


def _validate_header(stream_id: str, sequence: int) -> None:
    _require_nonblank(stream_id, label="stream ID")

    if sequence < 0:
        raise ValueError("event sequence must not be negative")


def _validate_ids(values: frozenset[str], *, label: str) -> None:
    for value in values:
        _require_nonblank(value, label=label)


@dataclass(frozen=True, slots=True)
class V2ReleasedRole:
    player_id: str
    role_id: str

    def __post_init__(self) -> None:
        _require_nonblank(self.player_id, label="released-role player ID")
        _require_nonblank(self.role_id, label="released role ID")


@dataclass(frozen=True, slots=True)
class V2InvestigationInitializedEvent:
    stream_id: str
    sequence: int
    initial_state: V2InvestigationState
    event_type: Literal["investigation_initialized"] = field(
        default="investigation_initialized",
        init=False,
    )

    def __post_init__(self) -> None:
        _validate_header(self.stream_id, self.sequence)

        if self.sequence != 0:
            raise ValueError("investigation initialization must use sequence 0")

        if self.initial_state.revision != 0:
            raise ValueError("initial investigation state must use revision 0")


@dataclass(frozen=True, slots=True)
class V2PlayerJoinedEvent:
    stream_id: str
    sequence: int
    player: V2PlayerState
    record_schema_version: Literal[2, 3] = 3
    event_type: Literal["player_joined"] = field(default="player_joined", init=False)

    def __post_init__(self) -> None:
        _validate_header(self.stream_id, self.sequence)
        if self.record_schema_version not in (2, 3):
            raise ValueError("unsupported player-joined event schema version")


@dataclass(frozen=True, slots=True)
class V2RoleAssignedEvent:
    stream_id: str
    sequence: int
    player_id: str
    role_id: str
    display_name: str | None = None
    description: str | None = None
    event_type: Literal["role_assigned"] = field(
        default="role_assigned",
        init=False,
    )

    def __post_init__(self) -> None:
        _validate_header(self.stream_id, self.sequence)
        _require_nonblank(self.player_id, label="player ID")
        _require_nonblank(self.role_id, label="role ID")
        if self.display_name is not None:
            _require_nonblank(self.display_name, label="role display name")
        if self.description is not None:
            _require_nonblank(self.description, label="role description")


@dataclass(frozen=True, slots=True)
class V2RoleReleasedEvent:
    stream_id: str
    sequence: int
    player_id: str
    role_id: str
    event_type: Literal["role_released"] = field(
        default="role_released",
        init=False,
    )

    def __post_init__(self) -> None:
        _validate_header(self.stream_id, self.sequence)
        _require_nonblank(self.player_id, label="player ID")
        _require_nonblank(self.role_id, label="role ID")


@dataclass(frozen=True, slots=True)
class V2PlayerMovedEvent:
    stream_id: str
    sequence: int
    player_id: str
    from_location_id: str
    to_location_id: str
    event_type: Literal["player_moved"] = field(
        default="player_moved",
        init=False,
    )

    def __post_init__(self) -> None:
        _validate_header(self.stream_id, self.sequence)
        _require_nonblank(self.player_id, label="player ID")
        _require_nonblank(
            self.from_location_id,
            label="origin location ID",
        )
        _require_nonblank(
            self.to_location_id,
            label="destination location ID",
        )


@dataclass(frozen=True, slots=True)
class V2EvidenceExaminedEvent:
    stream_id: str
    sequence: int
    player_id: str
    evidence_id: str
    event_type: Literal["evidence_examined"] = field(
        default="evidence_examined",
        init=False,
    )

    def __post_init__(self) -> None:
        _validate_header(self.stream_id, self.sequence)
        _require_nonblank(self.player_id, label="player ID")
        _require_nonblank(self.evidence_id, label="evidence ID")


@dataclass(frozen=True, slots=True)
class V2ActionPerformedEvent:
    stream_id: str
    sequence: int
    player_id: str
    action_id: str
    unlocked_evidence_ids: frozenset[str] = frozenset()
    tested_ordinary_explanation_ids: frozenset[str] = frozenset()
    preserved_contradiction_ids: frozenset[str] = frozenset()
    documented_information_gap_ids: frozenset[str] = frozenset()
    stochastic_resolution: V2StochasticResolutionState | None = None
    strategic_resolution: V2StrategicResolutionState | None = None
    event_type: Literal["action_performed"] = field(
        default="action_performed",
        init=False,
    )

    def __post_init__(self) -> None:
        _validate_header(self.stream_id, self.sequence)
        _require_nonblank(self.player_id, label="player ID")
        _require_nonblank(self.action_id, label="action ID")

        collections = (
            ("unlocked evidence ID", self.unlocked_evidence_ids),
            (
                "tested ordinary explanation ID",
                self.tested_ordinary_explanation_ids,
            ),
            (
                "preserved contradiction ID",
                self.preserved_contradiction_ids,
            ),
            (
                "documented information gap ID",
                self.documented_information_gap_ids,
            ),
        )

        for label, values in collections:
            _validate_ids(values, label=label)

        if self.stochastic_resolution is not None:
            if self.stochastic_resolution.action_id != self.action_id:
                raise ValueError("stochastic resolution action ID must match its event")
        if self.strategic_resolution is not None:
            if self.strategic_resolution.action_id != self.action_id:
                raise ValueError("strategic resolution action ID must match its event")
            if self.strategic_resolution.actor_player_id != self.player_id:
                raise ValueError("strategic resolution actor must match its event")


@dataclass(frozen=True, slots=True)
class V2ActionProposedEvent:
    stream_id: str
    sequence: int
    player_id: str
    proposal: V2StrategicProposalState
    board_after: V2StrategicBoardState
    campaign_tracks_after: tuple[V2StrategicTrackState, ...]
    event_type: Literal["action_proposed"] = field(
        default="action_proposed",
        init=False,
    )

    def __post_init__(self) -> None:
        _validate_header(self.stream_id, self.sequence)
        _require_nonblank(self.player_id, label="player ID")
        if self.proposal.proposer_player_id != self.player_id:
            raise ValueError("proposal event player must match the proposal author")
        if self.board_after.get_proposal(self.proposal.proposal_id) is None:
            raise ValueError("proposal event board must contain the proposal")


@dataclass(frozen=True, slots=True)
class V2ProposalSupportedEvent:
    stream_id: str
    sequence: int
    player_id: str
    proposal: V2StrategicProposalState
    board_after: V2StrategicBoardState
    campaign_tracks_after: tuple[V2StrategicTrackState, ...]
    event_type: Literal["proposal_supported"] = field(
        default="proposal_supported",
        init=False,
    )

    def __post_init__(self) -> None:
        _validate_header(self.stream_id, self.sequence)
        _require_nonblank(self.player_id, label="player ID")
        if self.player_id not in self.proposal.supporter_player_ids:
            raise ValueError("support event player must appear in the proposal support set")
        current = self.board_after.get_proposal(self.proposal.proposal_id)
        if current != self.proposal:
            raise ValueError("support event board must contain the updated proposal")


@dataclass(frozen=True, slots=True)
class V2CapacityPassedEvent:
    stream_id: str
    sequence: int
    player_id: str
    strategic_resolution: V2StrategicResolutionState
    event_type: Literal["capacity_passed"] = field(
        default="capacity_passed",
        init=False,
    )

    def __post_init__(self) -> None:
        _validate_header(self.stream_id, self.sequence)
        _require_nonblank(self.player_id, label="player ID")
        if self.strategic_resolution.action_id != "pass_capacity":
            raise ValueError("capacity-pass events require the pass_capacity resolution")
        if self.strategic_resolution.actor_player_id != self.player_id:
            raise ValueError("capacity-pass actor must match its event")


@dataclass(frozen=True, slots=True)
class V2AssessmentDraftedEvent:
    stream_id: str
    sequence: int
    assessment: V2AssessmentState
    event_type: Literal["assessment_drafted"] = field(
        default="assessment_drafted",
        init=False,
    )

    def __post_init__(self) -> None:
        _validate_header(self.stream_id, self.sequence)

        if self.assessment.status != "draft":
            raise ValueError("assessment-drafted events require draft assessments")


@dataclass(frozen=True, slots=True)
class V2AssessmentConfirmedEvent:
    stream_id: str
    sequence: int
    player_id: str
    assessment_id: str
    event_type: Literal["assessment_confirmed"] = field(
        default="assessment_confirmed",
        init=False,
    )

    def __post_init__(self) -> None:
        _validate_header(self.stream_id, self.sequence)
        _require_nonblank(self.player_id, label="player ID")
        _require_nonblank(self.assessment_id, label="assessment ID")


@dataclass(frozen=True, slots=True)
class V2PromotedFindingRegisteredEvent:
    stream_id: str
    sequence: int
    finding: V2PromotedFindingState
    event_type: Literal["promoted_finding_registered"] = field(
        default="promoted_finding_registered",
        init=False,
    )

    def __post_init__(self) -> None:
        _validate_header(self.stream_id, self.sequence)


@dataclass(frozen=True, slots=True)
class V2QualityReviewSubmittedEvent:
    stream_id: str
    sequence: int
    review: V2QualityReviewState
    event_type: Literal["quality_review_submitted"] = field(
        default="quality_review_submitted",
        init=False,
    )

    def __post_init__(self) -> None:
        _validate_header(self.stream_id, self.sequence)


@dataclass(frozen=True, slots=True)
class V2PositionCompletedEvent:
    stream_id: str
    sequence: int
    player_id: str
    position_id: str
    assessment_id: str
    next_position_id: str | None = None
    unlocked_location_ids: frozenset[str] = frozenset()
    unlocked_evidence_ids: frozenset[str] = frozenset()
    released_roles: tuple[V2ReleasedRole, ...] = ()
    quality_seal: V2PositionQualitySealState | None = None
    adaptation_selection: V2AdaptationSelectionState | None = None
    strategic_outcome: V2StrategicPositionOutcomeState | None = None
    campaign_tracks_after: tuple[V2StrategicTrackState, ...] = ()
    campaign_modifier_ids_after: frozenset[str] = frozenset()
    event_type: Literal["position_completed"] = field(
        default="position_completed",
        init=False,
    )

    def __post_init__(self) -> None:
        _validate_header(self.stream_id, self.sequence)
        _require_nonblank(self.player_id, label="player ID")
        _require_nonblank(self.position_id, label="position ID")
        _require_nonblank(self.assessment_id, label="assessment ID")

        if self.next_position_id is not None:
            _require_nonblank(
                self.next_position_id,
                label="next position ID",
            )

            if self.next_position_id == self.position_id:
                raise ValueError(
                    "position-completed events cannot advance to the completed position"
                )
        elif self.unlocked_location_ids or self.unlocked_evidence_ids:
            raise ValueError("final position-completed events cannot unlock entry material")

        _validate_ids(
            self.unlocked_location_ids,
            label="unlocked location ID",
        )
        _validate_ids(
            self.unlocked_evidence_ids,
            label="unlocked evidence ID",
        )

        released_players = tuple(item.player_id for item in self.released_roles)

        if len(released_players) != len(set(released_players)):
            raise ValueError(
                "position-completed events cannot release multiple roles for the same player"
            )
        if self.quality_seal is not None and self.quality_seal.position_id != self.position_id:
            raise ValueError("position completion quality seal must match its position")
        if self.adaptation_selection is not None:
            expected_target = self.next_position_id or "ending"
            if self.adaptation_selection.target_id != expected_target:
                raise ValueError("adaptation selection must target the next presentation")
        if self.strategic_outcome is not None:
            if self.strategic_outcome.position_id != self.position_id:
                raise ValueError("strategic outcome must match the completed position")
            if not self.campaign_tracks_after:
                raise ValueError("strategic position completion requires campaign tracks")
        _validate_ids(
            self.campaign_modifier_ids_after,
            label="campaign modifier ID",
        )


V2InvestigationEvent = (
    V2InvestigationInitializedEvent
    | V2PlayerJoinedEvent
    | V2RoleAssignedEvent
    | V2RoleReleasedEvent
    | V2PlayerMovedEvent
    | V2EvidenceExaminedEvent
    | V2ActionPerformedEvent
    | V2ActionProposedEvent
    | V2ProposalSupportedEvent
    | V2CapacityPassedEvent
    | V2AssessmentDraftedEvent
    | V2AssessmentConfirmedEvent
    | V2PromotedFindingRegisteredEvent
    | V2QualityReviewSubmittedEvent
    | V2PositionCompletedEvent
)
