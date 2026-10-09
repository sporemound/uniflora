from __future__ import annotations

import copy
import hashlib
import math
from typing import Any

from uniflora.content.schema import ObservationDefinition, PuzzleDefinition
from uniflora.engine.actions import (
    AddProposalKickerAction,
    BeginStackAction,
    BranchProposalAction,
    CalculateFlowAction,
    CandidateAction,
    ConfirmReconstructionAction,
    ConnectAction,
    MitigateAction,
    ObserveAction,
    OfferAction,
    OrientLocalAction,
    ProposeCirculationAction,
    ReactToStackAction,
    RelayAction,
    RequestSupportAction,
    ResolveStackAction,
    SummarizeAction,
    SustainAction,
    UseTriggeredReactionAction,
)
from uniflora.engine.cycles import current_cycle_contributions
from uniflora.engine.public_ids import semantic_trigger_aliases, semantic_trigger_id
from uniflora.engine.validation import ValidationContext, ValidationDecision

PRIOR_POSITION_TRIGGER_KINDS = {"inspect_capacity", "salvage_observation", "test_route"}


class PositionOneValidator:
    """Deterministic Circulation rules for Position 1."""

    def __init__(self, definition: PuzzleDefinition) -> None:
        if definition.position != 1 or definition.circulation is None:
            raise ValueError("PositionOneValidator requires complete Position 1 content")
        self.definition = definition
        self.constraints = definition.circulation
        self.aliases = definition.entity_aliases()
        self.entities = {entity.id: entity for entity in definition.entities}
        self.observations = {item.id: item for item in definition.observations}
        self.observations_by_entity: dict[str, list[ObservationDefinition]] = {}
        for observation in definition.observations:
            self.observations_by_entity.setdefault(observation.entity_id, []).append(observation)

    def initialize_from_previous(self, previous: dict[str, Any]) -> dict[str, Any]:
        state = self.definition.initial_state()
        state["session_generation"] = int(previous.get("session_generation", 0))
        previous_resources = previous.get("resources", {})
        for entity_id in ("northern_reservoir", "eastern_growth"):
            inherited = previous_resources.get(entity_id, {}).get(self.constraints.resource_id)
            if inherited is not None:
                state["resources"][entity_id][self.constraints.resource_id] = float(inherited)
        counters = copy.deepcopy(state["counters"])
        for key, value in previous.get("counters", {}).items():
            if isinstance(value, dict) and isinstance(counters.get(key), dict):
                counters[key] = {**counters[key], **copy.deepcopy(value)}
            else:
                counters[key] = copy.deepcopy(value)
        state["counters"] = counters
        state["counters"].setdefault("maintenance", {})
        state["persistent_effects"] = list(previous.get("persistent_effects", []))
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
            and str(item.get("kind", "")) not in PRIOR_POSITION_TRIGGER_KINDS
        ]
        state["world_flags"] = {
            **copy.deepcopy(previous.get("world_flags", {})),
            **state["world_flags"],
        }
        state["prior_confirmed_facts"] = copy.deepcopy(previous.get("confirmed_facts", []))
        state["position_history"] = [
            *copy.deepcopy(previous.get("position_history", [])),
            {
                "position": 0,
                "confirmed_facts": copy.deepcopy(previous.get("confirmed_facts", [])),
                "world_flags": copy.deepcopy(previous.get("world_flags", {})),
            },
        ]
        state["prior_position_summary"] = (
            "Position 0 preserved Eastern viability, Northern reserve, and repaired Route 03; "
            "the formerly separate regions now resolve as civic systems in one workers' settlement."
        )
        state["inherited_position"] = 0
        instability = int(state["counters"].get("instability", 0))
        state["forecast_branch"] = "accelerated" if instability else "stable"
        state["sustained_targets"] = []
        state["reassessed_pathways"] = []
        return state

    def upgrade_existing_state(self, previous: dict[str, Any]) -> dict[str, Any]:
        """Apply additive Position 1 content changes without erasing public progress."""

        state = copy.deepcopy(previous)
        fresh = self.definition.initial_state()
        state["content_key"] = self.definition.key
        state["content_version"] = self.definition.content_version
        resources = copy.deepcopy(state.get("resources", {}))
        for entity_id, values in fresh["resources"].items():
            resources.setdefault(entity_id, copy.deepcopy(values))
        state["resources"] = resources
        managed = {"content_key", "content_version", "resources", "counters", "world_flags"}
        for key, value in fresh.items():
            if key not in managed:
                state.setdefault(key, copy.deepcopy(value))
        state.setdefault("sustained_targets", [])
        state.setdefault("reassessed_pathways", [])
        state.setdefault("forecast_branch", "stable")
        state["triggered_reactions"] = [
            copy.deepcopy(item)
            for item in state.get("triggered_reactions", [])
            if str(item.get("kind", "")) not in PRIOR_POSITION_TRIGGER_KINDS
        ]
        state["world_flags"] = {
            **copy.deepcopy(fresh["world_flags"]),
            **copy.deepcopy(state.get("world_flags", {})),
        }
        counters = copy.deepcopy(state.get("counters", {}))
        for key, value in fresh["counters"].items():
            counters.setdefault(key, copy.deepcopy(value))
        state["counters"] = counters
        return state

    def validate(self, action: CandidateAction, context: ValidationContext) -> ValidationDecision:
        if context.current_position != 1:
            return self._reject(
                "content_not_loaded", "No complete validator matches this position."
            )
        if action.action not in self.definition.allowed_actions:
            return self._reject("invalid_action", "That action is unavailable in Circulation.")
        if isinstance(action, OrientLocalAction):
            return self._orient(context)
        if isinstance(action, ObserveAction):
            return self._observe(action, context)
        if isinstance(action, ConnectAction):
            return self._connect(action, context)
        if isinstance(action, OfferAction):
            return self._offer(action, context)
        if isinstance(action, RequestSupportAction):
            return self._request_support(action, context)
        if isinstance(action, SummarizeAction):
            return self._summarize(action, context)
        if isinstance(action, SustainAction):
            return self._sustain(action, context)
        if isinstance(action, RelayAction):
            return self._relay(action, context)
        if isinstance(action, MitigateAction):
            return self._mitigate(action, context)
        if isinstance(action, CalculateFlowAction):
            return self._calculate(action, context)
        if isinstance(action, ProposeCirculationAction):
            return self._propose(action, context)
        if isinstance(action, BranchProposalAction):
            return self._branch(action, context)
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
        return self._reject("invalid_action", "That action cannot alter Circulation yet.")

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

    def _observe(self, action: ObserveAction, context: ValidationContext) -> ValidationDecision:
        entity_id = self._resolve(action.entity_id)
        candidates = self.observations_by_entity.get(entity_id or "", [])
        if not candidates:
            return self._reject("invalid_action", "No public observation matches that entity.")
        unlocked = set(context.state.get("unlocked_observations", []))
        observation = next(
            (
                item
                for item in candidates
                if item.id not in unlocked
                and set(item.unlock.requires_observations).issubset(unlocked)
            ),
            None,
        )
        is_new = observation is not None
        if observation is None:
            observation = next((item for item in reversed(candidates) if item.id in unlocked), None)
            if observation is None:
                return self._reject(
                    "invalid_action", "An earlier public observation is required here."
                )
        public_text = self._observation_text(observation.id, context.state)
        state = (
            self._contribute(
                context.state, context.participant_id, observation.contribution_function, "observe"
            )
            if is_new
            else copy.deepcopy(context.state)
        )
        if is_new:
            state["unlocked_observations"] = [
                *state.get("unlocked_observations", []),
                observation.id,
            ]
            state["confirmed_facts"] = [
                *state.get("confirmed_facts", []),
                {
                    "observation_id": observation.id,
                    "fact_key": observation.fact_key,
                    "public_text": public_text,
                    "classification": self._fact_classification(observation.id),
                },
            ]
            if observation.id == "nursery_projected_need":
                self._append_trigger(
                    state,
                    context,
                    kind="inspect_capacity",
                    source_participant_id=context.participant_id,
                    observation_id="condensation_shared_output",
                )
        else:
            facts = list(state.get("confirmed_facts", []))
            for fact in facts:
                if fact.get("observation_id") == observation.id:
                    fact["public_text"] = public_text
            state["confirmed_facts"] = facts
        return ValidationDecision(
            True,
            "observation_unlocked" if is_new else "observation_corroborated",
            public_data={
                "public_text": public_text,
                "observation_id": observation.id,
                "is_new": is_new,
            },
            next_state=state,
            event_type="observation.unlocked" if is_new else "observation.corroborated",
            narration_key=self.definition.narration_keys[
                "observe_new" if is_new else "observe_repeat"
            ],
            contribution_function=observation.contribution_function if is_new else None,
            unlocked_observation_key=observation.id if is_new else None,
        )

    def _connect(self, action: ConnectAction, context: ValidationContext) -> ValidationDecision:
        source = self._resolve(action.source_entity_id)
        target = self._resolve(action.target_entity_id)
        allowed_pairs = {
            frozenset((self.constraints.source_entity_id, self.constraints.source_pathway_id)),
            frozenset((self.constraints.source_pathway_id, self.constraints.relay_entity_id)),
            frozenset((self.constraints.relay_entity_id, self.constraints.recipient_entity_id)),
        }
        if source is None or target is None or frozenset((source, target)) not in allowed_pairs:
            return self._reject("invalid_action", "That circulation relation is not public.")
        observed_entities = {
            self.observations[item].entity_id
            for item in context.state.get("unlocked_observations", [])
            if item in self.observations
        }
        if not {source, target}.issubset(observed_entities):
            return self._reject(
                "invalid_action", "Both sides must be publicly inspected before correlation."
            )
        state = self._contribute(context.state, context.participant_id, "connector", "connect")
        relation = {
            "source": source,
            "target": target,
            "participant_id": context.participant_id,
        }
        state["connections"] = [*state.get("connections", []), relation]
        return self._accepted(
            state,
            "A confirmed circulation relation is added to the public record.",
            "circulation.relation_recorded",
            "connector",
            target,
            "circulation_correlation",
        )

    def _offer(self, action: OfferAction, context: ValidationContext) -> ValidationDecision:
        target = self._resolve(action.target_entity_id or "")
        if action.resource_id.lower() != self.constraints.resource_id or target != (
            self.constraints.recipient_entity_id
        ):
            return self._reject("invalid_action", "That offer does not match the confirmed need.")
        if "nursery_projected_need" not in context.state.get("unlocked_observations", []):
            return self._reject("invalid_action", "The Nursery need must be public first.")
        state = self._contribute(context.state, context.participant_id, "carrier", "offer")
        state["offers"] = [
            *state.get("offers", []),
            {
                "recipient_id": target,
                "resource_id": self.constraints.resource_id,
                "amount": action.amount,
                "participant_id": context.participant_id,
            },
        ]
        return self._accepted(
            state,
            "A circulation offer is recorded; source and delivered quantities remain distinct.",
            "circulation.offer_recorded",
            "carrier",
            target,
            "resource_offer",
        )

    def _request_support(
        self, action: RequestSupportAction, context: ValidationContext
    ) -> ValidationDecision:
        accepted = {"nursery_projected_need", "pale_nursery", "nursery", "pale"}
        if action.need_id.lower() not in accepted or "nursery_projected_need" not in (
            context.state.get("unlocked_observations", [])
        ):
            return self._reject("invalid_action", "That need is not in the confirmed record.")
        state = self._contribute(
            context.state, context.participant_id, "need_advocate", "request_support"
        )
        state["support_requests"] = [
            *state.get("support_requests", []),
            {
                "need_id": "nursery_projected_need",
                "amount": action.amount,
                "participant_id": context.participant_id,
            },
        ]
        return self._accepted(
            state,
            "Pale Nursery's projected need is named publicly.",
            "circulation.support_requested",
            "need_advocate",
        )

    def _summarize(self, action: SummarizeAction, context: ValidationContext) -> ValidationDecision:
        facts = list(context.state.get("confirmed_facts", []))
        if action.focus:
            focus = action.focus.casefold()
            facts = [
                item
                for item in facts
                if focus in str(item.get("public_text", "")).casefold()
                or focus in str(item.get("fact_key", "")).casefold()
            ]
        if not facts:
            return self._reject("invalid_action", "No matching confirmed discoveries exist.")
        public_text = " ".join(str(item["public_text"]) for item in facts)
        state = self._contribute(context.state, context.participant_id, "archivist", "summarize")
        state["summaries"] = [
            *state.get("summaries", []),
            {"public_text": public_text, "participant_id": context.participant_id},
        ]
        return ValidationDecision(
            True,
            "accepted",
            public_data={"public_text": public_text},
            next_state=state,
            event_type="summary.recorded",
            narration_key=self.definition.narration_keys["action_accepted"],
            contribution_function="archivist",
            summary_projection={"summary_kind": "confirmed_public", "public_text": public_text},
        )

    def _sustain(self, action: SustainAction, context: ValidationContext) -> ValidationDecision:
        target = self._resolve(action.target_entity_id)
        if target is None:
            return self._reject("invalid_action", "No public entity matches that target.")
        if not self._contains(action.condition, self.constraints.maintenance_terms) and not (
            target == self.constraints.source_pathway_id
            and self._contains(action.condition, self.constraints.reassessment_terms)
        ):
            return self._reject(
                "invalid_action", "Sustain must name maintenance, monitoring, or reassessment."
            )
        unlocked = set(context.state.get("unlocked_observations", []))
        if target == self.constraints.source_entity_id and not {
            "condensation_shared_output",
            "veil_requires_maintenance",
        }.issubset(unlocked):
            return self._reject("invalid_action", "Inspect both Veil output and condition first.")
        if target == self.constraints.source_pathway_id and "route_07_loss" not in unlocked:
            return self._reject("invalid_action", "Route 07 loss must be public first.")
        state = self._contribute(context.state, context.participant_id, "maintainer", "sustain")
        state["sustains"] = [
            *state.get("sustains", []),
            {
                "target": target,
                "condition": action.condition.strip(),
                "participant_id": context.participant_id,
            },
        ]
        sustained = list(state.get("sustained_targets", []))
        if target not in sustained:
            sustained.append(target)
        state["sustained_targets"] = sustained
        counters = copy.deepcopy(state.get("counters", {}))
        maintenance = dict(counters.get("maintenance", {}))
        maintenance[target] = int(maintenance.get(target, 0)) + 1
        counters["maintenance"] = maintenance
        state["counters"] = counters
        if target == self.constraints.source_entity_id:
            self._append_trigger(
                state,
                context,
                kind="test_route_07",
                source_participant_id=context.participant_id,
                pathway_id=self.constraints.source_pathway_id,
            )
            text = "The Condensation Veil is sustained; its current-cycle output is available."
        elif target == self.constraints.source_pathway_id:
            reassessed = list(state.get("reassessed_pathways", []))
            if target not in reassessed:
                reassessed.append(target)
            state["reassessed_pathways"] = reassessed
            repair = dict(counters.get("repair", {}))
            repair[target] = int(repair.get(target, 0)) + 1
            counters["repair"] = repair
            state["counters"] = counters
            self._append_trigger(
                state,
                context,
                kind="calculate_flow",
                source_participant_id=context.participant_id,
                pathway_id=target,
            )
            text = "Route 07 is reassessed at full current-cycle delivery efficiency."
        elif target == "eastern_growth":
            water = float(state["resources"][target][self.constraints.resource_id])
            viability = float(self.entities[target].measurements["minimum_viability"])
            protected_total = viability + self.constraints.eastern_recovery_buffer
            additional = max(0.0, protected_total - water)
            text = (
                f"A maintenance condition is recorded for Eastern Growth. It holds {water:g} "
                f"water units and needs no additional water to remain at its {viability:g}-unit "
                f"minimum viability. `/interior act sustain` records maintenance and moves no "
                f"water. Before Eastern Growth could relay any excess, it would need "
                f"{additional:g} additional units to reach its {protected_total:g}-unit protected "
                "viability-and-recovery level."
            )
        else:
            text = f"A maintenance condition is recorded for `{target}`."
        return self._accepted(state, text, "circulation.sustained", "maintainer", target)

    def _calculate(
        self, action: CalculateFlowAction, context: ValidationContext
    ) -> ValidationDecision:
        pathway = self._resolve(action.pathway_entity_id)
        if pathway != self.constraints.source_pathway_id:
            return self._reject(
                "invalid_action", "No confirmed flow calculation matches that path."
            )
        if "route_07_loss" not in context.state.get("unlocked_observations", []):
            return self._reject("invalid_action", "Route efficiency must be public first.")
        unlocked = set(context.state.get("unlocked_observations", []))
        if (
            "condensation_shared_output" in unlocked
            and action.source_amount > self.constraints.source_output
        ):
            return self._reject(
                "invalid_action",
                f"The confirmed Condensation Veil output is "
                f"{self.constraints.source_output:g} units, so source amount cannot exceed "
                f"{self.constraints.source_output:g}. Calculate records Route 07 delivery; "
                "it does not create source water.",
            )
        efficiency = self._efficiency(context.state)
        pathway_delivery = action.source_amount * efficiency
        delivered = pathway_delivery + action.support_amount
        state = self._contribute(
            context.state, context.participant_id, "flow_calculator", "calculate_flow"
        )
        state["calculations"] = [
            *state.get("calculations", []),
            {
                "source_amount": action.source_amount,
                "pathway_id": pathway,
                "efficiency": efficiency,
                "pathway_delivery": pathway_delivery,
                "support_amount": action.support_amount,
                "delivered_amount": delivered,
                "participant_id": context.participant_id,
            },
        ]
        return ValidationDecision(
            True,
            "accepted",
            public_data={
                "public_text": (
                    f"Public calculation: {action.source_amount:g} source units through Route 07 "
                    f"at {efficiency * 100:g}% deliver {pathway_delivery:g}; "
                    f"{action.support_amount:g} protected support produces "
                    f"{delivered:g} total delivered units. Arithmetic only: this records source, "
                    "route loss, support, and delivery; it does not confirm source maintenance, "
                    "recipient need, or proposal readiness."
                )
            },
            next_state=state,
            event_type="circulation.flow_calculated",
            narration_key=self.definition.narration_keys["action_accepted"],
            contribution_function="flow_calculator",
        )

    def _relay(self, action: RelayAction, context: ValidationContext) -> ValidationDecision:
        source = self._resolve(action.source_entity_id)
        via = self._resolve(action.via_entity_id)
        target = self._resolve(action.target_entity_id)
        if (
            source != self.constraints.source_entity_id
            or via != self.constraints.relay_entity_id
            or target != self.constraints.recipient_entity_id
            or action.resource_id.lower() != self.constraints.resource_id
        ):
            return self._reject(
                "invalid_action", "That relay path is not the confirmed circulation."
            )
        if source not in context.state.get("sustained_targets", []):
            return self._reject(
                "invalid_action", "The Veil must be sustained before relay planning."
            )
        if action.amount > self.constraints.source_output:
            return self._reject("invalid_action", "The relay exceeds confirmed Veil output.")
        state = self._contribute(context.state, context.participant_id, "router", "relay")
        state["relays"] = [
            *state.get("relays", []),
            {
                "source": source,
                "via": via,
                "target": target,
                "resource_id": self.constraints.resource_id,
                "source_amount": action.amount,
                "expected_delivery": action.amount * self._efficiency(context.state),
                "participant_id": context.participant_id,
            },
        ]
        return self._accepted(
            state,
            "A same-cycle route through Central Relay is recorded; the Relay retains nothing.",
            "circulation.relay_planned",
            "router",
            target,
            "resource_relay",
        )

    def _mitigate(self, action: MitigateAction, context: ValidationContext) -> ValidationDecision:
        target = self._resolve(action.target_entity_id)
        allowed = {
            self.constraints.reserve_entity_id,
            self.constraints.archive_entity_id,
            self.constraints.relay_entity_id,
            self.constraints.source_pathway_id,
        }
        if target not in allowed:
            return self._reject("invalid_action", "That burden is not available for mitigation.")
        state = self._contribute(
            context.state, context.participant_id, "burden_auditor", "mitigate"
        )
        state["mitigations"] = [
            *state.get("mitigations", []),
            {
                "target": target,
                "risk": action.risk.strip().lower(),
                "detail": action.detail.strip(),
                "participant_id": context.participant_id,
            },
        ]
        return self._accepted(
            state,
            f"A public safeguard against `{action.risk.strip().lower()}` is recorded "
            f"for `{target}`.",
            "circulation.burden_mitigated",
            "burden_auditor",
            target,
            "burden_mitigation",
        )

    def _propose(
        self, action: ProposeCirculationAction, context: ValidationContext
    ) -> ValidationDecision:
        unlocked = set(context.state.get("unlocked_observations", []))
        if not set(self.constraints.required_observations).issubset(unlocked):
            return self._reject(
                "proposal_rejected",
                "Need, source, Veil condition, route loss, relay structure, and the dried civic "
                "basin must be public.",
            )
        source = self._resolve(action.source_entity_id)
        recipient = self._resolve(action.recipient_entity_id)
        pathway = self._resolve(action.pathway_entity_id)
        relay = self._resolve(action.relay_entity_id)
        support_source = (
            self._resolve(action.support_source_entity_id)
            if action.support_source_entity_id.strip()
            else None
        )
        if (
            source != self.constraints.source_entity_id
            or recipient != self.constraints.recipient_entity_id
            or pathway != self.constraints.source_pathway_id
            or relay != self.constraints.relay_entity_id
            or action.resource_id.lower() != self.constraints.resource_id
        ):
            return self._reject(
                "proposal_rejected", "The proposal does not match the confirmed circulation path."
            )
        if bool(support_source) != (action.support_amount > 0):
            return self._reject(
                "proposal_rejected",
                "Protected support requires both a listed support source and a positive amount.",
            )
        if support_source is not None and support_source not in (
            self.constraints.support_source_entity_ids
        ):
            return self._reject(
                "proposal_rejected", "Support may come only from the Northern cistern or Archive."
            )
        if source not in context.state.get("sustained_targets", []):
            return self._reject("proposal_rejected", "The Condensation Veil is not maintained.")
        limits = (
            self.constraints.source_output,
            self.constraints.relay_capacity,
            self.constraints.destination_pathway_capacity,
        )
        if action.source_amount > min(limits):
            return self._reject("proposal_rejected", "The source amount exceeds a public limit.")
        efficiency = self._efficiency(context.state)
        pathway_delivery = action.source_amount * efficiency
        expected = pathway_delivery + action.support_amount
        if not math.isclose(action.delivered_amount, expected, rel_tol=1e-9, abs_tol=1e-9):
            return self._reject(
                "proposal_rejected",
                f"The public calculation delivers {pathway_delivery:g} through Route 07 plus "
                f"{action.support_amount:g} support, or {expected:g} total—not "
                f"{action.delivered_amount:g}.",
            )
        calculation_exists = any(
            math.isclose(float(item.get("source_amount", -1)), action.source_amount)
            and math.isclose(float(item.get("support_amount", 0)), action.support_amount)
            and math.isclose(float(item.get("efficiency", -1)), efficiency)
            and math.isclose(float(item.get("delivered_amount", -1)), expected)
            for item in context.state.get("calculations", [])
        )
        if not calculation_exists:
            return self._reject(
                "proposal_rejected",
                "Use `/interior act calculate` with the proposed source and support amounts "
                "before submitting this circulation.",
            )
        need = self._nursery_need(context.state)
        if action.delivered_amount < need:
            return self._reject(
                "proposal_rejected",
                f"The current forecast requires {need:g} delivered units.",
            )
        support_before: float | None = None
        support_after: float | None = None
        support_requires_protection = False
        if support_source is not None:
            required_observation = {
                self.constraints.reserve_entity_id: "northern_inherited_burden",
                self.constraints.archive_entity_id: "archive_coherence_cost",
            }[support_source]
            if required_observation not in unlocked:
                return self._reject(
                    "proposal_rejected", "Inspect the selected support source's burden first."
                )
            support_before = float(
                context.state["resources"][support_source][self.constraints.resource_id]
            )
            support_after = support_before - action.support_amount
            if support_source == self.constraints.reserve_entity_id:
                strain = int(
                    context.state.get("counters", {}).get("strain", {}).get(support_source, 0)
                )
                tactical = self.definition.tactical
                assert tactical is not None
                effective_reserve = (
                    self.constraints.reserve_floor
                    + (strain // tactical.strain_threshold) * tactical.strain_reserve_penalty
                )
                if support_after < effective_reserve:
                    return self._reject(
                        "proposal_rejected",
                        "Northern support would cross its strain-adjusted civic reserve.",
                    )
                support_requires_protection = action.support_amount > 0
            else:
                if support_after < self.constraints.archive_viability_floor:
                    return self._reject(
                        "proposal_rejected",
                        "Archive support would make its planted bed nonviable.",
                    )
                support_requires_protection = (
                    support_after < self.constraints.archive_coherence_floor
                )
            relay_stable = self.constraints.relay_entity_id in context.state.get(
                "sustained_targets", []
            )
            if not relay_stable:
                return self._reject(
                    "proposal_rejected",
                    "Combining two inflows requires Central Relay to be publicly sustained.",
                )
        if not self._contains(action.maintenance, self.constraints.maintenance_terms):
            return self._reject("proposal_rejected", "The source needs a maintenance condition.")
        if not self._contains(action.reassessment, self.constraints.reassessment_terms):
            return self._reject("proposal_rejected", "The plan needs a reassessment condition.")
        if bool(action.branch_condition.strip()) != bool(action.branch_action.strip()):
            return self._reject(
                "proposal_rejected", "A branch must include both its condition and action."
            )
        if action.branch_condition and not self._contains(
            action.branch_condition, self.constraints.branch_terms
        ):
            return self._reject(
                "proposal_rejected", "The branch must respond to a public need or output change."
            )
        if action.branch_action and not self._contains(
            action.branch_action, self.constraints.branch_action_terms
        ):
            return self._reject(
                "proposal_rejected",
                "The branch action must revise, protect, repair, reroute, or release resources.",
            )
        contributions = current_cycle_contributions(context.state)
        participants = {item["participant_id"] for item in contributions}
        functions = {item["function"] for item in contributions}
        participants.add(context.participant_id)
        functions.add("circulation_planner")
        relational = self.definition.relational_requirements
        assert relational is not None
        if len(participants) < relational.minimum_distinct_users:
            return self._reject(
                "proposal_rejected", "At least three distinct public participants are required."
            )
        if len(functions) < relational.minimum_distinct_functions:
            return self._reject(
                "proposal_rejected", "At least three contribution functions are required."
            )
        strategy = (
            "shared_northern_support"
            if support_source == self.constraints.reserve_entity_id
            else "shared_archive_support"
            if support_source == self.constraints.archive_entity_id
            else "maintained_efficient_route"
            if math.isclose(efficiency, self.constraints.reassessed_efficiency)
            else "rapid_loss_accounted_route"
        )
        proposal_id = self._proposal_id(strategy, context.state.get("proposals", {}))
        proposal = {
            "proposal_id": proposal_id,
            "kind": "circulation",
            "author_participant_id": context.participant_id,
            "source_id": source,
            "recipient_id": recipient,
            "resource_id": self.constraints.resource_id,
            "source_amount": action.source_amount,
            "pathway_delivery": pathway_delivery,
            "pathway_id": pathway,
            "relay_id": relay,
            "delivered_amount": action.delivered_amount,
            "support_source_id": support_source,
            "support_amount": action.support_amount,
            "support_before": support_before,
            "support_after": support_after,
            "support_requires_protection": support_requires_protection,
            "strategy": strategy,
            "maintenance": action.maintenance.strip(),
            "reassessment": action.reassessment.strip(),
            "branch_condition": action.branch_condition.strip(),
            "branch_action": action.branch_action.strip(),
            "status": "pending",
            "kickers": [],
        }
        state = self._contribute(
            context.state,
            context.participant_id,
            "circulation_planner",
            "propose_circulation",
        )
        state["proposals"] = {**state.get("proposals", {}), proposal_id: proposal}
        branch_status = (
            "includes a contingency branch"
            if action.branch_condition
            else ("still needs a contingency branch")
        )
        non_author_support = any(
            item.get("participant_id") != context.participant_id
            and item.get("action")
            in {"sustain", "mitigate", "branch_proposal", "add_proposal_kicker"}
            for item in contributions
        )
        support_status = (
            "Non-author support is already public."
            if non_author_support
            else (
                "Before confirmation, a different participant must sustain, mitigate, or "
                "branch."
            )
        )
        return ValidationDecision(
            True,
            "proposal_accepted",
            public_data={
                "public_text": (
                    f"Circulation proposal `{proposal_id}` records `{strategy}`: "
                    f"{action.source_amount:g} Veil units deliver {pathway_delivery:g} through "
                    f"Route 07, {action.support_amount:g} protected support brings the total to "
                    f"{action.delivered_amount:g}; it {branch_status} and awaits non-author "
                    f"confirmation. {support_status}"
                ),
                "proposal_id": proposal_id,
            },
            next_state=state,
            event_type="circulation.proposed",
            narration_key=self.definition.narration_keys["proposal_accepted"],
            contribution_function="circulation_planner",
            proposal_projection={
                "id": proposal_id,
                "author_participant_id": context.participant_id,
                "status": "pending",
                "proposal_data": proposal,
            },
        )

    def _branch(
        self, action: BranchProposalAction, context: ValidationContext
    ) -> ValidationDecision:
        proposal = context.state.get("proposals", {}).get(action.proposal_id)
        if (
            proposal is None
            or proposal.get("status") != "pending"
            or proposal.get("kind") != ("circulation")
        ):
            return self._reject(
                "invalid_action", "No pending circulation proposal matches that ID."
            )
        if not self._contains(action.condition, self.constraints.branch_terms):
            return self._reject(
                "invalid_action", "The branch must respond to a public need or output change."
            )
        if not self._contains(action.branch_action, self.constraints.branch_action_terms):
            return self._reject(
                "invalid_action",
                "The branch action must revise, protect, repair, reroute, or release resources.",
            )
        state = self._contribute(
            context.state, context.participant_id, "contingency_planner", "branch_proposal"
        )
        updated = dict(proposal)
        updated["branch_condition"] = action.condition.strip()
        updated["branch_action"] = action.branch_action.strip()
        updated["branch_participant_id"] = context.participant_id
        state["proposals"] = {**state.get("proposals", {}), action.proposal_id: updated}
        state["branches"] = [
            *state.get("branches", []),
            {
                "proposal_id": action.proposal_id,
                "condition": action.condition.strip(),
                "action": action.branch_action.strip(),
                "participant_id": context.participant_id,
            },
        ]
        return ValidationDecision(
            True,
            "accepted",
            public_data={
                "public_text": f"A conditional branch is attached to `{action.proposal_id}`."
            },
            next_state=state,
            event_type="circulation.branch_added",
            narration_key=self.definition.narration_keys["action_accepted"],
            contribution_function="contingency_planner",
            proposal_data_update={
                "proposal_id": action.proposal_id,
                "proposal_data": updated,
            },
        )

    def _begin_stack(
        self, action: BeginStackAction, context: ValidationContext
    ) -> ValidationDecision:
        tactical = self.definition.tactical
        assert tactical is not None
        current = context.state.get("public_stack")
        if current and current.get("status") == "open":
            return self._reject("invalid_action", "A public stack is already open.")
        try:
            proposal_action = self._circulation_action(dict(action.proposal))
        except (TypeError, ValueError):
            return self._reject("invalid_action", "The circulation stack base is incomplete.")
        if (
            self._resolve(proposal_action.source_entity_id) != self.constraints.source_entity_id
            or self._resolve(proposal_action.recipient_entity_id)
            != self.constraints.recipient_entity_id
            or self._resolve(proposal_action.pathway_entity_id)
            != self.constraints.source_pathway_id
            or self._resolve(proposal_action.relay_entity_id) != self.constraints.relay_entity_id
        ):
            return self._reject("invalid_action", "The stack base uses an unknown circulation.")
        stack_id = self._public_id("s", context.session_id, context.action_id)
        state = self._contribute(
            context.state, context.participant_id, "circulation_planner", "begin_stack"
        )
        state["public_stack"] = {
            "stack_id": stack_id,
            "status": "open",
            "position": 1,
            "base": {
                "participant_id": context.participant_id,
                "proposal": proposal_action.model_dump(mode="json"),
            },
            "entries": [
                {
                    "kind": "proposal",
                    "participant_id": context.participant_id,
                    "label": "attempt circulation",
                }
            ],
        }
        return ValidationDecision(
            True,
            "stack_opened",
            public_data={
                "public_text": (
                    f"Circulation stack `{stack_id}` is open (1/{tactical.max_stack_depth}). "
                    "One objection, reassessment, or safeguard may be added per participant."
                ),
                "stack_id": stack_id,
            },
            next_state=state,
            event_type="stack.opened",
            narration_key=self.definition.narration_keys["action_accepted"],
            contribution_function="circulation_planner",
        )

    def _react_to_stack(
        self, action: ReactToStackAction, context: ValidationContext
    ) -> ValidationDecision:
        tactical = self.definition.tactical
        assert tactical is not None
        stack = context.state.get("public_stack")
        if (
            not stack
            or stack.get("status") != "open"
            or stack.get("stack_id") != action.stack_id
            or stack.get("position") != 1
        ):
            return self._reject("invalid_action", "No open Circulation stack matches that ID.")
        entries = list(stack.get("entries", []))
        if len(entries) >= tactical.max_stack_depth:
            return self._reject("invalid_action", "The public stack has reached its depth limit.")
        if action.reaction not in tactical.allowed_stack_reactions:
            return self._reject("invalid_action", "That reaction is unavailable in Circulation.")
        if any(item.get("participant_id") == context.participant_id for item in entries):
            return self._reject(
                "invalid_action", "Each participant may add only one entry to this stack."
            )
        unlocked = set(context.state.get("unlocked_observations", []))
        required = {
            "object_loss": "route_07_loss",
            "reassess_demand": "nursery_projected_need",
            "stabilize_relay": "central_relay_no_storage",
            "protect_archive": "archive_coherence_cost",
            "mitigate_north": "northern_inherited_burden",
        }
        if required[action.reaction] not in unlocked:
            return self._reject(
                "invalid_action", "That reaction requires its public condition to be inspected."
            )
        functions = {
            "object_loss": "loss_auditor",
            "reassess_demand": "forecast_reader",
            "stabilize_relay": "maintainer",
            "protect_archive": "archive_auditor",
            "mitigate_north": "burden_auditor",
        }
        labels = {
            "object_loss": "account for route loss",
            "reassess_demand": "reassess Nursery demand",
            "stabilize_relay": "stabilize Central Relay",
            "protect_archive": "protect archive coherence",
            "mitigate_north": "protect Northern reserve",
        }
        state = self._contribute(
            context.state,
            context.participant_id,
            functions[action.reaction],
            "react_to_stack",
        )
        updated = copy.deepcopy(stack)
        updated["entries"] = [
            *entries,
            {
                "kind": "reaction",
                "participant_id": context.participant_id,
                "reaction": action.reaction,
                "detail": action.detail.strip(),
                "label": labels[action.reaction],
            },
        ]
        state["public_stack"] = updated
        remaining = tactical.max_stack_depth - len(updated["entries"])
        return ValidationDecision(
            True,
            "stack_reaction_added",
            public_data={
                "public_text": (
                    f"{labels[action.reaction].capitalize()} is added to `{action.stack_id}`. "
                    f"{remaining} stack slot{'s' if remaining != 1 else ''} remain."
                )
            },
            next_state=state,
            event_type="stack.reaction_added",
            narration_key=self.definition.narration_keys["action_accepted"],
            contribution_function=functions[action.reaction],
        )

    def _resolve_stack(
        self, action: ResolveStackAction, context: ValidationContext
    ) -> ValidationDecision:
        stack = context.state.get("public_stack")
        if (
            not stack
            or stack.get("status") != "open"
            or stack.get("stack_id") != action.stack_id
            or stack.get("position") != 1
        ):
            return self._reject("invalid_action", "No open Circulation stack matches that ID.")
        working = copy.deepcopy(context.state)
        labels: list[str] = []
        proposal_data = dict(stack["base"]["proposal"])
        for entry in reversed(stack.get("entries", [])[1:]):
            reaction = str(entry["reaction"])
            labels.append(str(entry["label"]))
            if reaction == "reassess_demand":
                working["forecast_branch"] = "accelerated"
                facts = []
                for fact in working.get("confirmed_facts", []):
                    updated_fact = dict(fact)
                    if updated_fact.get("observation_id") == "nursery_projected_need":
                        updated_fact["public_text"] = self._observation_text(
                            "nursery_projected_need", working
                        )
                    facts.append(updated_fact)
                working["confirmed_facts"] = facts
                if not proposal_data.get("branch_condition"):
                    proposal_data["branch_condition"] = "if Nursery demand changes"
                    proposal_data["branch_action"] = (
                        "revise delivery to the confirmed need and release unused condensation"
                    )
                    proposal_data["branch_participant_id"] = entry["participant_id"]
            elif reaction == "stabilize_relay":
                sustained = list(working.get("sustained_targets", []))
                if self.constraints.relay_entity_id not in sustained:
                    sustained.append(self.constraints.relay_entity_id)
                working["sustained_targets"] = sustained
            elif reaction in {"protect_archive", "mitigate_north"}:
                target = (
                    self.constraints.archive_entity_id
                    if reaction == "protect_archive"
                    else self.constraints.reserve_entity_id
                )
                working["mitigations"] = [
                    *working.get("mitigations", []),
                    {
                        "target": target,
                        "risk": reaction,
                        "detail": entry.get("detail", ""),
                        "participant_id": entry["participant_id"],
                    },
                ]
        labels.append("attempt circulation")
        summary = "Resolution order: " + " -> ".join(labels) + "."
        try:
            proposal_action = self._circulation_action(proposal_data)
        except (TypeError, ValueError):
            return self._failed_stack(working, stack, context, summary, "The base is incomplete.")
        synthetic = ValidationContext(
            environment=context.environment,
            session_id=context.session_id,
            participant_id=str(stack["base"]["participant_id"]),
            action_id=f"{context.action_id}:stack-proposal",
            current_position=context.current_position,
            response_profile=context.response_profile,
            state=working,
        )
        proposed = self._propose(proposal_action, synthetic)
        if not proposed.accepted or proposed.next_state is None:
            feedback = str(proposed.public_data.get("feedback", "The proposal could not resolve."))
            return self._failed_stack(working, stack, context, summary, feedback)
        state = proposed.next_state
        updated_stack = copy.deepcopy(stack)
        updated_stack["status"] = "resolved"
        updated_stack["resolution_order"] = labels
        proposal_id = str(proposed.public_data["proposal_id"])
        updated_stack["proposal_id"] = proposal_id
        state["public_stack"] = updated_stack
        return ValidationDecision(
            True,
            "stack_resolved",
            public_data={
                "public_text": f"{summary} {proposed.public_data['public_text']}",
                "proposal_id": proposal_id,
            },
            next_state=state,
            event_type="stack.resolved",
            narration_key=self.definition.narration_keys["proposal_accepted"],
            proposal_projection=proposed.proposal_projection,
        )

    def _failed_stack(
        self,
        state: dict[str, Any],
        stack: dict[str, Any],
        context: ValidationContext,
        summary: str,
        feedback: str,
    ) -> ValidationDecision:
        updated = copy.deepcopy(stack)
        updated["status"] = "failed"
        updated["resolution_order"] = (
            summary.removeprefix("Resolution order: ").removesuffix(".").split(" -> ")
        )
        state["public_stack"] = updated
        counters = copy.deepcopy(state.get("counters", {}))
        counters["instability"] = int(counters.get("instability", 0)) + 1
        state["counters"] = counters
        return ValidationDecision(
            True,
            "stack_resolved_failed",
            public_data={"public_text": f"{summary} Resolution stops: {feedback}"},
            next_state=state,
            event_type="stack.resolved_failed",
            narration_key=self.definition.narration_keys["proposal_rejected"],
        )

    def _add_kicker(
        self, action: AddProposalKickerAction, context: ValidationContext
    ) -> ValidationDecision:
        proposal = context.state.get("proposals", {}).get(action.proposal_id)
        if (
            proposal is None
            or proposal.get("status") != "pending"
            or proposal.get("kind") != ("circulation")
        ):
            return self._reject(
                "invalid_action", "No pending circulation proposal matches that ID."
            )
        tactical = self.definition.tactical
        assert tactical is not None
        if action.kicker not in tactical.allowed_kickers:
            return self._reject("invalid_action", "That kicker is unavailable in Circulation.")
        kickers = list(proposal.get("kickers", []))
        if proposal["author_participant_id"] == context.participant_id or any(
            item["participant_id"] == context.participant_id for item in kickers
        ):
            return self._reject(
                "invalid_action", "A kicker must come from a distinct non-author contributor."
            )
        if any(item["kicker"] == action.kicker for item in kickers):
            return self._reject("invalid_action", "That kicker is already attached.")
        if len(kickers) >= 3:
            return self._reject("invalid_action", "This proposal already has three kickers.")
        if action.kicker == "adaptive_branch" and not self._contains(
            action.detail, self.constraints.branch_terms
        ):
            return self._reject(
                "invalid_action", "Adaptive branch detail must name a need or output condition."
            )
        functions = {
            "monitoring": "maintainer",
            "protect_donor": "burden_auditor",
            "document_flow": "archivist",
            "adaptive_branch": "contingency_planner",
        }
        state = self._contribute(
            context.state, context.participant_id, functions[action.kicker], "add_proposal_kicker"
        )
        updated = dict(proposal)
        updated["kickers"] = [
            *kickers,
            {
                "kicker": action.kicker,
                "participant_id": context.participant_id,
                "detail": action.detail.strip(),
            },
        ]
        if action.kicker == "adaptive_branch":
            updated["branch_condition"] = action.detail.strip()
            updated["branch_action"] = (
                "revise source and delivery to the newly confirmed need or output"
            )
            updated["branch_participant_id"] = context.participant_id
        state["proposals"] = {**state.get("proposals", {}), action.proposal_id: updated}
        return ValidationDecision(
            True,
            "kicker_added",
            public_data={
                "public_text": (
                    f"{action.kicker.replace('_', ' ').title()} is attached to "
                    f"`{action.proposal_id}`."
                )
            },
            next_state=state,
            event_type="proposal.kicker_added",
            narration_key=self.definition.narration_keys["action_accepted"],
            contribution_function=functions[action.kicker],
            proposal_data_update={
                "proposal_id": action.proposal_id,
                "proposal_data": updated,
            },
        )

    def _confirm(
        self, action: ConfirmReconstructionAction, context: ValidationContext
    ) -> ValidationDecision:
        proposals = dict(context.state.get("proposals", {}))
        proposal = proposals.get(action.proposal_id)
        if (
            proposal is None
            or proposal.get("status") != "pending"
            or proposal.get("kind") != ("circulation")
        ):
            return self._reject(
                "invalid_action", "No pending circulation proposal matches that ID."
            )
        author = str(proposal["author_participant_id"])
        if author == context.participant_id:
            return self._reject("invalid_action", "A non-author must confirm circulation.")
        if not proposal.get("branch_condition") or not proposal.get("branch_action"):
            return self._reject(
                "proposal_rejected", "A public contingency branch is still missing."
            )
        support_actions = {"sustain", "mitigate", "branch_proposal", "add_proposal_kicker"}
        supporting = {
            item["participant_id"]
            for item in current_cycle_contributions(context.state)
            if item.get("action") in support_actions and item.get("participant_id") != author
        }
        branch_participant = proposal.get("branch_participant_id")
        if branch_participant and branch_participant != author:
            supporting.add(str(branch_participant))
        stack = context.state.get("public_stack") or {}
        supporting.update(
            str(item["participant_id"])
            for item in stack.get("entries", [])
            if item.get("participant_id") != author
            and item.get("reaction")
            in {"reassess_demand", "stabilize_relay", "protect_archive", "mitigate_north"}
        )
        if not supporting:
            return self._reject(
                "proposal_rejected",
                "Maintenance, mitigation, or branching must include a non-author contributor.",
            )
        support_source = proposal.get("support_source_id")
        kicker_types = {item["kicker"] for item in proposal.get("kickers", [])}
        mitigation_targets = {item.get("target") for item in context.state.get("mitigations", [])}
        support_protected = (
            support_source is None
            or not proposal.get("support_requires_protection", False)
            or support_source in mitigation_targets
            or "protect_donor" in kicker_types
        )
        if not support_protected:
            label = (
                "Northern reserve"
                if support_source == self.constraints.reserve_entity_id
                else "Archive coherence"
            )
            return self._reject(
                "proposal_rejected",
                f"{label} needs a public mitigation or protect-donor safeguard before resolution.",
            )
        state = self._contribute(
            context.state, context.participant_id, "verifier", "confirm_reconstruction"
        )
        proposal = dict(proposal)
        proposal["status"] = "confirmed"
        proposals[action.proposal_id] = proposal
        state["proposals"] = proposals
        confirmation = {
            "proposal_id": action.proposal_id,
            "participant_id": context.participant_id,
        }
        state["confirmations"] = [*state.get("confirmations", []), confirmation]
        resources = copy.deepcopy(state["resources"])
        resources[self.constraints.source_entity_id][self.constraints.resource_id] = 0
        resources[self.constraints.recipient_entity_id][self.constraints.resource_id] += float(
            proposal["delivered_amount"]
        )
        if support_source is not None:
            resources[str(support_source)][self.constraints.resource_id] = float(
                proposal["support_after"]
            )
        resources[self.constraints.relay_entity_id][self.constraints.resource_id] = 0
        resources.setdefault(
            self.constraints.central_basin_entity_id,
            {self.constraints.resource_id: 0},
        )
        state["resources"] = resources
        effects = list(state.get("persistent_effects", []))
        if "adaptive_circulation_protocol" not in effects:
            effects.append("adaptive_circulation_protocol")
        counters = copy.deepcopy(state.get("counters", {}))
        if "document_flow" in kicker_types:
            counters["coherence"] = int(counters.get("coherence", 0)) + 1
        if "monitoring" in kicker_types and "cycle_monitor" not in effects:
            effects.append("cycle_monitor")
            unused_output = max(
                0.0, self.constraints.source_output - float(proposal["source_amount"])
            )
            resources[self.constraints.central_basin_entity_id][self.constraints.resource_id] += (
                unused_output
            )
            if unused_output and "first_bloom_monitoring" not in effects:
                effects.append("first_bloom_monitoring")
        if support_source == self.constraints.reserve_entity_id:
            strain = dict(counters.get("strain", {}))
            strain[str(support_source)] = int(strain.get(str(support_source), 0)) + 1
            counters["strain"] = strain
            if "northern_support_recorded" not in effects:
                effects.append("northern_support_recorded")
        elif support_source == self.constraints.archive_entity_id:
            if float(proposal["support_after"]) < self.constraints.archive_coherence_floor:
                if "archive_coherence_fragile" not in effects:
                    effects.append("archive_coherence_fragile")
            elif "archive_support_recorded" not in effects:
                effects.append("archive_support_recorded")
        repair_count = int(counters.get("repair", {}).get(self.constraints.source_pathway_id, 0))
        maintenance_count = int(
            counters.get("maintenance", {}).get(self.constraints.source_entity_id, 0)
        )
        tactical = self.definition.tactical
        assert tactical is not None
        if repair_count >= tactical.repair_threshold and "route_07_reinforced" not in effects:
            effects.append("route_07_reinforced")
        if maintenance_count >= 2 and "veil_stabilized" not in effects:
            effects.append("veil_stabilized")
        if (
            int(counters.get("coherence", 0)) >= tactical.coherence_threshold
            and "circulation_ledger" not in effects
        ):
            effects.append("circulation_ledger")
        state["counters"] = counters
        state["persistent_effects"] = effects
        state["world_flags"] = {
            **state.get("world_flags", {}),
            **self.definition.completion.world_flags,
            "village_system_recognized": True,
            "first_bloom_basin_discovered": True,
            "circulation_strategy": str(proposal["strategy"]),
            "archive_coherence_preserved": "archive_coherence_fragile" not in effects,
            "industrial_draw_identified": any(
                item in state.get("unlocked_observations", [])
                for item in ("upper_allocation_unresolved", "second_network_demand")
            ),
            "clean_altered_water_distinguished": "returned_volume_not_usable"
            in state.get("unlocked_observations", []),
            "limited_indicator_bed_identified": "indicator_bed_capacity_limited"
            in state.get("unlocked_observations", []),
        }
        state["position_completed"] = True
        return ValidationDecision(
            True,
            "position_completed",
            public_data={
                "public_text": (
                    f"Position 1 complete through `{proposal['strategy']}`. The current reaches "
                    "Pale Nursery, civic burdens remain visible, and the dried central basin is "
                    "retained as a future shared obligation. Source, delivery, maintenance, and "
                    "a condition for revision now form an Adaptive Circulation Protocol."
                )
            },
            next_state=state,
            event_type="position.completed",
            narration_key=self.definition.narration_keys["position_completed"],
            contribution_function="verifier",
            position_completed=True,
            next_position=self.definition.completion.next_position,
            next_response_profile=self.definition.completion.response_profile,
            confirmation_projection=confirmation,
            proposal_status_update={"proposal_id": action.proposal_id, "status": "confirmed"},
            world_flag_projections=self.definition.completion.world_flags,
        )

    def _use_trigger(
        self, action: UseTriggeredReactionAction, context: ValidationContext
    ) -> ValidationDecision:
        trigger = next(
            (
                item
                for item in context.state.get("triggered_reactions", [])
                if item.get("trigger_id") == action.trigger_id and not item.get("consumed", False)
            ),
            None,
        )
        if trigger is None:
            return self._reject("invalid_action", "No available public trigger matches that ID.")
        excluded = {str(trigger.get("source_participant_id", ""))}
        excluded.update(str(item) for item in trigger.get("excluded_participant_ids", []))
        if context.participant_id in excluded:
            return self._reject(
                "invalid_action", "This reaction must be taken by another participant."
            )
        kind = str(trigger.get("kind"))
        if kind == "inspect_capacity":
            observation_id = str(trigger.get("observation_id"))
            observation = self.observations.get(observation_id)
            if observation is None:
                return self._reject("invalid_action", "The triggered observation is unavailable.")
            observed = self._observe(
                ObserveAction(action="observe", entity_id=observation.entity_id), context
            )
            assert observed.next_state is not None
            state = observed.next_state
            self._consume_trigger(state, action.trigger_id, context.participant_id)
            return ValidationDecision(
                True,
                "trigger_resolved",
                public_data={
                    "public_text": "Triggered capacity inspection: "
                    + str(observed.public_data["public_text"])
                },
                next_state=state,
                event_type="trigger.resolved",
                narration_key=self.definition.narration_keys["action_accepted"],
                contribution_function=observed.contribution_function,
                unlocked_observation_key=observed.unlocked_observation_key,
            )
        state = copy.deepcopy(context.state)
        self._consume_trigger(state, action.trigger_id, context.participant_id)
        if kind == "test_route_07":
            reassessed = list(state.get("reassessed_pathways", []))
            if self.constraints.source_pathway_id not in reassessed:
                reassessed.append(self.constraints.source_pathway_id)
            state["reassessed_pathways"] = reassessed
            counters = copy.deepcopy(state.get("counters", {}))
            repair = dict(counters.get("repair", {}))
            repair[self.constraints.source_pathway_id] = (
                int(repair.get(self.constraints.source_pathway_id, 0)) + 1
            )
            counters["repair"] = repair
            state["counters"] = counters
            text = "Triggered route test: Route 07 now delivers at full current-cycle efficiency."
            function = "pathway_tester"
        elif kind == "calculate_flow":
            text = "Triggered calculation support is available through `/interior act calculate`."
            function = "calculation_support"
        elif kind == "risk_check":
            donor_id = str(trigger.get("donor_id", self.constraints.reserve_entity_id))
            strain = int(state.get("counters", {}).get("strain", {}).get(donor_id, 0))
            text = f"Inherited risk check: `{donor_id}` carries {strain} strain counter(s)."
            function = "burden_auditor"
        elif kind == "test_route":
            text = "Inherited Route 03 test remains confirmed in the prior-position record."
            function = "pathway_tester"
        else:
            text = "The public trigger is preserved as a useful circulation observation."
            function = "archivist"
        state = self._contribute(state, context.participant_id, function, "use_triggered_reaction")
        return ValidationDecision(
            True,
            "trigger_resolved",
            public_data={"public_text": text},
            next_state=state,
            event_type="trigger.resolved",
            narration_key=self.definition.narration_keys["action_accepted"],
            contribution_function=function,
        )

    def _observation_text(self, observation_id: str, state: dict[str, Any]) -> str:
        if observation_id == "nursery_projected_need":
            need = self._nursery_need(state)
            branch = str(state.get("forecast_branch", "stable"))
            return (
                f"Pale Nursery is viable now but is projected to require {need:g} additional "
                f"water units next cycle under the {branch} growth reading."
            )
        if observation_id == "northern_inherited_burden":
            water = float(
                state["resources"][self.constraints.reserve_entity_id][self.constraints.resource_id]
            )
            strain = int(
                state.get("counters", {})
                .get("strain", {})
                .get(self.constraints.reserve_entity_id, 0)
            )
            tactical = self.definition.tactical
            assert tactical is not None
            reserve = 4 + (strain // tactical.strain_threshold) * tactical.strain_reserve_penalty
            return (
                f"Northern Reservoir holds {water:g} water units, carries {strain} strain, and "
                f"must currently retain {reserve:g}; repeated use would deepen its burden."
            )
        if observation_id == "eastern_relay_limit":
            water = float(state["resources"]["eastern_growth"][self.constraints.resource_id])
            viability = float(self.entities["eastern_growth"].measurements["minimum_viability"])
            protected_total = viability + self.constraints.eastern_recovery_buffer
            additional = max(0.0, protected_total - water)
            relayable = max(0.0, water - protected_total)
            return (
                f"Eastern Growth holds {water:g} water units. Its minimum viability is "
                f"{viability:g}, so it currently needs no additional water merely to remain "
                f"viable. Its protected recovery level is {protected_total:g} units: viability "
                f"plus a {self.constraints.eastern_recovery_buffer:g}-unit recovery buffer. It "
                f"therefore needs {additional:g} additional units before it could relay any "
                f"excess, and can relay {relayable:g} now."
            )
        if observation_id == "indicator_bed_capacity_limited":
            arc = self.definition.provision_arc
            assert arc is not None
            target = "return_indicator_bed"
            viability = float(state.get("counters", {}).get("viability", {}).get(target, 0))
            saturation = float(
                state.get("counters", {}).get("saturation", {}).get(target, 0)
            )
            return (
                f"The indicator bed's viability is {viability:g} against a minimum of "
                f"{arc.thresholds.minimum_viability:g}; its saturation is {saturation:g} "
                f"against a limit of {arc.thresholds.saturation_limit:g}. It has "
                f"{max(0.0, arc.thresholds.saturation_limit - saturation):g} load(s) of "
                "headroom. Continued flow cannot expand that capacity, and visible change is "
                "not proof of safety."
            )
        return self.observations[observation_id].public_text

    @staticmethod
    def _circulation_action(proposal: dict[str, Any]) -> ProposeCirculationAction:
        return ProposeCirculationAction(
            action="propose_circulation",
            source_entity_id=str(proposal["source_entity_id"]),
            recipient_entity_id=str(proposal["recipient_entity_id"]),
            resource_id=str(proposal["resource_id"]),
            source_amount=float(proposal["source_amount"]),
            pathway_entity_id=str(proposal["pathway_entity_id"]),
            relay_entity_id=str(proposal["relay_entity_id"]),
            delivered_amount=float(proposal["delivered_amount"]),
            maintenance=str(proposal["maintenance"]),
            reassessment=str(proposal["reassessment"]),
            branch_condition=str(proposal.get("branch_condition", "")),
            branch_action=str(proposal.get("branch_action", "")),
            support_source_entity_id=str(proposal.get("support_source_entity_id", "")),
            support_amount=float(proposal.get("support_amount", 0)),
        )

    def _nursery_need(self, state: dict[str, Any]) -> float:
        nursery = self.entities[self.constraints.recipient_entity_id]
        branch = str(state.get("forecast_branch", "stable"))
        key = "accelerated_minimum" if branch == "accelerated" else "stable_minimum"
        minimum = float(nursery.measurements[key])
        current = float(
            state["resources"][self.constraints.recipient_entity_id][self.constraints.resource_id]
        )
        return max(0.0, minimum - current)

    def _efficiency(self, state: dict[str, Any]) -> float:
        return (
            self.constraints.reassessed_efficiency
            if self.constraints.source_pathway_id in state.get("reassessed_pathways", [])
            else self.constraints.unassessed_efficiency
        )

    def _fact_classification(self, observation_id: str) -> str:
        configured = self.observations[observation_id].classification
        if configured != "confirmed":
            return configured
        return (
            "projected"
            if observation_id
            in {
                "nursery_projected_need",
                "nursery_variable_demand",
            }
            else "confirmed"
        )

    def _resolve(self, value: str) -> str | None:
        return self.aliases.get(value.strip().lower())

    @staticmethod
    def _contains(value: str, terms: tuple[str, ...]) -> bool:
        lowered = value.strip().lower()
        return any(term in lowered for term in terms)

    @staticmethod
    def _public_id(prefix: str, *parts: str) -> str:
        return f"{prefix}-" + hashlib.sha256(":".join(parts).encode()).hexdigest()[:12]

    @staticmethod
    def _proposal_id(strategy: str, proposals: dict[str, Any]) -> str:
        bases = {
            "rapid_loss_accounted_route": "circulation-loss-accounted",
            "maintained_efficient_route": "circulation-maintained-route",
            "shared_northern_support": "circulation-northern-support",
            "shared_archive_support": "circulation-archive-support",
        }
        base = bases.get(strategy, "circulation-proposal")
        if base not in proposals:
            return base
        suffix = 2
        while f"{base}-{suffix}" in proposals:
            suffix += 1
        return f"{base}-{suffix}"

    @staticmethod
    def _contribute(
        state: dict[str, Any], participant_id: str, function: str, action: str
    ) -> dict[str, Any]:
        updated = copy.deepcopy(state)
        updated["contributions"] = [
            *updated.get("contributions", []),
            {"participant_id": participant_id, "function": function, "action": action},
        ]
        return updated

    def _accepted(
        self,
        state: dict[str, Any],
        text: str,
        event_type: str,
        function: str,
        target: str | None = None,
        relation_type: str | None = None,
    ) -> ValidationDecision:
        return ValidationDecision(
            True,
            "accepted",
            public_data={"public_text": text},
            next_state=state,
            event_type=event_type,
            narration_key=self.definition.narration_keys["action_accepted"],
            contribution_function=function,
            relational_target=target,
            relation_type=relation_type,
        )

    def _append_trigger(
        self,
        state: dict[str, Any],
        context: ValidationContext,
        *,
        kind: str,
        source_participant_id: str,
        observation_id: str | None = None,
        pathway_id: str | None = None,
    ) -> None:
        reactions = list(state.get("triggered_reactions", []))
        del context
        observation = self.observations.get(observation_id or "")
        subject = observation.entity_id if observation is not None else pathway_id
        aliases = semantic_trigger_aliases(
            reactions, {item.id: item.entity_id for item in self.definition.observations}
        )
        trigger_id = semantic_trigger_id(
            ({"trigger_id": item} for item in aliases.values()), kind, subject
        )
        reactions.append(
            {
                "trigger_id": trigger_id,
                "kind": kind,
                "source_participant_id": source_participant_id,
                "excluded_participant_ids": [],
                "observation_id": observation_id,
                "pathway_id": pathway_id,
                "consumed": False,
            }
        )
        state["triggered_reactions"] = reactions

    @staticmethod
    def _consume_trigger(state: dict[str, Any], trigger_id: str, participant_id: str) -> None:
        reactions = []
        for item in state.get("triggered_reactions", []):
            updated = dict(item)
            if updated.get("trigger_id") == trigger_id:
                updated["consumed"] = True
                updated["consumed_by"] = participant_id
            reactions.append(updated)
        state["triggered_reactions"] = reactions

    @staticmethod
    def _reject(reason_key: str, feedback: str) -> ValidationDecision:
        return ValidationDecision(
            False,
            reason_key,
            public_data={"feedback": feedback},
            narration_key=(
                "proposal_rejected" if reason_key == "proposal_rejected" else "invalid_action"
            ),
        )
