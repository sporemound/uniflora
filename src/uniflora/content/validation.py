from __future__ import annotations

from dataclasses import dataclass

from uniflora.content.loader import PuzzleRegistry
from uniflora.engine.actions import (
    AuditAction,
    CalculateFlowAction,
    ClassifyContradictionAction,
    CompareRecordsAction,
    ConfirmReconstructionAction,
    ConnectAction,
    ContainAction,
    DocumentAction,
    InspectAction,
    MitigateAction,
    ObserveAction,
    ProposeCirculationAction,
    ProposeMemoryArchiveAction,
    ProposeProductionReformAction,
    ProposeReciprocityAction,
    ProposeReconstructionAction,
    ProposeRemediationProtocolAction,
    ProposeTranslationAction,
    RedesignAction,
    ReduceAction,
    RelayRecordAction,
    RestAction,
    SampleAction,
    SeparateAction,
    SlowAction,
    SustainAction,
)
from uniflora.engine.core import DeterministicEngine
from uniflora.engine.position_zero import EnvironmentPositionValidator
from uniflora.narration import FallbackNarrator
from uniflora.runtime import Environment, RoutingSnapshot, SessionMode
from uniflora.storage.database import Database
from uniflora.storage.repository import GameRepository


@dataclass(frozen=True, slots=True)
class ContentValidationReport:
    valid: bool
    checks: tuple[str, ...]


async def validate_packaged_content() -> ContentValidationReport:
    checks: list[str] = []
    registry = PuzzleRegistry.load_packaged()
    checks.append("positions 0-6 pass strict YAML schema validation")
    checks.append("configured position presentation assets are valid and packaged")
    registry.validate_expansion_coverage()
    checks.append("Positions 0-6 are complete deterministic content")
    narrator = FallbackNarrator()
    registry.validate_narration_keys(narrator.templates)
    checks.append("all deterministic narration keys exist")
    definition = registry.get(0)
    constraints = definition.sustainability
    assert constraints is not None
    entities = {entity.id: entity for entity in definition.entities}
    donor = entities[constraints.donor_entity_id].resources[constraints.resource_id]
    recipient = entities[constraints.recipient_entity_id].resources[constraints.resource_id]
    transferable = donor - constraints.minimum_donor_reserve
    deficit = constraints.minimum_recipient_viability - recipient
    if transferable < deficit:
        raise ValueError("Position 0 has no sustainable resource solution")
    checks.append("Position 0 has a sustainable transfer interval")

    database = Database("sqlite+aiosqlite:///:memory:")
    try:
        await database.create_schema_for_tests()
        repository = GameRepository(database)
        _, refs = await repository.bootstrap(RoutingSnapshot(1, 10, 20, 30, frozenset({99})))
        ref = refs[Environment.TEST]
        await repository.initialize_content(ref, definition.initial_state())
        await repository.transition(
            ref, SessionMode.RUNNING, {SessionMode.LOCKED}, "system:content-validation"
        )
        engine = DeterministicEngine(
            repository, EnvironmentPositionValidator(registry, enforce_cycles=False)
        )

        async def act(participant: str, action: object, key: str) -> None:
            outcome = await engine.process(
                ref,
                participant_id=participant,
                action=action,  # type: ignore[arg-type]
                idempotency_key=key,
            )
            if not outcome.accepted:
                raise ValueError(f"Position 0 simulation failed at {key}: {outcome.reason_key}")

        await act("test:observer", ObserveAction(action="observe", entity_id="north"), "sim:1")
        await act("test:carrier", ObserveAction(action="observe", entity_id="east"), "sim:2")
        await act("test:binder", ObserveAction(action="observe", entity_id="path"), "sim:3")
        await act(
            "test:binder",
            ConnectAction(action="connect", source_entity_id="north", target_entity_id="east"),
            "sim:4",
        )
        await act(
            "test:observer",
            ProposeReconstructionAction(
                action="propose_reconstruction",
                proposal={
                    "donor_id": "north",
                    "recipient_id": "east",
                    "resource_id": constraints.resource_id,
                    "amount": deficit,
                    "pathway_id": "path",
                    "pathway_action": "repair",
                    "maintenance_condition": "reassess after the next cycle",
                },
            ),
            "sim:5",
        )
        state = await repository.state(ref)
        proposal_id = next(iter(state["data"]["proposals"]))
        await act(
            "test:carrier",
            ConfirmReconstructionAction(action="confirm_reconstruction", proposal_id=proposal_id),
            "sim:6",
        )
        completed = await repository.state(ref)
        if completed["current_position"] != 1:
            raise ValueError("Position 0 simulation did not advance exactly once")
        if completed["response_profile"] != definition.completion.response_profile:
            raise ValueError("Position 0 simulation did not apply its response profile")
        checks.append("isolated three-participant Position 0 simulation completes")

        await act(
            "test:need-reader",
            ObserveAction(action="observe", entity_id="nursery"),
            "sim:7",
        )
        await act("test:need-reader", ObserveAction(action="observe", entity_id="north"), "sim:8")
        await act("test:need-reader", ObserveAction(action="observe", entity_id="basin"), "sim:8b")
        await act("test:maintainer", ObserveAction(action="observe", entity_id="veil"), "sim:9")
        await act("test:maintainer", ObserveAction(action="observe", entity_id="veil"), "sim:10")
        await act(
            "test:maintainer",
            SustainAction(
                action="sustain",
                target_entity_id="veil",
                condition="maintain the collection surface each cycle",
            ),
            "sim:11",
        )
        await act("test:router", ObserveAction(action="observe", entity_id="route seven"), "sim:12")
        await act(
            "test:router",
            SustainAction(
                action="sustain",
                target_entity_id="route seven",
                condition="reassess route delivery",
            ),
            "sim:13",
        )
        await act("test:router", ObserveAction(action="observe", entity_id="relay"), "sim:14")
        await act(
            "test:router",
            CalculateFlowAction(
                action="calculate_flow", source_amount=9, pathway_entity_id="route seven"
            ),
            "sim:14b",
        )
        await act(
            "test:planner",
            ProposeCirculationAction(
                action="propose_circulation",
                source_entity_id="veil",
                recipient_entity_id="nursery",
                resource_id="water",
                source_amount=9,
                pathway_entity_id="route seven",
                relay_entity_id="relay",
                delivered_amount=9,
                maintenance="maintain the Veil surface",
                reassessment="reassess Nursery demand and output before the next cycle",
                branch_condition="if Nursery demand or Veil output changes",
                branch_action="send only the confirmed need and release unused condensation",
            ),
            "sim:15",
        )
        state = await repository.state(ref)
        circulation_id = next(
            key
            for key, item in state["data"]["proposals"].items()
            if item.get("kind") == "circulation"
        )
        await act(
            "test:need-reader",
            ConfirmReconstructionAction(
                action="confirm_reconstruction", proposal_id=circulation_id
            ),
            "sim:16",
        )
        completed = await repository.state(ref)
        if completed["current_position"] != 2:
            raise ValueError("Position 1 simulation did not advance exactly once")
        if completed["response_profile"] != registry.get(1).completion.response_profile:
            raise ValueError("Position 1 simulation did not apply its response profile")
        checks.append("isolated four-participant slash-only Position 1 simulation completes")

        await act(
            "test:ledger-reader",
            ObserveAction(action="observe", entity_id="ledger"),
            "sim:17",
        )
        await act(
            "test:intake-reader",
            ObserveAction(action="observe", entity_id="intake"),
            "sim:18",
        )
        await act(
            "test:survey-reader",
            ObserveAction(action="observe", entity_id="survey"),
            "sim:19",
        )
        await act(
            "test:terminologist",
            ObserveAction(action="observe", entity_id="glossary"),
            "sim:20",
        )
        await act(
            "test:auditor",
            ObserveAction(action="observe", entity_id="provenance"),
            "sim:21",
        )
        await act(
            "test:archivist",
            ObserveAction(action="observe", entity_id="margin"),
            "sim:22",
        )
        await act(
            "test:comparator",
            CompareRecordsAction(action="compare_records", record_a="ledger", record_b="intake"),
            "sim:23",
        )
        await act(
            "test:comparator",
            CompareRecordsAction(action="compare_records", record_a="intake", record_b="survey"),
            "sim:24",
        )
        await act(
            "test:classifier",
            ClassifyContradictionAction(
                action="classify_contradiction",
                record_a="intake",
                record_b="survey",
                classification="different_stages",
            ),
            "sim:25",
        )
        await act(
            "test:relay",
            RelayRecordAction(
                action="relay_record", record_id="ledger", summary="The ledger says sent 9."
            ),
            "sim:26",
        )
        await act(
            "test:editor",
            ProposeTranslationAction(
                action="propose_translation",
                record_a="ledger",
                record_b="intake",
                record_c="survey",
                classification="different_stages",
                mapping=(
                    "sent is source departure; delivered is boundary arrival; retained is the "
                    "later remainder"
                ),
                shared_summary="sent 9; delivered 9; retained 8 after one use interval",
                preserved_difference=(
                    "preserve the minority difference between delivery and later retention"
                ),
            ),
            "sim:27",
        )
        state = await repository.state(ref)
        translation_id = next(
            key
            for key, item in state["data"]["proposals"].items()
            if item.get("kind") == "translation"
        )
        await act(
            "test:auditor",
            ConfirmReconstructionAction(
                action="confirm_reconstruction", proposal_id=translation_id
            ),
            "sim:28",
        )
        completed = await repository.state(ref)
        if completed["current_position"] != 3:
            raise ValueError("Position 2 simulation did not advance exactly once")
        if completed["response_profile"] != registry.get(2).completion.response_profile:
            raise ValueError("Position 2 simulation did not apply its response profile")
        checks.append("isolated slash-only Position 2 translation simulation completes")

        if completed["data"].get("content_key") != "reciprocity":
            raise ValueError("Position 2 did not initialize Position 3 content atomically")
        position_three = registry.get(3)
        for index, observation_id in enumerate(
            position_three.provision_requirements.required_observations,
            start=29,  # type: ignore[union-attr]
        ):
            observation = next(
                item for item in position_three.observations if item.id == observation_id
            )
            await act(
                f"test:p3-observer-{index % 3}",
                ObserveAction(action="observe", entity_id=observation.entity_id),
                f"sim:{index}",
            )
        await act(
            "test:p3-auditor",
            AuditAction(
                action="audit",
                target_entity_id="provision_works",
                claim="works_benefit_claim",
                comparison="intake_exceeds_dry_limit",
            ),
            "sim:40",
        )
        await act(
            "test:p3-reducer",
            ReduceAction(
                action="reduce",
                target_entity_id="provision_works",
                measure="cap_unnecessary_throughput",
                amount=2,
            ),
            "sim:41",
        )
        await act(
            "test:p3-worker",
            MitigateAction(
                action="mitigate",
                target_entity_id="heat_court",
                risk="worker_heat",
                detail="public worker heat protection",
            ),
            "sim:42",
        )
        await act(
            "test:p3-custodian",
            ContainAction(
                action="contain",
                target_entity_id="white_rot_beds",
                destination_entity_id="spent_substrate_court",
                condition="isolate spent material in the public court",
            ),
            "sim:43",
        )
        await act(
            "test:p3-editor",
            ProposeReciprocityAction(
                action="propose_reciprocity",
                producer="provision_works",
                public_benefit="record verified local benefit without netting burden",
                local_burden="retain water, heat, labor, land, and maintenance burden",
                source_reduction_action="reduce and cap unnecessary throughput",
                material_disclosure="disclose every material record",
                maintenance_obligation="fund maintenance and replacement",
                containment_plan="contain spent substrate in public isolation",
                worker_protection="protect worker livelihoods and heat safety",
                shutdown_condition="public shutdown threshold and reassessment",
            ),
            "sim:44",
        )
        state = await repository.state(ref)
        reciprocity_id = next(
            key
            for key, item in state["data"]["proposals"].items()
            if item.get("kind") == "reciprocity"
        )
        await act(
            "test:p3-confirmer",
            ConfirmReconstructionAction(
                action="confirm_reconstruction", proposal_id=reciprocity_id
            ),
            "sim:45",
        )
        completed = await repository.state(ref)
        if completed["current_position"] != 4 or completed["data"].get("content_key") != (
            "maintenance"
        ):
            raise ValueError("Position 3 simulation did not initialize Position 4")
        checks.append("Position 3 separates public benefit, burden, and producer obligations")

        position_four = registry.get(4)
        ordered_first = ("production_exceeds_capacity", "characterized_return_class")
        for index, observation_id in enumerate(ordered_first, start=46):
            observation = next(
                item for item in position_four.observations if item.id == observation_id
            )
            await act(
                f"test:p4-cycle-{index}",
                InspectAction(action="inspect", target_entity_id=observation.entity_id),
                f"sim:{index}",
            )
        remaining = [
            item
            for item in position_four.provision_requirements.required_observations  # type: ignore[union-attr]
            if item not in ordered_first
        ]
        for index, observation_id in enumerate(remaining, start=48):
            observation = next(
                item for item in position_four.observations if item.id == observation_id
            )
            await act(
                f"test:p4-observer-{index % 4}",
                ObserveAction(action="observe", entity_id=observation.entity_id),
                f"sim:{index}",
            )
        await act(
            "test:p4-separator",
            SeparateAction(
                action="separate",
                source_entity_id="warm_return_channel",
                clean_target_entity_id="clear_return_channel",
                contaminated_target_entity_id="unknown_return_sump",
            ),
            "sim:64",
        )
        await act(
            "test:p4-maintainer",
            SustainAction(
                action="sustain",
                target_entity_id="white_rot_beds",
                condition="maintain_moisture_temperature_and_viability",
            ),
            "sim:65",
        )
        await act(
            "test:p4-archivist",
            DocumentAction(
                action="document",
                subject_entity_id="public_discharge_archive",
                record_type="treatment_failure",
                text="archive_preserves_failure",
            ),
            "sim:66",
        )
        await act(
            "test:p4-flow",
            SlowAction(
                action="slow",
                target_entity_id="warm_return_channel",
                condition="regulate_flow_and_contact_time",
            ),
            "sim:68",
        )
        await act(
            "test:p4-sampler",
            SampleAction(
                action="sample",
                source_entity_id="upstream_sample_port",
                comparison_entity_id="downstream_sample_port",
                measure="upstream_downstream_comparison",
            ),
            "sim:69",
        )
        sample_id = "upstream_sample_port:downstream_sample_port:upstream_downstream_comparison"
        await act(
            "test:p4-evidence",
            AuditAction(
                action="audit",
                target_entity_id="warm_return_channel",
                claim="visible_clarity_not_safety",
                comparison=sample_id,
            ),
            "sim:70",
        )
        await act(
            "test:p4-rest",
            RestAction(
                action="rest",
                target_entity_id="white_rot_beds",
                reassessment="reassess saturation before return to service",
            ),
            "sim:71",
        )
        await act(
            "test:p4-custodian",
            ContainAction(
                action="contain",
                target_entity_id="white_rot_beds",
                destination_entity_id="spent_substrate_court",
                condition="retain spent material under public custody",
            ),
            "sim:73",
        )
        await act(
            "test:p4-reducer",
            ReduceAction(
                action="reduce",
                target_entity_id="provision_works",
                measure="cap_unnecessary_throughput",
                amount=1,
            ),
            "sim:74",
        )
        await act(
            "test:p4-editor",
            ProposeRemediationProtocolAction(
                action="propose_remediation_protocol",
                source_discharge="warm_return_channel",
                contaminant_class="organic_dye_residue",
                production_reduction_action="reduce source throughput before treatment",
                treatment_bed="white_rot_beds",
                fungal_culture="archive_white_rot_culture",
                flow_rate_condition="regulate public contact time",
                moisture_condition="maintain documented viable moisture",
                monitoring_method="repeated upstream and downstream evidence",
                upstream_sample="upstream_sample_port",
                downstream_sample="downstream_sample_port",
                evidence_requirement="visible clarity is insufficient",
                saturation_limit=3,
                spent_substrate_destination="spent_substrate_court",
                maintenance_condition="named maintainers rest or replace the bed",
                shutdown_condition="shutdown when viability, saturation, or flow exceeds limits",
            ),
            "sim:75",
        )
        state = await repository.state(ref)
        remediation_id = next(
            key
            for key, item in state["data"]["proposals"].items()
            if item.get("kind") == "remediation_protocol"
        )
        await act(
            "test:p4-confirmer",
            ConfirmReconstructionAction(
                action="confirm_reconstruction", proposal_id=remediation_id
            ),
            "sim:76",
        )
        completed = await repository.state(ref)
        if completed["current_position"] != 5 or completed["data"].get("content_key") != "memory":
            raise ValueError("Position 4 simulation did not initialize Position 5")
        checks.append("Position 4 ordered remediation cycle completes with finite safeguards")

        position_five = registry.get(5)
        for index, observation_id in enumerate(
            position_five.provision_requirements.required_observations,
            start=77,  # type: ignore[union-attr]
        ):
            observation = next(
                item for item in position_five.observations if item.id == observation_id
            )
            await act(
                f"test:p5-reader-{index % 4}",
                ObserveAction(action="observe", entity_id=observation.entity_id),
                f"sim:{index}",
            )
        await act(
            "test:p5-inspector",
            InspectAction(action="inspect", target_entity_id="assurance_archive"),
            "sim:91",
        )
        await act(
            "test:p5-auditor",
            AuditAction(
                action="audit",
                target_entity_id="provision_works",
                claim="changed_shortage_definition",
                comparison="current_well_recovery_discrepancy",
            ),
            "sim:92",
        )
        await act(
            "test:p5-archivist-a",
            DocumentAction(
                action="document",
                subject_entity_id="assurance_archive",
                record_type="original_claim",
                text="original_limited_works_claim",
            ),
            "sim:93",
        )
        await act(
            "test:p5-archivist-b",
            DocumentAction(
                action="document",
                subject_entity_id="assurance_archive",
                record_type="later_revision",
                text="later_circulated_water_revision",
            ),
            "sim:94",
        )
        await act(
            "test:p5-custodian",
            ContainAction(
                action="contain",
                target_entity_id="white_rot_beds",
                destination_entity_id="spent_substrate_court",
                condition="preserve custody of accumulated substrate",
            ),
            "sim:95",
        )
        await act(
            "test:p5-editor",
            ProposeMemoryArchiveAction(
                action="propose_memory_archive",
                original_claim="original_limited_works_claim",
                later_revision="later_circulated_water_revision",
                physical_evidence="substrate_accumulation_evidence",
                affected_observation="affected_region_reentry_observation",
                uncertainty="unresolved contaminant scope remains explicit",
                correction="visible clarification did not establish safety",
                unresolved_conflict="the omitted failure and original assurance both remain",
                handling_requirement="contain spent substrate; never presume compost reuse",
            ),
            "sim:96",
        )
        state = await repository.state(ref)
        memory_id = next(
            key
            for key, item in state["data"]["proposals"].items()
            if item.get("kind") == "memory_archive"
        )
        await act(
            "test:p5-confirmer",
            ConfirmReconstructionAction(action="confirm_reconstruction", proposal_id=memory_id),
            "sim:97",
        )
        completed = await repository.state(ref)
        if completed["current_position"] != 6 or completed["data"].get("content_key") != (
            "reconstruction"
        ):
            raise ValueError("Position 5 simulation did not initialize Position 6")
        checks.append("Position 5 preserves versioned failed-treatment memory without erasure")

        position_six = registry.get(6)
        for index, observation in enumerate(position_six.observations, start=1):
            await act(
                f"test:p6-reader-{index % 4}",
                ObserveAction(action="observe", entity_id=observation.entity_id),
                f"sim:p6-observe:{index}",
            )
        await act(
            "test:p6-inspector",
            InspectAction(action="inspect", target_entity_id="provision_works"),
            "sim:115",
        )
        await act(
            "test:p6-sampler",
            SampleAction(
                action="sample",
                source_entity_id="production_intake_channel",
                comparison_entity_id="warm_return_channel",
                measure="usable_water_status",
            ),
            "sim:116",
        )
        p6_sample_id = "production_intake_channel:warm_return_channel:usable_water_status"
        await act(
            "test:p6-auditor",
            AuditAction(
                action="audit",
                target_entity_id="provision_works",
                claim="distant_surplus_control",
                comparison=p6_sample_id,
            ),
            "sim:117",
        )
        await act(
            "test:p6-separator",
            SeparateAction(
                action="separate",
                source_entity_id="warm_return_channel",
                clean_target_entity_id="treatment_yard",
                contaminated_target_entity_id="blackwater_berm",
            ),
            "sim:118",
        )
        await act(
            "test:p6-reducer",
            ReduceAction(
                action="reduce",
                target_entity_id="provision_works",
                measure="production_throughput",
                amount=2,
            ),
            "sim:119",
        )
        await act(
            "test:p6-designer",
            RedesignAction(
                action="redesign",
                target_entity_id="provision_works",
                change="durable_goods_standard",
                public_need="reconstruction_model_range",
            ),
            "sim:120",
        )
        await act(
            "test:p6-custodian",
            ContainAction(
                action="contain",
                target_entity_id="white_rot_beds",
                destination_entity_id="spent_substrate_court",
                condition="public spent-substrate custody",
            ),
            "sim:121",
        )
        await act(
            "test:p6-maintainer",
            SustainAction(
                action="sustain",
                target_entity_id="white_rot_beds",
                condition="monitor_viability",
            ),
            "sim:122",
        )
        await act(
            "test:p6-worker",
            MitigateAction(
                action="mitigate",
                target_entity_id="heat_court",
                risk="heat_exposure",
                detail="livelihood and heat transition",
            ),
            "sim:123",
        )
        await act(
            "test:p6-archivist",
            DocumentAction(
                action="document",
                subject_entity_id="public_memory_archive",
                record_type="reconstruction_covenant",
                text="historical_failure_preservation",
            ),
            "sim:124",
        )
        await act(
            "test:p6-editor",
            ProposeProductionReformAction(
                action="propose_production_reform",
                production_line="provision_works",
                current_output=10,
                revised_output=4,
                public_need_served="durable essential regional goods",
                water_cap=3,
                waste_reduction="end disposable output and reduce waste",
                worker_transition="worker livelihood and wage transition into repair work",
                ownership_or_governance="public community and worker accountability",
                remediation_obligation="source reduction before remediation expansion",
                clean_flow_plan="separate clean flow from contaminated flow",
                spent_substrate_plan="contain every spent substrate record",
                monitoring="public monitoring, samples, and evidence",
                maintenance="maintain and repair public infrastructure",
                historical_records="preserve the public archive and historical record",
                reassessment="seasonal reassessment and public review",
                shutdown_threshold="worker-controlled public shutdown threshold",
            ),
            "sim:125",
        )
        state = await repository.state(ref)
        reconstruction_id = next(
            key
            for key, item in state["data"]["proposals"].items()
            if item.get("kind") == "reconstruction"
        )
        await act(
            "test:p6-confirmer",
            ConfirmReconstructionAction(
                action="confirm_reconstruction", proposal_id=reconstruction_id
            ),
            "sim:126",
        )
        completed = await repository.state(ref)
        if completed["current_position"] != 6 or not completed["data"].get("position_completed"):
            raise ValueError("Position 6 simulation did not reach terminal reconstruction")
        terminal = await engine.process(
            ref,
            participant_id="test:late-action",
            action=ObserveAction(action="observe", entity_id="provision_works"),
            idempotency_key="sim:127",
        )
        if terminal.accepted:
            raise ValueError("Position 6 accepted mutation after terminal reconstruction")
        live_state = await repository.state(refs[Environment.LIVE])
        if live_state["current_position"] != 0:
            raise ValueError("test simulation leaked into the live environment")
        checks.append(
            "four-participant Position 6 reconstruction completes without test/live leakage"
        )
    finally:
        await database.dispose()
    return ContentValidationReport(True, tuple(checks))
