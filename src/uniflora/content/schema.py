from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

CANONICAL_REMEDIATION_HIERARCHY = (
    "refuse_unnecessary_production",
    "reduce_harmful_inputs",
    "redesign_production",
    "reuse_verified_safe_material",
    "separate_clean_and_contaminated_flows",
    "contain_unavoidable_waste",
    "remediate_compatible_contamination",
    "monitor_long_term_effects",
    "manage_spent_substrate",
)
ARC_COUNTER_NAMES = frozenset(
    {
        "saturation",
        "viability",
        "containment",
        "evidence",
        "source_reduction",
        "throughput",
        "extraction",
        "public_benefit",
        "burden",
        "remediation",
        "archival_coherence",
    }
)


class ContentModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class PositionStatus(StrEnum):
    COMPLETE = "complete"
    STUB = "stub"


class ExpansionMechanic(StrEnum):
    TEMPORARY_FUNCTIONS = "temporary_public_functions"
    RESOURCE_CIRCULATION = "resource_circulation"
    CONTRADICTORY_RECORDS = "contradictory_public_records"
    MAINTENANCE_CYCLES = "maintenance_cycles"
    SHARED_SUMMARIES = "shared_summaries"
    ACCESSIBILITY_REQUIREMENTS = "accessibility_requirements"
    RELATIONAL_PROGRESS = "relational_progress"
    ALTERED_RESPONSE_PROFILES = "altered_response_profiles"
    EVENT_REINTERPRETATION = "event_reinterpretation"


class EntityDefinition(ContentModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    title: str = Field(min_length=1, max_length=100)
    kind: str = Field(min_length=1, max_length=64)
    aliases: tuple[str, ...] = ()
    discovery_label: str | None = Field(default=None, min_length=1, max_length=100)
    public_description: str = Field(min_length=1, max_length=500)
    resources: dict[str, float] = Field(default_factory=dict)
    measurements: dict[str, float | str | bool] = Field(default_factory=dict)

    def resolution_aliases(self) -> tuple[str, ...]:
        discovery = (self.discovery_label,) if self.discovery_label is not None else ()
        return (self.id, *self.aliases, *discovery)


class UnlockCondition(ContentModel):
    action: str
    entity_id: str | None = None
    requires_observations: tuple[str, ...] = ()
    distinct_user_count: int = Field(default=1, ge=1)


class ObservationDefinition(ContentModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    entity_id: str
    public_text: str = Field(min_length=1, max_length=1000)
    fact_key: str
    unlock: UnlockCondition
    contribution_function: str
    classification: Literal[
        "confirmed",
        "historical_baseline",
        "current_measurement",
        "forecast",
        "conditional_projection",
        "obsolete_expectation",
        "unresolved_discrepancy",
        "provenance",
        "preserved_difference",
    ] = "confirmed"


class RelationalRequirements(ContentModel):
    minimum_distinct_users: int = Field(default=1, ge=1)
    minimum_distinct_functions: int = Field(default=1, ge=1)
    non_author_confirmation: bool = True


class SustainabilityConstraints(ContentModel):
    donor_entity_id: str
    recipient_entity_id: str
    resource_id: str
    pathway_entity_id: str
    minimum_donor_reserve: float = Field(ge=0)
    minimum_recipient_viability: float = Field(ge=0)
    allowed_pathway_actions: tuple[str, ...] = ("repair", "account")


class ReconstructionRequirements(ContentModel):
    required_observations: tuple[str, ...]
    required_fields: tuple[str, ...]
    maintenance_terms: tuple[str, ...]


class CirculationRequirements(ContentModel):
    source_entity_id: str
    recipient_entity_id: str
    relay_entity_id: str
    source_pathway_id: str
    destination_pathway_id: str
    reserve_entity_id: str
    archive_entity_id: str
    central_basin_entity_id: str
    support_source_entity_ids: tuple[str, ...] = Field(min_length=2)
    resource_id: str
    required_observations: tuple[str, ...]
    burden_observations: tuple[str, ...]
    source_output: float = Field(gt=0)
    unassessed_efficiency: float = Field(gt=0, le=1)
    reassessed_efficiency: float = Field(gt=0, le=1)
    relay_capacity: float = Field(gt=0)
    destination_pathway_capacity: float = Field(gt=0)
    archive_coherence_floor: float = Field(ge=0)
    archive_viability_floor: float = Field(ge=0)
    reserve_floor: float = Field(ge=0)
    eastern_recovery_buffer: float = Field(ge=0)
    maintenance_terms: tuple[str, ...] = Field(min_length=1)
    reassessment_terms: tuple[str, ...] = Field(min_length=1)
    branch_terms: tuple[str, ...] = Field(min_length=1)
    branch_action_terms: tuple[str, ...] = Field(min_length=1)


class TranslationRequirements(ContentModel):
    record_entity_ids: tuple[str, ...] = Field(min_length=3)
    glossary_entity_id: str
    provenance_entity_id: str
    minority_entity_id: str
    required_observations: tuple[str, ...] = Field(min_length=3)
    required_comparisons: int = Field(default=2, ge=1)
    allowed_classifications: tuple[str, ...] = Field(min_length=2)
    correct_classification: str
    mapping_terms: tuple[str, ...] = Field(min_length=3)
    preservation_terms: tuple[str, ...] = Field(min_length=1)
    required_public_relays: int = Field(default=1, ge=1)

    @model_validator(mode="after")
    def validate_translation_rules(self) -> TranslationRequirements:
        if len(set(self.record_entity_ids)) != len(self.record_entity_ids):
            raise ValueError("translation record entities must be distinct")
        if self.correct_classification not in self.allowed_classifications:
            raise ValueError("correct translation classification must be allowed")
        return self


class ConfirmationRequirements(ContentModel):
    minimum_confirmations: int = Field(default=1, ge=1)
    non_author_required: bool = True


class CompletionEffects(ContentModel):
    world_flags: dict[str, bool | int | float | str] = Field(default_factory=dict)
    next_position: int | None = Field(default=None, ge=0, le=6)
    response_profile: str = "surface_noise"


class AccessibilityDefinition(ContentModel):
    summary: str = Field(min_length=1, max_length=1000)
    explicit_command_help: tuple[str, ...] = ()
    public_recap_available: bool = True
    explicit_action_equivalents: bool = True
    no_timing_penalty: bool = True
    accepted_input_modes: tuple[Literal["natural_language", "explicit_command"], ...] = (
        "natural_language",
        "explicit_command",
    )


class OrientationDefinition(ContentModel):
    local_response: str = Field(min_length=1, max_length=500)
    specificity_invitation: str = Field(min_length=1, max_length=300)
    prohibited_automatic_reveals: tuple[str, ...] = ()


class PresentationImage(ContentModel):
    image_asset: str = Field(pattern=r"^assets/[a-z0-9][a-z0-9_-]*\.(png|jpg|jpeg|webp)$")
    image_alt_text: str = Field(min_length=1, max_length=300)


class PositionPresentation(PresentationImage):
    introduction: str = Field(min_length=1, max_length=1900)
    additional_images: tuple[PresentationImage, ...] = Field(default=(), max_length=9)


class RevealCondition(ContentModel):
    counter: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    target: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_]*$")
    minimum: float = Field(default=1, gt=0)


class TriggeredPresentation(ContentModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    condition: RevealCondition
    introduction: str = Field(min_length=1, max_length=1900)
    image_asset: str = Field(pattern=r"^assets/[a-z0-9][a-z0-9_-]*\.(png|jpg|jpeg|webp)$")
    image_alt_text: str = Field(min_length=1, max_length=300)


class TacticalDefinition(ContentModel):
    max_stack_depth: int = Field(default=4, ge=2, le=4)
    allowed_stack_reactions: tuple[str, ...]
    allowed_kickers: tuple[str, ...]
    strain_threshold: int = Field(default=3, ge=1)
    strain_reserve_penalty: float = Field(default=1, ge=0)
    repair_threshold: int = Field(default=2, ge=1)
    coherence_threshold: int = Field(default=2, ge=1)


class ContaminantClassDefinition(ContentModel):
    """A deliberately broad material class, never a handling recipe."""

    id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    public_label: str = Field(min_length=1, max_length=100)
    biological_treatment_eligible: bool
    visible_clarity_proves_safety: Literal[False] = False
    public_description: str = Field(min_length=1, max_length=500)


class FungalCultureDefinition(ContentModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    public_label: str = Field(min_length=1, max_length=100)
    compatible_contaminant_classes: tuple[str, ...] = ()
    heat_tolerance: Literal["low", "moderate", "high"]
    provenance: str = Field(min_length=1, max_length=300)
    uncertainty: str = Field(min_length=1, max_length=300)


class CompatibilityRule(ContentModel):
    contaminant_class: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    culture_id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    compatible: bool
    minimum_viability: int = Field(default=2, ge=1)
    maximum_saturation: int = Field(default=3, ge=1)
    required_evidence: int = Field(default=2, ge=1)


class RemediationSystemDefinition(ContentModel):
    entity_id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    processes: tuple[
        Literal[
            "biodegradation",
            "transformation",
            "filtration",
            "immobilization",
            "adsorption",
            "accumulation",
            "containment",
            "indicator_response",
            "soil_restoration",
        ],
        ...,
    ] = Field(min_length=1)
    contaminant_classes: tuple[str, ...] = Field(min_length=1)
    culture_ids: tuple[str, ...] = Field(min_length=1)
    containment_destination_ids: tuple[str, ...] = Field(min_length=1)
    moisture_required: Literal[True] = True
    temperature_required: Literal[True] = True
    contact_time_required: Literal[True] = True


class SubstrateDefinition(ContentModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    public_label: str = Field(min_length=1, max_length=100)
    compatible_system_ids: tuple[str, ...] = Field(min_length=1)
    contaminated_reuse_allowed: Literal[False] = False
    containment_required: Literal[True] = True


class ArcCounterThresholds(ContentModel):
    saturation_limit: int = Field(default=3, ge=1)
    minimum_viability: int = Field(default=2, ge=1)
    minimum_containment: int = Field(default=2, ge=1)
    minimum_evidence: int = Field(default=2, ge=1)
    maximum_throughput: int = Field(default=6, ge=1)


class ClimateRecordDefinition(ContentModel):
    historical_baseline: str = Field(min_length=1, max_length=300)
    current_measurement: str = Field(min_length=1, max_length=300)
    forecast: str = Field(min_length=1, max_length=300)
    conditional_projection: str = Field(min_length=1, max_length=300)
    obsolete_expectation: str = Field(min_length=1, max_length=300)
    unresolved_discrepancy: str = Field(min_length=1, max_length=300)


class ProvisionArcDefinition(ContentModel):
    """Reusable public rules for production, climate, and remediation systems."""

    entity_roles: dict[str, str] = Field(default_factory=dict)
    contaminant_classes: tuple[ContaminantClassDefinition, ...] = ()
    fungal_cultures: tuple[FungalCultureDefinition, ...] = ()
    compatibility_rules: tuple[CompatibilityRule, ...] = ()
    remediation_systems: tuple[RemediationSystemDefinition, ...] = ()
    substrates: tuple[SubstrateDefinition, ...] = ()
    thresholds: ArcCounterThresholds = Field(default_factory=ArcCounterThresholds)
    climate_record: ClimateRecordDefinition | None = None
    remediation_hierarchy: tuple[
        Literal[
            "refuse_unnecessary_production",
            "reduce_harmful_inputs",
            "redesign_production",
            "reuse_verified_safe_material",
            "separate_clean_and_contaminated_flows",
            "contain_unavoidable_waste",
            "remediate_compatible_contamination",
            "monitor_long_term_effects",
            "manage_spent_substrate",
        ],
        ...,
    ] = ()
    counter_defaults: dict[str, int] = Field(default_factory=dict)
    target_counter_defaults: dict[str, dict[str, int]] = Field(default_factory=dict)
    evidence_measures: tuple[str, ...] = ()
    visual_only_measures: tuple[str, ...] = ()
    reduction_measures: tuple[str, ...] = ()
    redesign_changes: tuple[str, ...] = ()
    mitigation_risks: tuple[str, ...] = ()
    maintenance_conditions: tuple[str, ...] = ()
    record_types: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_arc_rules(self) -> ProvisionArcDefinition:
        if not all(
            (
                self.entity_roles,
                self.contaminant_classes,
                self.fungal_cultures,
                self.compatibility_rules,
                self.remediation_systems,
                self.substrates,
                self.climate_record,
            )
        ):
            raise ValueError(
                "Provision Works arc requires roles, material classes, cultures, a complete "
                "compatibility matrix, systems, substrates, and climate records"
            )
        contaminant_ids = [item.id for item in self.contaminant_classes]
        culture_ids = [item.id for item in self.fungal_cultures]
        if len(set(contaminant_ids)) != len(contaminant_ids):
            raise ValueError("contaminant class IDs must be unique")
        if len(set(culture_ids)) != len(culture_ids):
            raise ValueError("fungal culture IDs must be unique")
        known_contaminants = set(contaminant_ids)
        known_cultures = set(culture_ids)
        for culture in self.fungal_cultures:
            unknown = set(culture.compatible_contaminant_classes) - known_contaminants
            if unknown:
                raise ValueError(f"fungal culture references unknown contaminants: {unknown}")
        pairs: set[tuple[str, str]] = set()
        for rule in self.compatibility_rules:
            if rule.contaminant_class not in known_contaminants:
                raise ValueError("compatibility rule references unknown contaminant")
            if rule.culture_id not in known_cultures:
                raise ValueError("compatibility rule references unknown fungal culture")
            pair = (rule.contaminant_class, rule.culture_id)
            if pair in pairs:
                raise ValueError("compatibility rules must have unique contaminant/culture pairs")
            if (
                rule.compatible
                and not next(
                    item for item in self.contaminant_classes if item.id == rule.contaminant_class
                ).biological_treatment_eligible
            ):
                raise ValueError("ineligible contaminants cannot have compatible treatment rules")
            pairs.add(pair)
        expected_pairs = {
            (contaminant, culture)
            for contaminant in known_contaminants
            for culture in known_cultures
        }
        if pairs != expected_pairs:
            raise ValueError(
                "compatibility matrix must explicitly cover every contaminant and culture pair"
            )
        compatible_pairs = {pair for pair, rule in self.compatibility_map().items() if rule}
        declared_pairs = {
            (contaminant, culture.id)
            for culture in self.fungal_cultures
            for contaminant in culture.compatible_contaminant_classes
        }
        if compatible_pairs != declared_pairs:
            raise ValueError("fungal culture compatibility must match the rule matrix")
        if tuple(self.remediation_hierarchy) != CANONICAL_REMEDIATION_HIERARCHY:
            raise ValueError("remediation hierarchy must use the canonical nine-layer order")
        unknown_counters = (
            set(self.counter_defaults) | set(self.target_counter_defaults)
        ) - ARC_COUNTER_NAMES
        if unknown_counters:
            raise ValueError(f"unknown Provision Works counters: {unknown_counters}")
        target_counter_names = {"saturation", "viability"}
        misplaced_target_counters = set(self.target_counter_defaults) - target_counter_names
        misplaced_scalar_counters = set(self.counter_defaults) & target_counter_names
        if misplaced_target_counters or misplaced_scalar_counters:
            raise ValueError(
                "saturation and viability must be target counters; all other Provision Works "
                "counters must be scalar"
            )
        if any(
            not self.target_counter_defaults.get(counter) for counter in ("saturation", "viability")
        ):
            raise ValueError("saturation and viability require at least one target counter")
        if any(value < 0 for value in self.counter_defaults.values()) or any(
            value < 0
            for values in self.target_counter_defaults.values()
            for value in values.values()
        ):
            raise ValueError("Provision Works counter defaults must be nonnegative")
        system_ids = [item.entity_id for item in self.remediation_systems]
        if len(set(system_ids)) != len(system_ids):
            raise ValueError("remediation system entity IDs must be unique")
        for system in self.remediation_systems:
            if not set(system.contaminant_classes).issubset(known_contaminants):
                raise ValueError("remediation system references unknown contaminant classes")
            if not set(system.culture_ids).issubset(known_cultures):
                raise ValueError("remediation system references unknown fungal cultures")
        substrate_ids = [item.id for item in self.substrates]
        if len(set(substrate_ids)) != len(substrate_ids):
            raise ValueError("substrate IDs must be unique")
        if not all(
            (
                self.evidence_measures,
                self.visual_only_measures,
                self.reduction_measures,
                self.redesign_changes,
                self.mitigation_risks,
                self.maintenance_conditions,
                self.record_types,
            )
        ):
            raise ValueError("Provision Works action vocabularies must be explicit")
        return self

    def compatibility_map(self) -> dict[tuple[str, str], bool]:
        return {
            (item.contaminant_class, item.culture_id): item.compatible
            for item in self.compatibility_rules
        }


class ProvisionPositionRequirements(ContentModel):
    proposal_kind: Literal[
        "reciprocity", "remediation_protocol", "memory_archive", "reconstruction"
    ]
    required_observations: tuple[str, ...] = Field(min_length=1)
    required_actions: tuple[str, ...] = Field(min_length=1)
    required_action_groups: tuple[tuple[str, ...], ...] = ()
    required_proposal_fields: tuple[str, ...] = Field(min_length=1)
    required_persistent_effects: tuple[str, ...] = ()
    required_persistent_effect_groups: tuple[tuple[str, ...], ...] = ()
    completion_effects: tuple[str, ...] = Field(min_length=1)
    maintenance_cycle_steps: tuple[str, ...] = ()
    minimum_distinct_users: int = Field(default=3, ge=2)
    minimum_distinct_functions: int = Field(default=3, ge=2)
    non_author_confirmation: Literal[True] = True

    @model_validator(mode="after")
    def validate_requirement_uniqueness(self) -> ProvisionPositionRequirements:
        for label, values in (
            ("required observations", self.required_observations),
            ("required actions", self.required_actions),
            ("required proposal fields", self.required_proposal_fields),
            ("completion effects", self.completion_effects),
            ("required persistent effects", self.required_persistent_effects),
        ):
            if len(set(values)) != len(values):
                raise ValueError(f"{label} must be unique")
        for label, groups in (
            ("required action groups", self.required_action_groups),
            ("required persistent-effect groups", self.required_persistent_effect_groups),
        ):
            if any(not group or len(set(group)) != len(group) for group in groups):
                raise ValueError(f"{label} must contain nonempty unique alternatives")
            if len(set(groups)) != len(groups):
                raise ValueError(f"{label} must be unique")
        return self


class TemporaryPublicFunctionFixture(ContentModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    public_label: str = Field(min_length=1, max_length=80)
    purpose: str = Field(min_length=1, max_length=300)
    scope: Literal["proposal", "cycle", "position"]
    granted_by: Literal["public_action", "confirmed_event", "shared_summary"]
    allowed_actions: tuple[str, ...] = Field(min_length=1)


class ResourceCirculationFixture(ContentModel):
    resource_id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    source_ref: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    target_ref: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    conservation_required: Literal[True] = True
    reassessment_required: Literal[True] = True

    @model_validator(mode="after")
    def validate_distinct_endpoints(self) -> ResourceCirculationFixture:
        if self.source_ref == self.target_ref:
            raise ValueError("resource circulation requires distinct endpoints")
        return self


class ContradictoryRecordFixture(ContentModel):
    record_refs: tuple[str, ...] = Field(min_length=2)
    resolution_action: str = Field(min_length=1, max_length=80)
    minimum_distinct_interpreters: int = Field(default=2, ge=2)
    preserve_disagreement: bool = True

    @model_validator(mode="after")
    def validate_distinct_records(self) -> ContradictoryRecordFixture:
        if len(set(self.record_refs)) != len(self.record_refs):
            raise ValueError("contradictory record references must be distinct")
        return self


class MaintenanceCycleFixture(ContentModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    interval_events: int = Field(ge=1)
    required_public_actions: tuple[str, ...] = Field(min_length=1)
    counter_key: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    threshold: int = Field(ge=1)


class SharedSummaryFixture(ContentModel):
    minimum_source_events: int = Field(default=2, ge=2)
    minimum_distinct_contributors: int = Field(default=2, ge=2)
    relay_required: bool = True
    public_revision_allowed: bool = True


class RelationalProgressFixture(ContentModel):
    minimum_distinct_users: int = Field(default=2, ge=2)
    minimum_distinct_functions: int = Field(default=2, ge=2)
    non_author_confirmation: bool = True
    no_single_participant_completion: Literal[True] = True


class ResponseProfileTransitionFixture(ContentModel):
    from_profile: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    to_profile: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    public_trigger: str = Field(min_length=1, max_length=120)

    @model_validator(mode="after")
    def validate_profile_change(self) -> ResponseProfileTransitionFixture:
        if self.from_profile == self.to_profile:
            raise ValueError("response profile transition must alter the profile")
        return self


class EventReinterpretationFixture(ContentModel):
    source_positions: tuple[int, ...] = Field(min_length=1)
    requires_confirmed_events: Literal[True] = True
    preserves_original_record: Literal[True] = True
    public_correction: Literal[True] = True

    @model_validator(mode="after")
    def validate_source_positions(self) -> EventReinterpretationFixture:
        if any(position < 0 or position > 6 for position in self.source_positions):
            raise ValueError("reinterpretation source positions must be between 0 and 6")
        if len(set(self.source_positions)) != len(self.source_positions):
            raise ValueError("reinterpretation source positions must be distinct")
        return self


class ExpansionFramework(ContentModel):
    mechanics: tuple[ExpansionMechanic, ...] = Field(min_length=2)
    temporary_functions: tuple[TemporaryPublicFunctionFixture, ...] = ()
    resource_circulation: tuple[ResourceCirculationFixture, ...] = ()
    contradictory_records: tuple[ContradictoryRecordFixture, ...] = ()
    maintenance_cycles: tuple[MaintenanceCycleFixture, ...] = ()
    shared_summary: SharedSummaryFixture | None = None
    relational_progress: RelationalProgressFixture
    response_profile_transitions: tuple[ResponseProfileTransitionFixture, ...] = ()
    event_reinterpretation: tuple[EventReinterpretationFixture, ...] = ()

    @model_validator(mode="after")
    def validate_mechanic_fixtures(self) -> ExpansionFramework:
        mechanics = set(self.mechanics)
        if len(mechanics) != len(self.mechanics):
            raise ValueError("expansion mechanics must be unique")
        fixtures = {
            ExpansionMechanic.TEMPORARY_FUNCTIONS: bool(self.temporary_functions),
            ExpansionMechanic.RESOURCE_CIRCULATION: bool(self.resource_circulation),
            ExpansionMechanic.CONTRADICTORY_RECORDS: bool(self.contradictory_records),
            ExpansionMechanic.MAINTENANCE_CYCLES: bool(self.maintenance_cycles),
            ExpansionMechanic.SHARED_SUMMARIES: self.shared_summary is not None,
            ExpansionMechanic.RELATIONAL_PROGRESS: self.relational_progress is not None,
            ExpansionMechanic.ALTERED_RESPONSE_PROFILES: bool(self.response_profile_transitions),
            ExpansionMechanic.EVENT_REINTERPRETATION: bool(self.event_reinterpretation),
        }
        for mechanic, present in fixtures.items():
            if (mechanic in mechanics) != present:
                raise ValueError(f"mechanic fixture mismatch for {mechanic.value}")
        function_ids = [item.id for item in self.temporary_functions]
        if len(set(function_ids)) != len(function_ids):
            raise ValueError("temporary function IDs must be unique")
        cycle_ids = [item.id for item in self.maintenance_cycles]
        if len(set(cycle_ids)) != len(cycle_ids):
            raise ValueError("maintenance cycle IDs must be unique")
        return self


class PuzzleDefinition(ContentModel):
    schema_version: int = Field(default=1, ge=1)
    content_version: str
    position: int = Field(ge=0, le=6)
    key: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    title: str
    status: PositionStatus
    public_premise: str
    entities: tuple[EntityDefinition, ...] = ()
    observations: tuple[ObservationDefinition, ...] = ()
    allowed_actions: tuple[str, ...] = ()
    relational_requirements: RelationalRequirements | None = None
    resource_values: dict[str, float] = Field(default_factory=dict)
    sustainability: SustainabilityConstraints | None = None
    reconstruction: ReconstructionRequirements | None = None
    circulation: CirculationRequirements | None = None
    translation: TranslationRequirements | None = None
    confirmation: ConfirmationRequirements | None = None
    completion: CompletionEffects
    narration_keys: dict[str, str] = Field(default_factory=dict)
    accessibility: AccessibilityDefinition
    orientation: OrientationDefinition | None = None
    presentation: PositionPresentation | None = None
    triggered_presentations: tuple[TriggeredPresentation, ...] = ()
    tactical: TacticalDefinition | None = None
    provision_arc: ProvisionArcDefinition | None = None
    provision_requirements: ProvisionPositionRequirements | None = None
    expansion: ExpansionFramework | None = None
    response_profile_changes: dict[str, str] = Field(default_factory=dict)
    reinterpretation_rules: dict[str, str] = Field(default_factory=dict)
    vocabulary: tuple[str, ...] = ()
    world_flags: dict[str, bool | int | float | str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_references(self) -> PuzzleDefinition:
        entity_ids = {entity.id for entity in self.entities}
        if len(entity_ids) != len(self.entities):
            raise ValueError("entity IDs must be unique within a position")
        aliases: set[str] = set()
        for entity in self.entities:
            for alias in entity.resolution_aliases():
                normalized = alias.strip().lower()
                if normalized in aliases:
                    raise ValueError(f"entity alias is ambiguous: {normalized}")
                aliases.add(normalized)
        observation_ids = {observation.id for observation in self.observations}
        if len(observation_ids) != len(self.observations):
            raise ValueError("observation IDs must be unique within a position")
        labeled_entity_ids = {
            entity.id for entity in self.entities if entity.discovery_label is not None
        }
        unlabeled_observation_entities = {
            observation.entity_id for observation in self.observations
        } - labeled_entity_ids
        if unlabeled_observation_entities:
            raise ValueError(
                "observation entities require spoiler-safe discovery labels: "
                f"{sorted(unlabeled_observation_entities)}"
            )
        for observation in self.observations:
            if observation.entity_id not in entity_ids:
                raise ValueError(f"observation references unknown entity: {observation.entity_id}")
            if observation.unlock.entity_id not in {None, *entity_ids}:
                raise ValueError("unlock condition references unknown entity")
            unknown = set(observation.unlock.requires_observations) - observation_ids
            if unknown:
                raise ValueError(f"unlock condition references unknown observations: {unknown}")
        if self.provision_arc is not None:
            unknown_arc_entities = set(self.provision_arc.entity_roles.values()) - entity_ids
            for system in self.provision_arc.remediation_systems:
                if system.entity_id not in entity_ids:
                    unknown_arc_entities.add(system.entity_id)
                unknown_arc_entities.update(set(system.containment_destination_ids) - entity_ids)
            for values in self.provision_arc.target_counter_defaults.values():
                unknown_arc_entities.update(set(values) - entity_ids)
            system_ids = {item.entity_id for item in self.provision_arc.remediation_systems}
            for substrate in self.provision_arc.substrates:
                unknown_systems = set(substrate.compatible_system_ids) - system_ids
                if unknown_systems:
                    raise ValueError(
                        f"substrate references unknown remediation systems: {unknown_systems}"
                    )
            if unknown_arc_entities:
                raise ValueError(
                    f"Provision Works arc references unknown entities: {unknown_arc_entities}"
                )
            required_scalar_counters = {
                "containment",
                "evidence",
                "source_reduction",
                "throughput",
                "extraction",
                "public_benefit",
                "burden",
            }
            required_target_counters = {"saturation", "viability"}
            if not required_scalar_counters.issubset(
                self.provision_arc.counter_defaults
            ) or not required_target_counters.issubset(self.provision_arc.target_counter_defaults):
                raise ValueError("Provision Works arc must initialize every core public counter")
        if self.status is PositionStatus.COMPLETE:
            if len(self.entities) < 5 or len(self.observations) < 5:
                raise ValueError(
                    "complete positions require at least five entities and observations"
                )
            if not all(
                (
                    self.relational_requirements,
                    self.confirmation,
                    self.allowed_actions,
                    self.narration_keys,
                    self.orientation,
                    self.tactical,
                )
            ):
                raise ValueError("complete position is missing deterministic requirements")
            if self.position == 0:
                if self.sustainability is None or self.reconstruction is None:
                    raise ValueError("Position 0 requires sustainability and reconstruction rules")
                sustainability_entities = {
                    self.sustainability.donor_entity_id,
                    self.sustainability.recipient_entity_id,
                    self.sustainability.pathway_entity_id,
                }
                if not sustainability_entities.issubset(entity_ids):
                    raise ValueError("sustainability references unknown entities")
                missing_observations = (
                    set(self.reconstruction.required_observations) - observation_ids
                )
                if missing_observations:
                    raise ValueError(
                        f"reconstruction references unknown observations: {missing_observations}"
                    )
            elif self.position == 1:
                if self.circulation is None:
                    raise ValueError("Position 1 requires circulation rules")
                circulation_entities = {
                    self.circulation.source_entity_id,
                    self.circulation.recipient_entity_id,
                    self.circulation.relay_entity_id,
                    self.circulation.source_pathway_id,
                    self.circulation.destination_pathway_id,
                    self.circulation.reserve_entity_id,
                    self.circulation.archive_entity_id,
                    self.circulation.central_basin_entity_id,
                    *self.circulation.support_source_entity_ids,
                }
                if not circulation_entities.issubset(entity_ids):
                    raise ValueError("circulation references unknown entities")
                circulation_observations = {
                    *self.circulation.required_observations,
                    *self.circulation.burden_observations,
                }
                if not circulation_observations.issubset(observation_ids):
                    raise ValueError("circulation references unknown observations")
            elif self.position == 2:
                if self.translation is None:
                    raise ValueError("Position 2 requires translation rules")
                translation_entities = {
                    *self.translation.record_entity_ids,
                    self.translation.glossary_entity_id,
                    self.translation.provenance_entity_id,
                    self.translation.minority_entity_id,
                }
                if not translation_entities.issubset(entity_ids):
                    raise ValueError("translation references unknown entities")
                if not set(self.translation.required_observations).issubset(observation_ids):
                    raise ValueError("translation references unknown observations")
            else:
                if self.provision_arc is None or self.provision_requirements is None:
                    raise ValueError("complete Positions 3-6 require Provision Works arc rules")
                missing_arc_observations = (
                    set(self.provision_requirements.required_observations) - observation_ids
                )
                if missing_arc_observations:
                    raise ValueError(
                        "Provision Works requirements reference unknown observations: "
                        f"{missing_arc_observations}"
                    )
                proposal_kinds = {
                    3: "reciprocity",
                    4: "remediation_protocol",
                    5: "memory_archive",
                    6: "reconstruction",
                }
                if self.provision_requirements.proposal_kind != proposal_kinds[self.position]:
                    raise ValueError("Provision Works proposal kind does not match its position")
                canonical_cycle = (
                    "inspect_discharge",
                    "identify_contaminant_class",
                    "verify_fungal_compatibility",
                    "maintain_or_inoculate_bed",
                    "regulate_flow_and_contact_time",
                    "sample_upstream_and_downstream",
                    "evaluate_evidence",
                    "rest_or_replace_saturated_substrate",
                    "contain_spent_material",
                    "reassess_production_limits",
                )
                if self.position == 4 and (
                    self.provision_requirements.maintenance_cycle_steps != canonical_cycle
                ):
                    raise ValueError("Position 4 requires the canonical ordered maintenance cycle")
                required_or_alternative_actions = {
                    *self.provision_requirements.required_actions,
                    *(
                        action
                        for group in self.provision_requirements.required_action_groups
                        for action in group
                    ),
                }
                if not required_or_alternative_actions.issubset(self.allowed_actions):
                    raise ValueError("Provision Works required actions must be allowed")
                relational = self.relational_requirements
                confirmation = self.confirmation
                assert relational is not None and confirmation is not None
                if (
                    relational.minimum_distinct_users
                    != self.provision_requirements.minimum_distinct_users
                    or relational.minimum_distinct_functions
                    != self.provision_requirements.minimum_distinct_functions
                    or not relational.non_author_confirmation
                    or not confirmation.non_author_required
                ):
                    raise ValueError(
                        "Provision Works relational and confirmation requirements must agree"
                    )
            if self.expansion is not None:
                raise ValueError("complete positions cannot use non-playable expansion fixtures")
        else:
            if self.expansion is None:
                raise ValueError("stub positions require an expansion framework fixture")
            if any(
                (
                    self.entities,
                    self.observations,
                    self.allowed_actions,
                    self.relational_requirements,
                    self.resource_values,
                    self.sustainability,
                    self.reconstruction,
                    self.circulation,
                    self.translation,
                    self.confirmation,
                    self.orientation,
                    self.presentation,
                    self.triggered_presentations,
                    self.tactical,
                    self.provision_arc,
                    self.provision_requirements,
                    self.narration_keys,
                    self.response_profile_changes,
                    self.reinterpretation_rules,
                    self.vocabulary,
                    self.world_flags,
                )
            ):
                raise ValueError("stub positions cannot contain playable puzzle requirements")
            required = {
                ExpansionMechanic.TEMPORARY_FUNCTIONS,
                ExpansionMechanic.RELATIONAL_PROGRESS,
            }
            if not required.issubset(set(self.expansion.mechanics)):
                raise ValueError(
                    "stub positions require temporary functions and relational progress"
                )
            if ExpansionMechanic.ACCESSIBILITY_REQUIREMENTS not in self.expansion.mechanics:
                raise ValueError("stub positions require public accessibility fixtures")
            accessibility = self.accessibility
            if not (
                accessibility.public_recap_available
                and accessibility.explicit_action_equivalents
                and accessibility.no_timing_penalty
                and set(accessibility.accepted_input_modes)
                == {"natural_language", "explicit_command"}
            ):
                raise ValueError("stub accessibility fixtures must preserve both public modes")
            for fixture in self.expansion.event_reinterpretation:
                if any(source >= self.position for source in fixture.source_positions):
                    raise ValueError("reinterpretation may reference only earlier positions")
        return self

    def entity_aliases(self) -> dict[str, str]:
        result: dict[str, str] = {}
        for entity in self.entities:
            for alias in entity.resolution_aliases():
                result[alias.strip().lower()] = entity.id
        return result

    def initial_state(self) -> dict[str, Any]:
        resources = {entity.id: dict(entity.resources) for entity in self.entities}
        state = {
            "content_key": self.key,
            "content_version": self.content_version,
            "session_generation": 0,
            "confirmed_facts": [],
            "unlocked_observations": [],
            "contributions": [],
            "connections": [],
            "offers": [],
            "support_requests": [],
            "sustains": [],
            "relays": [],
            "mitigations": [],
            "branches": [],
            "calculations": [],
            "comparisons": [],
            "clarifications": [],
            "classifications": [],
            "annotations": [],
            "summaries": [],
            "proposals": {},
            "confirmations": [],
            "resources": resources,
            "world_flags": dict(self.world_flags),
            "position_completed": False,
            "announced_position_introductions": [],
            "revealed_artifacts": [],
            "artifact_reveal_deliveries": {},
            "public_stack": None,
            "triggered_reactions": [],
            "persistent_effects": [],
            "settlement_scar": None,
            "settlement_event": None,
            "settlement_event_history": [],
            "settlement_event_actions_since_last": 0,
            "settlement_event_trigger_after": 0,
            "settlement_escalation": 0,
            "settlement_strain": 0,
            "settlement_burden": 0,
            "settlement_lost_capacity": 0,
            "settlement_last_intervener": None,
            "settlement_restart_pending": False,
            "settlement_restart_count": 0,
            "cycle": {
                "position": self.position,
                "index": 1,
                "phase": "orientation",
                "observation_count": 0,
                "orientation_participants": [],
                "primary_contributors": {},
                "response_actions": {},
                "response_window_id": None,
                "proposal_author_id": None,
            },
            "cycle_history": [],
            "counters": {
                "strain": {},
                "repair": {},
                "coherence": 0,
                "trust": 0,
                "maintenance": {},
                "instability": 0,
            },
        }
        if self.provision_arc is not None:
            state.update(
                {
                    "material_terms_ledger": [],
                    "versioned_records": [],
                    "samples": [],
                    "separations": [],
                    "inoculations": [],
                    "containments": [],
                    "reductions": [],
                    "redesigns": [],
                    "audits": [],
                    "maintenance_protocol": [],
                    "failed_treatments": [],
                    "documented_records": [],
                    "characterized_contaminants": {},
                    "beds_offline": [],
                    "arc_actions": [],
                    "position_history": [],
                }
            )
            if self.provision_arc.climate_record is not None:
                state["climate_record"] = self.provision_arc.climate_record.model_dump(mode="json")
            if self.provision_requirements is not None and (
                self.provision_requirements.maintenance_cycle_steps
            ):
                state["maintenance_cycle"] = {
                    "cycle_index": 1,
                    "stage": 0,
                    "completed_steps": [],
                    "bed_offline": False,
                }
            counters = state["counters"]
            counters.update(self.provision_arc.counter_defaults)
            for name, values in self.provision_arc.target_counter_defaults.items():
                counters[name] = dict(values)
        return state
