from __future__ import annotations

import copy
import hashlib
import math
import re
from dataclasses import replace
from typing import Any

from pydantic import ValidationError

from uniflora.content.schema import ObservationDefinition, PuzzleDefinition
from uniflora.engine.actions import (
    AddProposalKickerAction,
    AuditAction,
    BeginStackAction,
    CandidateAction,
    ConfirmReconstructionAction,
    ContainAction,
    DocumentAction,
    InoculateAction,
    InspectAction,
    MitigateAction,
    ObserveAction,
    OrientLocalAction,
    ProposeMemoryArchiveAction,
    ProposeProductionReformAction,
    ProposeReciprocityAction,
    ProposeRemediationProtocolAction,
    ReactToStackAction,
    RedesignAction,
    ReduceAction,
    RefuseAction,
    ReplaceAction,
    ResolveStackAction,
    RestAction,
    SampleAction,
    SeparateAction,
    SlowAction,
    SummarizeAction,
    SustainAction,
    UseTriggeredReactionAction,
)
from uniflora.engine.cycles import current_cycle_contributions
from uniflora.engine.public_ids import semantic_trigger_id
from uniflora.engine.validation import ValidationContext, ValidationDecision

ARC_PROPOSAL_TYPES = (
    ProposeReciprocityAction
    | ProposeRemediationProtocolAction
    | ProposeMemoryArchiveAction
    | ProposeProductionReformAction
)


class ProvisionArcValidator:
    """Shared deterministic rules for the playable Provision Works arc (Positions 3-6)."""

    _proposal_actions = {
        "reciprocity": ProposeReciprocityAction,
        "remediation_protocol": ProposeRemediationProtocolAction,
        "memory_archive": ProposeMemoryArchiveAction,
        "reconstruction": ProposeProductionReformAction,
    }
    _proposal_action_names = {
        "reciprocity": "propose_reciprocity",
        "remediation_protocol": "propose_remediation_protocol",
        "memory_archive": "propose_memory_archive",
        "reconstruction": "propose_production_reform",
    }

    def __init__(self, definition: PuzzleDefinition) -> None:
        if (
            definition.position not in {3, 4, 5, 6}
            or definition.provision_arc is None
            or definition.provision_requirements is None
        ):
            raise ValueError("ProvisionArcValidator requires complete Position 3-6 content")
        self.definition = definition
        self.arc = definition.provision_arc
        self.requirements = definition.provision_requirements
        self.aliases = definition.entity_aliases()
        self.entities = {item.id: item for item in definition.entities}
        self.observations = {item.id: item for item in definition.observations}
        self.observations_by_entity: dict[str, list[ObservationDefinition]] = {}
        for observation in definition.observations:
            self.observations_by_entity.setdefault(observation.entity_id, []).append(observation)
        self.contaminants = {item.id: item for item in self.arc.contaminant_classes}
        self.cultures = {item.id: item for item in self.arc.fungal_cultures}
        self.systems = {item.entity_id: item for item in self.arc.remediation_systems}
        self.compatibility = {
            (item.contaminant_class, item.culture_id): item for item in self.arc.compatibility_rules
        }

    def initialize_from_previous(self, previous: dict[str, Any]) -> dict[str, Any]:
        state = self.definition.initial_state()
        state["session_generation"] = int(previous.get("session_generation", 0))
        resources = copy.deepcopy(previous.get("resources", {}))
        for entity_id, values in state.get("resources", {}).items():
            resources[entity_id] = {
                **copy.deepcopy(resources.get(entity_id, {})),
                **copy.deepcopy(values),
            }
        state["resources"] = resources
        state["counters"] = self._transition_counters(
            state["counters"], previous.get("counters", {})
        )
        state["persistent_effects"] = list(dict.fromkeys(previous.get("persistent_effects", [])))
        state["settlement_scar"] = copy.deepcopy(previous.get("settlement_scar"))
        state["announced_position_introductions"] = list(
            previous.get("announced_position_introductions", [])
        )
        state["revealed_artifacts"] = list(previous.get("revealed_artifacts", []))
        state["artifact_reveal_deliveries"] = copy.deepcopy(
            previous.get("artifact_reveal_deliveries", {})
        )
        state["triggered_reactions"] = [
            copy.deepcopy(item)
            for item in previous.get("triggered_reactions", [])
            if not item.get("consumed", False)
        ]
        state["world_flags"] = {
            **copy.deepcopy(previous.get("world_flags", {})),
            **state["world_flags"],
        }
        for key in (
            "material_terms_ledger",
            "versioned_records",
            "samples",
            "separations",
            "inoculations",
            "containments",
            "reductions",
            "redesigns",
            "audits",
            "maintenance_protocol",
            "failed_treatments",
            "documented_records",
            "mitigations",
            "sustains",
            "beds_offline",
            "characterized_contaminants",
        ):
            state[key] = copy.deepcopy(previous.get(key, state.get(key, [])))
        state["prior_confirmed_facts"] = copy.deepcopy(previous.get("confirmed_facts", []))
        state["position_history"] = [
            *copy.deepcopy(previous.get("position_history", [])),
            {
                "position": self.definition.position - 1,
                "confirmed_facts": copy.deepcopy(previous.get("confirmed_facts", [])),
                "world_flags": copy.deepcopy(previous.get("world_flags", {})),
            },
        ]
        state["prior_position_summary"] = self._inherited_summary(previous)
        state["inherited_position"] = self.definition.position - 1
        return state

    def upgrade_existing_state(self, previous: dict[str, Any]) -> dict[str, Any]:
        state = copy.deepcopy(previous)
        fresh = self.definition.initial_state()
        state["content_key"] = self.definition.key
        state["content_version"] = self.definition.content_version
        for key, value in fresh.items():
            state.setdefault(key, copy.deepcopy(value))
        resources = copy.deepcopy(state.get("resources", {}))
        for entity_id, values in fresh.get("resources", {}).items():
            resources.setdefault(entity_id, copy.deepcopy(values))
        state["resources"] = resources
        state["counters"] = self._merged_counters(
            fresh.get("counters", {}), state.get("counters", {})
        )
        state["world_flags"] = {
            **copy.deepcopy(fresh.get("world_flags", {})),
            **copy.deepcopy(state.get("world_flags", {})),
        }
        return state

    def validate(self, action: CandidateAction, context: ValidationContext) -> ValidationDecision:
        if context.current_position != self.definition.position:
            return self._reject(
                "content_not_loaded", "No complete validator matches this position."
            )
        if context.state.get("position_completed"):
            return self._reject(
                "invalid_action", "The final reconstruction is complete and remains read-only."
            )
        if action.action not in self.definition.allowed_actions:
            return self._reject(
                "invalid_action", f"That action is unavailable in {self.definition.title}."
            )
        if isinstance(action, OrientLocalAction):
            return self._orient(context)
        if isinstance(action, ObserveAction):
            return self._observe(action.entity_id, context, "observe")
        if isinstance(action, InspectAction):
            return self._observe(action.target_entity_id, context, "inspect")
        if isinstance(action, SummarizeAction):
            return self._summarize(context)
        if isinstance(action, SampleAction):
            return self._sample(action, context)
        if isinstance(action, SeparateAction):
            return self._separate(action, context)
        if isinstance(action, InoculateAction):
            return self._inoculate(action, context)
        if isinstance(action, SlowAction):
            return self._slow(action, context)
        if isinstance(action, ContainAction):
            return self._contain(action, context)
        if isinstance(action, RestAction):
            return self._rest(action, context)
        if isinstance(action, ReplaceAction):
            return self._replace(action, context)
        if isinstance(action, RefuseAction):
            return self._refuse(action, context)
        if isinstance(action, ReduceAction):
            return self._reduce(action, context)
        if isinstance(action, RedesignAction):
            return self._redesign(action, context)
        if isinstance(action, DocumentAction):
            return self._document(action, context)
        if isinstance(action, AuditAction):
            return self._audit(action, context)
        if isinstance(action, SustainAction):
            return self._sustain(action, context)
        if isinstance(action, MitigateAction):
            return self._mitigate(action, context)
        if isinstance(
            action,
            (
                ProposeReciprocityAction,
                ProposeRemediationProtocolAction,
                ProposeMemoryArchiveAction,
                ProposeProductionReformAction,
            ),
        ):
            return self._propose(action, context)
        if isinstance(action, ConfirmReconstructionAction):
            return self._confirm(action, context)
        if isinstance(action, BeginStackAction):
            return self._begin_stack(action, context)
        if isinstance(action, ReactToStackAction):
            return self._react_to_stack(action, context)
        if isinstance(action, ResolveStackAction):
            return self._resolve_stack(action, context)
        if isinstance(action, AddProposalKickerAction):
            return self._add_kicker(action, context)
        if isinstance(action, UseTriggeredReactionAction):
            return self._use_trigger(action, context)
        return self._reject("invalid_action", "That action cannot alter this position.")

    def _orient(self, context: ValidationContext) -> ValidationDecision:
        orientation = self.definition.orientation
        assert orientation is not None
        return ValidationDecision(
            True,
            "local_orientation",
            public_data={
                "public_text": f"{orientation.local_response} {orientation.specificity_invitation}",
                "reveal_scope": "local_only",
            },
            next_state=copy.deepcopy(context.state),
            event_type="orientation.local",
            narration_key=self.definition.narration_keys["orient_local"],
        )

    def _observe(
        self, supplied_entity: str, context: ValidationContext, action_name: str
    ) -> ValidationDecision:
        entity_id = self._resolve_entity(supplied_entity)
        candidates = self.observations_by_entity.get(entity_id or "", [])
        if not entity_id or not candidates:
            return self._reject("invalid_action", "No public inspection matches that entity.")
        unlocked = set(context.state.get("unlocked_observations", []))
        available = [
            item for item in candidates if set(item.unlock.requires_observations).issubset(unlocked)
        ]
        if not available:
            return self._reject(
                "invalid_action", "An earlier public inspection is required at that entity."
            )
        observation = next((item for item in available if item.id not in unlocked), available[-1])
        is_new = observation.id not in unlocked
        cycle_step = self._observation_cycle_step(observation) if is_new else None
        if cycle_step:
            cycle_error = self._cycle_error(context.state, cycle_step)
            if cycle_error:
                return self._reject("invalid_action", cycle_error)
        state = copy.deepcopy(context.state)
        facts = list(state.get("confirmed_facts", []))
        public_text = self._observation_text(observation, state)
        if is_new:
            state["unlocked_observations"] = [
                *state.get("unlocked_observations", []),
                observation.id,
            ]
            fact: dict[str, Any] = {
                "observation_id": observation.id,
                "fact_key": observation.fact_key,
                "public_text": public_text,
            }
            fact["classification"] = observation.classification
            facts.append(fact)
            state["confirmed_facts"] = facts
            contaminant = self.entities[entity_id].measurements.get("contaminant_class")
            if isinstance(contaminant, str):
                characterized = dict(state.get("characterized_contaminants", {}))
                characterized[entity_id] = contaminant
                state["characterized_contaminants"] = characterized
            if cycle_step:
                self._advance_cycle(state, cycle_step)
        else:
            for fact in facts:
                if fact.get("observation_id") == observation.id:
                    fact["public_text"] = public_text
            state["confirmed_facts"] = facts
        function = observation.contribution_function if is_new else "corroboration"
        state, counted = self._record_action(
            state, context.participant_id, "inspect", observation.id, function
        )
        text = public_text
        if not is_new:
            text = f"Corroborated without creating a second discovery: {text}"
        return ValidationDecision(
            True,
            "observation_unlocked" if is_new else "observation_corroborated",
            public_data={"public_text": text, "observation_id": observation.id, "is_new": is_new},
            next_state=state,
            event_type="observation.unlocked" if is_new else "observation.corroborated",
            narration_key=self.definition.narration_keys[
                "observe_new" if is_new else "observe_repeat"
            ],
            contribution_function=function if counted else None,
            unlocked_observation_key=observation.id if is_new else None,
        )

    def _observation_text(
        self, observation: ObservationDefinition, state: dict[str, Any]
    ) -> str:
        """Render actionable public quantities from the current public state."""
        counters = state.get("counters", {})
        thresholds = self.arc.thresholds

        if observation.id == "intake_exceeds_dry_limit":
            measurements = self.entities[observation.entity_id].measurements
            draw = float(measurements["average_draw"])
            limit = float(measurements["dry_season_limit"])
            return (
                f"Production draw is {draw:g} water units against a dry-season maximum of "
                f"{limit:g}, an excess of {max(0.0, draw - limit):g}. Source reduction must "
                "remove at least that excess before the draw meets the published limit."
            )

        if observation.id == "production_exceeds_capacity":
            throughput = float(counters.get("throughput", 0))
            capacity = float(thresholds.maximum_throughput)
            return (
                f"Works throughput is {throughput:g} units against documented treatment "
                f"capacity of {capacity:g}, an excess of {max(0.0, throughput - capacity):g}. "
                "`/interior works reduce` must bring throughput to the capacity or below before "
                "remediation can be credited."
            )

        if observation.id == "bed_viability_stressed":
            viability = float(
                counters.get("viability", {}).get(observation.entity_id, 0)
            )
            minimum = float(thresholds.minimum_viability)
            shortfall = max(0.0, minimum - viability)
            return (
                f"Culture viability is {viability:g}; the public minimum is {minimum:g}, so the "
                f"current shortfall is {shortfall:g}. Maintenance must keep viability at "
                f"{minimum:g} or higher before another treatment load. `sustain` records that "
                "maintenance and does not add water or treatment capacity."
            )

        if observation.id == "bed_saturation_overloaded":
            saturation = float(
                counters.get("saturation", {}).get(observation.entity_id, 0)
            )
            limit = float(thresholds.saturation_limit)
            headroom = max(0.0, limit - saturation)
            return (
                f"Bed saturation is {saturation:g} against a limit of {limit:g}, leaving "
                f"{headroom:g} load of headroom. At {limit:g}, the bed must rest or be replaced; "
                "continued loading is not allowed."
            )

        if observation.id in {"upstream_requires_repetition", "downstream_requires_comparison"}:
            evidence = float(counters.get("evidence", 0))
            minimum = float(thresholds.minimum_evidence)
            shortfall = max(0.0, minimum - evidence)
            return (
                f"Public paired-sample evidence is {evidence:g}; at least {minimum:g} valid "
                f"evidence records are required, leaving a shortfall of {shortfall:g}. Use "
                "paired upstream and downstream sampling; color, odor, or clarity alone does "
                "not count."
            )

        if observation.id == "spent_substrate_needs_custody":
            containment = float(counters.get("containment", 0))
            minimum = float(thresholds.minimum_containment)
            shortfall = max(0.0, minimum - containment)
            return (
                f"Public containment is {containment:g}; at least {minimum:g} valid containment "
                f"records are required, leaving a shortfall of {shortfall:g}. Replaced substrate "
                "requires lined containment, a custody manifest, and no return to general "
                "circulation."
            )

        if observation.id == "unnecessary_output_quota":
            output = float(counters.get("throughput", 0))
            verified_need = float(
                self.entities[observation.entity_id].measurements[
                    "verified_public_need_output"
                ]
            )
            avoidable = max(0.0, output - verified_need)
            return (
                f"Current output is {output:g} public units while verified regional need "
                f"accounts for {verified_need:g}, leaving {avoidable:g} units not established as "
                "necessary. The reconstruction proposal must choose a revised output below "
                f"{output:g}; {verified_need:g} is the documented need, not an automatically "
                "imposed quota."
            )

        if observation.id == "production_water_competition":
            draw = float(counters.get("extraction", 0))
            well_id = self._role_entity("public_water_source", "shared_water_source")
            recovery = float(
                self.entities[well_id].measurements["current_recovery"] if well_id else 0
            )
            return (
                f"Production currently receives {draw:g} units of priority water draw while "
                f"Public Well Seven recovers {recovery:g}. A reconstruction water cap must be "
                f"lower than the current {draw:g}-unit draw; the assembly chooses the exact cap "
                "and must justify it from public recovery, essential use, heat, and verified "
                "reuse evidence."
            )

        if observation.id == "returned_water_use_limit":
            returned = float(
                self.entities[observation.entity_id].resources.get("returned_volume", 0)
            )
            return (
                f"{returned:g} units return, but elevated temperature and unresolved dissolved "
                f"residue mean 0 of those {returned:g} units are presently verified as usable "
                "public water. Returned volume cannot be added to the usable-water budget until "
                "public measurements establish eligibility."
            )

        if observation.id == "public_water_cap_basis":
            draw = float(counters.get("extraction", 0))
            return (
                f"The reconstruction water cap must be at least 0 and strictly below the current "
                f"{draw:g}-unit production draw. There is no single preselected cap: participants "
                "must justify their chosen value from current well recovery, essential use, "
                "forecast heat, and measured reuse eligibility."
            )

        return observation.public_text

    def _summarize(self, context: ValidationContext) -> ValidationDecision:
        facts = context.state.get("confirmed_facts", [])
        if not facts:
            return self._reject(
                "invalid_action", "There are no confirmed discoveries to summarize."
            )
        state, counted = self._record_action(
            context.state, context.participant_id, "summarize", "confirmed_facts", "documentation"
        )
        public_text = " ".join(str(item["public_text"]) for item in facts)
        state["summaries"] = [
            *state.get("summaries", []),
            {"participant_id": context.participant_id, "public_text": public_text},
        ]
        return self._accepted(
            state,
            public_text,
            "summary.recorded",
            "documentation" if counted else None,
        )

    def _sample(self, action: SampleAction, context: ValidationContext) -> ValidationDecision:
        source = self._resolve_entity(action.source_entity_id)
        comparison = self._resolve_entity(action.comparison_entity_id)
        if not source or not comparison or source == comparison:
            return self._reject("invalid_action", "Sampling requires two distinct public entities.")
        observed_entities = {
            self.observations[item].entity_id
            for item in context.state.get("unlocked_observations", [])
            if item in self.observations
        }
        if not {source, comparison}.issubset(observed_entities):
            return self._reject(
                "invalid_action", "Inspect both sampling points before comparing them."
            )
        cycle_error = self._cycle_error(context.state, "sample_upstream_and_downstream")
        if cycle_error:
            return self._reject("invalid_action", cycle_error)
        state = copy.deepcopy(context.state)
        measure = action.measure.strip().lower().replace(" ", "_")
        allowed_measures = {*self.arc.evidence_measures, *self.arc.visual_only_measures}
        if measure not in allowed_measures:
            return self._reject("invalid_action", "Use a configured public sampling measure.")
        visual_only = measure in self.arc.visual_only_measures
        sample_key = f"{source}:{comparison}:{measure}"
        samples = list(state.get("samples", []))
        if any(
            item.get("measure") == measure
            and {item.get("source"), item.get("comparison")} == {source, comparison}
            for item in samples
        ):
            return self._duplicate_action(
                state,
                "That sampling relation is already public; repeating it does not add evidence.",
                "evidence.sample_repeated",
            )
        samples.append(
            {
                "sample_key": sample_key,
                "source": source,
                "comparison": comparison,
                "measure": measure,
                "participant_id": context.participant_id,
                "visual_only": visual_only,
            }
        )
        state["samples"] = samples
        counters = copy.deepcopy(state.get("counters", {}))
        if not visual_only:
            counters["evidence"] = int(counters.get("evidence", 0)) + 1
        state["counters"] = counters
        self._advance_cycle(state, "sample_upstream_and_downstream")
        state, counted = self._record_action(
            state, context.participant_id, "sample", sample_key, "sampling"
        )
        self._add_effect(state, "Upstream and Downstream Sampled")
        if visual_only:
            text = "The color has diminished. Evidence of safety has not increased."
            self._append_trigger(
                state,
                kind="test_usability",
                source_participant_id=context.participant_id,
                subject=comparison,
            )
        else:
            text = (
                f"Public {measure.replace('_', ' ')} evidence now compares `{source}` with "
                f"`{comparison}`; evidence={counters.get('evidence', 0)}."
            )
        return self._accepted(state, text, "evidence.sampled", "sampling" if counted else None)

    def _separate(self, action: SeparateAction, context: ValidationContext) -> ValidationDecision:
        source = self._resolve_entity(action.source_entity_id)
        clean = self._resolve_entity(action.clean_target_entity_id)
        contaminated = self._resolve_entity(action.contaminated_target_entity_id)
        if not source or not clean or not contaminated or len({source, clean, contaminated}) != 3:
            return self._reject(
                "invalid_action", "Separation requires three distinct public flow entities."
            )
        source_roles = {
            self._role_entity(
                "warm_return_channel",
                "altered_return",
                "characterized_return",
                "returned_water",
            )
        }
        clean_targets = {
            self._role_entity("separated_clean_flow"),
        }
        if clean_targets == {None}:
            clean_targets = {self._role_entity("treatment_yard", "remediation_yard")}
        contaminated_targets = {
            self.arc.entity_roles.get(role)
            for role in (
                "treatment_yard",
                "remediation_yard",
                "unknown_return",
                "containment_berm",
            )
        } | set(self.systems)
        if (
            source not in source_roles
            or clean not in clean_targets
            or contaminated not in (contaminated_targets - {None})
        ):
            return self._reject(
                "invalid_action",
                "Use the configured returned-water, clean-route, and contaminated-route entities.",
            )
        if not self._entity_observed(source, context.state):
            return self._reject("invalid_action", "Inspect the source flow before separating it.")
        relation_key = f"{source}:{clean}:{contaminated}"
        if self._action_recorded(context.state, "separate", relation_key):
            return self._duplicate_action(
                context.state,
                "That flow separation is already recorded and does not add containment twice.",
                "flow.separation_repeated",
            )
        state = copy.deepcopy(context.state)
        separation = {
            "source": source,
            "clean_target": clean,
            "contaminated_target": contaminated,
            "participant_id": context.participant_id,
        }
        if separation not in state.get("separations", []):
            state["separations"] = [*state.get("separations", []), separation]
        counters = copy.deepcopy(state.get("counters", {}))
        counters["containment"] = int(counters.get("containment", 0)) + 1
        state["counters"] = counters
        self._add_effect(state, "Clean and Contaminated Flows Separated")
        state, counted = self._record_action(
            state,
            context.participant_id,
            "separate",
            relation_key,
            "containment",
        )
        return self._accepted(
            state,
            "Clean and contaminated flows now have separate public destinations.",
            "flow.separated",
            "containment" if counted else None,
        )

    def _inoculate(self, action: InoculateAction, context: ValidationContext) -> ValidationDecision:
        target = self._resolve_entity(action.target_entity_id)
        culture_id = self._resolve_culture(action.culture_id)
        if not target or not culture_id:
            return self._reject("invalid_action", "The treatment bed or culture is not public.")
        system = self.systems.get(target)
        substrate_id = action.substrate.strip().lower().replace(" ", "_").replace("-", "_")
        substrate = next(
            (
                item
                for item in self.arc.substrates
                if item.id == substrate_id
                or item.public_label.strip().lower() == action.substrate.strip().lower()
            ),
            None,
        )
        if system is None or substrate is None or target not in substrate.compatible_system_ids:
            return self._reject(
                "invalid_action", "Use a configured treatment system and compatible substrate ID."
            )
        state = copy.deepcopy(context.state)
        cycle_error = self._cycle_error(state, "maintain_or_inoculate_bed")
        if cycle_error:
            return self._reject("invalid_action", cycle_error)
        source = self._role_entity(
            "characterized_return",
            "warm_return_channel",
            "altered_return",
            "returned_water",
        )
        reported_contaminant = state.get("characterized_contaminants", {}).get(source or "")
        contaminant = (
            self._resolve_contaminant(str(reported_contaminant)) if reported_contaminant else None
        )
        attempt = {
            "source_entity_id": source,
            "reported_contaminant_class": reported_contaminant,
            "culture_id": culture_id,
            "substrate_id": substrate.id,
        }
        if not contaminant:
            return self._failed_treatment(
                state,
                context,
                target,
                "unknown_discharge",
                "Unknown or mixed discharge cannot enter biological treatment; "
                "characterization is now a public evidence deficit.",
                attempt=attempt,
            )
        if not self._culture_is_public(culture_id, target, state):
            return self._failed_treatment(
                state,
                context,
                target,
                "culture_not_public",
                "A configured culture is not an available public treatment culture until its "
                "provenance and compatibility record have been inspected.",
                attempt=attempt,
            )
        contaminant_definition = self.contaminants.get(contaminant)
        rule = self.compatibility.get((contaminant, culture_id))
        if (
            contaminant_definition is None
            or not contaminant_definition.biological_treatment_eligible
            or rule is None
            or not rule.compatible
            or contaminant not in system.contaminant_classes
            or culture_id not in system.culture_ids
        ):
            return self._failed_treatment(
                state,
                context,
                target,
                "incompatible_culture",
                "The culture is not compatible with the confirmed material class. "
                "The failed pairing remains public and no treatment claim is created.",
                attempt=attempt,
            )
        counters = copy.deepcopy(state.get("counters", {}))
        viability = int(counters.get("viability", {}).get(target, 0))
        saturation = int(counters.get("saturation", {}).get(target, 0))
        entity = self.entities[target]
        moisture_ok = bool(entity.measurements.get("moisture_suitable", False))
        temperature_ok = bool(entity.measurements.get("temperature_suitable", False))
        if viability < rule.minimum_viability or not moisture_ok or not temperature_ok:
            return self._failed_treatment(
                state,
                context,
                target,
                "low_viability",
                "The fungal bed exists but is not viable under the confirmed heat or moisture "
                "condition. Treatment does not proceed.",
                attempt=attempt,
            )
        if target in state.get("beds_offline", []):
            return self._failed_treatment(
                state,
                context,
                target,
                "bed_offline",
                "The bed remains publicly offline pending reassessment or replacement; "
                "treatment does not proceed.",
                attempt=attempt,
            )
        if saturation >= rule.maximum_saturation:
            return self._failed_treatment(
                state,
                context,
                target,
                "saturated_bed",
                "The bed is saturated. Continued loading would transfer the quota into "
                "instability; rest or replacement is required.",
                attempt=attempt,
            )
        if int(counters.get("throughput", 0)) > self.arc.thresholds.maximum_throughput:
            return self._failed_treatment(
                state,
                context,
                target,
                "throughput_overload",
                "Production throughput exceeds the bed's public limit and accelerates "
                "saturation; treatment does not proceed.",
                attempt=attempt,
            )
        if "Clean and Contaminated Flows Separated" not in state.get("persistent_effects", []):
            return self._failed_treatment(
                state,
                context,
                target,
                "containment_missing",
                "A compatible culture still requires separated flows and a public "
                "containment route.",
                attempt=attempt,
            )
        if int(counters.get("containment", 0)) < self.arc.thresholds.minimum_containment:
            return self._failed_treatment(
                state,
                context,
                target,
                "containment_missing",
                "The public containment counter is below the treatment minimum.",
                attempt=attempt,
            )
        if not any(
            item.get("target") == target
            and item.get("destination") in system.containment_destination_ids
            for item in state.get("containments", [])
        ):
            return self._failed_treatment(
                state,
                context,
                target,
                "containment_missing",
                "The selected treatment system has no public target-specific containment plan.",
                attempt=attempt,
            )
        if int(counters.get("source_reduction", 0)) < 1:
            return self._failed_treatment(
                state,
                context,
                target,
                "source_reduction_missing",
                "Compatible treatment cannot substitute for source reduction. The unmet "
                "producer obligation remains public and treatment does not proceed.",
                attempt=attempt,
            )
        inoculation_key = f"{target}:{culture_id}:{contaminant}:{saturation}"
        if self._action_recorded(state, "inoculate", inoculation_key):
            return self._duplicate_action(
                state,
                "That inoculation state is already recorded; it cannot be farmed for remediation.",
                "remediation.inoculation_repeated",
            )
        saturation_map = dict(counters.get("saturation", {}))
        saturation_map[target] = saturation + 1
        counters["saturation"] = saturation_map
        counters["remediation"] = int(counters.get("remediation", 0)) + 1
        state["counters"] = counters
        inoculation = {
            "target": target,
            "culture_id": culture_id,
            "contaminant_class": contaminant,
            "substrate": action.substrate,
            "participant_id": context.participant_id,
        }
        state["inoculations"] = [*state.get("inoculations", []), inoculation]
        self._advance_cycle(state, "maintain_or_inoculate_bed")
        self._add_effect(state, "White Rot Bed Stabilized")
        state, counted = self._record_action(
            state, context.participant_id, "inoculate", inoculation_key, "remediation"
        )
        return self._accepted(
            state,
            "The compatible bed remains alive. Its capacity does not expand with the quota.",
            "remediation.inoculated",
            "remediation" if counted else None,
        )

    def _slow(self, action: SlowAction, context: ValidationContext) -> ValidationDecision:
        target = self._resolve_entity(action.target_entity_id)
        if not target:
            return self._reject("invalid_action", "That public pathway is unknown.")
        if target != self._role_entity(
            "warm_return_channel",
            "altered_return",
            "characterized_return",
            "returned_water",
        ):
            return self._reject(
                "invalid_action", "Flow control applies to the configured returned-water route."
            )
        condition = action.condition.strip().lower().replace(" ", "_")
        if condition not in self.arc.maintenance_conditions:
            return self._reject("invalid_action", "Use a configured public flow condition.")
        if self._action_recorded(context.state, "slow", target):
            return self._duplicate_action(
                context.state,
                "That pathway is already slowed for this cycle.",
                "flow.slow_repeated",
            )
        cycle_error = self._cycle_error(context.state, "regulate_flow_and_contact_time")
        if cycle_error:
            return self._reject("invalid_action", cycle_error)
        state = copy.deepcopy(context.state)
        state["maintenance_protocol"] = [
            *state.get("maintenance_protocol", []),
            {"action": "slow", "target": target, "condition": action.condition},
        ]
        self._add_effect(state, "Contact Time Regulated")
        self._advance_cycle(state, "regulate_flow_and_contact_time")
        state, counted = self._record_action(
            state, context.participant_id, "slow", target, "maintenance"
        )
        return self._accepted(
            state,
            "Flow is conditionally slowed to preserve contact time; capacity remains bounded.",
            "flow.slowed",
            "maintenance" if counted else None,
        )

    def _contain(self, action: ContainAction, context: ValidationContext) -> ValidationDecision:
        target = self._resolve_entity(action.target_entity_id)
        destination = self._resolve_entity(action.destination_entity_id)
        if not target or not destination or target == destination:
            return self._reject(
                "invalid_action", "Containment requires a distinct public destination."
            )
        system = self.systems.get(target)
        if system is None or destination not in system.containment_destination_ids:
            return self._reject(
                "invalid_action",
                "Contain a configured treatment system only at its approved spent-material route.",
            )
        if not bool(self.entities[destination].measurements.get("containment_destination", False)):
            return self._reject(
                "invalid_action",
                "That destination is not approved for contaminated material.",
            )
        containment_key = f"{target}:{destination}"
        if self._action_recorded(context.state, "contain", containment_key):
            return self._duplicate_action(
                context.state,
                "That material route is already contained and cannot raise the counter twice.",
                "material.containment_repeated",
            )
        cycle_error = self._cycle_error(context.state, "contain_spent_material")
        if cycle_error:
            return self._reject("invalid_action", cycle_error)
        state = copy.deepcopy(context.state)
        state["containments"] = [
            *state.get("containments", []),
            {
                "target": target,
                "destination": destination,
                "condition": action.condition,
                "participant_id": context.participant_id,
            },
        ]
        counters = copy.deepcopy(state.get("counters", {}))
        counters["containment"] = int(counters.get("containment", 0)) + 1
        state["counters"] = counters
        self._add_effect(state, "Spent Substrate Contained")
        self._advance_cycle(state, "contain_spent_material")
        state, counted = self._record_action(
            state, context.participant_id, "contain", containment_key, "containment"
        )
        return self._accepted(
            state,
            "The substrate now carries what the channel no longer displays; it is isolated "
            "rather than reclassified as compost.",
            "material.contained",
            "containment" if counted else None,
        )

    def _rest(self, action: RestAction, context: ValidationContext) -> ValidationDecision:
        target = self._resolve_entity(action.target_entity_id)
        if not target or target not in self.systems:
            return self._reject("invalid_action", "That treatment system is unknown.")
        if self._action_recorded(context.state, "rest", target):
            return self._duplicate_action(
                context.state,
                "The bed is already offline for this maintenance cycle.",
                "remediation.rest_repeated",
            )
        cycle_error = self._cycle_error(context.state, "rest_or_replace_saturated_substrate")
        if cycle_error:
            return self._reject("invalid_action", cycle_error)
        state = copy.deepcopy(context.state)
        counters = copy.deepcopy(state.get("counters", {}))
        state["counters"] = counters
        offline = list(state.get("beds_offline", []))
        if target not in offline:
            offline.append(target)
        state["beds_offline"] = offline
        if "maintenance_cycle" in state:
            state["maintenance_cycle"]["bed_offline"] = True
        state["maintenance_protocol"] = [
            *state.get("maintenance_protocol", []),
            {"action": "rest", "target": target, "reassessment": action.reassessment},
        ]
        self._add_effect(state, "Treatment Bed Rested")
        self._advance_cycle(state, "rest_or_replace_saturated_substrate")
        state, counted = self._record_action(
            state, context.participant_id, "rest", target, "maintenance"
        )
        return self._accepted(
            state,
            "The overloaded bed is offline pending public reassessment; throughput does not "
            "inherit its capacity.",
            "remediation.rested",
            "maintenance" if counted else None,
        )

    def _replace(self, action: ReplaceAction, context: ValidationContext) -> ValidationDecision:
        target = self._resolve_entity(action.target_entity_id)
        destination = self._resolve_entity(action.destination_entity_id)
        system = self.systems.get(target or "")
        if not target or not destination or system is None:
            return self._reject("invalid_action", "The bed or containment destination is unknown.")
        if destination not in system.containment_destination_ids:
            return self._reject(
                "invalid_action", "Use the treatment system's configured containment destination."
            )
        if not bool(self.entities[destination].measurements.get("containment_destination", False)):
            return self._reject(
                "invalid_action", "Spent substrate requires a containment destination."
            )
        replacement_key = f"{target}:{destination}"
        if self._action_recorded(context.state, "replace", replacement_key):
            return self._duplicate_action(
                context.state,
                "That saturated substrate has already been replaced and contained.",
                "remediation.replacement_repeated",
            )
        cycle_error = self._cycle_error(context.state, "rest_or_replace_saturated_substrate")
        if cycle_error:
            return self._reject("invalid_action", cycle_error)
        state = copy.deepcopy(context.state)
        counters = copy.deepcopy(state.get("counters", {}))
        saturation = dict(counters.get("saturation", {}))
        viability = dict(counters.get("viability", {}))
        saturation[target] = 0
        viability[target] = max(
            self.arc.thresholds.minimum_viability, int(viability.get(target, 0))
        )
        counters["saturation"] = saturation
        counters["viability"] = viability
        counters["containment"] = int(counters.get("containment", 0)) + 1
        state["counters"] = counters
        state["containments"] = [
            *state.get("containments", []),
            {"target": target, "destination": destination, "replacement": action.replacement},
        ]
        self._add_effect(state, "Spent Substrate Contained")
        self._add_effect(state, "Treatment Substrate Replaced")
        state["beds_offline"] = [item for item in state.get("beds_offline", []) if item != target]
        self._advance_cycle(state, "rest_or_replace_saturated_substrate")
        state, counted = self._record_action(
            state, context.participant_id, "replace", replacement_key, "maintenance"
        )
        return self._accepted(
            state,
            "Saturated substrate is replaced and remains classified for containment, "
            "not automatic reuse.",
            "remediation.replaced",
            "maintenance" if counted else None,
        )

    def _refuse(self, action: RefuseAction, context: ValidationContext) -> ValidationDecision:
        target = self._resolve_entity(action.target_entity_id)
        if not target:
            return self._reject("invalid_action", "That production or discharge target is unknown.")
        allowed_targets = {
            self._role_entity("provision_works", "producer", "industrial_producer"),
            self._role_entity(
                "production_intake_channel", "production_intake", "production_intake"
            ),
            self._role_entity("warm_return_channel", "altered_return", "returned_water"),
        }
        if target not in allowed_targets:
            return self._reject("invalid_action", "Refusal applies to a public production flow.")
        public_bases = {
            *context.state.get("unlocked_observations", []),
            *(item.get("audit_id") for item in context.state.get("audits", [])),
            *(item.get("sample_key") for item in context.state.get("samples", [])),
        }
        if action.basis not in public_bases:
            return self._reject(
                "invalid_action",
                "The refusal basis must be a confirmed public observation, audit, or sample ID.",
            )
        evidence = int(context.state.get("counters", {}).get("evidence", 0))
        if evidence < self.arc.thresholds.minimum_evidence:
            return self._reject(
                "proposal_rejected",
                "Refusal requires enough public evidence to name the ecological limit.",
            )
        refusal_key = f"{target}:{action.basis}"
        if self._action_recorded(context.state, "refuse", refusal_key):
            return self._duplicate_action(
                context.state,
                "That evidenced refusal is already active.",
                "production.refusal_repeated",
            )
        state = copy.deepcopy(context.state)
        counters = copy.deepcopy(state.get("counters", {}))
        current_throughput = int(counters.get("throughput", 0))
        if current_throughput <= 0:
            return self._duplicate_action(
                context.state,
                "Production is already at zero throughput; another refusal cannot be farmed.",
                "production.refusal_repeated",
            )
        counters["source_reduction"] = int(counters.get("source_reduction", 0)) + 2
        counters["throughput"] = max(0, current_throughput - 2)
        state["counters"] = counters
        self._add_effect(state, "Worker-Controlled Shutdown Threshold")
        self._add_effect(state, "Throughput Reduced")
        state, counted = self._record_action(
            state, context.participant_id, "refuse", refusal_key, "source_reduction"
        )
        return self._accepted(
            state,
            "The evidenced limit is enforceable. Treatment capacity does not create "
            "permission to pollute.",
            "production.refused",
            "source_reduction" if counted else None,
        )

    def _reduce(self, action: ReduceAction, context: ValidationContext) -> ValidationDecision:
        target = self._resolve_entity(action.target_entity_id)
        if not target:
            return self._reject("invalid_action", "That production target is unknown.")
        if target not in {
            self._role_entity("provision_works", "producer", "industrial_producer"),
            self._role_entity("production_intake_channel", "production_intake"),
        }:
            return self._reject(
                "invalid_action", "Source reduction applies to production or its intake."
            )
        measure = action.measure.strip().lower().replace(" ", "_")
        if measure not in self.arc.reduction_measures:
            return self._reject("invalid_action", "Use a configured source-reduction measure.")
        if action.amount is None and not action.condition.strip():
            return self._reject("invalid_action", "Name a reduction amount or public condition.")
        if action.condition and action.condition not in context.state.get(
            "unlocked_observations", []
        ):
            return self._reject(
                "invalid_action", "A reduction condition must reference a confirmed observation ID."
            )
        cycle_error = self._cycle_error(context.state, "reassess_production_limits")
        if cycle_error:
            return self._reject("invalid_action", cycle_error)
        state = copy.deepcopy(context.state)
        counters = copy.deepcopy(state.get("counters", {}))
        decrement = max(1, math.ceil(action.amount or 1))
        throughput_before = int(counters.get("throughput", 0))
        extraction_before = int(counters.get("extraction", 0))
        throughput_after = max(0, throughput_before - decrement)
        extraction_after = max(0, extraction_before - decrement)
        if (throughput_after, extraction_after) == (throughput_before, extraction_before):
            return self._duplicate_action(
                context.state,
                "No remaining throughput or extraction changed; another wording cannot farm "
                "source reduction.",
                "production.reduction_repeated",
            )
        reduction_key = (
            f"{target}:{measure}:throughput:{throughput_before}->{throughput_after}:"
            f"extraction:{extraction_before}->{extraction_after}"
        )
        counters["source_reduction"] = int(counters.get("source_reduction", 0)) + 1
        counters["throughput"] = throughput_after
        counters["extraction"] = extraction_after
        counters["burden"] = max(0, int(counters.get("burden", 0)) - 1)
        state["counters"] = counters
        state["reductions"] = [
            *state.get("reductions", []),
            {
                "target": target,
                "measure": action.measure,
                "amount": action.amount,
                "condition": action.condition,
                "participant_id": context.participant_id,
            },
        ]
        self._add_effect(state, "Source Reduction Mandate")
        self._add_effect(state, "Throughput Reduced")
        self._add_effect(state, "Production Limits Reassessed")
        self._advance_cycle(state, "reassess_production_limits")
        self._append_trigger(
            state,
            kind="audit_capacity",
            source_participant_id=context.participant_id,
            subject=target,
        )
        state, counted = self._record_action(
            state, context.participant_id, "reduce", reduction_key, "source_reduction"
        )
        return self._accepted(
            state,
            "Avoidable throughput is reduced at its source before remediation capacity is counted.",
            "production.reduced",
            "source_reduction" if counted else None,
        )

    def _redesign(self, action: RedesignAction, context: ValidationContext) -> ValidationDecision:
        target = self._resolve_entity(action.target_entity_id)
        if not target:
            return self._reject("invalid_action", "That production target is unknown.")
        if target != self._role_entity("provision_works", "producer", "industrial_producer"):
            return self._reject(
                "invalid_action", "Production redesign applies to the configured producer."
            )
        change = action.change.strip().lower().replace(" ", "_")
        if change not in self.arc.redesign_changes:
            return self._reject(
                "proposal_rejected",
                "Use a configured durable, repairable, reuse, or essential-goods redesign.",
            )
        if action.public_need not in context.state.get("unlocked_observations", []):
            return self._reject(
                "proposal_rejected", "Public need must reference a confirmed observation ID."
            )
        redesign_key = f"{target}:{change}:{action.public_need}"
        if self._action_recorded(context.state, "redesign", redesign_key):
            return self._duplicate_action(
                context.state,
                "That production redesign is already public.",
                "production.redesign_repeated",
            )
        state = copy.deepcopy(context.state)
        state["redesigns"] = [
            *state.get("redesigns", []),
            {
                "target": target,
                "change": action.change,
                "public_need": action.public_need,
                "participant_id": context.participant_id,
            },
        ]
        counters = copy.deepcopy(state.get("counters", {}))
        counters["source_reduction"] = int(counters.get("source_reduction", 0)) + 1
        counters["public_benefit"] = int(counters.get("public_benefit", 0)) + 1
        state["counters"] = counters
        self._add_effect(state, "Repairable Goods Standard")
        state, counted = self._record_action(
            state, context.participant_id, "redesign", redesign_key, "redesign"
        )
        return self._accepted(
            state,
            "Production is now measured against durable public need rather than departure alone.",
            "production.redesigned",
            "redesign" if counted else None,
        )

    def _document(self, action: DocumentAction, context: ValidationContext) -> ValidationDecision:
        subject = self._resolve_entity(action.subject_entity_id)
        if not subject:
            return self._reject("invalid_action", "That record subject is unknown.")
        record_type = action.record_type.strip().lower().replace(" ", "_")
        if record_type not in self.arc.record_types:
            return self._reject("invalid_action", "Use a configured public archive record type.")
        public_references = {
            *context.state.get("unlocked_observations", []),
            *(item.get("failure_id") for item in context.state.get("failed_treatments", [])),
            *(item.get("record_id") for item in context.state.get("versioned_records", [])),
        }
        if action.text not in public_references:
            return self._reject(
                "invalid_action",
                "Documentation must reference an existing observation, failure, or record ID.",
            )
        document_key = f"{subject}:{record_type}:{action.text}"
        if self._action_recorded(context.state, "document", document_key):
            return self._duplicate_action(
                context.state,
                "That public record reference is already versioned.",
                "archive.document_repeated",
            )
        state = copy.deepcopy(context.state)
        records = list(state.get("versioned_records", []))
        version = 1 + sum(item.get("subject") == subject for item in records)
        record = {
            "record_id": f"record-{subject}-{version}",
            "subject": subject,
            "version": version,
            "record_type": record_type,
            "source_reference": action.text,
            "participant_id": context.participant_id,
            "preserves_prior_versions": True,
        }
        records.append(record)
        state["versioned_records"] = records
        state["documented_records"] = [*state.get("documented_records", []), record["record_id"]]
        if "failed" in record_type or "treatment" in record_type:
            self._add_effect(state, "Archive of Failed Treatments")
        if "claim" in record_type or "correction" in record_type:
            self._add_effect(state, "Versioned Public Record")
        counters = copy.deepcopy(state.get("counters", {}))
        counters["archival_coherence"] = int(counters.get("archival_coherence", 0)) + 1
        state["counters"] = counters
        state, counted = self._record_action(
            state, context.participant_id, "document", document_key, "documentation"
        )
        return self._accepted(
            state,
            f"Public record `{record['record_id']}` preserves this version without deleting "
            "earlier claims.",
            "archive.documented",
            "documentation" if counted else None,
        )

    def _audit(self, action: AuditAction, context: ValidationContext) -> ValidationDecision:
        target = self._resolve_entity(action.target_entity_id)
        if not target:
            return self._reject("invalid_action", "That audit target is unknown.")
        if not self._entity_observed(target, context.state):
            return self._reject("invalid_action", "Inspect the target before auditing its claim.")
        claim_refs = {
            *context.state.get("unlocked_observations", []),
            *(item.get("record_id") for item in context.state.get("versioned_records", [])),
        }
        comparison_refs = {
            *context.state.get("unlocked_observations", []),
            *(item.get("sample_key") for item in context.state.get("samples", [])),
        }
        if action.claim not in claim_refs or action.comparison not in comparison_refs:
            return self._reject(
                "invalid_action",
                "Audit fields must reference a public claim/record and observation/sample ID.",
            )
        cycle_error = self._cycle_error(context.state, "evaluate_evidence")
        if cycle_error:
            return self._reject("invalid_action", cycle_error)
        state = copy.deepcopy(context.state)
        audit_key = self._public_id("audit", target, action.claim, action.comparison)
        audits = list(state.get("audits", []))
        is_new = not any(item.get("audit_id") == audit_key for item in audits)
        if is_new:
            comparison_sample = next(
                (
                    item
                    for item in context.state.get("samples", [])
                    if item.get("sample_key") == action.comparison
                ),
                None,
            )
            supports_safety_evidence = not bool(
                comparison_sample and comparison_sample.get("visual_only", False)
            )
            audits.append(
                {
                    "audit_id": audit_key,
                    "target": target,
                    "claim": action.claim,
                    "comparison": action.comparison,
                    "participant_id": context.participant_id,
                    "supports_safety_evidence": supports_safety_evidence,
                }
            )
        state["audits"] = audits
        counters = copy.deepcopy(state.get("counters", {}))
        if is_new:
            if supports_safety_evidence:
                counters["evidence"] = int(counters.get("evidence", 0)) + 1
            counters["burden"] = int(counters.get("burden", 0)) + 1
            counters["extraction"] = int(counters.get("extraction", 0)) + 1
        state["counters"] = counters
        self._add_effect(state, "Public Discharge Ledger")
        self._advance_cycle(state, "evaluate_evidence")
        state, counted = self._record_action(
            state, context.participant_id, "audit", audit_key, "audit"
        )
        return self._accepted(
            state,
            "The Works' claim and the public physical measurement remain side by side; "
            "benefit does not erase burden.",
            "production.audited",
            "audit" if counted else None,
        )

    def _sustain(self, action: SustainAction, context: ValidationContext) -> ValidationDecision:
        target = self._resolve_entity(action.target_entity_id)
        if not target or target not in self.systems:
            return self._reject("invalid_action", "That maintenance target is unknown.")
        condition = action.condition.strip().lower().replace(" ", "_")
        if condition not in self.arc.maintenance_conditions:
            return self._reject(
                "invalid_action",
                "Use a configured monitoring, viability, or reassessment condition.",
            )
        sustain_key = f"{target}:{condition}"
        if self._action_recorded(context.state, "sustain", sustain_key):
            return self._duplicate_action(
                context.state,
                "That maintenance condition is already recorded for this target.",
                "maintenance.sustain_repeated",
            )
        cycle_error = self._cycle_error(context.state, "maintain_or_inoculate_bed")
        if cycle_error:
            return self._reject("invalid_action", cycle_error)
        state = copy.deepcopy(context.state)
        counters = copy.deepcopy(state.get("counters", {}))
        viability = dict(counters.get("viability", {}))
        viability[target] = int(viability.get(target, 0)) + 1
        counters["viability"] = viability
        maintenance = dict(counters.get("maintenance", {}))
        maintenance[target] = int(maintenance.get(target, 0)) + 1
        counters["maintenance"] = maintenance
        state["counters"] = counters
        if target in state.get("beds_offline", []):
            saturation = int(counters.get("saturation", {}).get(target, 0))
            if saturation >= self.arc.thresholds.saturation_limit:
                return self._reject(
                    "invalid_action",
                    "A saturated offline bed requires replacement before recommissioning.",
                )
            state["beds_offline"] = [
                item for item in state.get("beds_offline", []) if item != target
            ]
        state["maintenance_protocol"] = [
            *state.get("maintenance_protocol", []),
            {"action": "sustain", "target": target, "condition": action.condition},
        ]
        self._add_effect(state, "Maintained Remediation Cycle")
        self._advance_cycle(state, "maintain_or_inoculate_bed")
        state, counted = self._record_action(
            state, context.participant_id, "sustain", sustain_key, "maintenance"
        )
        return self._accepted(
            state,
            "Maintenance restores bounded viability; it does not authorize additional discharge.",
            "maintenance.sustained",
            "maintenance" if counted else None,
        )

    def _mitigate(self, action: MitigateAction, context: ValidationContext) -> ValidationDecision:
        target = self._resolve_entity(action.target_entity_id)
        if not target:
            return self._reject("invalid_action", "That protection target is unknown.")
        risk = action.risk.strip().lower().replace(" ", "_")
        if risk not in self.arc.mitigation_risks:
            return self._reject("invalid_action", "Use a configured public burden or risk ID.")
        mitigation_key = f"{target}:{risk}"
        if self._action_recorded(context.state, "mitigate", mitigation_key):
            return self._duplicate_action(
                context.state,
                "That burden protection is already active.",
                "burden.mitigation_repeated",
            )
        state = copy.deepcopy(context.state)
        counters = copy.deepcopy(state.get("counters", {}))
        counters["burden"] = max(0, int(counters.get("burden", 0)) - 1)
        state["counters"] = counters
        if risk in {
            "worker_burden",
            "labor_burden",
            "heat_exposure",
            "worker_heat",
            "maintainer_exposure",
            "culture_heat_stress",
            "livelihood_loss",
        }:
            self._add_effect(state, "Worker Protection")
        state["mitigations"] = [
            *state.get("mitigations", []),
            {
                "target": target,
                "risk": action.risk,
                "detail": action.detail,
                "participant_id": context.participant_id,
            },
        ]
        state, counted = self._record_action(
            state, context.participant_id, "mitigate", mitigation_key, "mitigation"
        )
        return self._accepted(
            state,
            "Worker, archive, and donor protections remain obligations rather than offsets.",
            "burden.mitigated",
            "mitigation" if counted else None,
        )

    def _propose(
        self,
        action: ProposeReciprocityAction
        | ProposeRemediationProtocolAction
        | ProposeMemoryArchiveAction
        | ProposeProductionReformAction,
        context: ValidationContext,
    ) -> ValidationDecision:
        expected_action = self._proposal_action_names[self.requirements.proposal_kind]
        if action.action != expected_action:
            return self._reject(
                "invalid_action",
                f"This position requires a {self.requirements.proposal_kind} proposal.",
            )
        missing_observations = set(self.requirements.required_observations) - set(
            context.state.get("unlocked_observations", [])
        )
        if missing_observations:
            return self._reject(
                "proposal_rejected",
                "Required public inspections remain incomplete: "
                + ", ".join(sorted(missing_observations)),
            )
        performed = {item.get("action") for item in context.state.get("arc_actions", [])}
        missing_actions = set(self.requirements.required_actions) - performed
        if missing_actions:
            return self._reject(
                "proposal_rejected",
                "Required public work remains incomplete: " + ", ".join(sorted(missing_actions)),
            )
        missing_action_groups = [
            group
            for group in self.requirements.required_action_groups
            if not set(group).intersection(performed)
        ]
        if missing_action_groups:
            choices = "; ".join(" or ".join(group) for group in missing_action_groups)
            return self._reject(
                "proposal_rejected",
                "Required public work still needs one action from each alternative: " + choices,
            )
        missing_effects = set(self.requirements.required_persistent_effects) - set(
            context.state.get("persistent_effects", [])
        )
        if missing_effects:
            return self._reject(
                "proposal_rejected",
                "The proposal depends on unresolved public safeguards: "
                + ", ".join(sorted(missing_effects)),
            )
        effects = set(context.state.get("persistent_effects", []))
        missing_effect_groups = [
            group
            for group in self.requirements.required_persistent_effect_groups
            if not set(group).intersection(effects)
        ]
        if missing_effect_groups:
            choices = "; ".join(" or ".join(group) for group in missing_effect_groups)
            return self._reject(
                "proposal_rejected",
                "The proposal still needs one safeguard from each alternative: " + choices,
            )
        payload = action.model_dump(mode="json", exclude={"action"})
        empty_fields = [
            field
            for field in self.requirements.required_proposal_fields
            if field not in payload
            or payload[field] is None
            or isinstance(payload[field], str)
            and not payload[field].strip()
        ]
        if empty_fields:
            return self._reject(
                "proposal_rejected",
                "Required proposal fields are empty: " + ", ".join(empty_fields),
            )
        specialized = self._validate_specialized_proposal(action, context)
        if specialized is not None:
            return specialized
        if not self._cycle_complete(context.state):
            return self._reject(
                "proposal_rejected", "Complete the ordered public maintenance cycle first."
            )
        contributions = current_cycle_contributions(context.state)
        participants = {str(item.get("participant_id")) for item in contributions} | {
            context.participant_id
        }
        functions = {str(item.get("function")) for item in contributions} | {
            self.requirements.proposal_kind
        }
        if len(participants) < self.requirements.minimum_distinct_users:
            return self._reject(
                "proposal_rejected",
                f"At least {self.requirements.minimum_distinct_users} distinct participants "
                "are required.",
            )
        if len(functions) < self.requirements.minimum_distinct_functions:
            return self._reject(
                "proposal_rejected",
                f"At least {self.requirements.minimum_distinct_functions} distinct "
                "contribution functions are required.",
            )
        state, counted = self._record_action(
            context.state,
            context.participant_id,
            action.action,
            self.requirements.proposal_kind,
            self.requirements.proposal_kind,
        )
        proposal_id = self._proposal_id(state.get("proposals", {}), context.session_id)
        proposal = {
            "proposal_id": proposal_id,
            "kind": self.requirements.proposal_kind,
            "author_participant_id": context.participant_id,
            "status": "pending",
            "kickers": [],
            **payload,
        }
        state["proposals"] = {**state.get("proposals", {}), proposal_id: proposal}
        public_text = self._proposal_public_text(proposal_id, state)
        return ValidationDecision(
            True,
            "proposal_accepted",
            public_data={"public_text": public_text, "proposal_id": proposal_id},
            next_state=state,
            event_type=f"{self.requirements.proposal_kind}.proposed",
            narration_key=self.definition.narration_keys["proposal_accepted"],
            contribution_function=self.requirements.proposal_kind if counted else None,
            proposal_projection={
                "id": proposal_id,
                "author_participant_id": context.participant_id,
                "status": "pending",
                "proposal_data": proposal,
            },
        )

    def _validate_specialized_proposal(
        self,
        action: ProposeReciprocityAction
        | ProposeRemediationProtocolAction
        | ProposeMemoryArchiveAction
        | ProposeProductionReformAction,
        context: ValidationContext,
    ) -> ValidationDecision | None:
        if isinstance(action, ProposeReciprocityAction):
            field_terms = (
                (action.source_reduction_action, ("reduce", "cap", "refuse")),
                (action.material_disclosure, ("disclose", "material", "record")),
                (action.maintenance_obligation, ("maintain", "fund", "replace")),
                (action.containment_plan, ("contain", "isolate", "spent")),
                (action.worker_protection, ("worker", "labor", "livelihood")),
                (
                    action.shutdown_condition,
                    ("shutdown", "stop", "threshold", "reassess"),
                ),
            )
            if not all(self._has_affirmative_term(value, terms) for value, terms in field_terms):
                return self._reject(
                    "proposal_rejected",
                    "Reciprocity must bind source reduction, disclosure, maintenance, "
                    "containment, worker protection, and a shutdown threshold.",
                )
            if int(context.state.get("counters", {}).get("source_reduction", 0)) < 1:
                return self._reject(
                    "proposal_rejected",
                    "Producer obligations must begin with public source reduction.",
                )
        elif isinstance(action, ProposeRemediationProtocolAction):
            contaminant = self._resolve_contaminant(action.contaminant_class)
            culture = self._resolve_culture(action.fungal_culture)
            bed = self._resolve_entity(action.treatment_bed)
            destination = self._resolve_entity(action.spent_substrate_destination)
            rule = self.compatibility.get((contaminant or "", culture or ""))
            system = self.systems.get(bed or "")
            if (
                contaminant is None
                or culture is None
                or bed is None
                or system is None
                or rule is None
                or not rule.compatible
                or contaminant not in system.contaminant_classes
                or culture not in system.culture_ids
            ):
                return self._reject(
                    "proposal_rejected",
                    "Unknown or incompatible treatment cannot become a protocol.",
                )
            if (
                not destination
                or destination not in system.containment_destination_ids
                or not bool(
                    self.entities[destination].measurements.get("containment_destination", False)
                )
            ):
                return self._reject(
                    "proposal_rejected",
                    "Spent substrate requires a valid public containment destination.",
                )
            counters = context.state.get("counters", {})
            if int(counters.get("source_reduction", 0)) < 1:
                return self._reject(
                    "proposal_rejected", "The protocol treats waste without reducing its source."
                )
            if int(counters.get("evidence", 0)) < rule.required_evidence:
                return self._reject(
                    "proposal_rejected",
                    "Visible clarification is not sufficient treatment evidence.",
                )
            if int(counters.get("viability", {}).get(bed, 0)) < rule.minimum_viability:
                return self._reject(
                    "proposal_rejected", "Low viability prevents a treatment claim."
                )
            if int(counters.get("saturation", {}).get(bed, 0)) >= action.saturation_limit:
                return self._reject(
                    "proposal_rejected", "The proposed saturation limit is already met."
                )
            if action.saturation_limit > self.arc.thresholds.saturation_limit:
                return self._reject(
                    "proposal_rejected",
                    "The protocol cannot raise the configured saturation limit.",
                )
            if not context.state.get("samples"):
                return self._reject(
                    "proposal_rejected", "Upstream and downstream public samples are required."
                )
            sample_entities = {
                value
                for item in context.state.get("samples", [])
                for value in (item.get("source"), item.get("comparison"))
            }
            upstream = self._resolve_entity(action.upstream_sample)
            downstream = self._resolve_entity(action.downstream_sample)
            relevant_samples = [
                item
                for item in context.state.get("samples", [])
                if not item.get("visual_only", False)
                and {item.get("source"), item.get("comparison")} == {upstream, downstream}
            ]
            if (
                upstream not in sample_entities
                or downstream not in sample_entities
                or not relevant_samples
            ):
                return self._reject(
                    "proposal_rejected",
                    "Protocol sample fields require a non-visual public comparison for the exact "
                    "upstream/downstream pair.",
                )
            if not self._has_affirmative_term(
                action.production_reduction_action, ("reduce", "cap", "refuse")
            ):
                return self._reject(
                    "proposal_rejected", "The protocol must name source reduction before treatment."
                )
        elif isinstance(action, ProposeMemoryArchiveAction):
            records = context.state.get("versioned_records", [])
            if len(records) < 2 or not all(
                item.get("preserves_prior_versions") for item in records
            ):
                return self._reject(
                    "proposal_rejected",
                    "The archive must preserve at least two versioned public records.",
                )
            public_refs = {
                *context.state.get("unlocked_observations", []),
                *(item.get("record_id") for item in records),
                *(item.get("failure_id") for item in context.state.get("failed_treatments", [])),
            }
            required_refs = {
                action.original_claim,
                action.later_revision,
                action.physical_evidence,
                action.affected_observation,
            }
            if not required_refs.issubset(public_refs):
                return self._reject(
                    "proposal_rejected",
                    "Archive claim, revision, evidence, and affected observation must use "
                    "public record IDs.",
                )
            if not self._has_affirmative_term(
                action.handling_requirement, ("substrate", "contain", "accumulat")
            ):
                return self._reject(
                    "proposal_rejected",
                    "The failed-treatment record must preserve substrate handling.",
                )
        elif isinstance(action, ProposeProductionReformAction):
            current_throughput = float(context.state.get("counters", {}).get("throughput", 0))
            if not math.isclose(action.current_output, current_throughput):
                return self._reject(
                    "proposal_rejected",
                    "Current output must match the confirmed public throughput counter.",
                )
            if action.revised_output >= action.current_output:
                return self._reject(
                    "proposal_rejected", "Final reconstruction must reduce unnecessary throughput."
                )
            producer_id = self._role_entity("provision_works", "producer", "industrial_producer")
            water_draw = float(
                self.entities[producer_id].measurements.get(
                    "current_water_draw",
                    self.entities[producer_id].measurements.get("water_draw", 0),
                )
                if producer_id
                else 0
            )
            if water_draw <= 0 or action.water_cap >= water_draw:
                return self._reject(
                    "proposal_rejected",
                    "The public water cap must reduce the confirmed current water draw.",
                )
            field_terms = (
                (action.worker_transition, ("livelihood", "transition", "wage")),
                (
                    action.ownership_or_governance,
                    ("public", "community", "worker", "accountab"),
                ),
                (
                    action.remediation_obligation,
                    ("source reduction", "reduce first", "after reduction"),
                ),
                (action.clean_flow_plan, ("separate", "clean flow", "contaminated flow")),
                (action.spent_substrate_plan, ("spent", "substrate", "contain")),
                (action.monitoring, ("monitor", "sample", "evidence")),
                (action.maintenance, ("maintain", "maintenance", "repair")),
                (action.historical_records, ("archive", "record", "history")),
                (action.reassessment, ("reassess", "seasonal", "review")),
                (action.shutdown_threshold, ("shutdown", "stop", "threshold")),
            )
            if not all(self._has_affirmative_term(value, terms) for value, terms in field_terms):
                return self._reject(
                    "proposal_rejected",
                    "Final reconstruction must preserve livelihoods, public governance, source "
                    "reduction, separated flows, spent-substrate handling, monitoring, "
                    "maintenance, memory, reassessment, and shutdown authority.",
                )
            if int(context.state.get("counters", {}).get("source_reduction", 0)) < 1:
                return self._reject(
                    "proposal_rejected",
                    "Remediation expansion cannot substitute for source reduction.",
                )
        return None

    def _confirm(
        self, action: ConfirmReconstructionAction, context: ValidationContext
    ) -> ValidationDecision:
        proposals = dict(context.state.get("proposals", {}))
        proposal = proposals.get(action.proposal_id)
        if (
            proposal is None
            or proposal.get("status") != "pending"
            or proposal.get("kind") != self.requirements.proposal_kind
        ):
            return self._reject("invalid_action", "No pending proposal matches that public ID.")
        author = str(proposal.get("author_participant_id"))
        if author == context.participant_id:
            return self._reject("invalid_action", "A non-author must confirm the proposal.")
        action_type = self._proposal_actions[self.requirements.proposal_kind]
        try:
            proposal_action = action_type.model_validate(
                {
                    "action": self._proposal_action_names[self.requirements.proposal_kind],
                    **{
                        key: value
                        for key, value in proposal.items()
                        if key
                        not in {
                            "proposal_id",
                            "kind",
                            "author_participant_id",
                            "status",
                            "kickers",
                        }
                    },
                }
            )
        except ValidationError:
            return self._reject("proposal_rejected", "The stored proposal is no longer valid.")
        revalidation = self._validate_specialized_proposal(proposal_action, context)
        if revalidation is not None:
            return self._reject(
                "proposal_rejected",
                "Conditions changed before confirmation: "
                + str(revalidation.public_data.get("feedback", "revalidation failed")),
            )
        state, counted = self._record_action(
            context.state,
            context.participant_id,
            "confirm_reconstruction",
            action.proposal_id,
            "confirmation",
        )
        updated = dict(proposal)
        updated["status"] = "confirmed"
        proposals[action.proposal_id] = updated
        state["proposals"] = proposals
        confirmation = {
            "proposal_id": action.proposal_id,
            "participant_id": context.participant_id,
        }
        state["confirmations"] = [*state.get("confirmations", []), confirmation]
        for effect in self.requirements.completion_effects:
            self._add_effect(state, effect)
        for kicker in updated.get("kickers", []):
            self._apply_kicker(state, str(kicker.get("kicker", "")))
        state["world_flags"] = {
            **state.get("world_flags", {}),
            **self.definition.completion.world_flags,
        }
        counters = copy.deepcopy(state.get("counters", {}))
        counters["coherence"] = int(counters.get("coherence", 0)) + 1
        state["counters"] = counters
        state["position_completed"] = True
        text = self._completion_public_text()
        return ValidationDecision(
            True,
            "position_completed",
            public_data={"public_text": text},
            next_state=state,
            event_type="position.completed",
            narration_key=self.definition.narration_keys["position_completed"],
            contribution_function="confirmation" if counted else None,
            position_completed=True,
            next_position=self.definition.completion.next_position,
            next_response_profile=self.definition.completion.response_profile,
            confirmation_projection=confirmation,
            proposal_status_update={"proposal_id": action.proposal_id, "status": "confirmed"},
            world_flag_projections=self.definition.completion.world_flags,
        )

    def _begin_stack(
        self, action: BeginStackAction, context: ValidationContext
    ) -> ValidationDecision:
        tactical = self.definition.tactical
        assert tactical is not None
        current = context.state.get("public_stack")
        if current and current.get("status") == "open":
            return self._reject("invalid_action", "A public response stack is already open.")
        proposal = dict(action.proposal)
        if proposal.get("kind") != self.requirements.proposal_kind:
            return self._reject(
                "invalid_action",
                f"Open a `{self.requirements.proposal_kind}` stack in this position.",
            )
        stack_id = self._public_id(
            "stack", self.requirements.proposal_kind, context.participant_id, context.action_id
        )
        state, counted = self._record_action(
            context.state, context.participant_id, "begin_stack", stack_id, "proposal"
        )
        state["public_stack"] = {
            "stack_id": stack_id,
            "status": "open",
            "author_participant_id": context.participant_id,
            "proposal": proposal,
            "entries": [
                {
                    "label": "base proposal",
                    "participant_id": context.participant_id,
                    "kind": "base",
                }
            ],
            "max_depth": tactical.max_stack_depth,
        }
        return self._accepted(
            state,
            f"Public stack `{stack_id}` is open with room for "
            f"{tactical.max_stack_depth - 1} reactions.",
            "stack.opened",
            "proposal" if counted else None,
        )

    def _react_to_stack(
        self, action: ReactToStackAction, context: ValidationContext
    ) -> ValidationDecision:
        tactical = self.definition.tactical
        assert tactical is not None
        stack = copy.deepcopy(context.state.get("public_stack"))
        if not stack or stack.get("status") != "open" or stack.get("stack_id") != action.stack_id:
            return self._reject("invalid_action", "No open public stack matches that ID.")
        if action.reaction not in tactical.allowed_stack_reactions:
            return self._reject("invalid_action", "That reaction is unavailable in this position.")
        entries = list(stack.get("entries", []))
        if len(entries) >= tactical.max_stack_depth:
            return self._reject("invalid_action", "The four-entry public stack is full.")
        if any(item.get("participant_id") == context.participant_id for item in entries):
            return self._reject("invalid_action", "Each participant may add only one stack entry.")
        public_bases = {
            *context.state.get("unlocked_observations", []),
            *(item.get("sample_key") for item in context.state.get("samples", [])),
            *(item.get("audit_id") for item in context.state.get("audits", [])),
            *context.state.get("persistent_effects", []),
        }
        if not action.detail or action.detail not in public_bases:
            return self._reject(
                "invalid_action",
                "Arc stack reactions must cite a public observation, sample, audit, or effect ID.",
            )
        semantic_subject = f"{action.reaction}:{action.detail}"
        state, counted = self._record_action(
            context.state,
            context.participant_id,
            "react_to_stack",
            semantic_subject,
            self._reaction_function(action.reaction),
        )
        entries.append(
            {
                "label": action.reaction.replace("_", " "),
                "reaction": action.reaction,
                "detail": action.detail,
                "participant_id": context.participant_id,
                "kind": "reaction",
                "applies_collective_change": counted,
            }
        )
        stack["entries"] = entries
        state["public_stack"] = stack
        return self._accepted(
            state,
            f"`{action.reaction}` enters the stack and will resolve before earlier entries.",
            "stack.reaction_added",
            self._reaction_function(action.reaction) if counted else None,
        )

    def _resolve_stack(
        self, action: ResolveStackAction, context: ValidationContext
    ) -> ValidationDecision:
        stack = copy.deepcopy(context.state.get("public_stack"))
        if not stack or stack.get("status") != "open" or stack.get("stack_id") != action.stack_id:
            return self._reject("invalid_action", "No open public stack matches that ID.")
        state = copy.deepcopy(context.state)
        entries = list(stack.get("entries", []))
        resolution_order: list[str] = []
        fundamental_objection = False
        for entry in reversed(entries[1:]):
            reaction = str(entry.get("reaction", ""))
            resolution_order.append(reaction)
            fundamental_objection = (
                self._apply_stack_reaction(
                    state,
                    reaction,
                    stack.get("proposal", {}),
                    apply_collective_change=bool(entry.get("applies_collective_change", True)),
                )
                or fundamental_objection
            )
        stack["status"] = "resolved"
        stack["resolution_order"] = resolution_order
        state["public_stack"] = stack
        if fundamental_objection:
            return self._failed_stack(
                state,
                context,
                "The stack exposed a fundamental compatibility or evidence failure. "
                "Safeguards cannot rescue an impossible treatment.",
            )
        proposal_payload = dict(stack.get("proposal", {}))
        proposal_payload.pop("kind", None)
        action_type = self._proposal_actions[self.requirements.proposal_kind]
        try:
            proposal_action = action_type.model_validate(
                {
                    "action": self._proposal_action_names[self.requirements.proposal_kind],
                    **proposal_payload,
                }
            )
        except ValidationError:
            return self._failed_stack(
                state,
                context,
                "The base proposal lacks required public fields; the failure remains "
                "available for revision.",
            )
        state, _ = self._record_action(
            state,
            context.participant_id,
            "resolve_stack",
            action.stack_id,
            "documentation",
        )
        temporary_context = ValidationContext(
            environment=context.environment,
            session_id=context.session_id,
            participant_id=str(stack.get("author_participant_id")),
            action_id=context.action_id,
            current_position=context.current_position,
            response_profile=context.response_profile,
            state=state,
        )
        decision = self._propose(proposal_action, temporary_context)
        if not decision.accepted or decision.next_state is None:
            return self._failed_stack(
                state,
                context,
                str(decision.public_data.get("feedback", "The base proposal remains incomplete.")),
            )
        final_state = decision.next_state
        final_stack = copy.deepcopy(final_state.get("public_stack", stack))
        final_stack["status"] = "resolved"
        final_stack["resolution_order"] = resolution_order
        final_state["public_stack"] = final_stack
        public_data = dict(decision.public_data)
        order = " -> ".join(resolution_order) if resolution_order else "base only"
        public_data["public_text"] = f"Stack resolved last-in-first-out ({order}). " + str(
            public_data.get("public_text", "")
        )
        return replace(
            decision,
            public_data=public_data,
            next_state=final_state,
            event_type="stack.resolved",
        )

    def _add_kicker(
        self, action: AddProposalKickerAction, context: ValidationContext
    ) -> ValidationDecision:
        tactical = self.definition.tactical
        assert tactical is not None
        proposals = copy.deepcopy(context.state.get("proposals", {}))
        proposal = proposals.get(action.proposal_id)
        if proposal is None or proposal.get("status") != "pending":
            return self._reject("invalid_action", "No pending proposal matches that ID.")
        if action.kicker not in tactical.allowed_kickers:
            return self._reject("invalid_action", "That kicker is unavailable in this position.")
        kickers = list(proposal.get("kickers", []))
        if proposal.get("author_participant_id") == context.participant_id:
            return self._reject("invalid_action", "A proposal author cannot add its safeguards.")
        if len(kickers) >= tactical.max_stack_depth - 1:
            return self._reject(
                "invalid_action", "The proposal already has the maximum safeguards."
            )
        if any(item.get("participant_id") == context.participant_id for item in kickers):
            return self._reject("invalid_action", "Each participant may add only one safeguard.")
        if any(item.get("kicker") == action.kicker for item in kickers):
            return self._reject("invalid_action", "That safeguard is already attached.")
        kickers.append(
            {
                "kicker": action.kicker,
                "detail": action.detail,
                "participant_id": context.participant_id,
            }
        )
        proposal["kickers"] = kickers
        proposals[action.proposal_id] = proposal
        state, counted = self._record_action(
            context.state,
            context.participant_id,
            "add_proposal_kicker",
            action.kicker,
            self._kicker_function(action.kicker),
        )
        state["proposals"] = proposals
        return ValidationDecision(
            True,
            "accepted",
            public_data={
                "public_text": (
                    f"Safeguard `{action.kicker}` is attached without replacing the base "
                    "requirements."
                )
            },
            next_state=state,
            event_type="proposal.kicker_added",
            narration_key=self.definition.narration_keys["action_accepted"],
            contribution_function=self._kicker_function(action.kicker) if counted else None,
            proposal_data_update={"proposal_id": action.proposal_id, "proposal_data": proposal},
        )

    def _use_trigger(
        self, action: UseTriggeredReactionAction, context: ValidationContext
    ) -> ValidationDecision:
        reactions = copy.deepcopy(context.state.get("triggered_reactions", []))
        trigger = next(
            (item for item in reactions if item.get("trigger_id") == action.trigger_id), None
        )
        if trigger is None or trigger.get("consumed"):
            return self._reject("invalid_action", "No unused public trigger matches that ID.")
        if trigger.get("source_participant_id") == context.participant_id:
            return self._reject("invalid_action", "Another participant must answer this trigger.")
        state = copy.deepcopy(context.state)
        for item in state.get("triggered_reactions", []):
            if item.get("trigger_id") == action.trigger_id:
                item["consumed"] = True
                item["consumed_by"] = context.participant_id
        kind = str(trigger.get("kind", "public_check"))
        if kind in {"test_usability", "audit_capacity", "audit_return"}:
            function = "audit"
            text = (
                "A second participant opens the public claim for an explicit audit; "
                "no evidence is granted until that audit is performed."
            )
        elif kind in {"characterize_discharge", "inspect_compatibility"}:
            function = "sampling"
            text = (
                "A second participant opens characterization as the next explicit sample; "
                "unknown compatibility remains unresolved."
            )
        elif kind in {"contain_failure", "replace_saturated_substrate"}:
            function = "containment"
            text = (
                "A second participant opens the failed material route for an explicit contain "
                "or replace action; containment has not yet increased."
            )
        else:
            function = "documentation"
            text = "The public trigger is answered once and remains in the durable record."
        state, counted = self._record_action(
            state, context.participant_id, "use_triggered_reaction", action.trigger_id, function
        )
        return self._accepted(state, text, "trigger.resolved", function if counted else None)

    def _failed_treatment(
        self,
        state: dict[str, Any],
        context: ValidationContext,
        target: str,
        failure: str,
        public_text: str,
        *,
        attempt: dict[str, Any] | None = None,
    ) -> ValidationDecision:
        failure_key = f"{target}:{failure}"
        if self._action_recorded(state, "failed_inoculate", failure_key):
            return self._duplicate_action(
                state,
                "That failed treatment condition is already public; repeating it adds no burden.",
                "remediation.failure_repeated",
            )
        counters = copy.deepcopy(state.get("counters", {}))
        counters["instability"] = int(counters.get("instability", 0)) + 1
        if failure in {"saturated_bed", "containment_missing"}:
            saturation = dict(counters.get("saturation", {}))
            saturation[target] = int(saturation.get(target, 0)) + 1
            counters["saturation"] = saturation
        state["counters"] = counters
        failure_id = self._public_id("failure", target, failure, context.action_id)
        state["failed_treatments"] = [
            *state.get("failed_treatments", []),
            {
                "failure_id": failure_id,
                "target": target,
                "failure": failure,
                "participant_id": context.participant_id,
                "public_text": public_text,
                "attempt": copy.deepcopy(attempt or {}),
                "counter_snapshot": {
                    "throughput": counters.get("throughput", 0),
                    "source_reduction": counters.get("source_reduction", 0),
                    "containment": counters.get("containment", 0),
                    "evidence": counters.get("evidence", 0),
                    "viability": counters.get("viability", {}).get(target, 0),
                    "saturation": counters.get("saturation", {}).get(target, 0),
                },
            },
        ]
        trigger_kind = {
            "unknown_discharge": "characterize_discharge",
            "incompatible_culture": "inspect_compatibility",
            "low_viability": "reassess_viability",
            "saturated_bed": "replace_saturated_substrate",
            "containment_missing": "contain_failure",
            "throughput_overload": "audit_capacity",
            "source_reduction_missing": "reduce_source",
            "culture_not_public": "inspect_compatibility",
            "bed_offline": "reassess_viability",
        }.get(failure, "archive_failure")
        self._append_trigger(
            state,
            kind=trigger_kind,
            source_participant_id=context.participant_id,
            subject=target,
        )
        state, counted = self._record_action(
            state,
            context.participant_id,
            "failed_inoculate",
            failure_key,
            "documentation",
        )
        return ValidationDecision(
            True,
            "treatment_failed_safely",
            public_data={"public_text": public_text, "failure_id": failure_id},
            next_state=state,
            event_type="remediation.failed",
            narration_key=self.definition.narration_keys.get(
                "treatment_failed", self.definition.narration_keys["action_accepted"]
            ),
            contribution_function="documentation" if counted else None,
        )

    def _failed_stack(
        self, state: dict[str, Any], context: ValidationContext, feedback: str
    ) -> ValidationDecision:
        stack = copy.deepcopy(state.get("public_stack", {}))
        stack["status"] = "failed"
        state["public_stack"] = stack
        counters = copy.deepcopy(state.get("counters", {}))
        counters["instability"] = int(counters.get("instability", 0)) + 1
        state["counters"] = counters
        self._append_trigger(
            state,
            kind="archive_failure",
            source_participant_id=context.participant_id,
            subject=str(stack.get("stack_id", "proposal")),
        )
        state, counted = self._record_action(
            state,
            context.participant_id,
            "resolve_stack_failure",
            str(stack.get("stack_id", "proposal")),
            "documentation",
        )
        return ValidationDecision(
            True,
            "proposal_incomplete",
            public_data={"public_text": feedback},
            next_state=state,
            event_type="stack.failed",
            narration_key=self.definition.narration_keys["proposal_rejected"],
            contribution_function="documentation" if counted else None,
        )

    def _apply_stack_reaction(
        self,
        state: dict[str, Any],
        reaction: str,
        proposal: dict[str, Any],
        *,
        apply_collective_change: bool,
    ) -> bool:
        counters = copy.deepcopy(state.get("counters", {}))
        fundamental = False
        if reaction == "object_evidence":
            fundamental = int(counters.get("evidence", 0)) < self.arc.thresholds.minimum_evidence
        elif reaction == "object_compatibility":
            contaminant = self._resolve_contaminant(str(proposal.get("contaminant_class", "")))
            culture = self._resolve_culture(str(proposal.get("fungal_culture", "")))
            rule = self.compatibility.get((contaminant or "", culture or ""))
            fundamental = rule is None or not rule.compatible
        elif not apply_collective_change:
            pass
        elif reaction == "reduce_source":
            self._add_effect(state, "Source Reduction Safeguard Attached")
        elif reaction == "slow_flow":
            self._add_effect(state, "Contact Time Safeguard Attached")
        elif reaction == "protect_workers":
            self._add_effect(state, "Worker Protection Safeguard Attached")
        elif reaction == "contain_substrate":
            self._add_effect(state, "Spent Substrate Plan Attached")
        elif reaction == "audit_return":
            self._add_effect(state, "Return Audit Requested")
        elif reaction == "cap_throughput":
            self._add_effect(state, "Production Water Cap Requested")
        elif reaction == "reassess_viability":
            self._add_effect(state, "Viability Reassessment Requested")
        elif reaction == "preserve_archive":
            self._add_effect(state, "Archive Preservation Safeguard Attached")
        state["counters"] = counters
        return fundamental

    def _apply_kicker(self, state: dict[str, Any], kicker: str) -> None:
        counters = copy.deepcopy(state.get("counters", {}))
        if kicker in {"upstream_sampling", "downstream_sampling"}:
            if state.get("samples"):
                self._add_effect(state, "Sampling Safeguard Attached")
        elif kicker == "source_reduction":
            if int(counters.get("source_reduction", 0)):
                self._add_effect(state, "Source Reduction Safeguard Attached")
        elif kicker == "worker_protection":
            self._add_effect(state, "Worker Protection")
        elif kicker == "spent_substrate_plan":
            if int(counters.get("containment", 0)):
                self._add_effect(state, "Spent Substrate Plan Attached")
        elif kicker == "public_disclosure":
            self._add_effect(state, "Public Discharge Ledger")
        elif kicker == "long_term_monitoring":
            self._add_effect(state, "Indicator Garden Established")
        elif kicker == "repairability_standard":
            self._add_effect(state, "Repairable Goods Standard")
        elif kicker == "seasonal_shutdown":
            self._add_effect(state, "Worker-Controlled Shutdown Threshold")
        elif kicker == "archive_failure":
            self._add_effect(state, "Archive of Failed Treatments")
        state["counters"] = counters

    def _proposal_public_text(self, proposal_id: str, state: dict[str, Any]) -> str:
        counters = state.get("counters", {})
        if self.requirements.proposal_kind == "reciprocity":
            return (
                f"Reciprocity proposal `{proposal_id}` records "
                f"benefit={counters.get('public_benefit', 0)} and "
                f"burden={counters.get('burden', 0)} separately; producer obligations await "
                "non-author confirmation."
            )
        if self.requirements.proposal_kind == "remediation_protocol":
            return (
                f"Remediation protocol `{proposal_id}` places reduction, compatibility, "
                "evidence, maintenance, containment, and shutdown in one public cycle."
            )
        if self.requirements.proposal_kind == "memory_archive":
            return (
                f"Memory proposal `{proposal_id}` preserves the original claim, revision, "
                "evidence, correction, and unresolved conflict as separate versions."
            )
        return (
            f"Reconstruction proposal `{proposal_id}` makes production answerable to need, "
            "ecological limits, public memory, and collective control."
        )

    def _completion_public_text(self) -> str:
        return {
            3: (
                "Position 3 complete. The objects leave intact; benefit and burden remain "
                "separately public, with producer obligations and worker protection enforceable."
            ),
            4: (
                "Position 4 complete. The living bed is a maintained boundary with limits, "
                "not a mouth beneath the Works."
            ),
            5: (
                "Position 5 complete. The archive preserves the treatment claim, its revision, "
                "the accumulated substrate, and the correction without erasure."
            ),
            6: (
                "Position 6 complete. Production is no longer confused with provision; refusal, "
                "reduction, containment, remediation, memory, livelihoods, and public authority "
                "remain joined."
            ),
        }[self.definition.position]

    @staticmethod
    def _reaction_function(reaction: str) -> str:
        return {
            "object_compatibility": "audit",
            "object_evidence": "audit",
            "reduce_source": "source_reduction",
            "slow_flow": "maintenance",
            "protect_workers": "mitigation",
            "contain_substrate": "containment",
            "audit_return": "audit",
            "cap_throughput": "source_reduction",
            "reassess_viability": "maintenance",
            "preserve_archive": "documentation",
        }.get(reaction, "documentation")

    @staticmethod
    def _has_affirmative_term(value: str, terms: tuple[str, ...]) -> bool:
        """Require a positive commitment, not a keyword appearing under nearby negation."""
        normalized = value.lower()
        negation = re.compile(
            r"(?:\bno\b|\bnot\b|\bnever\b|\bwithout\b|\bomit\b|\bexclude\b|"
            r"\bdo\s+not\b|\bdon't\b|\bcannot\b|\bcan't\b)"
            r"(?:\W+\w+){0,3}\W*$"
        )
        for term in terms:
            for match in re.finditer(re.escape(term.lower()), normalized):
                prefix = normalized[max(0, match.start() - 80) : match.start()]
                if not negation.search(prefix):
                    return True
        return False

    @staticmethod
    def _kicker_function(kicker: str) -> str:
        return {
            "upstream_sampling": "sampling",
            "downstream_sampling": "sampling",
            "source_reduction": "source_reduction",
            "worker_protection": "mitigation",
            "spent_substrate_plan": "containment",
            "public_disclosure": "audit",
            "long_term_monitoring": "maintenance",
            "repairability_standard": "redesign",
            "seasonal_shutdown": "source_reduction",
            "archive_failure": "documentation",
        }.get(kicker, "documentation")

    def _culture_is_public(self, culture_id: str, target: str, state: dict[str, Any]) -> bool:
        culture_entity = self._role_entity("culture_record", "culture_library")
        if culture_entity and self._entity_observed(culture_entity, state):
            return True
        for observation_id in state.get("unlocked_observations", []):
            observation = self.observations.get(observation_id)
            if observation is None or observation.entity_id != target:
                continue
            public_record = (
                f"{observation.id} {observation.fact_key} {observation.public_text}"
            ).lower()
            if "compatib" in public_record and culture_id in self.cultures:
                return True
        return False

    def _resolve_entity(self, value: str) -> str | None:
        normalized = value.strip().lower()
        return self.aliases.get(normalized)

    def _role_entity(self, *roles: str) -> str | None:
        return next(
            (self.arc.entity_roles[role] for role in roles if role in self.arc.entity_roles),
            None,
        )

    def _resolve_contaminant(self, value: str) -> str | None:
        normalized = value.strip().lower().replace("-", "_").replace(" ", "_")
        if normalized in self.contaminants:
            return normalized
        return next(
            (
                item.id
                for item in self.contaminants.values()
                if item.public_label.strip().lower() == value.strip().lower()
            ),
            None,
        )

    def _resolve_culture(self, value: str) -> str | None:
        normalized = value.strip().lower().replace("-", "_").replace(" ", "_")
        if normalized in self.cultures:
            return normalized
        return next(
            (
                item.id
                for item in self.cultures.values()
                if item.public_label.strip().lower() == value.strip().lower()
            ),
            None,
        )

    def _entity_observed(self, entity_id: str, state: dict[str, Any]) -> bool:
        unlocked = set(state.get("unlocked_observations", []))
        return any(item.id in unlocked for item in self.observations_by_entity.get(entity_id, []))

    def _cycle_error(self, state: dict[str, Any], step: str) -> str | None:
        steps = self.requirements.maintenance_cycle_steps
        if not steps:
            return None
        cycle = state.get("maintenance_cycle", {})
        stage = int(cycle.get("stage", 0))
        if stage >= len(steps):
            return "The public maintenance cycle is already complete."
        expected = steps[stage]
        if expected != step:
            return f"Maintenance cycle step {stage + 1} requires `{expected}` before `{step}`."
        return None

    def _cycle_complete(self, state: dict[str, Any]) -> bool:
        steps = self.requirements.maintenance_cycle_steps
        if not steps:
            return True
        cycle = state.get("maintenance_cycle", {})
        return int(cycle.get("stage", 0)) >= len(steps)

    def _observation_cycle_step(self, observation: ObservationDefinition) -> str | None:
        if not self.requirements.maintenance_cycle_steps:
            return None
        key = f"{observation.id} {observation.fact_key}".lower()
        if observation.id == "production_exceeds_capacity":
            return "inspect_discharge"
        if observation.id == "characterized_return_class":
            return "identify_contaminant_class"
        if observation.id == "culture_compatibility_limited":
            return "verify_fungal_compatibility"
        if "contaminant" in key and ("class" in key or "character" in key):
            return "identify_contaminant_class"
        if "discharge" in key or "runoff" in key:
            return "inspect_discharge"
        return None

    def _advance_cycle(self, state: dict[str, Any], step: str) -> None:
        if not self.requirements.maintenance_cycle_steps:
            return
        cycle = copy.deepcopy(state.get("maintenance_cycle", {}))
        completed = list(cycle.get("completed_steps", []))
        completed.append(step)
        cycle["completed_steps"] = completed
        cycle["stage"] = int(cycle.get("stage", 0)) + 1
        state["maintenance_cycle"] = cycle

    def _record_action(
        self,
        state: dict[str, Any],
        participant_id: str,
        action: str,
        subject: str,
        function: str,
    ) -> tuple[dict[str, Any], bool]:
        updated = copy.deepcopy(state)
        key = f"{action}:{subject}"
        actions = list(updated.get("arc_actions", []))
        if any(item.get("semantic_key") == key for item in actions):
            return updated, False
        actions.append(
            {
                "semantic_key": key,
                "participant_id": participant_id,
                "action": action,
                "subject": subject,
                "function": function,
            }
        )
        updated["arc_actions"] = actions
        updated["contributions"] = [
            *updated.get("contributions", []),
            {
                "participant_id": participant_id,
                "function": function,
                "action": action,
                "subject": subject,
            },
        ]
        return updated, True

    @staticmethod
    def _action_recorded(state: dict[str, Any], action: str, subject: str) -> bool:
        key = f"{action}:{subject}"
        return any(item.get("semantic_key") == key for item in state.get("arc_actions", []))

    def _duplicate_action(
        self, state: dict[str, Any], public_text: str, event_type: str
    ) -> ValidationDecision:
        return self._accepted(copy.deepcopy(state), public_text, event_type, None)

    def _append_trigger(
        self,
        state: dict[str, Any],
        *,
        kind: str,
        source_participant_id: str,
        subject: str,
    ) -> None:
        reactions = list(state.get("triggered_reactions", []))
        if any(
            item.get("kind") == kind
            and item.get("subject") == subject
            and not item.get("consumed", False)
            for item in reactions
        ):
            return
        trigger_id = semantic_trigger_id(reactions, kind, subject)
        reactions.append(
            {
                "trigger_id": trigger_id,
                "kind": kind,
                "subject": subject,
                "source_participant_id": source_participant_id,
                "consumed": False,
            }
        )
        state["triggered_reactions"] = reactions

    @staticmethod
    def _add_effect(state: dict[str, Any], effect: str) -> None:
        effects = list(state.get("persistent_effects", []))
        if effect not in effects:
            effects.append(effect)
        state["persistent_effects"] = effects

    def _proposal_id(self, proposals: dict[str, Any], session_id: str) -> str:
        prefix = {
            "reciprocity": "rec",
            "remediation_protocol": "rem",
            "memory_archive": "mem",
            "reconstruction": "recon",
        }[self.requirements.proposal_kind]
        scope = hashlib.sha256(session_id.encode()).hexdigest()[:8]
        number = 1
        while f"{prefix}-{scope}-{number}" in proposals:
            number += 1
        return f"{prefix}-{scope}-{number}"

    @staticmethod
    def _public_id(prefix: str, *parts: str) -> str:
        seed = ":".join(parts)
        return f"{prefix}-" + hashlib.sha256(seed.encode()).hexdigest()[:12]

    @staticmethod
    def _merged_counters(defaults: dict[str, Any], inherited: dict[str, Any]) -> dict[str, Any]:
        merged = copy.deepcopy(defaults)
        for key, value in inherited.items():
            if isinstance(value, dict) and isinstance(merged.get(key), dict):
                merged[key] = {**merged[key], **copy.deepcopy(value)}
            else:
                merged[key] = copy.deepcopy(value)
        return merged

    @staticmethod
    def _transition_counters(defaults: dict[str, Any], inherited: dict[str, Any]) -> dict[str, Any]:
        """Carry history forward without erasing the next position's configured baseline."""
        merged = copy.deepcopy(defaults)
        for key, value in inherited.items():
            if key not in merged:
                merged[key] = copy.deepcopy(value)
                continue
            default = merged[key]
            if isinstance(value, dict) and isinstance(default, dict):
                # Preserve counters for prior entities, while the new position owns the current
                # condition of any target it explicitly configures.
                merged[key] = {**copy.deepcopy(value), **copy.deepcopy(default)}
            elif (
                isinstance(value, (int, float))
                and not isinstance(value, bool)
                and isinstance(default, (int, float))
                and not isinstance(default, bool)
            ):
                # Scalar defaults are public baselines, not resets. Prior collective progress or
                # accumulated burden survives when it is already higher.
                merged[key] = max(default, value)
        return merged

    def _inherited_summary(self, previous: dict[str, Any]) -> str:
        effects = ", ".join(str(item) for item in previous.get("persistent_effects", []))
        return (
            f"Position {self.definition.position - 1} left public effects: {effects}."
            if effects
            else f"Position {self.definition.position - 1} remains in the public archive."
        )

    def _accepted(
        self,
        state: dict[str, Any],
        public_text: str,
        event_type: str,
        function: str | None,
    ) -> ValidationDecision:
        return ValidationDecision(
            True,
            "accepted",
            public_data={"public_text": public_text},
            next_state=state,
            event_type=event_type,
            narration_key=self.definition.narration_keys["action_accepted"],
            contribution_function=function,
        )

    def _reject(self, reason_key: str, feedback: str) -> ValidationDecision:
        return ValidationDecision(
            False,
            reason_key,
            public_data={"feedback": feedback},
            narration_key=(
                self.definition.narration_keys.get("proposal_rejected", "proposal_rejected")
                if reason_key == "proposal_rejected"
                else self.definition.narration_keys.get("invalid_action", "invalid_action")
            ),
        )
