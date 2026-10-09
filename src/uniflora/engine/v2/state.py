from __future__ import annotations

from dataclasses import dataclass, field
from fractions import Fraction
from typing import Literal

from uniflora.engine.v2.quality import (
    V2AdaptationBand,
    V2ReviewSubjectKind,
    validate_rubric_score,
)


def _require_nonblank(value: str, *, label: str) -> None:
    if not value.strip():
        raise ValueError(f"{label} must not be blank")


def _duplicate_values(values: tuple[str, ...]) -> tuple[str, ...]:
    seen: set[str] = set()
    duplicates: set[str] = set()

    for value in values:
        if value in seen:
            duplicates.add(value)
        else:
            seen.add(value)

    return tuple(sorted(duplicates))


def _validate_nonblank_collection(
    values: frozenset[str],
    *,
    label: str,
) -> None:
    for value in values:
        _require_nonblank(value, label=label)


@dataclass(frozen=True, slots=True)
class V2PlayerState:
    player_id: str
    current_location_id: str
    active_role_id: str | None = None
    active_role_display_name: str | None = None
    active_role_description: str | None = None
    proficiencies: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        _require_nonblank(self.player_id, label="player ID")
        _require_nonblank(
            self.current_location_id,
            label="current location ID",
        )

        if self.active_role_id is not None:
            _require_nonblank(self.active_role_id, label="active role ID")
        elif self.active_role_display_name is not None or self.active_role_description is not None:
            raise ValueError("custom role metadata requires an active role")
        if self.active_role_display_name is not None:
            _require_nonblank(self.active_role_display_name, label="active role display name")
        if self.active_role_description is not None:
            _require_nonblank(self.active_role_description, label="active role description")

        _validate_nonblank_collection(
            self.proficiencies,
            label="proficiency",
        )


@dataclass(frozen=True, slots=True)
class V2HypothesisState:
    id: str
    author_player_id: str
    statement: str
    status: Literal[
        "registered",
        "under_test",
        "retained",
        "unsupported",
    ] = "registered"

    def __post_init__(self) -> None:
        _require_nonblank(self.id, label="hypothesis ID")
        _require_nonblank(
            self.author_player_id,
            label="hypothesis author player ID",
        )
        _require_nonblank(
            self.statement,
            label="hypothesis statement",
        )


@dataclass(frozen=True, slots=True)
class V2AssessmentState:
    id: str
    author_player_id: str
    statement: str
    evidence_ids: frozenset[str] = frozenset()
    tested_ordinary_explanation_ids: frozenset[str] = frozenset()
    preserved_contradiction_ids: frozenset[str] = frozenset()
    documented_information_gap_ids: frozenset[str] = frozenset()
    confidence: Literal["low", "moderate", "high"] = "low"
    next_collection: str = "No next collection specified."
    minority_view: str | None = None
    status: Literal["draft", "confirmed"] = "draft"
    confirmed_by_player_ids: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        _require_nonblank(self.id, label="assessment ID")
        _require_nonblank(
            self.author_player_id,
            label="assessment author player ID",
        )
        _require_nonblank(
            self.statement,
            label="assessment statement",
        )
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
            ("assessment evidence ID", self.evidence_ids),
            (
                "assessment tested ordinary explanation ID",
                self.tested_ordinary_explanation_ids,
            ),
            (
                "assessment preserved contradiction ID",
                self.preserved_contradiction_ids,
            ),
            (
                "assessment documented information gap ID",
                self.documented_information_gap_ids,
            ),
            ("confirming player ID", self.confirmed_by_player_ids),
        )

        for label, values in collections:
            _validate_nonblank_collection(values, label=label)

        if self.author_player_id in self.confirmed_by_player_ids:
            raise ValueError("assessment authors cannot confirm their own assessment")

        if self.status == "draft" and self.confirmed_by_player_ids:
            raise ValueError("draft assessments cannot have confirmations")

        if self.status == "confirmed" and not self.confirmed_by_player_ids:
            raise ValueError("confirmed assessments require a confirmation")


@dataclass(frozen=True, slots=True)
class V2PromotedFindingState:
    finding_id: str
    revision: int
    position_id: str
    author_player_id: str

    def __post_init__(self) -> None:
        _require_nonblank(self.finding_id, label="finding ID")
        _require_nonblank(self.position_id, label="finding position ID")
        _require_nonblank(self.author_player_id, label="finding author player ID")
        if self.revision < 1:
            raise ValueError("finding revision must be positive")


@dataclass(frozen=True, slots=True)
class V2QualityReviewState:
    subject_kind: V2ReviewSubjectKind
    subject_id: str
    subject_revision: int
    position_id: str
    author_player_id: str
    reviewer_player_id: str
    evidence_support: int
    ordinary_alternatives: int
    contradictions_preserved: int
    confidence_calibration: int
    reproducibility: int
    rationale: str

    def __post_init__(self) -> None:
        _require_nonblank(self.subject_id, label="review subject ID")
        _require_nonblank(self.position_id, label="review position ID")
        _require_nonblank(self.author_player_id, label="review subject author player ID")
        _require_nonblank(self.reviewer_player_id, label="reviewer player ID")
        _require_nonblank(self.rationale, label="review rationale")
        if self.subject_revision < 1:
            raise ValueError("review subject revision must be positive")
        if self.author_player_id == self.reviewer_player_id:
            raise ValueError("authors cannot review their own work")
        for label, value in (
            ("evidence-support score", self.evidence_support),
            ("ordinary-alternatives score", self.ordinary_alternatives),
            ("contradictions-preserved score", self.contradictions_preserved),
            ("confidence-calibration score", self.confidence_calibration),
            ("reproducibility score", self.reproducibility),
        ):
            validate_rubric_score(value, label=label)


@dataclass(frozen=True, slots=True)
class V2PositionQualitySealState:
    position_id: str
    position_ordinal: int
    score_numerator: int | None
    score_denominator: int | None
    reviewed_subject_count: int
    baseline_fallback: bool

    def __post_init__(self) -> None:
        _require_nonblank(self.position_id, label="sealed position ID")
        if self.position_ordinal < 1:
            raise ValueError("sealed position ordinal must be positive")
        if self.reviewed_subject_count < 0:
            raise ValueError("reviewed subject count must not be negative")
        if self.baseline_fallback:
            if self.score_numerator is not None or self.score_denominator is not None:
                raise ValueError("baseline fallback seals cannot contain a score")
            if self.reviewed_subject_count:
                raise ValueError("baseline fallback seals cannot contain reviewed subjects")
        else:
            if self.score_numerator is None or self.score_denominator is None:
                raise ValueError("graded seals require an exact score")
            if self.score_denominator <= 0:
                raise ValueError("sealed score denominator must be positive")
            if not 0 <= Fraction(self.score_numerator, self.score_denominator) <= 10:
                raise ValueError("sealed position score must be from 0 through 10")
            if self.reviewed_subject_count < 1:
                raise ValueError("graded seals require reviewed subjects")

    @property
    def score(self) -> Fraction | None:
        if self.score_numerator is None or self.score_denominator is None:
            return None
        return Fraction(self.score_numerator, self.score_denominator)


@dataclass(frozen=True, slots=True)
class V2AdaptationSelectionState:
    target_id: str
    presentation_id: str
    band: V2AdaptationBand

    def __post_init__(self) -> None:
        _require_nonblank(self.target_id, label="adaptation target ID")
        _require_nonblank(self.presentation_id, label="adaptation presentation ID")


@dataclass(frozen=True, slots=True)
class V2StochasticDatumState:
    key: str
    value: str | int | float | bool
    unit: str | None = None
    uncertainty: str | None = None

    def __post_init__(self) -> None:
        _require_nonblank(self.key, label="stochastic datum key")
        if self.unit is not None:
            _require_nonblank(self.unit, label="stochastic datum unit")
        if self.uncertainty is not None:
            _require_nonblank(self.uncertainty, label="stochastic datum uncertainty")


@dataclass(frozen=True, slots=True)
class V2StochasticDrawState:
    purpose: str
    upper_bound: int
    raw_value: int
    selected_index: int
    selected_weight: int

    def __post_init__(self) -> None:
        _require_nonblank(self.purpose, label="stochastic draw purpose")
        if self.upper_bound <= 0:
            raise ValueError("stochastic draw upper bound must be positive")
        if not 0 <= self.raw_value < self.upper_bound:
            raise ValueError("stochastic draw value must fall within its upper bound")
        if self.selected_index < 0:
            raise ValueError("stochastic selected index must not be negative")
        if self.selected_weight <= 0:
            raise ValueError("stochastic selected weight must be positive")


@dataclass(frozen=True, slots=True)
class V2ModelProbabilityState:
    model_id: str
    basis_points: int

    def __post_init__(self) -> None:
        _require_nonblank(self.model_id, label="stochastic model ID")
        if not 0 <= self.basis_points <= 10_000:
            raise ValueError("model probability must be from 0 through 10000 basis points")


@dataclass(frozen=True, slots=True)
class V2StochasticModelSupportState:
    process_id: str
    models: tuple[V2ModelProbabilityState, ...]

    def __post_init__(self) -> None:
        _require_nonblank(self.process_id, label="stochastic support process ID")
        if not self.models:
            raise ValueError("stochastic model support requires models")
        model_ids = tuple(item.model_id for item in self.models)
        if len(model_ids) != len(set(model_ids)):
            raise ValueError("stochastic model support IDs must be unique")
        if sum(item.basis_points for item in self.models) != 10_000:
            raise ValueError("stochastic model support must total 10000 basis points")


@dataclass(frozen=True, slots=True)
class V2StochasticProcessState:
    process_id: str
    state_id: str
    observation_count: int = 0
    dwell_count: int = 0
    last_sequence: int | None = None

    def __post_init__(self) -> None:
        _require_nonblank(self.process_id, label="stochastic process ID")
        _require_nonblank(self.state_id, label="stochastic state ID")
        if self.observation_count < 0 or self.dwell_count < 0:
            raise ValueError("stochastic process counters must not be negative")
        if self.last_sequence is not None and self.last_sequence < 0:
            raise ValueError("stochastic process sequence must not be negative")


@dataclass(frozen=True, slots=True)
class V2StochasticObservationState:
    process_id: str
    action_id: str
    channel_id: str
    outcome_id: str
    public_summary: str
    measurements: tuple[V2StochasticDatumState, ...]
    sequence: int
    observed_state_label: str | None = None

    def __post_init__(self) -> None:
        for value, label in (
            (self.process_id, "observation process ID"),
            (self.action_id, "observation action ID"),
            (self.channel_id, "observation channel ID"),
            (self.outcome_id, "observation outcome ID"),
            (self.public_summary, "observation summary"),
        ):
            _require_nonblank(value, label=label)
        if self.sequence < 1:
            raise ValueError("stochastic observation sequence must be positive")
        if self.observed_state_label is not None:
            _require_nonblank(self.observed_state_label, label="observed state label")
        keys = tuple(item.key for item in self.measurements)
        if len(keys) != len(set(keys)):
            raise ValueError("stochastic observation datum keys must be unique")


@dataclass(frozen=True, slots=True)
class V2StochasticResolutionState:
    process_id: str
    action_id: str
    channel_id: str
    algorithm: Literal["hidden_markov", "semi_markov"]
    algorithm_version: int
    previous_state_id: str
    next_state_id: str
    state_advanced: bool
    observed_state_label: str | None
    transition_draw: V2StochasticDrawState | None
    outcome_draw: V2StochasticDrawState
    outcome_id: str
    public_summary: str
    measurements: tuple[V2StochasticDatumState, ...]
    model_support_after: V2StochasticModelSupportState
    weight_table_hash: str

    def __post_init__(self) -> None:
        for value, label in (
            (self.process_id, "resolution process ID"),
            (self.action_id, "resolution action ID"),
            (self.channel_id, "resolution channel ID"),
            (self.previous_state_id, "previous stochastic state ID"),
            (self.next_state_id, "next stochastic state ID"),
            (self.outcome_id, "stochastic outcome ID"),
            (self.public_summary, "stochastic public summary"),
            (self.weight_table_hash, "stochastic weight-table hash"),
        ):
            _require_nonblank(value, label=label)
        if self.algorithm_version < 1:
            raise ValueError("stochastic algorithm version must be positive")
        if self.observed_state_label is not None:
            _require_nonblank(self.observed_state_label, label="observed state label")


@dataclass(frozen=True, slots=True)
class V2StrategicTrackState:
    track_id: str
    value: int
    minimum: int
    maximum: int

    def __post_init__(self) -> None:
        _require_nonblank(self.track_id, label="strategic track ID")
        if self.minimum >= self.maximum:
            raise ValueError("strategic track minimum must be below maximum")
        if not self.minimum <= self.value <= self.maximum:
            raise ValueError("strategic track value must be within range")


@dataclass(frozen=True, slots=True)
class V2StrategicResourceState:
    resource_id: str
    title: str
    value: int
    minimum: int
    maximum: int

    def __post_init__(self) -> None:
        _require_nonblank(self.resource_id, label="strategic resource ID")
        _require_nonblank(self.title, label="strategic resource title")
        if self.minimum >= self.maximum:
            raise ValueError("strategic resource minimum must be below maximum")
        if not self.minimum <= self.value <= self.maximum:
            raise ValueError("strategic resource value must be within range")


@dataclass(frozen=True, slots=True)
class V2StrategicConditionState:
    condition_id: str
    duration: Literal["round", "next_round", "position", "campaign"]
    created_round: int
    expires_after_round: int | None = None

    def __post_init__(self) -> None:
        _require_nonblank(self.condition_id, label="strategic condition ID")
        if self.created_round < 1:
            raise ValueError("strategic condition creation round must be positive")
        if self.expires_after_round is not None and self.expires_after_round < self.created_round:
            raise ValueError("strategic condition expiry cannot precede creation")
        if self.duration in {"round", "next_round"} and self.expires_after_round is None:
            raise ValueError("round-scoped strategic conditions require an expiry round")
        if self.duration in {"position", "campaign"} and self.expires_after_round is not None:
            raise ValueError("position/campaign conditions cannot have a round expiry")


@dataclass(frozen=True, slots=True)
class V2StrategicPlayerRoundState:
    player_id: str
    operation_count: int = 0
    locked_role_id: str | None = None
    supported_proposal_ids: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        _require_nonblank(self.player_id, label="strategic player ID")
        if self.operation_count < 0:
            raise ValueError("strategic operation count must not be negative")
        if self.locked_role_id is not None:
            _require_nonblank(self.locked_role_id, label="strategic locked role ID")
        _validate_nonblank_collection(
            self.supported_proposal_ids,
            label="supported strategic proposal ID",
        )


@dataclass(frozen=True, slots=True)
class V2StrategicProposalState:
    proposal_id: str
    action_id: str
    proposer_player_id: str
    round_index: int
    required_supporter_count: int
    supporter_player_ids: frozenset[str]
    definition_hash: str
    status: Literal["active", "stale"] = "active"

    def __post_init__(self) -> None:
        for value, label in (
            (self.proposal_id, "strategic proposal ID"),
            (self.action_id, "strategic proposal action ID"),
            (self.proposer_player_id, "strategic proposal player ID"),
            (self.definition_hash, "strategic proposal definition hash"),
        ):
            _require_nonblank(value, label=label)
        if self.round_index < 1:
            raise ValueError("strategic proposal round must be positive")
        if self.required_supporter_count < 1:
            raise ValueError("strategic proposals require independent support")
        if self.proposer_player_id in self.supporter_player_ids:
            raise ValueError("strategic proposal authors cannot support themselves")
        _validate_nonblank_collection(
            self.supporter_player_ids,
            label="strategic supporter player ID",
        )


@dataclass(frozen=True, slots=True)
class V2StrategicDriftResolutionState:
    process_id: str
    previous_state_id: str
    next_state_id: str
    transition_draw: V2StochasticDrawState
    weight_table_hash: str

    def __post_init__(self) -> None:
        for value, label in (
            (self.process_id, "strategic drift process ID"),
            (self.previous_state_id, "strategic drift previous state ID"),
            (self.next_state_id, "strategic drift next state ID"),
            (self.weight_table_hash, "strategic drift weight-table hash"),
        ):
            _require_nonblank(value, label=label)


@dataclass(frozen=True, slots=True)
class V2StrategicPositionOutcomeState:
    position_id: str
    grade: Literal["controlled", "compromised", "incomplete", "critical"]
    round_index: int
    case_integrity: int
    institutional_trust: int
    escalation: int
    asset_ids: tuple[str, ...] = ()
    liability_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_nonblank(self.position_id, label="strategic outcome position ID")
        if self.round_index < 1:
            raise ValueError("strategic outcome round must be positive")
        for label, value in (
            ("case integrity", self.case_integrity),
            ("institutional trust", self.institutional_trust),
            ("escalation", self.escalation),
        ):
            if value < 0:
                raise ValueError(f"strategic outcome {label} must not be negative")
        if len(self.asset_ids) != len(set(self.asset_ids)):
            raise ValueError("strategic outcome assets must be unique")
        if len(self.liability_ids) != len(set(self.liability_ids)):
            raise ValueError("strategic outcome liabilities must be unique")


@dataclass(frozen=True, slots=True)
class V2StrategicBoardState:
    position_id: str
    round_index: int
    max_rounds: int
    capacity_remaining: int
    capacity_per_round: int
    coordination: int
    coordination_maximum: int
    escalation: int
    escalation_maximum: int
    local_resource: V2StrategicResourceState
    conditions: tuple[V2StrategicConditionState, ...] = ()
    players: tuple[V2StrategicPlayerRoundState, ...] = ()
    proposals: tuple[V2StrategicProposalState, ...] = ()
    forced_review: bool = False

    def __post_init__(self) -> None:
        _require_nonblank(self.position_id, label="strategic board position ID")
        if not 1 <= self.round_index <= self.max_rounds:
            raise ValueError("strategic round must fall within the position range")
        if self.capacity_per_round < 1:
            raise ValueError("strategic round capacity must be positive")
        if not 0 <= self.capacity_remaining <= self.capacity_per_round:
            raise ValueError("strategic remaining capacity is out of range")
        if not 0 <= self.coordination <= self.coordination_maximum:
            raise ValueError("strategic coordination is out of range")
        if not 0 <= self.escalation <= self.escalation_maximum:
            raise ValueError("strategic escalation is out of range")
        condition_ids = tuple(item.condition_id for item in self.conditions)
        if len(condition_ids) != len(set(condition_ids)):
            raise ValueError("strategic board conditions must be unique")
        player_ids = tuple(item.player_id for item in self.players)
        if len(player_ids) != len(set(player_ids)):
            raise ValueError("strategic board player records must be unique")
        proposal_ids = tuple(item.proposal_id for item in self.proposals)
        if len(proposal_ids) != len(set(proposal_ids)):
            raise ValueError("strategic proposal IDs must be unique")
        if self.forced_review and self.capacity_remaining:
            raise ValueError("forced-review boards cannot retain operation capacity")

    def get_player(self, player_id: str) -> V2StrategicPlayerRoundState | None:
        return next((item for item in self.players if item.player_id == player_id), None)

    def get_proposal(self, proposal_id: str) -> V2StrategicProposalState | None:
        return next((item for item in self.proposals if item.proposal_id == proposal_id), None)

    def has_condition(self, condition_id: str) -> bool:
        return any(item.condition_id == condition_id for item in self.conditions)


@dataclass(frozen=True, slots=True)
class V2StrategicResolutionState:
    action_id: str
    actor_player_id: str
    capacity_cost: int
    coordination_cost: int
    board_before_hash: str
    board_after: V2StrategicBoardState
    campaign_tracks_after: tuple[V2StrategicTrackState, ...]
    supporter_player_ids: frozenset[str] = frozenset()
    proposal_id: str | None = None
    natural_drift: V2StrategicDriftResolutionState | None = None

    def __post_init__(self) -> None:
        for value, label in (
            (self.action_id, "strategic resolution action ID"),
            (self.actor_player_id, "strategic resolution player ID"),
            (self.board_before_hash, "strategic board-before hash"),
        ):
            _require_nonblank(value, label=label)
        if self.capacity_cost < 0 or self.coordination_cost < 0:
            raise ValueError("strategic resolution costs must not be negative")
        if self.proposal_id is not None:
            _require_nonblank(self.proposal_id, label="strategic resolution proposal ID")
        if self.actor_player_id in self.supporter_player_ids:
            raise ValueError("strategic action actor cannot be their own supporter")
        _validate_nonblank_collection(
            self.supporter_player_ids,
            label="strategic resolution supporter player ID",
        )


@dataclass(frozen=True, slots=True)
class V2InvestigationState:
    pack_id: str
    current_position_id: str

    available_location_ids: frozenset[str]
    players: tuple[V2PlayerState, ...]

    available_evidence_ids: frozenset[str]
    examined_evidence_ids: frozenset[str] = frozenset()

    hypotheses: tuple[V2HypothesisState, ...] = ()
    assessments: tuple[V2AssessmentState, ...] = ()

    completed_action_ids: frozenset[str] = frozenset()
    tested_ordinary_explanation_ids: frozenset[str] = frozenset()
    preserved_contradiction_ids: frozenset[str] = frozenset()
    documented_information_gap_ids: frozenset[str] = frozenset()
    completed_position_ids: frozenset[str] = frozenset()
    promoted_findings: tuple[V2PromotedFindingState, ...] = ()
    quality_reviews: tuple[V2QualityReviewState, ...] = ()
    position_quality_seals: tuple[V2PositionQualitySealState, ...] = ()
    adaptation_selections: tuple[V2AdaptationSelectionState, ...] = ()
    stochastic_processes: tuple[V2StochasticProcessState, ...] = ()
    stochastic_observations: tuple[V2StochasticObservationState, ...] = ()
    stochastic_model_support: tuple[V2StochasticModelSupportState, ...] = ()
    campaign_tracks: tuple[V2StrategicTrackState, ...] = ()
    strategic_board: V2StrategicBoardState | None = None
    strategic_position_outcomes: tuple[V2StrategicPositionOutcomeState, ...] = ()
    campaign_modifier_ids: frozenset[str] = frozenset()

    revision: int = 0
    serialization_schema: Literal[1, 2, 3, 4] = field(default=2, compare=False, repr=False)

    def __post_init__(self) -> None:
        _require_nonblank(self.pack_id, label="pack ID")
        _require_nonblank(
            self.current_position_id,
            label="current position ID",
        )

        if self.revision < 0:
            raise ValueError("revision must not be negative")

        if not self.available_location_ids:
            raise ValueError("investigation state must expose at least one location")

        player_ids = tuple(player.player_id for player in self.players)
        duplicate_players = _duplicate_values(player_ids)

        if duplicate_players:
            raise ValueError(
                "duplicate player IDs: " + ", ".join(repr(value) for value in duplicate_players)
            )

        unavailable_player_locations = {
            player.current_location_id
            for player in self.players
            if player.current_location_id not in self.available_location_ids
        }

        if unavailable_player_locations:
            raise ValueError(
                "players occupy unavailable locations: "
                + ", ".join(sorted(unavailable_player_locations))
            )

        unavailable_examined_evidence = self.examined_evidence_ids - self.available_evidence_ids

        if unavailable_examined_evidence:
            raise ValueError(
                "examined evidence is not available: "
                + ", ".join(sorted(unavailable_examined_evidence))
            )

        hypothesis_ids = tuple(hypothesis.id for hypothesis in self.hypotheses)
        duplicate_hypotheses = _duplicate_values(hypothesis_ids)

        if duplicate_hypotheses:
            raise ValueError(
                "duplicate hypothesis IDs: "
                + ", ".join(repr(value) for value in duplicate_hypotheses)
            )

        assessment_ids = tuple(assessment.id for assessment in self.assessments)
        duplicate_assessments = _duplicate_values(assessment_ids)

        if duplicate_assessments:
            raise ValueError(
                "duplicate assessment IDs: "
                + ", ".join(repr(value) for value in duplicate_assessments)
            )

        known_player_ids = set(player_ids)

        for assessment in self.assessments:
            if assessment.author_player_id not in known_player_ids:
                raise ValueError(
                    f"assessment {assessment.id!r} has unknown author "
                    f"{assessment.author_player_id!r}"
                )

            unknown_confirmers = set(assessment.confirmed_by_player_ids) - known_player_ids
            if unknown_confirmers:
                raise ValueError(
                    f"assessment {assessment.id!r} has unknown confirming players: "
                    + ", ".join(sorted(unknown_confirmers))
                )

            unavailable_assessment_evidence = assessment.evidence_ids - self.examined_evidence_ids
            if unavailable_assessment_evidence:
                raise ValueError(
                    f"assessment {assessment.id!r} cites unexamined evidence: "
                    + ", ".join(sorted(unavailable_assessment_evidence))
                )

            unavailable_assessment_explanations = (
                assessment.tested_ordinary_explanation_ids - self.tested_ordinary_explanation_ids
            )
            if unavailable_assessment_explanations:
                raise ValueError(
                    f"assessment {assessment.id!r} cites untested explanations: "
                    + ", ".join(sorted(unavailable_assessment_explanations))
                )

            unavailable_assessment_contradictions = (
                assessment.preserved_contradiction_ids - self.preserved_contradiction_ids
            )
            if unavailable_assessment_contradictions:
                raise ValueError(
                    f"assessment {assessment.id!r} cites unpreserved contradictions: "
                    + ", ".join(sorted(unavailable_assessment_contradictions))
                )

            unavailable_assessment_gaps = (
                assessment.documented_information_gap_ids - self.documented_information_gap_ids
            )
            if unavailable_assessment_gaps:
                raise ValueError(
                    f"assessment {assessment.id!r} cites undocumented gaps: "
                    + ", ".join(sorted(unavailable_assessment_gaps))
                )

        finding_keys = tuple(
            (finding.finding_id, finding.revision) for finding in self.promoted_findings
        )
        if len(finding_keys) != len(set(finding_keys)):
            raise ValueError("duplicate promoted finding revisions")

        for finding in self.promoted_findings:
            if finding.author_player_id not in known_player_ids:
                raise ValueError(
                    f"finding {finding.finding_id!r} has unknown author "
                    f"{finding.author_player_id!r}"
                )

        review_keys = tuple(
            (
                review.subject_kind,
                review.subject_id,
                review.subject_revision,
                review.reviewer_player_id,
            )
            for review in self.quality_reviews
        )
        if len(review_keys) != len(set(review_keys)):
            raise ValueError("duplicate reviewer submissions for a subject revision")

        for review in self.quality_reviews:
            if review.author_player_id not in known_player_ids:
                raise ValueError("quality review references an unknown subject author")
            if review.reviewer_player_id not in known_player_ids:
                raise ValueError("quality review references an unknown reviewer")

        seal_positions = tuple(seal.position_id for seal in self.position_quality_seals)
        if len(seal_positions) != len(set(seal_positions)):
            raise ValueError("position quality can only be sealed once")

        adaptation_targets = tuple(item.target_id for item in self.adaptation_selections)
        if len(adaptation_targets) != len(set(adaptation_targets)):
            raise ValueError("adaptation targets can only be selected once")

        process_ids = tuple(item.process_id for item in self.stochastic_processes)
        if len(process_ids) != len(set(process_ids)):
            raise ValueError("stochastic process state IDs must be unique")
        support_ids = tuple(item.process_id for item in self.stochastic_model_support)
        if len(support_ids) != len(set(support_ids)):
            raise ValueError("stochastic model support may occur once per process")
        if set(support_ids) - set(process_ids):
            raise ValueError("stochastic model support references unknown process state")
        for process in self.stochastic_processes:
            if process.last_sequence is not None and process.last_sequence > self.revision:
                raise ValueError("stochastic process sequence exceeds state revision")
        observation_keys = tuple(
            (item.process_id, item.sequence, item.channel_id) for item in self.stochastic_observations
        )
        if len(observation_keys) != len(set(observation_keys)):
            raise ValueError("duplicate stochastic observations")
        for observation in self.stochastic_observations:
            if observation.process_id not in set(process_ids):
                raise ValueError("stochastic observation references unknown process state")
            if observation.sequence > self.revision:
                raise ValueError("stochastic observation sequence exceeds state revision")

        track_ids = tuple(item.track_id for item in self.campaign_tracks)
        if len(track_ids) != len(set(track_ids)):
            raise ValueError("strategic campaign track IDs must be unique")
        outcome_positions = tuple(item.position_id for item in self.strategic_position_outcomes)
        if len(outcome_positions) != len(set(outcome_positions)):
            raise ValueError("strategic position outcomes may occur once per position")
        _validate_nonblank_collection(
            self.campaign_modifier_ids,
            label="strategic campaign modifier ID",
        )
        if self.strategic_board is not None:
            if self.strategic_board.position_id != self.current_position_id:
                raise ValueError("strategic board position must match current position")
            board_player_ids = {item.player_id for item in self.strategic_board.players}
            if board_player_ids - known_player_ids:
                raise ValueError("strategic board references unknown players")
            for proposal in self.strategic_board.proposals:
                if proposal.proposer_player_id not in known_player_ids:
                    raise ValueError("strategic proposal references an unknown proposer")
                if set(proposal.supporter_player_ids) - known_player_ids:
                    raise ValueError("strategic proposal references unknown supporters")

        collections = (
            ("available location ID", self.available_location_ids),
            ("available evidence ID", self.available_evidence_ids),
            ("examined evidence ID", self.examined_evidence_ids),
            ("completed action ID", self.completed_action_ids),
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
            ("completed position ID", self.completed_position_ids),
        )

        for label, values in collections:
            _validate_nonblank_collection(values, label=label)

    def get_player(self, player_id: str) -> V2PlayerState | None:
        return next(
            (player for player in self.players if player.player_id == player_id),
            None,
        )

    def get_assessment(self, assessment_id: str) -> V2AssessmentState | None:
        return next(
            (assessment for assessment in self.assessments if assessment.id == assessment_id),
            None,
        )

    def get_position_quality_seal(self, position_id: str) -> V2PositionQualitySealState | None:
        return next(
            (seal for seal in self.position_quality_seals if seal.position_id == position_id),
            None,
        )

    def get_adaptation_selection(self, target_id: str) -> V2AdaptationSelectionState | None:
        return next(
            (item for item in self.adaptation_selections if item.target_id == target_id),
            None,
        )

    def get_stochastic_process(
        self,
        process_id: str,
    ) -> V2StochasticProcessState | None:
        return next(
            (item for item in self.stochastic_processes if item.process_id == process_id),
            None,
        )

    def get_stochastic_support(
        self,
        process_id: str,
    ) -> V2StochasticModelSupportState | None:
        return next(
            (item for item in self.stochastic_model_support if item.process_id == process_id),
            None,
        )

    def get_campaign_track(self, track_id: str) -> V2StrategicTrackState | None:
        return next((item for item in self.campaign_tracks if item.track_id == track_id), None)

    def get_strategic_outcome(
        self, position_id: str
    ) -> V2StrategicPositionOutcomeState | None:
        return next(
            (item for item in self.strategic_position_outcomes if item.position_id == position_id),
            None,
        )

    def stochastic_observation_count(self, process_id: str) -> int:
        return sum(
            item.process_id == process_id
            for item in self.stochastic_observations
        )
