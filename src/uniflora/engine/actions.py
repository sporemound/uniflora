from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictAction(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class ObserveAction(StrictAction):
    action: Literal["observe"]
    entity_id: str = Field(min_length=1, max_length=128)


class OrientLocalAction(StrictAction):
    action: Literal["orient_local"]
    atmospheric_text: str = Field(default="", max_length=500)


class AwakenVesselAction(StrictAction):
    action: Literal["awaken_vessel"]
    name: str = Field(
        min_length=2,
        max_length=32,
        pattern=r"^[A-Za-z][A-Za-z0-9 '\-]*$",
    )
    fate: Literal["plant", "open", "keep"]


class ConnectAction(StrictAction):
    action: Literal["connect"]
    source_entity_id: str = Field(min_length=1, max_length=128)
    target_entity_id: str = Field(min_length=1, max_length=128)


class OfferAction(StrictAction):
    action: Literal["offer"]
    resource_id: str = Field(min_length=1, max_length=128)
    amount: float = Field(gt=0)
    target_entity_id: str | None = Field(default=None, max_length=128)


class RequestSupportAction(StrictAction):
    action: Literal["request_support"]
    need_id: str = Field(min_length=1, max_length=128)
    amount: float | None = Field(default=None, gt=0)


class SummarizeAction(StrictAction):
    action: Literal["summarize"]
    focus: str | None = Field(default=None, max_length=256)


class SustainAction(StrictAction):
    action: Literal["sustain"]
    target_entity_id: str = Field(min_length=1, max_length=128)
    condition: str = Field(min_length=1, max_length=500)


class RelayAction(StrictAction):
    action: Literal["relay"]
    source_entity_id: str = Field(min_length=1, max_length=128)
    via_entity_id: str = Field(min_length=1, max_length=128)
    target_entity_id: str = Field(min_length=1, max_length=128)
    resource_id: str = Field(min_length=1, max_length=128)
    amount: float = Field(gt=0)


class MitigateAction(StrictAction):
    action: Literal["mitigate"]
    target_entity_id: str = Field(min_length=1, max_length=128)
    risk: str = Field(min_length=1, max_length=128)
    detail: str = Field(default="", max_length=500)


class CalculateFlowAction(StrictAction):
    action: Literal["calculate_flow"]
    source_amount: float = Field(gt=0)
    pathway_entity_id: str = Field(min_length=1, max_length=128)
    support_amount: float = Field(default=0, ge=0)


class BranchProposalAction(StrictAction):
    action: Literal["branch_proposal"]
    proposal_id: str = Field(min_length=1, max_length=128)
    condition: str = Field(min_length=1, max_length=500)
    branch_action: str = Field(min_length=1, max_length=500)


class ProposeCirculationAction(StrictAction):
    action: Literal["propose_circulation"]
    source_entity_id: str = Field(min_length=1, max_length=128)
    recipient_entity_id: str = Field(min_length=1, max_length=128)
    resource_id: str = Field(min_length=1, max_length=128)
    source_amount: float = Field(gt=0)
    pathway_entity_id: str = Field(min_length=1, max_length=128)
    relay_entity_id: str = Field(min_length=1, max_length=128)
    delivered_amount: float = Field(gt=0)
    maintenance: str = Field(min_length=1, max_length=500)
    reassessment: str = Field(min_length=1, max_length=500)
    branch_condition: str = Field(default="", max_length=500)
    branch_action: str = Field(default="", max_length=500)
    support_source_entity_id: str = Field(default="", max_length=128)
    support_amount: float = Field(default=0, ge=0)


class CompareRecordsAction(StrictAction):
    action: Literal["compare_records"]
    record_a: str = Field(min_length=1, max_length=128)
    record_b: str = Field(min_length=1, max_length=128)


class ClarifyRecordAction(StrictAction):
    action: Literal["clarify_record"]
    record_id: str = Field(min_length=1, max_length=128)
    term: str = Field(min_length=1, max_length=128)


class ClassifyContradictionAction(StrictAction):
    action: Literal["classify_contradiction"]
    record_a: str = Field(min_length=1, max_length=128)
    record_b: str = Field(min_length=1, max_length=128)
    classification: str = Field(min_length=1, max_length=64)


class RelayRecordAction(StrictAction):
    action: Literal["relay_record"]
    record_id: str = Field(min_length=1, max_length=128)
    summary: str = Field(min_length=1, max_length=1000)


class AnnotateDifferenceAction(StrictAction):
    action: Literal["annotate_difference"]
    record_id: str = Field(min_length=1, max_length=128)
    note: str = Field(min_length=1, max_length=1000)


class InspectAction(StrictAction):
    action: Literal["inspect"]
    target_entity_id: str = Field(min_length=1, max_length=128)


class SampleAction(StrictAction):
    action: Literal["sample"]
    source_entity_id: str = Field(min_length=1, max_length=128)
    comparison_entity_id: str = Field(min_length=1, max_length=128)
    measure: str = Field(min_length=1, max_length=128)


class SeparateAction(StrictAction):
    action: Literal["separate"]
    source_entity_id: str = Field(min_length=1, max_length=128)
    clean_target_entity_id: str = Field(min_length=1, max_length=128)
    contaminated_target_entity_id: str = Field(min_length=1, max_length=128)


class InoculateAction(StrictAction):
    action: Literal["inoculate"]
    target_entity_id: str = Field(min_length=1, max_length=128)
    culture_id: str = Field(min_length=1, max_length=128)
    substrate: str = Field(min_length=1, max_length=256)


class SlowAction(StrictAction):
    action: Literal["slow"]
    target_entity_id: str = Field(min_length=1, max_length=128)
    condition: str = Field(min_length=1, max_length=500)


class ContainAction(StrictAction):
    action: Literal["contain"]
    target_entity_id: str = Field(min_length=1, max_length=128)
    destination_entity_id: str = Field(min_length=1, max_length=128)
    condition: str = Field(min_length=1, max_length=500)


class RestAction(StrictAction):
    action: Literal["rest"]
    target_entity_id: str = Field(min_length=1, max_length=128)
    reassessment: str = Field(min_length=1, max_length=500)


class ReplaceAction(StrictAction):
    action: Literal["replace"]
    target_entity_id: str = Field(min_length=1, max_length=128)
    destination_entity_id: str = Field(min_length=1, max_length=128)
    replacement: str = Field(min_length=1, max_length=500)


class RefuseAction(StrictAction):
    action: Literal["refuse"]
    target_entity_id: str = Field(min_length=1, max_length=128)
    basis: str = Field(min_length=1, max_length=500)


class ReduceAction(StrictAction):
    action: Literal["reduce"]
    target_entity_id: str = Field(min_length=1, max_length=128)
    measure: str = Field(min_length=1, max_length=128)
    amount: float | None = Field(default=None, gt=0)
    condition: str = Field(default="", max_length=500)


class RedesignAction(StrictAction):
    action: Literal["redesign"]
    target_entity_id: str = Field(min_length=1, max_length=128)
    change: str = Field(min_length=1, max_length=1000)
    public_need: str = Field(min_length=1, max_length=500)


class DocumentAction(StrictAction):
    action: Literal["document"]
    subject_entity_id: str = Field(min_length=1, max_length=128)
    record_type: str = Field(min_length=1, max_length=128)
    text: str = Field(min_length=1, max_length=1500)


class AuditAction(StrictAction):
    action: Literal["audit"]
    target_entity_id: str = Field(min_length=1, max_length=128)
    claim: str = Field(min_length=1, max_length=1000)
    comparison: str = Field(min_length=1, max_length=1000)


class ProposeTranslationAction(StrictAction):
    action: Literal["propose_translation"]
    record_a: str = Field(min_length=1, max_length=128)
    record_b: str = Field(min_length=1, max_length=128)
    record_c: str = Field(min_length=1, max_length=128)
    classification: str = Field(min_length=1, max_length=64)
    mapping: str = Field(min_length=1, max_length=1000)
    shared_summary: str = Field(min_length=1, max_length=1500)
    preserved_difference: str = Field(min_length=1, max_length=1000)


class ProposeReciprocityAction(StrictAction):
    action: Literal["propose_reciprocity"]
    producer: str = Field(min_length=1, max_length=128)
    public_benefit: str = Field(min_length=1, max_length=500)
    local_burden: str = Field(min_length=1, max_length=500)
    source_reduction_action: str = Field(min_length=1, max_length=500)
    material_disclosure: str = Field(min_length=1, max_length=500)
    maintenance_obligation: str = Field(min_length=1, max_length=500)
    containment_plan: str = Field(min_length=1, max_length=500)
    worker_protection: str = Field(min_length=1, max_length=500)
    shutdown_condition: str = Field(min_length=1, max_length=500)


class ProposeRemediationProtocolAction(StrictAction):
    action: Literal["propose_remediation_protocol"]
    source_discharge: str = Field(min_length=1, max_length=128)
    contaminant_class: str = Field(min_length=1, max_length=128)
    production_reduction_action: str = Field(min_length=1, max_length=500)
    treatment_bed: str = Field(min_length=1, max_length=128)
    fungal_culture: str = Field(min_length=1, max_length=128)
    flow_rate_condition: str = Field(min_length=1, max_length=500)
    moisture_condition: str = Field(min_length=1, max_length=500)
    monitoring_method: str = Field(min_length=1, max_length=500)
    upstream_sample: str = Field(min_length=1, max_length=128)
    downstream_sample: str = Field(min_length=1, max_length=128)
    evidence_requirement: str = Field(min_length=1, max_length=500)
    saturation_limit: int = Field(ge=1)
    spent_substrate_destination: str = Field(min_length=1, max_length=128)
    maintenance_condition: str = Field(min_length=1, max_length=500)
    shutdown_condition: str = Field(min_length=1, max_length=500)


class ProposeMemoryArchiveAction(StrictAction):
    action: Literal["propose_memory_archive"]
    original_claim: str = Field(min_length=1, max_length=1000)
    later_revision: str = Field(min_length=1, max_length=1000)
    physical_evidence: str = Field(min_length=1, max_length=1000)
    affected_observation: str = Field(min_length=1, max_length=1000)
    uncertainty: str = Field(min_length=1, max_length=500)
    correction: str = Field(min_length=1, max_length=1000)
    unresolved_conflict: str = Field(min_length=1, max_length=1000)
    handling_requirement: str = Field(min_length=1, max_length=1000)


class ProposeProductionReformAction(StrictAction):
    action: Literal["propose_production_reform"]
    production_line: str = Field(min_length=1, max_length=128)
    current_output: float = Field(ge=0)
    revised_output: float = Field(ge=0)
    public_need_served: str = Field(min_length=1, max_length=500)
    water_cap: float = Field(ge=0)
    waste_reduction: str = Field(min_length=1, max_length=500)
    worker_transition: str = Field(min_length=1, max_length=1000)
    ownership_or_governance: str = Field(min_length=1, max_length=1000)
    remediation_obligation: str = Field(min_length=1, max_length=1000)
    clean_flow_plan: str = Field(min_length=1, max_length=1000)
    spent_substrate_plan: str = Field(min_length=1, max_length=1000)
    monitoring: str = Field(min_length=1, max_length=1000)
    maintenance: str = Field(min_length=1, max_length=1000)
    historical_records: str = Field(min_length=1, max_length=1000)
    reassessment: str = Field(min_length=1, max_length=1000)
    shutdown_threshold: str = Field(min_length=1, max_length=1000)


class ProposeReconstructionAction(StrictAction):
    action: Literal["propose_reconstruction"]
    proposal: dict[str, object]


class ConfirmReconstructionAction(StrictAction):
    action: Literal["confirm_reconstruction"]
    proposal_id: str = Field(min_length=1, max_length=128)


class BeginStackAction(StrictAction):
    action: Literal["begin_stack"]
    proposal: dict[str, object]


class ReactToStackAction(StrictAction):
    action: Literal["react_to_stack"]
    stack_id: str = Field(min_length=1, max_length=128)
    reaction: Literal[
        "object_pathway",
        "repair_pathway",
        "reassess_pathway",
        "sustain",
        "mitigate_donor",
        "object_loss",
        "reassess_demand",
        "stabilize_relay",
        "protect_archive",
        "mitigate_north",
        "challenge_mapping",
        "request_provenance",
        "preserve_difference",
        "clarify_scale",
        "relay_summary",
        "object_compatibility",
        "object_evidence",
        "reduce_source",
        "slow_flow",
        "protect_workers",
        "contain_substrate",
        "audit_return",
        "cap_throughput",
        "reassess_viability",
        "preserve_archive",
    ]
    detail: str = Field(default="", max_length=500)


class ResolveStackAction(StrictAction):
    action: Literal["resolve_stack"]
    stack_id: str = Field(min_length=1, max_length=128)


class AddProposalKickerAction(StrictAction):
    action: Literal["add_proposal_kicker"]
    proposal_id: str = Field(min_length=1, max_length=128)
    kicker: Literal[
        "monitoring",
        "protect_donor",
        "document",
        "document_flow",
        "adaptive_branch",
        "cite_provenance",
        "preserve_minority",
        "accessibility_glossary",
        "upstream_sampling",
        "downstream_sampling",
        "source_reduction",
        "worker_protection",
        "spent_substrate_plan",
        "public_disclosure",
        "long_term_monitoring",
        "repairability_standard",
        "seasonal_shutdown",
        "archive_failure",
    ]
    detail: str = Field(default="", max_length=500)


class UseTriggeredReactionAction(StrictAction):
    action: Literal["use_triggered_reaction"]
    trigger_id: str = Field(min_length=1, max_length=128)


class UnknownAction(StrictAction):
    action: Literal["unknown"]
    raw_text: str = Field(default="", max_length=2000)


CandidateAction = Annotated[
    ObserveAction
    | OrientLocalAction
    | AwakenVesselAction
    | ConnectAction
    | OfferAction
    | RequestSupportAction
    | SummarizeAction
    | SustainAction
    | RelayAction
    | MitigateAction
    | CalculateFlowAction
    | BranchProposalAction
    | ProposeCirculationAction
    | CompareRecordsAction
    | ClarifyRecordAction
    | ClassifyContradictionAction
    | RelayRecordAction
    | AnnotateDifferenceAction
    | InspectAction
    | SampleAction
    | SeparateAction
    | InoculateAction
    | SlowAction
    | ContainAction
    | RestAction
    | ReplaceAction
    | RefuseAction
    | ReduceAction
    | RedesignAction
    | DocumentAction
    | AuditAction
    | ProposeTranslationAction
    | ProposeReciprocityAction
    | ProposeRemediationProtocolAction
    | ProposeMemoryArchiveAction
    | ProposeProductionReformAction
    | ProposeReconstructionAction
    | ConfirmReconstructionAction
    | BeginStackAction
    | ReactToStackAction
    | ResolveStackAction
    | AddProposalKickerAction
    | UseTriggeredReactionAction
    | UnknownAction,
    Field(discriminator="action"),
]
