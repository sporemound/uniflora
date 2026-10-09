from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from uniflora.content.loader import PuzzleRegistry
from uniflora.content.schema import PuzzleDefinition
from uniflora.engine.actions import (
    AuditAction,
    BeginStackAction,
    CandidateAction,
    ConfirmReconstructionAction,
    ContainAction,
    DocumentAction,
    InoculateAction,
    InspectAction,
    ObserveAction,
    ProposeProductionReformAction,
    ProposeRemediationProtocolAction,
    ReactToStackAction,
    ReduceAction,
    ReplaceAction,
    ResolveStackAction,
    RestAction,
    SampleAction,
    SeparateAction,
    SlowAction,
    SustainAction,
)
from uniflora.engine.core import DeterministicEngine
from uniflora.engine.position_zero import EnvironmentPositionValidator
from uniflora.engine.provision_arc import ProvisionArcValidator
from uniflora.engine.validation import ValidationContext, ValidationDecision
from uniflora.game_service import GameService
from uniflora.runtime import Environment, RoutingSnapshot, SessionMode
from uniflora.storage.database import Database
from uniflora.storage.repository import GameRepository, MutationPlan


@dataclass
class ArcRun:
    definition: PuzzleDefinition
    validator: ProvisionArcValidator
    state: dict[str, Any]
    serial: int = 0

    def act(
        self,
        action: CandidateAction,
        participant_id: str = "test:observer",
        *,
        environment: Environment = Environment.TEST,
    ) -> ValidationDecision:
        self.serial += 1
        decision = self.validator.validate(
            action,
            ValidationContext(
                environment=environment,
                session_id=f"provision-{self.definition.position}",
                participant_id=participant_id,
                action_id=f"action-{self.serial}",
                current_position=self.definition.position,
                response_profile="plural_translation",
                state=self.state,
            ),
        )
        if decision.accepted:
            assert decision.next_state is not None
            self.state = decision.next_state
        return decision


def arc_run(position: int) -> ArcRun:
    definition = PuzzleRegistry.load_packaged().get(position)
    return ArcRun(
        definition,
        ProvisionArcValidator(definition),
        definition.initial_state(),
    )


@pytest.mark.legacy_content
@pytest.mark.parametrize(
    ("position", "cue", "observation_id"),
    (
        (3, "Warm water route — altered flow", "clear_return_not_safe"),
        (4, "Clear-Flow Branch", "clear_flow_branch_planned"),
        (5, "Layered assurance record wall", "original_limited_works_claim"),
        (6, "Versioned record of prior failure", "historical_failure_preservation"),
    ),
)
def test_inspection_accepts_spoiler_safe_public_cues(
    position: int, cue: str, observation_id: str
) -> None:
    run = arc_run(position)

    inspected = run.act(InspectAction(action="inspect", target_entity_id=cue))

    assert inspected.accepted
    assert observation_id in run.state["unlocked_observations"]


def ready_reconstruction_run(*, source_reduction: int) -> ArcRun:
    run = arc_run(6)
    requirements = run.definition.provision_requirements
    assert requirements is not None
    run.state["unlocked_observations"] = list(requirements.required_observations)
    run.state["persistent_effects"] = list(requirements.required_persistent_effects)
    participants = ("test:water", "test:worker", "test:maintainer", "test:archivist")
    functions = ("sampling", "livelihood", "maintenance", "documentation")
    run.state["arc_actions"] = [
        {
            "semantic_key": f"fixture:{action}",
            "participant_id": participants[index % len(participants)],
            "action": action,
            "subject": f"fixture-{index}",
            "function": functions[index % len(functions)],
        }
        for index, action in enumerate(requirements.required_actions)
    ]
    run.state["contributions"] = [
        {
            "participant_id": participant,
            "function": function,
            "action": "fixture",
            "subject": "public-reconstruction",
        }
        for participant, function in zip(participants, functions, strict=True)
    ]
    run.state["counters"]["source_reduction"] = source_reduction
    return run


def valid_reconstruction(**changes: Any) -> ProposeProductionReformAction:
    payload: dict[str, Any] = {
        "action": "propose_production_reform",
        "production_line": "durable regional goods and civic repair",
        "current_output": 12,
        "revised_output": 5,
        "public_need_served": "essential durable regional goods and public repair",
        "water_cap": 4,
        "waste_reduction": "End disposable lines and reduce rejected output and packaging.",
        "worker_transition": (
            "Protect worker livelihoods with wages, training, repair work, and a paid transition."
        ),
        "ownership_or_governance": (
            "Worker and community public governance controls accounts, caps, and surplus."
        ),
        "remediation_obligation": (
            "Source reduction first; remediation begins only after reduction and containment."
        ),
        "clean_flow_plan": (
            "Separate clean flow from characterized contaminated flow and verify any reuse."
        ),
        "spent_substrate_plan": (
            "Contain spent substrate under public inventory with no automatic reuse."
        ),
        "monitoring": "Public monitoring, paired samples, and evidence remain open.",
        "maintenance": "Fund public maintenance, repair, viability checks, and containment.",
        "historical_records": (
            "Preserve the versioned archive, failed-treatment records, and unresolved history."
        ),
        "reassessment": (
            "Seasonal reassessment and public review follow heat, water, viability, and burden."
        ),
        "shutdown_threshold": (
            "A public shutdown threshold stops a line when ecological or worker limits are crossed."
        ),
    }
    payload.update(changes)
    return ProposeProductionReformAction.model_validate(payload)


def configured_inoculation() -> InoculateAction:
    return InoculateAction(
        action="inoculate",
        target_entity_id="white_rot_beds",
        culture_id="public_white_rot_line",
        substrate="bounded_woody_filter_medium",
    )


def prepare_treatable_state(run: ArcRun) -> None:
    run.state["characterized_contaminants"] = {"warm_return_channel": "organic_dye_residue"}
    run.state["unlocked_observations"] = [
        "returned_water_use_limit",
        "culture_library_scope",
    ]
    run.state["counters"]["throughput"] = 6
    run.state["counters"]["containment"] = 2
    run.state["counters"]["viability"]["white_rot_beds"] = 2
    run.state["counters"]["saturation"]["white_rot_beds"] = 0
    run.state["persistent_effects"] = ["Clean and Contaminated Flows Separated"]
    run.state["containments"] = [
        {"target": "white_rot_beds", "destination": "spent_substrate_court"}
    ]


def prepare_sampling_state(run: ArcRun) -> None:
    run.state["unlocked_observations"] = [
        "production_water_competition",
        "returned_water_use_limit",
    ]


def valid_remediation_protocol() -> ProposeRemediationProtocolAction:
    return ProposeRemediationProtocolAction(
        action="propose_remediation_protocol",
        source_discharge="warm_return_channel",
        contaminant_class="organic_dye_residue",
        production_reduction_action="reduce unnecessary production to the public cap",
        treatment_bed="white_rot_beds",
        fungal_culture="archive_white_rot_culture",
        flow_rate_condition="regulate flow and contact time",
        moisture_condition="maintain moisture, temperature, and viability",
        monitoring_method="paired repeated public samples",
        upstream_sample="upstream_sample_port",
        downstream_sample="downstream_sample_port",
        evidence_requirement="two non-visual public evidence records",
        saturation_limit=3,
        spent_substrate_destination="spent_substrate_court",
        maintenance_condition="rest or replace at saturation",
        shutdown_condition="shutdown when capacity or viability crosses its threshold",
    )


def test_position_transition_uses_new_baselines_and_preserves_collective_history() -> None:
    registry = PuzzleRegistry.load_packaged()
    position_two = registry.get(2).initial_state()
    position_two["counters"]["throughput"] = 1
    position_two["counters"]["source_reduction"] = 2
    position_two["counters"]["saturation"]["white_rot_beds"] = 1
    position_two["counters"]["viability"]["white_rot_beds"] = 3
    position_two["counters"]["saturation"]["prior_indicator_bed"] = 2
    position_two["resources"]["provision_works"]["prior_only_marker"] = 9

    position_three_validator = ProvisionArcValidator(registry.get(3))
    position_three = position_three_validator.initialize_from_previous(position_two)

    assert position_three["counters"]["throughput"] == 8
    assert position_three["counters"]["source_reduction"] == 2
    assert position_three["counters"]["saturation"]["white_rot_beds"] == 0
    assert position_three["counters"]["viability"]["white_rot_beds"] == 2
    assert position_three["counters"]["saturation"]["prior_indicator_bed"] == 2
    assert position_three["resources"]["provision_works"]["prior_only_marker"] == 9
    assert position_three["resources"]["provision_works"]["goods"] == 8

    position_three["counters"]["throughput"] = 6
    position_three["counters"]["saturation"]["white_rot_beds"] = 0
    position_four = ProvisionArcValidator(registry.get(4)).initialize_from_previous(position_three)

    assert position_four["counters"]["throughput"] == 7
    assert position_four["counters"]["source_reduction"] == 2
    assert position_four["counters"]["saturation"]["white_rot_beds"] == 2

    position_five = registry.get(5).initial_state()
    position_five["resources"]["provision_works"]["prior_only_marker"] = 11
    position_six = ProvisionArcValidator(registry.get(6)).initialize_from_previous(position_five)
    assert position_six["resources"]["provision_works"]["prior_only_marker"] == 11
    assert position_six["resources"]["provision_works"]["production_capacity"] == 12


def test_reconstruction_rejects_remediation_without_source_reduction() -> None:
    run = ready_reconstruction_run(source_reduction=0)
    rejected = run.act(valid_reconstruction(), "test:author")
    assert not rejected.accepted
    assert rejected.reason_key == "proposal_rejected"
    assert "source reduction" in str(rejected.public_data["feedback"]).lower()
    assert run.state["proposals"] == {}

    run.state["counters"]["source_reduction"] = 1
    accepted = run.act(valid_reconstruction(), "test:author")
    assert accepted.accepted
    assert accepted.public_data["proposal_id"].startswith("recon-")


@pytest.mark.parametrize(
    ("characterized_as", "expected_failure"),
    [
        ("unlisted_discharge", "unknown_discharge"),
        ("mineral_glaze_runoff", "incompatible_culture"),
    ],
)
def test_unknown_and_incompatible_treatment_fail_safely(
    characterized_as: str, expected_failure: str
) -> None:
    run = arc_run(6)
    before_remediation = run.state["counters"]["remediation"]
    run.state["characterized_contaminants"] = {"warm_return_channel": characterized_as}
    run.state["unlocked_observations"] = ["culture_library_scope"]

    decision = run.act(configured_inoculation())

    assert decision.accepted
    assert decision.reason_key == "treatment_failed_safely"
    assert run.state["failed_treatments"][-1]["failure"] == expected_failure
    assert run.state["counters"]["instability"] == 1
    assert run.state["counters"]["remediation"] == before_remediation
    assert "White Rot Bed Stabilized" not in run.state["persistent_effects"]
    assert run.state["triggered_reactions"][-1]["consumed"] is False
    failure = run.state["failed_treatments"][-1]
    assert failure["attempt"]["reported_contaminant_class"] == characterized_as
    assert failure["attempt"]["culture_id"] == "public_white_rot_line"
    assert "throughput" in failure["counter_snapshot"]


def test_hidden_measurements_and_uninspected_culture_cannot_authorize_treatment() -> None:
    run = arc_run(6)
    prepare_treatable_state(run)
    run.state["counters"]["source_reduction"] = 1
    run.state["characterized_contaminants"] = {}

    hidden_measurement = run.act(configured_inoculation(), "test:hidden-measurement")

    assert hidden_measurement.accepted
    assert run.state["failed_treatments"][-1]["failure"] == "unknown_discharge"

    run = arc_run(6)
    prepare_treatable_state(run)
    run.state["counters"]["source_reduction"] = 1
    run.state["unlocked_observations"].remove("culture_library_scope")

    hidden_culture = run.act(configured_inoculation(), "test:hidden-culture")

    assert hidden_culture.accepted
    assert run.state["failed_treatments"][-1]["failure"] == "culture_not_public"


def test_low_viability_prevents_treatment() -> None:
    run = arc_run(6)
    prepare_treatable_state(run)
    run.state["counters"]["viability"]["white_rot_beds"] = 1

    decision = run.act(configured_inoculation())

    assert decision.accepted
    assert decision.reason_key == "treatment_failed_safely"
    assert run.state["failed_treatments"][-1]["failure"] == "low_viability"
    assert run.state["counters"]["saturation"]["white_rot_beds"] == 0
    assert "White Rot Bed Stabilized" not in run.state["persistent_effects"]


def test_treatment_cannot_bypass_source_reduction() -> None:
    run = arc_run(6)
    prepare_treatable_state(run)
    before_remediation = run.state["counters"]["remediation"]

    decision = run.act(configured_inoculation())

    assert decision.accepted
    assert decision.reason_key == "treatment_failed_safely"
    assert run.state["failed_treatments"][-1]["failure"] == "source_reduction_missing"
    assert run.state["counters"]["remediation"] == before_remediation
    assert run.state["triggered_reactions"][-1]["kind"] == "reduce_source"
    assert "White Rot Bed Stabilized" not in run.state["persistent_effects"]


def test_treatment_requires_target_containment_and_recommissioned_bed() -> None:
    run = arc_run(6)
    prepare_treatable_state(run)
    run.state["counters"]["source_reduction"] = 1
    run.state["containments"] = [
        {"target": "blackwater_berm", "destination": "spent_substrate_court"}
    ]

    uncontained = run.act(configured_inoculation(), "test:uncontained")

    assert uncontained.accepted
    assert run.state["failed_treatments"][-1]["failure"] == "containment_missing"

    run = arc_run(6)
    prepare_treatable_state(run)
    run.state["counters"]["source_reduction"] = 1
    run.state["beds_offline"] = ["white_rot_beds"]

    offline = run.act(configured_inoculation(), "test:offline")
    assert offline.accepted
    assert run.state["failed_treatments"][-1]["failure"] == "bed_offline"

    recommissioned = run.act(
        SustainAction(
            action="sustain",
            target_entity_id="white_rot_beds",
            condition="monitor_viability",
        ),
        "test:maintainer",
    )
    assert recommissioned.accepted
    assert "white_rot_beds" not in run.state["beds_offline"]


def test_source_reduction_requires_a_real_numeric_delta() -> None:
    run = arc_run(6)
    run.state["counters"]["throughput"] = 1
    run.state["counters"]["extraction"] = 1
    before_source_reduction = run.state["counters"]["source_reduction"]

    first = run.act(
        ReduceAction(
            action="reduce",
            target_entity_id="provision_works",
            measure="production_throughput",
            amount=5,
        ),
        "test:first-reducer",
    )
    assert first.accepted
    assert run.state["counters"]["source_reduction"] == before_source_reduction + 1

    repeated = run.act(
        ReduceAction(
            action="reduce",
            target_entity_id="provision_works",
            measure="production_throughput",
            amount=4,
        ),
        "test:wording-reducer",
    )
    assert repeated.accepted
    assert run.state["counters"]["source_reduction"] == before_source_reduction + 1
    assert sum(item["action"] == "reduce" for item in run.state["contributions"]) == 1


@pytest.mark.parametrize(
    ("saturation", "throughput", "expected_failure", "expected_saturation"),
    [
        (3, 6, "saturated_bed", 4),
        (0, 7, "throughput_overload", 0),
    ],
)
def test_saturation_and_throughput_overload_preserve_public_progress(
    saturation: int,
    throughput: int,
    expected_failure: str,
    expected_saturation: int,
) -> None:
    run = arc_run(6)
    prepare_treatable_state(run)
    run.state["counters"]["saturation"]["white_rot_beds"] = saturation
    run.state["counters"]["throughput"] = throughput
    run.state["unlocked_observations"] = list(
        dict.fromkeys([*run.state["unlocked_observations"], "source_reduction_before_remediation"])
    )
    public_observations = list(run.state["unlocked_observations"])
    run.state["persistent_effects"].append("Source Reduction Mandate")

    decision = run.act(configured_inoculation())

    assert decision.accepted
    assert decision.reason_key == "treatment_failed_safely"
    assert run.state["failed_treatments"][-1]["failure"] == expected_failure
    assert run.state["counters"]["saturation"]["white_rot_beds"] == expected_saturation
    assert run.state["unlocked_observations"] == public_observations
    assert "Source Reduction Mandate" in run.state["persistent_effects"]


def test_visible_clarity_does_not_add_safety_evidence() -> None:
    run = arc_run(6)
    prepare_sampling_state(run)
    before_evidence = run.state["counters"]["evidence"]

    decision = run.act(
        SampleAction(
            action="sample",
            source_entity_id="production_intake_channel",
            comparison_entity_id="warm_return_channel",
            measure="visible_clarity",
        )
    )

    assert decision.accepted
    assert run.state["samples"][-1]["visual_only"] is True
    assert run.state["counters"]["evidence"] == before_evidence
    assert "Evidence of safety has not increased" in decision.public_data["public_text"]
    assert "Upstream and Downstream Sampled" in run.state["persistent_effects"]

    visual_sample_id = run.state["samples"][-1]["sample_key"]
    audited = run.act(
        AuditAction(
            action="audit",
            target_entity_id="warm_return_channel",
            claim="returned_water_use_limit",
            comparison=visual_sample_id,
        ),
        "test:visual-auditor",
    )
    assert audited.accepted
    assert run.state["counters"]["evidence"] == before_evidence
    assert run.state["audits"][-1]["supports_safety_evidence"] is False


def test_remediation_protocol_requires_exact_nonvisual_sample_pair() -> None:
    run = arc_run(4)
    requirements = run.definition.provision_requirements
    assert requirements is not None
    run.state["unlocked_observations"] = list(requirements.required_observations)
    run.state["arc_actions"] = [
        {
            "semantic_key": f"fixture:{action}",
            "action": action,
            "participant_id": f"test:{index}",
            "function": f"function-{index}",
            "subject": "fixture",
        }
        for index, action in enumerate((*requirements.required_actions, "sustain", "rest"), start=1)
    ]
    run.state["contributions"] = [
        {
            "participant_id": f"test:{index}",
            "function": f"function-{index}",
            "action": "fixture",
            "subject": "fixture",
        }
        for index in range(1, 4)
    ]
    run.state["persistent_effects"] = [
        *requirements.required_persistent_effects,
        "Maintained Remediation Cycle",
        "Treatment Bed Rested",
    ]
    run.state["counters"]["source_reduction"] = 1
    run.state["counters"]["evidence"] = 99
    run.state["counters"]["viability"]["white_rot_beds"] = 2
    run.state["counters"]["saturation"]["white_rot_beds"] = 0
    run.state["samples"] = [
        {
            "sample_key": "visual-only-pair",
            "source": "upstream_sample_port",
            "comparison": "downstream_sample_port",
            "measure": "visible_clarity",
            "visual_only": True,
        }
    ]
    run.state["maintenance_cycle"]["stage"] = len(requirements.maintenance_cycle_steps)

    rejected = run.act(valid_remediation_protocol(), "test:protocol-author")

    assert not rejected.accepted
    assert "non-visual" in str(rejected.public_data["feedback"]).lower()


def test_duplicate_sampling_does_not_farm_evidence_or_contributions() -> None:
    run = arc_run(6)
    prepare_sampling_state(run)
    action = SampleAction(
        action="sample",
        source_entity_id="production_intake_channel",
        comparison_entity_id="warm_return_channel",
        measure="dissolved_residue",
    )

    first = run.act(action, "test:water")
    assert first.accepted
    evidence = run.state["counters"]["evidence"]
    contributions = len(run.state["contributions"])
    repeated = run.act(
        SampleAction(
            action="sample",
            source_entity_id="warm_return_channel",
            comparison_entity_id="production_intake_channel",
            measure="dissolved_residue",
        ),
        "test:second-water",
    )

    assert repeated.accepted
    assert repeated.contribution_function is None
    assert run.state["counters"]["evidence"] == evidence
    assert len(run.state["samples"]) == 1
    assert len(run.state["contributions"]) == contributions


def test_observe_and_inspect_share_one_semantic_discovery_key() -> None:
    run = arc_run(6)

    first = run.act(
        ObserveAction(action="observe", entity_id="provision_works"), "test:first-reader"
    )
    second = run.act(
        InspectAction(action="inspect", target_entity_id="provision_works"),
        "test:second-reader",
    )
    contribution_count = len(run.state["contributions"])
    repeated = run.act(
        ObserveAction(action="observe", entity_id="provision_works"), "test:third-reader"
    )

    assert first.accepted and second.accepted and repeated.accepted
    assert {"unnecessary_output_quota", "distant_surplus_control"}.issubset(
        run.state["unlocked_observations"]
    )
    assert len(run.state["contributions"]) == contribution_count
    assert repeated.contribution_function is None


def test_position_three_water_limit_reports_current_limit_and_excess() -> None:
    run = arc_run(3)

    decision = run.act(
        InspectAction(action="inspect", target_entity_id="production_intake_channel")
    )

    assert decision.accepted
    text = decision.public_data["public_text"]
    assert "8 water units" in text
    assert "maximum of 5" in text
    assert "excess of 3" in text


def test_position_four_observations_report_live_operating_thresholds() -> None:
    run = arc_run(4)

    throughput = run.act(InspectAction(action="inspect", target_entity_id="provision_works"))
    viability = run.act(InspectAction(action="inspect", target_entity_id="white_rot_beds"))
    saturation = run.act(InspectAction(action="inspect", target_entity_id="white_rot_beds"))

    assert throughput.accepted and viability.accepted and saturation.accepted
    assert "7 units" in throughput.public_data["public_text"]
    assert "capacity of 6" in throughput.public_data["public_text"]
    assert "excess of 1" in throughput.public_data["public_text"]
    assert "viability is 2" in viability.public_data["public_text"]
    assert "minimum is 2" in viability.public_data["public_text"]
    assert "shortfall is 0" in viability.public_data["public_text"]
    assert "saturation is 2" in saturation.public_data["public_text"]
    assert "limit of 3" in saturation.public_data["public_text"]
    assert "1 load of headroom" in saturation.public_data["public_text"]


def test_corroboration_refreshes_dynamic_threshold_in_public_record() -> None:
    run = arc_run(4)
    first = run.act(InspectAction(action="inspect", target_entity_id="provision_works"))
    assert first.accepted and "excess of 1" in first.public_data["public_text"]

    run.state["counters"]["throughput"] = 6
    repeated = run.act(
        InspectAction(action="inspect", target_entity_id="provision_works"),
        "test:corroborator",
    )

    assert repeated.accepted
    assert "excess of 0" in repeated.public_data["public_text"]
    fact = next(
        item
        for item in run.state["confirmed_facts"]
        if item["observation_id"] == "production_exceeds_capacity"
    )
    assert "excess of 0" in fact["public_text"]


def test_position_six_observations_expose_ranges_without_preselecting_policy() -> None:
    run = arc_run(6)

    output = run.act(InspectAction(action="inspect", target_entity_id="provision_works"))
    water = run.act(InspectAction(action="inspect", target_entity_id="production_intake_channel"))
    returned = run.act(InspectAction(action="inspect", target_entity_id="warm_return_channel"))
    cap = run.act(
        InspectAction(action="inspect", target_entity_id="public_well_seven"),
        "test:second-water-reader",
    )

    assert output.accepted and water.accepted and returned.accepted and cap.accepted
    assert "Current output is 12" in output.public_data["public_text"]
    assert "verified regional need accounts for 5" in output.public_data["public_text"]
    assert "7 units not established as necessary" in output.public_data["public_text"]
    assert "choose a revised output below 12" in output.public_data["public_text"]
    assert "9 units of priority water draw" in water.public_data["public_text"]
    assert "Well Seven recovers 4" in water.public_data["public_text"]
    assert "lower than the current 9-unit draw" in water.public_data["public_text"]
    assert "0 of those 7 units" in returned.public_data["public_text"]
    assert "at least 0 and strictly below the current 9-unit" in cap.public_data["public_text"]
    assert "no single preselected cap" in cap.public_data["public_text"]


def test_recall_resource_status_is_discovery_scoped_and_uses_live_counters() -> None:
    registry = PuzzleRegistry.load_packaged()
    game = object.__new__(GameService)
    game.registries = {Environment.TEST: registry}
    data = registry.get(4).initial_state()

    assert game._public_resource_status(Environment.TEST, current_position=4, data=data) == []

    data["unlocked_observations"] = [
        "production_exceeds_capacity",
        "bed_viability_stressed",
        "bed_saturation_overloaded",
    ]
    lines = game._public_resource_status(Environment.TEST, current_position=4, data=data)
    joined = "\n".join(lines)
    assert "Treatment throughput: current 7; maximum 6; excess 1" in joined
    assert "White Rot Bed viability: current 2; minimum 2; deficit 0" in joined
    assert "White Rot Bed saturation: current 2; limit 3; headroom 1" in joined

    data["counters"]["throughput"] = 5
    refreshed = "\n".join(
        game._public_resource_status(Environment.TEST, current_position=4, data=data)
    )
    assert "Treatment throughput: current 5; maximum 6; excess 0" in refreshed


@pytest.mark.parametrize(
    "action",
    [
        RestAction(
            action="rest",
            target_entity_id="provision_works",
            reassessment="public reassessment",
        ),
        ReplaceAction(
            action="replace",
            target_entity_id="provision_works",
            destination_entity_id="spent_substrate_court",
            replacement="replacement",
        ),
        ContainAction(
            action="contain",
            target_entity_id="provision_works",
            destination_entity_id="spent_substrate_court",
            condition="custody",
        ),
        SlowAction(
            action="slow",
            target_entity_id="provision_works",
            condition="monitor_viability",
        ),
        SustainAction(
            action="sustain",
            target_entity_id="provision_works",
            condition="monitor_viability",
        ),
    ],
)
def test_remediation_actions_reject_non_system_targets(action: CandidateAction) -> None:
    run = arc_run(6)

    decision = run.act(action)

    assert not decision.accepted
    assert decision.reason_key == "invalid_action"


def test_spent_substrate_requires_valid_containment_and_cannot_be_farmed() -> None:
    run = arc_run(6)
    before_containment = run.state["counters"]["containment"]
    invalid = run.act(
        ContainAction(
            action="contain",
            target_entity_id="white_rot_beds",
            destination_entity_id="clear_water_test_garden",
            condition="public custody",
        )
    )
    assert not invalid.accepted
    assert run.state["counters"]["containment"] == before_containment

    action = ContainAction(
        action="contain",
        target_entity_id="white_rot_beds",
        destination_entity_id="spent_substrate_court",
        condition="isolate under the public spent-material inventory",
    )
    accepted = run.act(action, "test:containment")
    assert accepted.accepted
    assert run.state["counters"]["containment"] == before_containment + 1
    assert "Spent Substrate Contained" in run.state["persistent_effects"]
    repeated = run.act(action, "test:second-containment")
    assert repeated.accepted
    assert repeated.contribution_function is None
    assert run.state["counters"]["containment"] == before_containment + 1
    assert len(run.state["containments"]) == 1


def test_returned_water_is_not_automatically_usable() -> None:
    definition = PuzzleRegistry.load_packaged().get(6)
    entities = {item.id: item for item in definition.entities}
    observations = {item.id: item for item in definition.observations}
    requirements = definition.provision_requirements
    assert requirements is not None

    assert entities["warm_return_channel"].measurements["reuse_eligibility"] == "unconfirmed"
    assert "public_water_cap_basis" in requirements.required_observations
    assert (
        "returned_water_use_limit"
        in observations["public_water_cap_basis"].unlock.requires_observations
    )
    public_text = observations["returned_water_use_limit"].public_text.lower()
    assert "return" in public_text
    assert "usable" in public_text


def test_public_benefit_does_not_erase_local_burden() -> None:
    run = arc_run(3)
    run.state["unlocked_observations"] = [
        "works_benefit_claim",
        "remediation_cost_externalized",
    ]
    before_benefit = run.state["counters"]["public_benefit"]
    before_burden = run.state["counters"]["burden"]

    decision = run.act(
        AuditAction(
            action="audit",
            target_entity_id="provision_works",
            claim="works_benefit_claim",
            comparison="remediation_cost_externalized",
        )
    )

    assert decision.accepted
    assert run.state["counters"]["public_benefit"] == before_benefit
    assert run.state["counters"]["burden"] == before_burden + 1
    assert "Public Discharge Ledger" in run.state["persistent_effects"]
    assert "benefit does not erase burden" in decision.public_data["public_text"].lower()


@pytest.mark.parametrize(
    ("changes", "feedback_fragment"),
    [
        ({"revised_output": 12}, "reduce unnecessary throughput"),
        ({"worker_transition": "Remove the line immediately."}, "livelihood"),
        (
            {"ownership_or_governance": "Charter Holders retain unilateral quota authority."},
            "public governance",
        ),
        ({"worker_transition": "Workers receive no livelihood transition."}, "livelihood"),
        ({"ownership_or_governance": "There is no public accountability."}, "public governance"),
        ({"remediation_obligation": "Do not reduce first."}, "source reduction"),
        ({"clean_flow_plan": "Do not separate clean flow."}, "separated flows"),
        ({"current_output": 13}, "current output"),
        ({"water_cap": 9}, "water cap"),
    ],
)
def test_reconstruction_enforces_throughput_livelihood_and_governance(
    changes: dict[str, Any], feedback_fragment: str
) -> None:
    run = ready_reconstruction_run(source_reduction=1)
    decision = run.act(valid_reconstruction(**changes), "test:author")

    assert not decision.accepted
    assert decision.reason_key == "proposal_rejected"
    assert feedback_fragment in str(decision.public_data["feedback"]).lower()
    assert run.state["proposals"] == {}


def test_final_proposal_requires_non_author_confirmation() -> None:
    run = ready_reconstruction_run(source_reduction=1)
    proposed = run.act(valid_reconstruction(), "test:author")
    assert proposed.accepted
    proposal_id = proposed.public_data["proposal_id"]

    author_confirmation = run.act(
        ConfirmReconstructionAction(action="confirm_reconstruction", proposal_id=proposal_id),
        "test:author",
    )
    assert not author_confirmation.accepted
    assert "non-author" in str(author_confirmation.public_data["feedback"]).lower()
    assert run.state["position_completed"] is False

    public_confirmation = run.act(
        ConfirmReconstructionAction(action="confirm_reconstruction", proposal_id=proposal_id),
        "test:worker",
    )
    assert public_confirmation.accepted
    assert public_confirmation.position_completed
    assert public_confirmation.next_position is None
    assert run.state["position_completed"] is True
    assert run.state["world_flags"]["livelihood_transition_secured"] is True
    assert run.state["world_flags"]["distant_private_accumulation_overridden"] is True


def test_repeated_stack_reaction_cannot_farm_collective_counters() -> None:
    run = ready_reconstruction_run(source_reduction=1)
    before_stack = dict(run.state["counters"])
    detail = run.definition.provision_requirements.required_observations[0]  # type: ignore[union-attr]
    proposal = {
        "kind": "reconstruction",
        **valid_reconstruction().model_dump(exclude={"action"}),
    }

    def resolve_reduction_stack(suffix: str) -> None:
        opened = run.act(
            BeginStackAction(action="begin_stack", proposal=proposal),
            f"test:author-{suffix}",
        )
        assert opened.accepted
        stack_id = run.state["public_stack"]["stack_id"]
        reacted = run.act(
            ReactToStackAction(
                action="react_to_stack",
                stack_id=stack_id,
                reaction="reduce_source",
                detail=detail,
            ),
            f"test:reactor-{suffix}",
        )
        assert reacted.accepted
        resolved = run.act(
            ResolveStackAction(action="resolve_stack", stack_id=stack_id),
            f"test:resolver-{suffix}",
        )
        assert resolved.accepted

    resolve_reduction_stack("first")
    after_first = dict(run.state["counters"])
    assert after_first == before_stack

    resolve_reduction_stack("repeat")

    assert run.state["counters"]["source_reduction"] == after_first["source_reduction"]
    assert run.state["counters"]["throughput"] == after_first["throughput"]
    assert (
        sum(
            item["action"] == "react_to_stack" and item["subject"] == f"reduce_source:{detail}"
            for item in run.state["contributions"]
        )
        == 1
    )


def test_position_four_cycle_is_ordered_and_preserves_a_safe_failure() -> None:
    run = arc_run(4)
    inoculation = InoculateAction(
        action="inoculate",
        target_entity_id="white_rot_beds",
        culture_id="archive_white_rot_culture",
        substrate="yard_wood_fiber_matrix",
    )
    run.state["counters"]["throughput"] = 6
    run.state["counters"]["containment"] = 2
    run.state["counters"]["source_reduction"] = 1
    run.state["persistent_effects"] = ["Clean and Contaminated Flows Separated"]
    run.state["containments"] = [
        {"target": "white_rot_beds", "destination": "spent_substrate_court"}
    ]
    out_of_order = run.act(inoculation)
    assert not out_of_order.accepted
    assert "inspect_discharge" in str(out_of_order.public_data["feedback"])
    assert run.state["maintenance_cycle"]["stage"] == 0

    inspected = run.act(
        InspectAction(action="inspect", target_entity_id="provision_works"),
        "test:capacity",
    )
    characterized = run.act(
        InspectAction(action="inspect", target_entity_id="warm_return_channel"),
        "test:materials",
    )
    assert inspected.accepted and characterized.accepted
    assert run.state["maintenance_cycle"]["stage"] == 2

    compatibility = run.act(
        InspectAction(action="inspect", target_entity_id="culture_archive"),
        "test:compatibility",
    )
    assert compatibility.accepted
    assert run.state["maintenance_cycle"]["stage"] == 3

    run.state["counters"]["throughput"] = 7
    failed = run.act(inoculation, "test:treatment")
    assert failed.accepted
    assert failed.reason_key == "treatment_failed_safely"
    failure_id = failed.public_data["failure_id"]
    assert run.state["failed_treatments"][-1]["failure"] == "throughput_overload"
    assert run.state["maintenance_cycle"]["stage"] == 3
    assert "production_exceeds_capacity" in run.state["unlocked_observations"]

    documented = run.act(
        DocumentAction(
            action="document",
            subject_entity_id="public_discharge_archive",
            record_type="treatment_failure",
            text=failure_id,
        ),
        "test:archive",
    )
    separated = run.act(
        SeparateAction(
            action="separate",
            source_entity_id="warm_return_channel",
            clean_target_entity_id="clear_return_channel",
            contaminated_target_entity_id="treatment_yard",
        ),
        "test:flows",
    )
    assert documented.accepted and separated.accepted

    run.state["counters"]["throughput"] = 6
    inoculated = run.act(inoculation, "test:treatment")
    assert inoculated.accepted
    assert inoculated.reason_key == "accepted"
    assert run.state["maintenance_cycle"]["stage"] == 4

    slowed = run.act(
        SlowAction(
            action="slow",
            target_entity_id="warm_return_channel",
            condition="regulate_flow_and_contact_time",
        ),
        "test:flow-control",
    )
    assert slowed.accepted
    run.state["unlocked_observations"] = list(
        dict.fromkeys(
            [
                *run.state["unlocked_observations"],
                *run.definition.provision_requirements.required_observations,
            ]
        )
    )
    sampled = run.act(
        SampleAction(
            action="sample",
            source_entity_id="upstream_sample_port",
            comparison_entity_id="downstream_sample_port",
            measure="upstream_downstream_comparison",
        ),
        "test:sample",
    )
    assert sampled.accepted
    sample_id = run.state["samples"][-1]["sample_key"]
    audited = run.act(
        AuditAction(
            action="audit",
            target_entity_id="warm_return_channel",
            claim="characterized_return_class",
            comparison=sample_id,
        ),
        "test:audit",
    )
    assert audited.accepted

    replaced = run.act(
        ReplaceAction(
            action="replace",
            target_entity_id="white_rot_beds",
            destination_entity_id="spent_substrate_court",
            replacement="conditioned replacement with public custody",
        ),
        "test:replace",
    )
    assert replaced.accepted
    assert run.state["maintenance_cycle"]["stage"] == 8
    contained = run.act(
        ContainAction(
            action="contain",
            target_entity_id="white_rot_beds",
            destination_entity_id="spent_substrate_court",
            condition="retain the custody manifest",
        ),
        "test:contain",
    )
    reduced = run.act(
        ReduceAction(
            action="reduce",
            target_entity_id="provision_works",
            measure="cap_unnecessary_throughput",
            amount=1,
            condition="production_exceeds_capacity",
        ),
        "test:reduction",
    )
    assert contained.accepted and reduced.accepted
    assert run.state["maintenance_cycle"]["stage"] == 10

    proposed = run.act(
        ProposeRemediationProtocolAction(
            action="propose_remediation_protocol",
            source_discharge="warm_return_channel",
            contaminant_class="organic_dye_residue",
            production_reduction_action="reduce unnecessary production to the public cap",
            treatment_bed="white_rot_beds",
            fungal_culture="archive_white_rot_culture",
            flow_rate_condition="regulate flow and contact time",
            moisture_condition="maintain moisture, temperature, and viability",
            monitoring_method="paired repeated public samples",
            upstream_sample="upstream_sample_port",
            downstream_sample="downstream_sample_port",
            evidence_requirement="two non-visual public evidence records",
            saturation_limit=3,
            spent_substrate_destination="spent_substrate_court",
            maintenance_condition="rest or replace at saturation",
            shutdown_condition="shutdown when capacity or viability crosses its threshold",
        ),
        "test:protocol-author",
    )
    assert proposed.accepted
    assert run.state["maintenance_cycle"]["completed_steps"] == list(
        run.definition.provision_requirements.maintenance_cycle_steps
    )
    confirmed = run.act(
        ConfirmReconstructionAction(
            action="confirm_reconstruction",
            proposal_id=proposed.public_data["proposal_id"],
        ),
        "test:protocol-confirmer",
    )
    assert confirmed.accepted and confirmed.position_completed
    assert any(
        record["source_reference"] == failure_id for record in run.state["versioned_records"]
    )
    assert any(failure["failure_id"] == failure_id for failure in run.state["failed_treatments"])


@pytest.mark.asyncio
async def test_provision_arc_test_session_is_isolated_from_live(tmp_path: Path) -> None:
    database = Database(f"sqlite+aiosqlite:///{(tmp_path / 'arc-isolation.db').as_posix()}")
    await database.create_schema_for_tests()
    repository = GameRepository(database)
    try:
        _, refs = await repository.bootstrap(RoutingSnapshot(1, 10, 20, 30, frozenset({99})))
        registry = PuzzleRegistry.load_packaged()
        definition = registry.get(6)

        def place_test_at_reconstruction(state: dict[str, Any]) -> MutationPlan:
            return MutationPlan(
                event_type="test.provision.positioned",
                state_after={
                    **state,
                    "current_position": 6,
                    "response_profile": "plural_translation",
                    "data": definition.initial_state(),
                },
                payload={},
            )

        await repository.mutate(
            refs[Environment.TEST],
            actor_id="test:setup",
            idempotency_key="position-at-six",
            planner=place_test_at_reconstruction,
        )
        await repository.transition(
            refs[Environment.TEST],
            SessionMode.RUNNING,
            {SessionMode.LOCKED},
            "discord:99",
        )
        live_before = await repository.state(refs[Environment.LIVE])
        engine = DeterministicEngine(
            repository, EnvironmentPositionValidator(registry, enforce_cycles=False)
        )
        outcome = await engine.process(
            refs[Environment.TEST],
            participant_id="test:observer",
            action=InspectAction(action="inspect", target_entity_id="provision_works"),
            idempotency_key="inspect-test-works",
        )
        assert outcome.accepted
        test_state = await repository.state(refs[Environment.TEST])
        live_after = await repository.state(refs[Environment.LIVE])
        assert "unnecessary_output_quota" in test_state["data"]["unlocked_observations"]
        assert live_after == live_before
        assert live_after["current_position"] == 0
        assert live_after["data"]["confirmed_facts"] == []
    finally:
        await database.dispose()
