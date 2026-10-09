from __future__ import annotations

import re
from typing import Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationInfo,
    field_validator,
    model_validator,
)

_IDENTIFIER_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")


def _identifier(value: str) -> str:
    cleaned = value.strip()

    if not _IDENTIFIER_PATTERN.fullmatch(cleaned):
        raise ValueError(
            "identifiers must begin with a lowercase letter and contain "
            "only lowercase letters, numbers, and underscores"
        )

    return cleaned


def _nonblank(value: str) -> str:
    cleaned = value.strip()

    if not cleaned:
        raise ValueError("text must not be blank")

    return cleaned


def _optional_text(value: str | None) -> str | None:
    if value is None:
        return None

    return _nonblank(value)


def _identifier_tuple(
    values: tuple[str, ...],
    *,
    label: str,
) -> tuple[str, ...]:
    cleaned = tuple(_identifier(value) for value in values)

    if len(cleaned) != len(set(cleaned)):
        raise ValueError(f"{label} must be unique")

    return cleaned


def _text_tuple(
    values: tuple[str, ...],
    *,
    label: str,
) -> tuple[str, ...]:
    cleaned = tuple(_nonblank(value) for value in values)
    normalized = tuple(value.casefold() for value in cleaned)

    if len(normalized) != len(set(normalized)):
        raise ValueError(f"{label} must be unique")

    return cleaned


def _duplicate_values(values: tuple[str | int, ...]) -> tuple[str | int, ...]:
    seen: set[str | int] = set()
    duplicates: set[str | int] = set()

    for value in values:
        if value in seen:
            duplicates.add(value)
        else:
            seen.add(value)

    return tuple(sorted(duplicates, key=str))


class _V2StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class V2PackMetadataDefinition(_V2StrictModel):
    id: str
    title: str
    content_version: str
    initial_position_id: str

    @field_validator("id", "initial_position_id")
    @classmethod
    def validate_identifiers(cls, value: str) -> str:
        return _identifier(value)

    @field_validator("title", "content_version")
    @classmethod
    def validate_text(cls, value: str) -> str:
        return _nonblank(value)


class V2LocationDefinition(_V2StrictModel):
    id: str
    name: str
    description: str
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    map_label: str | None = None
    public_coordinate_precision_km: float | None = Field(default=None, gt=0, le=1000)

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        return _identifier(value)

    @field_validator("name", "description")
    @classmethod
    def validate_text(cls, value: str) -> str:
        return _nonblank(value)

    @field_validator("map_label")
    @classmethod
    def validate_optional_map_label(cls, value: str | None) -> str | None:
        return _optional_text(value)

    @model_validator(mode="after")
    def validate_map_coordinates(self) -> Self:
        mapped = (
            self.latitude,
            self.longitude,
            self.map_label,
            self.public_coordinate_precision_km,
        )
        if any(value is not None for value in mapped) and any(
            value is None for value in mapped
        ):
            raise ValueError(
                "latitude, longitude, map_label, and public_coordinate_precision_km "
                "must be supplied together"
            )
        return self


class V2CompletionRouteDefinition(_V2StrictModel):
    """One bounded, valid route through a position.

    Routes replace the old requirement that every listed capability be completed.
    A route is satisfied when its explicit requirements and its candidate-action
    threshold are met. Static completion fields remain supported for legacy packs.
    """

    id: str
    title: str
    description: str
    required_action_ids: tuple[str, ...] = ()
    candidate_action_ids: tuple[str, ...] = ()
    minimum_completed_action_count: int = Field(default=0, ge=0)
    required_stochastic_process_ids: tuple[str, ...] = ()
    minimum_stochastic_observation_count: int = Field(default=0, ge=0)

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        return _identifier(value)

    @field_validator("title", "description")
    @classmethod
    def validate_text(cls, value: str) -> str:
        return _nonblank(value)

    @field_validator(
        "required_action_ids",
        "candidate_action_ids",
        "required_stochastic_process_ids",
    )
    @classmethod
    def validate_identifiers(
        cls,
        value: tuple[str, ...],
        info: ValidationInfo,
    ) -> tuple[str, ...]:
        return _identifier_tuple(
            value,
            label=(info.field_name or "route IDs").replace("_", " "),
        )

    @model_validator(mode="after")
    def validate_threshold(self) -> Self:
        if self.minimum_completed_action_count > len(self.candidate_action_ids):
            raise ValueError(
                "minimum_completed_action_count cannot exceed candidate_action_ids"
            )
        if self.minimum_stochastic_observation_count and not self.required_stochastic_process_ids:
            raise ValueError(
                "minimum stochastic observations require at least one stochastic process"
            )
        return self


class V2StochasticDatumDefinition(_V2StrictModel):
    key: str
    value: str | int | float | bool
    unit: str | None = None
    uncertainty: str | None = None

    @field_validator("key")
    @classmethod
    def validate_key(cls, value: str) -> str:
        return _identifier(value)

    @field_validator("unit", "uncertainty")
    @classmethod
    def validate_optional_text(cls, value: str | None) -> str | None:
        return _optional_text(value)


class V2StochasticLikelihoodDefinition(_V2StrictModel):
    model_id: str
    weight: int = Field(ge=0, le=1_000_000)

    @field_validator("model_id")
    @classmethod
    def validate_model_id(cls, value: str) -> str:
        return _identifier(value)


class V2StochasticTransitionDefinition(_V2StrictModel):
    state_id: str
    weight: int = Field(gt=0, le=1_000_000)

    @field_validator("state_id")
    @classmethod
    def validate_state_id(cls, value: str) -> str:
        return _identifier(value)


class V2StochasticOutcomeDefinition(_V2StrictModel):
    id: str
    public_summary: str
    weight: int = Field(gt=0, le=1_000_000)
    tags: tuple[str, ...] = ()
    measurements: tuple[V2StochasticDatumDefinition, ...] = ()
    likelihoods: tuple[V2StochasticLikelihoodDefinition, ...] = ()
    unlock_evidence_ids: tuple[str, ...] = ()

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        return _identifier(value)

    @field_validator("public_summary")
    @classmethod
    def validate_summary(cls, value: str) -> str:
        return _nonblank(value)

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _identifier_tuple(value, label="stochastic outcome tags")

    @field_validator("unlock_evidence_ids")
    @classmethod
    def validate_unlocks(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _identifier_tuple(value, label="stochastic outcome unlock evidence IDs")

    @model_validator(mode="after")
    def validate_unique_values(self) -> Self:
        measurement_keys = tuple(item.key for item in self.measurements)
        likelihood_models = tuple(item.model_id for item in self.likelihoods)
        if len(measurement_keys) != len(set(measurement_keys)):
            raise ValueError("stochastic outcome measurement keys must be unique")
        if len(likelihood_models) != len(set(likelihood_models)):
            raise ValueError("stochastic outcome likelihood models must be unique")
        return self


class V2StochasticEmissionDefinition(_V2StrictModel):
    channel_id: str
    outcomes: tuple[V2StochasticOutcomeDefinition, ...]

    @field_validator("channel_id")
    @classmethod
    def validate_channel_id(cls, value: str) -> str:
        return _identifier(value)

    @model_validator(mode="after")
    def validate_outcomes(self) -> Self:
        if not self.outcomes:
            raise ValueError("a stochastic emission channel requires outcomes")
        outcome_ids = tuple(item.id for item in self.outcomes)
        if len(outcome_ids) != len(set(outcome_ids)):
            raise ValueError("stochastic outcome IDs must be unique within a channel")
        return self


class V2StochasticStateDefinition(_V2StrictModel):
    id: str
    public_label: str | None = None
    tags: tuple[str, ...] = ()
    transitions: tuple[V2StochasticTransitionDefinition, ...]
    emissions: tuple[V2StochasticEmissionDefinition, ...]

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        return _identifier(value)

    @field_validator("public_label")
    @classmethod
    def validate_public_label(cls, value: str | None) -> str | None:
        return _optional_text(value)

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _identifier_tuple(value, label="stochastic state tags")

    @model_validator(mode="after")
    def validate_state(self) -> Self:
        if not self.transitions:
            raise ValueError("a stochastic state requires transitions")
        if not self.emissions:
            raise ValueError("a stochastic state requires emission channels")
        transition_ids = tuple(item.state_id for item in self.transitions)
        channel_ids = tuple(item.channel_id for item in self.emissions)
        if len(transition_ids) != len(set(transition_ids)):
            raise ValueError("stochastic transition targets must be unique")
        if len(channel_ids) != len(set(channel_ids)):
            raise ValueError("stochastic emission channel IDs must be unique")
        return self


class V2StochasticProcessDefinition(_V2StrictModel):
    """Content-driven hidden-state process resolved before event persistence."""

    id: str
    title: str
    description: str
    location_id: str
    algorithm: Literal["hidden_markov", "semi_markov"] = "hidden_markov"
    algorithm_version: int = Field(default=1, ge=1)
    initial_state_id: str
    model_ids: tuple[str, ...]
    initial_model_weights: tuple[V2StochasticLikelihoodDefinition, ...]
    posterior_learning_rate_basis_points: int = Field(default=3000, ge=0, le=10_000)
    minimum_model_support_basis_points: int = Field(default=250, ge=0, le=2500)
    reveal_latent_state: bool = False
    states: tuple[V2StochasticStateDefinition, ...]

    @field_validator("id", "location_id", "initial_state_id")
    @classmethod
    def validate_identifiers(cls, value: str) -> str:
        return _identifier(value)

    @field_validator("title", "description")
    @classmethod
    def validate_text(cls, value: str) -> str:
        return _nonblank(value)

    @field_validator("model_ids")
    @classmethod
    def validate_models(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = _identifier_tuple(value, label="stochastic model IDs")
        if not cleaned:
            raise ValueError("a stochastic process requires at least one model")
        return cleaned

    @model_validator(mode="after")
    def validate_process(self) -> Self:
        if not self.states:
            raise ValueError("a stochastic process requires states")
        state_ids = tuple(item.id for item in self.states)
        if len(state_ids) != len(set(state_ids)):
            raise ValueError("stochastic state IDs must be unique")
        if self.initial_state_id not in state_ids:
            raise ValueError("initial_state_id must reference a process state")
        model_set = set(self.model_ids)
        initial_models = tuple(item.model_id for item in self.initial_model_weights)
        if set(initial_models) != model_set or len(initial_models) != len(model_set):
            raise ValueError("initial_model_weights must define every model exactly once")
        if sum(item.weight for item in self.initial_model_weights) <= 0:
            raise ValueError("initial model weights must have positive total weight")
        if self.minimum_model_support_basis_points * len(self.model_ids) >= 10_000:
            raise ValueError(
                "minimum model support must leave probability mass for updating"
            )
        state_set = set(state_ids)
        expected_channels: set[str] | None = None
        for state in self.states:
            unknown_targets = {item.state_id for item in state.transitions} - state_set
            if unknown_targets:
                raise ValueError(
                    f"stochastic state {state.id!r} transitions to unknown states: "
                    + ", ".join(sorted(unknown_targets))
                )
            channels = {item.channel_id for item in state.emissions}
            if expected_channels is None:
                expected_channels = channels
            elif channels != expected_channels:
                raise ValueError("every stochastic state must expose the same channels")
            for emission in state.emissions:
                for outcome in emission.outcomes:
                    outcome_models = {item.model_id for item in outcome.likelihoods}
                    if outcome_models and outcome_models != model_set:
                        raise ValueError(
                            f"outcome {outcome.id!r} must provide likelihoods for every model"
                        )
        return self


class V2PositionCompletionDefinition(_V2StrictModel):
    minimum_examined_source_classes: int = Field(default=0, ge=0)
    minimum_confirmation_count: int = Field(default=1, ge=1)
    completion_routes: tuple[V2CompletionRouteDefinition, ...] = ()
    required_completed_action_ids: tuple[str, ...] = ()
    required_tested_ordinary_explanation_ids: tuple[str, ...] = ()
    required_preserved_contradiction_ids: tuple[str, ...] = ()
    required_documented_information_gap_ids: tuple[str, ...] = ()

    @field_validator(
        "required_completed_action_ids",
        "required_tested_ordinary_explanation_ids",
        "required_preserved_contradiction_ids",
        "required_documented_information_gap_ids",
    )
    @classmethod
    def validate_identifier_collections(
        cls,
        value: tuple[str, ...],
        info: ValidationInfo,
    ) -> tuple[str, ...]:
        field_name = info.field_name or "values"

        return _identifier_tuple(
            value,
            label=field_name.replace("_", " "),
        )


class V2AdaptationVariantDefinition(_V2StrictModel):
    presentation_id: str
    prologue: str
    guidance: tuple[str, ...] = ()
    required_action_id: str | None = None
    optional_action_ids: tuple[str, ...] = ()
    unlock_evidence_ids: tuple[str, ...] = ()

    @field_validator("presentation_id")
    @classmethod
    def validate_presentation_id(cls, value: str) -> str:
        return _identifier(value)

    @field_validator("required_action_id")
    @classmethod
    def validate_required_action_id(cls, value: str | None) -> str | None:
        return None if value is None else _identifier(value)

    @field_validator("prologue")
    @classmethod
    def validate_prologue(cls, value: str) -> str:
        return _nonblank(value)

    @field_validator("guidance")
    @classmethod
    def validate_guidance(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _text_tuple(value, label="adaptation guidance")

    @field_validator("optional_action_ids", "unlock_evidence_ids")
    @classmethod
    def validate_ids(
        cls,
        value: tuple[str, ...],
        info: ValidationInfo,
    ) -> tuple[str, ...]:
        return _identifier_tuple(
            value,
            label=(info.field_name or "adaptation IDs").replace("_", " "),
        )


class V2AdaptationManifestDefinition(_V2StrictModel):
    corrective: V2AdaptationVariantDefinition
    baseline: V2AdaptationVariantDefinition
    advanced: V2AdaptationVariantDefinition


class V2EndingVariantDefinition(_V2StrictModel):
    presentation_id: str
    prose: str

    @field_validator("presentation_id")
    @classmethod
    def validate_presentation_id(cls, value: str) -> str:
        return _identifier(value)

    @field_validator("prose")
    @classmethod
    def validate_prose(cls, value: str) -> str:
        return _nonblank(value)


class V2EndingManifestDefinition(_V2StrictModel):
    corrective: V2EndingVariantDefinition
    baseline: V2EndingVariantDefinition
    advanced: V2EndingVariantDefinition


class V2InvestigationPositionDefinition(_V2StrictModel):
    id: str
    ordinal: int = Field(ge=0)
    title: str
    focus_location_id: str
    next_position_id: str | None = None
    initially_available_location_ids: tuple[str, ...]
    available_evidence_ids_on_entry: tuple[str, ...] = ()
    required_location_ids: tuple[str, ...] = ()
    completion: V2PositionCompletionDefinition = Field(
        default_factory=V2PositionCompletionDefinition
    )
    adaptation: V2AdaptationManifestDefinition | None = None
    fixed_opening: V2AdaptationVariantDefinition | None = None

    @field_validator("id", "focus_location_id")
    @classmethod
    def validate_identifiers(cls, value: str) -> str:
        return _identifier(value)

    @field_validator("next_position_id")
    @classmethod
    def validate_optional_next_position_id(
        cls,
        value: str | None,
    ) -> str | None:
        if value is None:
            return None

        return _identifier(value)

    @field_validator("title")
    @classmethod
    def validate_title(cls, value: str) -> str:
        return _nonblank(value)

    @field_validator(
        "initially_available_location_ids",
        "required_location_ids",
    )
    @classmethod
    def validate_location_ids(
        cls,
        value: tuple[str, ...],
        info: ValidationInfo,
    ) -> tuple[str, ...]:
        field_name = info.field_name or "location IDs"

        return _identifier_tuple(
            value,
            label=field_name.replace("_", " "),
        )

    @field_validator("available_evidence_ids_on_entry")
    @classmethod
    def validate_entry_evidence_ids(
        cls,
        value: tuple[str, ...],
    ) -> tuple[str, ...]:
        return _identifier_tuple(
            value,
            label="available evidence IDs on entry",
        )


class V2RoleDefinition(_V2StrictModel):
    id: str
    name: str
    scope: Literal["position", "arc"]
    description: str
    allowed_location_ids: tuple[str, ...] = ()
    allow_player_defined_name: bool = True
    allow_player_defined_description: bool = True

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        return _identifier(value)

    @field_validator("name", "description")
    @classmethod
    def validate_text(cls, value: str) -> str:
        return _nonblank(value)

    @field_validator("allowed_location_ids")
    @classmethod
    def validate_allowed_locations(
        cls,
        value: tuple[str, ...],
    ) -> tuple[str, ...]:
        return _identifier_tuple(
            value,
            label="allowed location IDs",
        )


class V2InstrumentDefinition(_V2StrictModel):
    id: str
    name: str
    location_id: str

    intended_purpose: str
    operational_reliability: str
    scientific_suitability: str

    calibration_status: str
    alignment_status: str | None = None
    resolution: str | None = None

    coverage_limits: tuple[str, ...] = ()
    assumptions: tuple[str, ...] = ()

    @field_validator("id", "location_id")
    @classmethod
    def validate_identifiers(cls, value: str) -> str:
        return _identifier(value)

    @field_validator(
        "name",
        "intended_purpose",
        "operational_reliability",
        "scientific_suitability",
        "calibration_status",
    )
    @classmethod
    def validate_text(cls, value: str) -> str:
        return _nonblank(value)

    @field_validator("alignment_status", "resolution")
    @classmethod
    def validate_optional_text(cls, value: str | None) -> str | None:
        return _optional_text(value)

    @field_validator("coverage_limits", "assumptions")
    @classmethod
    def validate_text_collections(
        cls,
        value: tuple[str, ...],
        info: ValidationInfo,
    ) -> tuple[str, ...]:
        field_name = info.field_name or "values"

        return _text_tuple(
            value,
            label=field_name.replace("_", " "),
        )


class V2EvidenceSourceDefinition(_V2StrictModel):
    id: str
    name: str
    source_class: str

    origin_location_id: str
    instrument_id: str | None = None

    provenance: str
    independence_group: str
    raw_or_derived: Literal[
        "raw",
        "processed",
        "derived",
        "testimony",
        "summary",
    ]

    processing_history: tuple[str, ...] = ()
    uncertainty: str
    limitations: tuple[str, ...] = ()
    supported_conclusions: tuple[str, ...] = ()
    unsupported_extrapolations: tuple[str, ...] = ()

    initially_available: bool = False

    @field_validator(
        "id",
        "source_class",
        "origin_location_id",
        "independence_group",
    )
    @classmethod
    def validate_identifiers(cls, value: str) -> str:
        return _identifier(value)

    @field_validator("instrument_id")
    @classmethod
    def validate_optional_identifier(
        cls,
        value: str | None,
    ) -> str | None:
        if value is None:
            return None

        return _identifier(value)

    @field_validator("name", "provenance", "uncertainty")
    @classmethod
    def validate_text(cls, value: str) -> str:
        return _nonblank(value)

    @field_validator(
        "processing_history",
        "limitations",
        "supported_conclusions",
        "unsupported_extrapolations",
    )
    @classmethod
    def validate_text_collections(
        cls,
        value: tuple[str, ...],
        info: ValidationInfo,
    ) -> tuple[str, ...]:
        field_name = info.field_name or "values"

        return _text_tuple(
            value,
            label=field_name.replace("_", " "),
        )


class V2InvestigationItemDefinition(_V2StrictModel):
    id: str
    title: str
    description: str

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        return _identifier(value)

    @field_validator("title", "description")
    @classmethod
    def validate_text(cls, value: str) -> str:
        return _nonblank(value)


class V2ActionPrerequisitesDefinition(_V2StrictModel):
    """Hard requirements plus bounded choice gates for one capability.

    ``required_*`` values are conjunctive. Candidate collections are threshold
    gates: a capability may proceed after enough items from the collection have
    been established. This lets a position offer genuinely different evidence
    routes without weakening role, location, or replay guarantees.
    """

    required_role_ids: tuple[str, ...] = ()
    required_examined_evidence_ids: tuple[str, ...] = ()
    candidate_examined_evidence_ids: tuple[str, ...] = ()
    minimum_examined_evidence_count: int = Field(default=0, ge=0)
    required_completed_action_ids: tuple[str, ...] = ()
    candidate_completed_action_ids: tuple[str, ...] = ()
    minimum_completed_action_count: int = Field(default=0, ge=0)
    required_stochastic_process_ids: tuple[str, ...] = ()
    minimum_stochastic_observation_count: int = Field(default=0, ge=0)

    @field_validator(
        "required_role_ids",
        "required_examined_evidence_ids",
        "candidate_examined_evidence_ids",
        "required_completed_action_ids",
        "candidate_completed_action_ids",
        "required_stochastic_process_ids",
    )
    @classmethod
    def validate_identifier_collections(
        cls,
        value: tuple[str, ...],
        info: ValidationInfo,
    ) -> tuple[str, ...]:
        field_name = info.field_name or "values"

        return _identifier_tuple(
            value,
            label=field_name.replace("_", " "),
        )

    @model_validator(mode="after")
    def validate_choice_gates(self) -> Self:
        if self.minimum_examined_evidence_count > len(
            self.candidate_examined_evidence_ids
        ):
            raise ValueError(
                "minimum_examined_evidence_count cannot exceed "
                "candidate_examined_evidence_ids"
            )
        if self.minimum_completed_action_count > len(
            self.candidate_completed_action_ids
        ):
            raise ValueError(
                "minimum_completed_action_count cannot exceed "
                "candidate_completed_action_ids"
            )
        if (
            self.minimum_stochastic_observation_count
            and not self.required_stochastic_process_ids
        ):
            raise ValueError(
                "minimum stochastic observations require stochastic process IDs"
            )
        if set(self.required_examined_evidence_ids) & set(
            self.candidate_examined_evidence_ids
        ):
            raise ValueError(
                "required and candidate examined evidence IDs must be disjoint"
            )
        if set(self.required_completed_action_ids) & set(
            self.candidate_completed_action_ids
        ):
            raise ValueError(
                "required and candidate completed action IDs must be disjoint"
            )
        return self


class V2ActionEffectsDefinition(_V2StrictModel):
    unlock_evidence_ids: tuple[str, ...] = ()
    mark_ordinary_explanation_tested_ids: tuple[str, ...] = ()
    preserve_contradiction_ids: tuple[str, ...] = ()
    document_information_gap_ids: tuple[str, ...] = ()

    @field_validator(
        "unlock_evidence_ids",
        "mark_ordinary_explanation_tested_ids",
        "preserve_contradiction_ids",
        "document_information_gap_ids",
    )
    @classmethod
    def validate_identifier_collections(
        cls,
        value: tuple[str, ...],
        info: ValidationInfo,
    ) -> tuple[str, ...]:
        field_name = info.field_name or "values"

        return _identifier_tuple(
            value,
            label=field_name.replace("_", " "),
        )


class V2StrategicDeltaDefinition(_V2StrictModel):
    target_id: str
    amount: int = Field(ge=-8, le=8)

    @field_validator("target_id")
    @classmethod
    def validate_target_id(cls, value: str) -> str:
        return _identifier(value)


class V2StrategicConditionGrantDefinition(_V2StrictModel):
    id: str
    duration: Literal["round", "next_round", "position", "campaign"] = "position"

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        return _identifier(value)


class V2StrategicTagModifierDefinition(_V2StrictModel):
    id: str
    target_tags: tuple[str, ...]
    multiplier_basis_points: int = Field(ge=1, le=100_000)
    when_condition: str | None = None
    unless_condition: str | None = None

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        return _identifier(value)

    @field_validator("target_tags")
    @classmethod
    def validate_target_tags(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = _identifier_tuple(value, label="strategic modifier target tags")
        if not cleaned:
            raise ValueError("strategic modifiers require at least one target tag")
        return cleaned

    @field_validator("when_condition", "unless_condition")
    @classmethod
    def validate_condition_id(cls, value: str | None) -> str | None:
        return None if value is None else _identifier(value)

    @model_validator(mode="after")
    def validate_condition_gate(self) -> Self:
        if self.when_condition is not None and self.when_condition == self.unless_condition:
            raise ValueError("when_condition and unless_condition cannot be identical")
        return self


class V2StrategicActionEffectsDefinition(_V2StrictModel):
    campaign_track_deltas: tuple[V2StrategicDeltaDefinition, ...] = ()
    position_track_deltas: tuple[V2StrategicDeltaDefinition, ...] = ()
    resource_deltas: tuple[V2StrategicDeltaDefinition, ...] = ()
    add_conditions: tuple[V2StrategicConditionGrantDefinition, ...] = ()
    remove_condition_ids: tuple[str, ...] = ()

    @field_validator("remove_condition_ids")
    @classmethod
    def validate_remove_condition_ids(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _identifier_tuple(value, label="strategic removed condition IDs")

    @model_validator(mode="after")
    def validate_unique_effect_targets(self) -> Self:
        for label, values in (
            ("campaign track deltas", self.campaign_track_deltas),
            ("position track deltas", self.position_track_deltas),
            ("resource deltas", self.resource_deltas),
        ):
            ids = tuple(item.target_id for item in values)
            if len(ids) != len(set(ids)):
                raise ValueError(f"{label} must target each ID at most once")
        condition_ids = tuple(item.id for item in self.add_conditions)
        if len(condition_ids) != len(set(condition_ids)):
            raise ValueError("strategic condition grants must be unique")
        return self


class V2StrategicActionProfileDefinition(_V2StrictModel):
    strategic_class: Literal[
        "observe", "prepare", "probe", "secure", "coordinate", "commit", "reconcile"
    ]
    capacity_cost: int = Field(default=1, ge=0, le=3)
    coordination_cost: int = Field(default=0, ge=0, le=3)
    supporter_count: int = Field(default=0, ge=0, le=4)
    irreversible: bool = False
    stochastic_mode: Literal["none", "emit_only", "intervention_then_emit"] = "none"
    deterministic_effects: V2StrategicActionEffectsDefinition = Field(
        default_factory=V2StrategicActionEffectsDefinition
    )
    transition_modifiers: tuple[V2StrategicTagModifierDefinition, ...] = ()
    emission_modifiers: tuple[V2StrategicTagModifierDefinition, ...] = ()

    @model_validator(mode="after")
    def validate_profile(self) -> Self:
        if self.strategic_class == "commit" and self.supporter_count < 1:
            raise ValueError("commit actions require at least one independent supporter")
        if self.irreversible and self.supporter_count < 1:
            raise ValueError("irreversible actions require at least one independent supporter")
        if self.stochastic_mode == "none" and (
            self.transition_modifiers or self.emission_modifiers
        ):
            raise ValueError("probability modifiers require a stochastic action mode")
        if self.stochastic_mode != "intervention_then_emit" and self.transition_modifiers:
            raise ValueError("transition modifiers require intervention_then_emit")
        return self


class V2StrategicTrackDefinition(_V2StrictModel):
    id: str
    title: str
    minimum: int = Field(default=0, ge=0, le=100)
    maximum: int = Field(default=8, ge=1, le=100)
    initial: int = Field(default=5, ge=0, le=100)

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        return _identifier(value)

    @field_validator("title")
    @classmethod
    def validate_title(cls, value: str) -> str:
        return _nonblank(value)

    @model_validator(mode="after")
    def validate_range(self) -> Self:
        if self.minimum >= self.maximum:
            raise ValueError("strategic track minimum must be below maximum")
        if not self.minimum <= self.initial <= self.maximum:
            raise ValueError("strategic track initial value must be in range")
        return self


class V2StrategicResourceDefinition(_V2StrictModel):
    id: str
    title: str
    minimum: int = Field(default=0, ge=0, le=100)
    maximum: int = Field(default=3, ge=1, le=100)
    initial: int = Field(default=2, ge=0, le=100)

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        return _identifier(value)

    @field_validator("title")
    @classmethod
    def validate_title(cls, value: str) -> str:
        return _nonblank(value)

    @model_validator(mode="after")
    def validate_range(self) -> Self:
        if self.minimum >= self.maximum:
            raise ValueError("strategic resource minimum must be below maximum")
        if not self.minimum <= self.initial <= self.maximum:
            raise ValueError("strategic resource initial value must be in range")
        return self


class V2StrategicPositionDefinition(_V2StrictModel):
    position_id: str
    max_rounds: int = Field(default=4, ge=1, le=8)
    capacity_per_round: int = Field(default=3, ge=1, le=8)
    coordination_maximum: int = Field(default=3, ge=1, le=8)
    escalation_maximum: int = Field(default=6, ge=1, le=12)
    local_resource: V2StrategicResourceDefinition
    natural_drift_process_id: str | None = None
    controlled_integrity_minimum: int = Field(default=4, ge=0, le=8)
    controlled_trust_minimum: int = Field(default=3, ge=0, le=8)
    controlled_escalation_maximum: int = Field(default=3, ge=0, le=12)

    @field_validator("position_id")
    @classmethod
    def validate_position_id(cls, value: str) -> str:
        return _identifier(value)

    @field_validator("natural_drift_process_id")
    @classmethod
    def validate_process_id(cls, value: str | None) -> str | None:
        return None if value is None else _identifier(value)

    @model_validator(mode="after")
    def validate_thresholds(self) -> Self:
        if self.controlled_escalation_maximum > self.escalation_maximum:
            raise ValueError("controlled escalation threshold exceeds the track maximum")
        return self


class V2StrategicCampaignDefinition(_V2StrictModel):
    campaign_tracks: tuple[V2StrategicTrackDefinition, ...]
    positions: tuple[V2StrategicPositionDefinition, ...]
    second_operation_surcharge: int = Field(default=1, ge=0, le=3)
    max_operations_per_player_per_round: int = Field(default=2, ge=1, le=4)
    maximum_active_proposals_per_player: int = Field(default=1, ge=1, le=4)

    @model_validator(mode="after")
    def validate_unique_ids(self) -> Self:
        track_ids = tuple(item.id for item in self.campaign_tracks)
        position_ids = tuple(item.position_id for item in self.positions)
        if not track_ids:
            raise ValueError("strategic campaigns require campaign tracks")
        if len(track_ids) != len(set(track_ids)):
            raise ValueError("strategic campaign track IDs must be unique")
        if len(position_ids) != len(set(position_ids)):
            raise ValueError("strategic position rules must be unique")
        return self


class V2InvestigationActionDefinition(_V2StrictModel):
    id: str
    title: str
    description: str
    action_type: Literal[
        "inspect",
        "calibrate",
        "request",
        "compare",
        "test_explanation",
        "document_gap",
    ]
    position_id: str | None = None
    location_id: str
    prerequisites: V2ActionPrerequisitesDefinition = Field(
        default_factory=V2ActionPrerequisitesDefinition
    )
    effects: V2ActionEffectsDefinition = Field(default_factory=V2ActionEffectsDefinition)
    repeatable: bool = False
    stochastic_process_id: str | None = None
    stochastic_channel_id: str | None = None
    advance_stochastic_state: bool = True
    strategic: V2StrategicActionProfileDefinition | None = None

    @field_validator("id", "location_id")
    @classmethod
    def validate_identifiers(cls, value: str) -> str:
        return _identifier(value)

    @field_validator("position_id")
    @classmethod
    def validate_position_id(cls, value: str | None) -> str | None:
        return None if value is None else _identifier(value)

    @field_validator("stochastic_process_id", "stochastic_channel_id")
    @classmethod
    def validate_optional_stochastic_identifier(cls, value: str | None) -> str | None:
        return None if value is None else _identifier(value)

    @field_validator("title", "description")
    @classmethod
    def validate_text(cls, value: str) -> str:
        return _nonblank(value)

    @model_validator(mode="after")
    def validate_stochastic_binding(self) -> Self:
        bound = (self.stochastic_process_id, self.stochastic_channel_id)
        if any(value is not None for value in bound) and any(value is None for value in bound):
            raise ValueError(
                "stochastic_process_id and stochastic_channel_id must be supplied together"
            )
        if self.strategic is not None:
            if self.strategic.stochastic_mode != "none" and self.stochastic_process_id is None:
                raise ValueError("strategic stochastic modes require a stochastic binding")
            if self.strategic.stochastic_mode == "none" and self.stochastic_process_id is not None:
                # Explicit none is permitted only for compatibility when the action does not sample.
                pass
        return self


class V2InvestigationPack(_V2StrictModel):
    schema_version: Literal[2, 3]
    pack: V2PackMetadataDefinition

    locations: tuple[V2LocationDefinition, ...]
    positions: tuple[V2InvestigationPositionDefinition, ...]
    roles: tuple[V2RoleDefinition, ...] = ()
    instruments: tuple[V2InstrumentDefinition, ...] = ()
    evidence_sources: tuple[V2EvidenceSourceDefinition, ...] = ()

    ordinary_explanations: tuple[V2InvestigationItemDefinition, ...] = ()
    contradictions: tuple[V2InvestigationItemDefinition, ...] = ()
    information_gaps: tuple[V2InvestigationItemDefinition, ...] = ()
    actions: tuple[V2InvestigationActionDefinition, ...] = ()
    stochastic_processes: tuple[V2StochasticProcessDefinition, ...] = ()
    strategic: V2StrategicCampaignDefinition | None = None
    endings: V2EndingManifestDefinition | None = None

    @model_validator(mode="after")
    def validate_pack_references(self) -> Self:
        if not self.locations:
            raise ValueError("an investigation pack must define at least one location")

        if not self.positions:
            raise ValueError("an investigation pack must define at least one position")

        location_ids = tuple(location.id for location in self.locations)
        position_ids = tuple(position.id for position in self.positions)
        position_ordinals = tuple(position.ordinal for position in self.positions)
        role_ids = tuple(role.id for role in self.roles)
        instrument_ids = tuple(instrument.id for instrument in self.instruments)
        evidence_ids = tuple(source.id for source in self.evidence_sources)
        ordinary_explanation_ids = tuple(item.id for item in self.ordinary_explanations)
        contradiction_ids = tuple(item.id for item in self.contradictions)
        information_gap_ids = tuple(item.id for item in self.information_gaps)
        action_ids = tuple(action.id for action in self.actions)
        stochastic_process_ids = tuple(item.id for item in self.stochastic_processes)

        uniqueness_checks = (
            ("location IDs", location_ids),
            ("position IDs", position_ids),
            ("position ordinals", position_ordinals),
            ("role IDs", role_ids),
            ("instrument IDs", instrument_ids),
            ("evidence source IDs", evidence_ids),
            ("ordinary explanation IDs", ordinary_explanation_ids),
            ("contradiction IDs", contradiction_ids),
            ("information gap IDs", information_gap_ids),
            ("action IDs", action_ids),
            ("stochastic process IDs", stochastic_process_ids),
        )

        for label, values in uniqueness_checks:
            duplicates = _duplicate_values(values)

            if duplicates:
                rendered = ", ".join(repr(value) for value in duplicates)
                raise ValueError(f"duplicate {label}: {rendered}")

        known_locations = set(location_ids)
        known_positions = set(position_ids)
        known_roles = set(role_ids)
        known_instruments = set(instrument_ids)
        known_evidence = set(evidence_ids)
        known_ordinary_explanations = set(ordinary_explanation_ids)
        known_contradictions = set(contradiction_ids)
        known_information_gaps = set(information_gap_ids)
        known_actions = set(action_ids)
        known_stochastic_processes = set(stochastic_process_ids)
        stochastic_by_id = {item.id: item for item in self.stochastic_processes}

        if self.pack.initial_position_id not in known_positions:
            raise ValueError(
                "initial position references an unknown position: "
                f"{self.pack.initial_position_id!r}"
            )

        for position in self.positions:
            if position.focus_location_id not in known_locations:
                raise ValueError(
                    f"position {position.id!r} references unknown focus location "
                    f"{position.focus_location_id!r}"
                )

            unknown_initial_locations = (
                set(position.initially_available_location_ids) - known_locations
            )

            if unknown_initial_locations:
                raise ValueError(
                    f"position {position.id!r} initially exposes unknown locations: "
                    + ", ".join(sorted(unknown_initial_locations))
                )

            unknown_required_locations = set(position.required_location_ids) - known_locations

            if unknown_required_locations:
                raise ValueError(
                    f"position {position.id!r} requires unknown locations: "
                    + ", ".join(sorted(unknown_required_locations))
                )

            if position.focus_location_id not in position.initially_available_location_ids:
                raise ValueError(
                    f"position {position.id!r} focus location "
                    f"{position.focus_location_id!r} must be initially available"
                )

            if position.next_position_id == position.id:
                raise ValueError(f"position {position.id!r} cannot advance to itself")

            if (
                position.next_position_id is not None
                and position.next_position_id not in known_positions
            ):
                raise ValueError(
                    f"position {position.id!r} advances to unknown position "
                    f"{position.next_position_id!r}"
                )

            unknown_entry_evidence = set(position.available_evidence_ids_on_entry) - known_evidence
            if unknown_entry_evidence:
                raise ValueError(
                    f"position {position.id!r} exposes unknown evidence on entry: "
                    + ", ".join(sorted(unknown_entry_evidence))
                )

            completion = position.completion

            if position.ordinal in {0, 1}:
                if position.adaptation is not None:
                    raise ValueError("positions 0 and 1 retain fixed openings")
            elif position.fixed_opening is not None:
                raise ValueError("only positions 0 and 1 may define fixed openings")
            if position.ordinal > 1 and position.adaptation is not None:
                for band in ("corrective", "baseline", "advanced"):
                    variant = getattr(position.adaptation, band)
                    referenced_actions = set(variant.optional_action_ids)
                    if variant.required_action_id is not None:
                        referenced_actions.add(variant.required_action_id)
                    unknown_adaptation_actions = referenced_actions - known_actions
                    if unknown_adaptation_actions:
                        raise ValueError(
                            f"position {position.id!r} {band} adaptation references "
                            "unknown actions: " + ", ".join(sorted(unknown_adaptation_actions))
                        )
                    unknown_adaptation_evidence = set(variant.unlock_evidence_ids) - known_evidence
                    if unknown_adaptation_evidence:
                        raise ValueError(
                            f"position {position.id!r} {band} adaptation unlocks "
                            "unknown evidence: " + ", ".join(sorted(unknown_adaptation_evidence))
                        )

            unknown_completion_actions = (
                set(completion.required_completed_action_ids) - known_actions
            )
            if unknown_completion_actions:
                raise ValueError(
                    f"position {position.id!r} completion requires unknown actions: "
                    + ", ".join(sorted(unknown_completion_actions))
                )

            unknown_completion_explanations = (
                set(completion.required_tested_ordinary_explanation_ids)
                - known_ordinary_explanations
            )
            if unknown_completion_explanations:
                raise ValueError(
                    f"position {position.id!r} completion requires unknown "
                    "ordinary explanations: " + ", ".join(sorted(unknown_completion_explanations))
                )

            unknown_completion_contradictions = (
                set(completion.required_preserved_contradiction_ids) - known_contradictions
            )
            if unknown_completion_contradictions:
                raise ValueError(
                    f"position {position.id!r} completion requires unknown "
                    "contradictions: " + ", ".join(sorted(unknown_completion_contradictions))
                )

            unknown_completion_gaps = (
                set(completion.required_documented_information_gap_ids) - known_information_gaps
            )
            if unknown_completion_gaps:
                raise ValueError(
                    f"position {position.id!r} completion requires unknown "
                    "information gaps: " + ", ".join(sorted(unknown_completion_gaps))
                )

            route_ids = tuple(route.id for route in completion.completion_routes)
            if len(route_ids) != len(set(route_ids)):
                raise ValueError(
                    f"position {position.id!r} completion route IDs must be unique"
                )
            for route in completion.completion_routes:
                referenced_actions = set(route.required_action_ids) | set(route.candidate_action_ids)
                unknown_route_actions = referenced_actions - known_actions
                if unknown_route_actions:
                    raise ValueError(
                        f"position {position.id!r} route {route.id!r} references unknown actions: "
                        + ", ".join(sorted(unknown_route_actions))
                    )
                unknown_route_processes = (
                    set(route.required_stochastic_process_ids) - known_stochastic_processes
                )
                if unknown_route_processes:
                    raise ValueError(
                        f"position {position.id!r} route {route.id!r} references unknown "
                        "stochastic processes: " + ", ".join(sorted(unknown_route_processes))
                    )

            available_source_class_count = len(
                {source.source_class for source in self.evidence_sources}
            )
            if completion.minimum_examined_source_classes > available_source_class_count:
                raise ValueError(
                    f"position {position.id!r} completion requires "
                    f"{completion.minimum_examined_source_classes} source classes, "
                    f"but the pack defines only {available_source_class_count}"
                )

        position_by_id = {position.id: position for position in self.positions}
        first_ordinal = min(position_ordinals)
        expected_ordinals = tuple(
            range(first_ordinal, first_ordinal + len(self.positions))
        )

        if (
            first_ordinal not in {0, 1}
            or tuple(sorted(position_ordinals)) != expected_ordinals
        ):
            raise ValueError(
                "position ordinals must be contiguous and begin at 0 or 1"
            )

        progression: list[V2InvestigationPositionDefinition] = []
        progression_ids: set[str] = set()
        current_position_id: str | None = self.pack.initial_position_id

        while current_position_id is not None:
            if current_position_id in progression_ids:
                raise ValueError(f"cyclic position progression involving {current_position_id!r}")

            current_position = position_by_id[current_position_id]
            progression.append(current_position)
            progression_ids.add(current_position_id)
            current_position_id = current_position.next_position_id

        unreachable_positions = known_positions - progression_ids
        if unreachable_positions:
            raise ValueError(
                "positions are unreachable from the initial position: "
                + ", ".join(sorted(unreachable_positions))
            )

        for current, following in zip(progression, progression[1:], strict=False):
            if following.ordinal != current.ordinal + 1:
                raise ValueError(
                    f"position {current.id!r} must advance to ordinal "
                    f"{current.ordinal + 1}, not {following.ordinal}"
                )

        cumulative_locations: set[str] = set()
        for position in progression:
            cumulative_locations.update(position.initially_available_location_ids)
            missing_required_locations = set(position.required_location_ids) - cumulative_locations
            if missing_required_locations:
                raise ValueError(
                    f"position {position.id!r} requires locations unavailable "
                    "along its progression path: " + ", ".join(sorted(missing_required_locations))
                )

        for role in self.roles:
            unknown_locations = set(role.allowed_location_ids) - known_locations

            if unknown_locations:
                raise ValueError(
                    f"role {role.id!r} references unknown locations: "
                    + ", ".join(sorted(unknown_locations))
                )

        instrument_by_id = {instrument.id: instrument for instrument in self.instruments}

        for instrument in self.instruments:
            if instrument.location_id not in known_locations:
                raise ValueError(
                    f"instrument {instrument.id!r} references unknown location "
                    f"{instrument.location_id!r}"
                )

        for source in self.evidence_sources:
            if source.origin_location_id not in known_locations:
                raise ValueError(
                    f"evidence source {source.id!r} references unknown origin "
                    f"location {source.origin_location_id!r}"
                )

            if source.instrument_id is None:
                continue

            if source.instrument_id not in known_instruments:
                raise ValueError(
                    f"evidence source {source.id!r} references unknown instrument "
                    f"{source.instrument_id!r}"
                )

            instrument = instrument_by_id[source.instrument_id]

            if instrument.location_id != source.origin_location_id:
                raise ValueError(
                    f"evidence source {source.id!r} origin location "
                    f"{source.origin_location_id!r} does not match instrument "
                    f"{source.instrument_id!r} location {instrument.location_id!r}"
                )

        action_dependencies: dict[str, set[str]] = {}

        for action in self.actions:
            if action.position_id is not None and action.position_id not in known_positions:
                raise ValueError(
                    f"action {action.id!r} references unknown position "
                    f"{action.position_id!r}"
                )
            if action.location_id not in known_locations:
                raise ValueError(
                    f"action {action.id!r} references unknown location {action.location_id!r}"
                )

            unknown_roles = set(action.prerequisites.required_role_ids) - known_roles
            if unknown_roles:
                raise ValueError(
                    f"action {action.id!r} requires unknown roles: "
                    + ", ".join(sorted(unknown_roles))
                )

            unknown_evidence = (
                set(action.prerequisites.required_examined_evidence_ids) - known_evidence
            )
            if unknown_evidence:
                raise ValueError(
                    f"action {action.id!r} requires unknown evidence: "
                    + ", ".join(sorted(unknown_evidence))
                )

            unknown_candidate_evidence = (
                set(action.prerequisites.candidate_examined_evidence_ids)
                - known_evidence
            )
            if unknown_candidate_evidence:
                raise ValueError(
                    f"action {action.id!r} references unknown candidate evidence: "
                    + ", ".join(sorted(unknown_candidate_evidence))
                )

            unknown_actions = (
                set(action.prerequisites.required_completed_action_ids) - known_actions
            )
            if unknown_actions:
                raise ValueError(
                    f"action {action.id!r} requires unknown actions: "
                    + ", ".join(sorted(unknown_actions))
                )

            unknown_candidate_actions = (
                set(action.prerequisites.candidate_completed_action_ids)
                - known_actions
            )
            if unknown_candidate_actions:
                raise ValueError(
                    f"action {action.id!r} references unknown candidate actions: "
                    + ", ".join(sorted(unknown_candidate_actions))
                )

            unknown_prerequisite_processes = (
                set(action.prerequisites.required_stochastic_process_ids)
                - known_stochastic_processes
            )
            if unknown_prerequisite_processes:
                raise ValueError(
                    f"action {action.id!r} references unknown prerequisite stochastic "
                    "processes: "
                    + ", ".join(sorted(unknown_prerequisite_processes))
                )

            if action.id in (
                set(action.prerequisites.required_completed_action_ids)
                | set(action.prerequisites.candidate_completed_action_ids)
            ):
                raise ValueError(f"action {action.id!r} cannot require itself")

            unknown_unlocks = set(action.effects.unlock_evidence_ids) - known_evidence
            if unknown_unlocks:
                raise ValueError(
                    f"action {action.id!r} unlocks unknown evidence: "
                    + ", ".join(sorted(unknown_unlocks))
                )

            unknown_explanations = (
                set(action.effects.mark_ordinary_explanation_tested_ids)
                - known_ordinary_explanations
            )
            if unknown_explanations:
                raise ValueError(
                    f"action {action.id!r} tests unknown ordinary explanations: "
                    + ", ".join(sorted(unknown_explanations))
                )

            unknown_contradictions = (
                set(action.effects.preserve_contradiction_ids) - known_contradictions
            )
            if unknown_contradictions:
                raise ValueError(
                    f"action {action.id!r} preserves unknown contradictions: "
                    + ", ".join(sorted(unknown_contradictions))
                )

            unknown_gaps = set(action.effects.document_information_gap_ids) - known_information_gaps
            if unknown_gaps:
                raise ValueError(
                    f"action {action.id!r} documents unknown information gaps: "
                    + ", ".join(sorted(unknown_gaps))
                )

            if action.stochastic_process_id is not None:
                process = stochastic_by_id.get(action.stochastic_process_id)
                if process is None:
                    raise ValueError(
                        f"action {action.id!r} references unknown stochastic process "
                        f"{action.stochastic_process_id!r}"
                    )
                if process.location_id != action.location_id:
                    raise ValueError(
                        f"action {action.id!r} stochastic process location does not match"
                    )
                channels = {
                    emission.channel_id
                    for state in process.states
                    for emission in state.emissions
                }
                if action.stochastic_channel_id not in channels:
                    raise ValueError(
                        f"action {action.id!r} references unknown stochastic channel "
                        f"{action.stochastic_channel_id!r}"
                    )

            action_dependencies[action.id] = set(action.prerequisites.required_completed_action_ids)

        for process in self.stochastic_processes:
            if process.location_id not in known_locations:
                raise ValueError(
                    f"stochastic process {process.id!r} references unknown location "
                    f"{process.location_id!r}"
                )
            for state in process.states:
                for emission in state.emissions:
                    for outcome in emission.outcomes:
                        unknown_outcome_unlocks = set(outcome.unlock_evidence_ids) - known_evidence
                        if unknown_outcome_unlocks:
                            raise ValueError(
                                f"stochastic outcome {outcome.id!r} unlocks unknown evidence: "
                                + ", ".join(sorted(unknown_outcome_unlocks))
                            )

        if self.strategic is not None:
            if self.schema_version < 3:
                raise ValueError("strategic campaign content requires schema_version 3")
            strategic_position_ids = {item.position_id for item in self.strategic.positions}
            expected_strategic_positions = {
                item.id for item in self.positions if item.ordinal > 0
            }
            missing_strategic_positions = expected_strategic_positions - strategic_position_ids
            unknown_strategic_positions = strategic_position_ids - known_positions
            if missing_strategic_positions:
                raise ValueError(
                    "strategic rules are missing positions: "
                    + ", ".join(sorted(missing_strategic_positions))
                )
            if unknown_strategic_positions:
                raise ValueError(
                    "strategic rules reference unknown positions: "
                    + ", ".join(sorted(unknown_strategic_positions))
                )
            campaign_track_ids = {item.id for item in self.strategic.campaign_tracks}
            required_tracks = {"case_integrity", "institutional_trust"}
            if not required_tracks.issubset(campaign_track_ids):
                raise ValueError(
                    "strategic campaign tracks must include case_integrity and institutional_trust"
                )
            for rules in self.strategic.positions:
                if (
                    rules.natural_drift_process_id is not None
                    and rules.natural_drift_process_id not in known_stochastic_processes
                ):
                    raise ValueError(
                        f"strategic position {rules.position_id!r} references unknown drift process "
                        f"{rules.natural_drift_process_id!r}"
                    )
                local_ids = {
                    "coordination", "escalation", rules.local_resource.id
                }
                for action in self.actions:
                    if action.position_id != rules.position_id or action.strategic is None:
                        continue
                    profile = action.strategic
                    unknown_campaign_deltas = {
                        item.target_id
                        for item in profile.deterministic_effects.campaign_track_deltas
                    } - campaign_track_ids
                    if unknown_campaign_deltas:
                        raise ValueError(
                            f"action {action.id!r} changes unknown campaign tracks: "
                            + ", ".join(sorted(unknown_campaign_deltas))
                        )
                    unknown_position_deltas = {
                        item.target_id
                        for item in profile.deterministic_effects.position_track_deltas
                    } - {"coordination", "escalation"}
                    if unknown_position_deltas:
                        raise ValueError(
                            f"action {action.id!r} changes unknown position tracks: "
                            + ", ".join(sorted(unknown_position_deltas))
                        )
                    unknown_resource_deltas = {
                        item.target_id
                        for item in profile.deterministic_effects.resource_deltas
                    } - local_ids
                    if unknown_resource_deltas:
                        raise ValueError(
                            f"action {action.id!r} changes unknown resources: "
                            + ", ".join(sorted(unknown_resource_deltas))
                        )

        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(action_id: str) -> None:
            if action_id in visited:
                return

            if action_id in visiting:
                raise ValueError(f"cyclic action dependency involving {action_id!r}")

            visiting.add(action_id)

            for dependency_id in action_dependencies[action_id]:
                visit(dependency_id)

            visiting.remove(action_id)
            visited.add(action_id)

        for action_id in action_dependencies:
            visit(action_id)

        return self
