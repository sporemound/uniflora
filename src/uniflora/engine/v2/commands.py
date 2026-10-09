from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from uniflora.engine.v2.quality import (
    V2ReviewSubjectKind,
    validate_rubric_score,
)

ORIENTATION_ASSESSMENT_ID = "orientation_acknowledged"
ORIENTATION_POSITION_ID = "network_orientation"


def _require_nonblank(value: str, *, label: str) -> None:
    if not value.strip():
        raise ValueError(f"{label} must not be blank")


def _validate_ids(values: tuple[str, ...], *, label: str) -> None:
    for value in values:
        _require_nonblank(value, label=label)


@dataclass(frozen=True, slots=True)
class V2JoinInvestigationCommand:
    player_id: str

    def __post_init__(self) -> None:
        _require_nonblank(self.player_id, label="player ID")


@dataclass(frozen=True, slots=True)
class V2AssignRoleCommand:
    player_id: str
    role_id: str
    display_name: str | None = None
    description: str | None = None

    def __post_init__(self) -> None:
        _require_nonblank(self.player_id, label="player ID")
        _require_nonblank(self.role_id, label="role ID")
        if self.display_name is not None:
            _require_nonblank(self.display_name, label="role display name")
            if len(self.display_name) > 48:
                raise ValueError("role display name cannot exceed 48 characters")
        if self.description is not None:
            _require_nonblank(self.description, label="role description")
            if len(self.description) > 240:
                raise ValueError("role description cannot exceed 240 characters")


@dataclass(frozen=True, slots=True)
class V2ReleaseRoleCommand:
    player_id: str

    def __post_init__(self) -> None:
        _require_nonblank(self.player_id, label="player ID")


@dataclass(frozen=True, slots=True)
class V2MovePlayerCommand:
    player_id: str
    location_id: str

    def __post_init__(self) -> None:
        _require_nonblank(self.player_id, label="player ID")
        _require_nonblank(self.location_id, label="location ID")


@dataclass(frozen=True, slots=True)
class V2ExamineEvidenceCommand:
    player_id: str
    evidence_id: str

    def __post_init__(self) -> None:
        _require_nonblank(self.player_id, label="player ID")
        _require_nonblank(self.evidence_id, label="evidence ID")


@dataclass(frozen=True, slots=True)
class V2PerformActionCommand:
    player_id: str
    action_id: str

    def __post_init__(self) -> None:
        _require_nonblank(self.player_id, label="player ID")
        _require_nonblank(self.action_id, label="action ID")


@dataclass(frozen=True, slots=True)
class V2DraftAssessmentCommand:
    player_id: str
    assessment_id: str
    statement: str
    evidence_ids: tuple[str, ...]
    tested_ordinary_explanation_ids: tuple[str, ...] = ()
    preserved_contradiction_ids: tuple[str, ...] = ()
    documented_information_gap_ids: tuple[str, ...] = ()
    confidence: Literal["low", "moderate", "high"] = "low"
    next_collection: str = "No next collection specified."
    minority_view: str | None = None

    def __post_init__(self) -> None:
        _require_nonblank(self.player_id, label="player ID")
        _require_nonblank(self.assessment_id, label="assessment ID")
        _require_nonblank(self.statement, label="assessment statement")
        _require_nonblank(
            self.next_collection,
            label="assessment next collection",
        )

        if self.minority_view is not None:
            _require_nonblank(
                self.minority_view,
                label="assessment minority view",
            )

        collections = (
            ("evidence ID", self.evidence_ids),
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


@dataclass(frozen=True, slots=True)
class V2ConfirmAssessmentCommand:
    player_id: str
    assessment_id: str

    def __post_init__(self) -> None:
        _require_nonblank(self.player_id, label="player ID")
        _require_nonblank(self.assessment_id, label="assessment ID")


@dataclass(frozen=True, slots=True)
class V2CompletePositionCommand:
    player_id: str
    assessment_id: str

    def __post_init__(self) -> None:
        _require_nonblank(self.player_id, label="player ID")
        _require_nonblank(self.assessment_id, label="assessment ID")


@dataclass(frozen=True, slots=True)
class V2BeginInvestigationCommand:
    player_id: str

    def __post_init__(self) -> None:
        _require_nonblank(self.player_id, label="player ID")


@dataclass(frozen=True, slots=True)
class V2RegisterPromotedFindingCommand:
    player_id: str
    finding_id: str
    finding_revision: int
    author_player_id: str

    def __post_init__(self) -> None:
        _require_nonblank(self.player_id, label="player ID")
        _require_nonblank(self.finding_id, label="finding ID")
        _require_nonblank(self.author_player_id, label="finding author player ID")
        if self.finding_revision < 1:
            raise ValueError("finding revision must be positive")


@dataclass(frozen=True, slots=True)
class V2SubmitQualityReviewCommand:
    player_id: str
    subject_kind: V2ReviewSubjectKind
    subject_id: str
    subject_revision: int
    evidence_support: int
    ordinary_alternatives: int
    contradictions_preserved: int
    confidence_calibration: int
    reproducibility: int
    rationale: str

    def __post_init__(self) -> None:
        _require_nonblank(self.player_id, label="player ID")
        _require_nonblank(self.subject_id, label="review subject ID")
        _require_nonblank(self.rationale, label="review rationale")
        if self.subject_revision < 1:
            raise ValueError("review subject revision must be positive")
        for label, value in (
            ("evidence-support score", self.evidence_support),
            ("ordinary-alternatives score", self.ordinary_alternatives),
            ("contradictions-preserved score", self.contradictions_preserved),
            ("confidence-calibration score", self.confidence_calibration),
            ("reproducibility score", self.reproducibility),
        ):
            validate_rubric_score(value, label=label)


@dataclass(frozen=True, slots=True)
class V2ViewStrategicBoardCommand:
    player_id: str

    def __post_init__(self) -> None:
        _require_nonblank(self.player_id, label="player ID")


@dataclass(frozen=True, slots=True)
class V2ProposeActionCommand:
    player_id: str
    action_id: str

    def __post_init__(self) -> None:
        _require_nonblank(self.player_id, label="player ID")
        _require_nonblank(self.action_id, label="action ID")


@dataclass(frozen=True, slots=True)
class V2SupportActionCommand:
    player_id: str
    proposal_id: str

    def __post_init__(self) -> None:
        _require_nonblank(self.player_id, label="player ID")
        _require_nonblank(self.proposal_id, label="proposal ID")


@dataclass(frozen=True, slots=True)
class V2PassCapacityCommand:
    player_id: str

    def __post_init__(self) -> None:
        _require_nonblank(self.player_id, label="player ID")


V2InvestigationCommand = (
    V2JoinInvestigationCommand
    | V2BeginInvestigationCommand
    | V2AssignRoleCommand
    | V2ReleaseRoleCommand
    | V2MovePlayerCommand
    | V2ExamineEvidenceCommand
    | V2PerformActionCommand
    | V2ViewStrategicBoardCommand
    | V2ProposeActionCommand
    | V2SupportActionCommand
    | V2PassCapacityCommand
    | V2DraftAssessmentCommand
    | V2ConfirmAssessmentCommand
    | V2RegisterPromotedFindingCommand
    | V2SubmitQualityReviewCommand
    | V2CompletePositionCommand
)
