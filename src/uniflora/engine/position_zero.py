from __future__ import annotations

import copy
import hashlib
import math
from dataclasses import replace
from typing import Any

from uniflora.content.loader import PuzzleRegistry
from uniflora.content.schema import PuzzleDefinition
from uniflora.engine.actions import (
    AddProposalKickerAction,
    AwakenVesselAction,
    BeginStackAction,
    CandidateAction,
    ConfirmReconstructionAction,
    ConnectAction,
    ObserveAction,
    OfferAction,
    OrientLocalAction,
    ProposeReconstructionAction,
    ReactToStackAction,
    RequestSupportAction,
    ResolveStackAction,
    SummarizeAction,
    UseTriggeredReactionAction,
)
from uniflora.engine.cycles import (
    apply_cycle_decision,
    current_cycle_contributions,
    initialize_next_position_cycle,
    prepare_cycle_action,
)
from uniflora.engine.position_one import PositionOneValidator
from uniflora.engine.position_two import PositionTwoValidator
from uniflora.engine.provision_arc import ProvisionArcValidator
from uniflora.engine.public_ids import semantic_trigger_aliases, semantic_trigger_id
from uniflora.engine.settlement_events import apply_settlement_event
from uniflora.engine.validation import ValidationContext, ValidationDecision
from uniflora.runtime import Environment


def position_zero_proposal_guidance(
    state: dict[str, Any], definition: PuzzleDefinition
) -> str | None:
    """Return concise proposal help only after every deterministic prerequisite is public."""
    constraints = definition.sustainability
    reconstruction = definition.reconstruction
    relational = definition.relational_requirements
    if constraints is None or reconstruction is None or relational is None:
        return None
    if state.get("position_completed") or any(
        item.get("status") == "pending" for item in state.get("proposals", {}).values()
    ):
        return None
    if not set(reconstruction.required_observations).issubset(
        state.get("unlocked_observations", [])
    ):
        return None
    if not any(
        item.get("pathway_id") == constraints.pathway_entity_id
        for item in state.get("connections", [])
    ):
        return None
    contributions = current_cycle_contributions(state)
    participants = {item.get("participant_id") for item in contributions}
    functions = {item.get("function") for item in contributions}
    if (
        len(participants) < relational.minimum_distinct_users
        or len(functions) < relational.minimum_distinct_functions
    ):
        return None
    donor = state.get("resources", {}).get(constraints.donor_entity_id, {})
    recipient = state.get("resources", {}).get(constraints.recipient_entity_id, {})
    donor_units = float(donor.get(constraints.resource_id, 0))
    recipient_units = float(recipient.get(constraints.resource_id, 0))
    amount = constraints.minimum_recipient_viability - recipient_units
    if amount <= 0 or donor_units - amount < constraints.minimum_donor_reserve:
        return None
    return (
        "**Position 0 is ready for a proposal.**\n"
        "Sorry—the valid maintenance choices were not explained earlier. The `maintenance` "
        "field takes one short choice; no sentence is required.\n"
        "Enter `/interior act reconstruct`, then use:\n"
        f"`donor:north` · `recipient:east` · `resource:water` · `amount:{amount:g}`\n"
        "`pathway:path` · `pathway_action:repair` · `maintenance:monitor`\n"
        "After Hypha returns a proposal ID, a different participant confirms it with "
        "`/interior act confirm proposal_id:<id>`."
    )


class EnvironmentPositionValidator:
    """Routes each environment to the validator for its current complete position."""

    def __init__(
        self,
        content: PuzzleDefinition | PuzzleRegistry,
        *,
        enforce_cycles: bool = True,
        settlement_events: bool = False,
        settlement_event_response_minutes: int = 120,
    ) -> None:
        definitions = (
            {item.position: item for item in content.all()}
            if isinstance(content, PuzzleRegistry)
            else {content.position: content}
        )
        self._definitions = {environment: dict(definitions) for environment in Environment}
        self.enforce_cycles = enforce_cycles
        self.settlement_events = settlement_events
        self.settlement_event_response_minutes = settlement_event_response_minutes
        self._validators = {
            environment: self._build_validators(definitions) for environment in Environment
        }

    @staticmethod
    def _build_validators(definitions: dict[int, PuzzleDefinition]) -> dict[int, object]:
        validators: dict[int, object] = {}
        position_zero = definitions.get(0)
        if position_zero is not None and position_zero.status.value == "complete":
            validators[0] = PositionZeroValidator(position_zero)
        position_one = definitions.get(1)
        if position_one is not None and position_one.status.value == "complete":
            validators[1] = PositionOneValidator(position_one)
        position_two = definitions.get(2)
        if position_two is not None and position_two.status.value == "complete":
            validators[2] = PositionTwoValidator(position_two)
        for position in range(3, 7):
            definition = definitions.get(position)
            if definition is not None and definition.status.value == "complete":
                validators[position] = ProvisionArcValidator(definition)
        return validators

    def initialize_position(
        self, environment: Environment, position: int, previous: dict[str, Any]
    ) -> dict[str, Any] | None:
        validator = self._validators[environment].get(position)
        initializer = getattr(validator, "initialize_from_previous", None)
        if callable(initializer):
            return initializer(previous)
        return None

    def upgrade_position(
        self, environment: Environment, position: int, current: dict[str, Any]
    ) -> dict[str, Any] | None:
        validator = self._validators[environment].get(position)
        upgrader = getattr(validator, "upgrade_existing_state", None)
        if callable(upgrader):
            return upgrader(current)
        return None

    def set_definition(self, environment: Environment, definition: PuzzleDefinition) -> None:
        definitions = dict(self._definitions[environment])
        definitions[definition.position] = definition
        self._definitions[environment] = definitions
        self._validators[environment] = self._build_validators(definitions)

    def set_registry(self, environment: Environment, registry: PuzzleRegistry) -> None:
        definitions = {item.position: item for item in registry.all()}
        self._definitions[environment] = definitions
        self._validators[environment] = self._build_validators(definitions)

    def validate(self, action: CandidateAction, context: ValidationContext) -> ValidationDecision:
        validator = self._validators[context.environment].get(context.current_position)
        if validator is None:
            return ValidationDecision(
                False,
                "content_not_loaded",
                public_data={"feedback": "No complete later position is loaded."},
                narration_key="content_not_loaded",
            )
        cycle_context = context
        action_kind = None
        if self.enforce_cycles:
            cycle_context, action_kind, cycle_rejection = prepare_cycle_action(action, context)
            if cycle_rejection is not None:
                return cycle_rejection
        decision = validator.validate(action, cycle_context)  # type: ignore[union-attr]
        if self.enforce_cycles:
            assert action_kind is not None
            decision = apply_cycle_decision(action, cycle_context, action_kind, decision)
        if self.settlement_events:
            decision = apply_settlement_event(
                action,
                cycle_context,
                decision,
                response_minutes=self.settlement_event_response_minutes,
            )
        if not decision.position_completed or decision.next_state is None:
            return decision
        next_position = decision.next_position
        if next_position is None:
            return decision
        initialized = self.initialize_position(
            cycle_context.environment, next_position, decision.next_state
        )
        if initialized is not None:
            return replace(
                decision,
                next_state=(
                    initialize_next_position_cycle(initialized, decision.next_state, next_position)
                    if self.enforce_cycles
                    else initialized
                ),
            )
        return decision


class PositionZeroValidator:
    def __init__(self, definition: PuzzleDefinition) -> None:
        if definition.position != 0:
            raise ValueError("PositionZeroValidator requires Position 0 content")
        self.definition = definition
        self.aliases = definition.entity_aliases()
        self.observations = {observation.id: observation for observation in definition.observations}
        self.observations_by_entity = {
            observation.entity_id: observation for observation in definition.observations
        }

    def upgrade_existing_state(self, previous: dict[str, Any]) -> dict[str, Any]:
        """Add the opening encounter to an active Position 0 without erasing play."""
        state = copy.deepcopy(previous)
        state["content_key"] = self.definition.key
        state["content_version"] = self.definition.content_version
        state.setdefault("settlement_scar", None)
        return state

    def validate(self, action: CandidateAction, context: ValidationContext) -> ValidationDecision:
        # A donor-risk trigger may remain available after Position 0 advances.
        if isinstance(action, UseTriggeredReactionAction):
            decision = self._use_trigger(action, context)
            return (
                self._with_proposal_guidance(decision)
                if context.current_position == 0
                else decision
            )
        if context.current_position != 0:
            return self._reject("content_not_loaded", "No complete later position is loaded.")
        if action.action not in self.definition.allowed_actions:
            return self._reject("invalid_action", "That action is unavailable here.")
        if isinstance(action, OrientLocalAction):
            return self._orient_local(action, context)
        if isinstance(action, AwakenVesselAction):
            return self._awaken_vessel(action, context)
        if isinstance(action, ObserveAction):
            decision = self._observe(action, context)
        elif isinstance(action, ConnectAction):
            decision = self._connect(action, context)
        elif isinstance(action, OfferAction):
            decision = self._offer(action, context)
        elif isinstance(action, RequestSupportAction):
            decision = self._request_support(action, context)
        elif isinstance(action, SummarizeAction):
            decision = self._summarize(action, context)
        elif isinstance(action, ProposeReconstructionAction):
            decision = self._propose(action, context)
        elif isinstance(action, ConfirmReconstructionAction):
            decision = self._confirm(action, context)
        elif isinstance(action, BeginStackAction):
            decision = self._begin_stack(action, context)
        elif isinstance(action, ReactToStackAction):
            decision = self._react_to_stack(action, context)
        elif isinstance(action, ResolveStackAction):
            decision = self._resolve_stack(action, context)
        elif isinstance(action, AddProposalKickerAction):
            decision = self._add_kicker(action, context)
        else:
            decision = self._reject("invalid_action", "That action cannot alter this position.")
        return self._with_proposal_guidance(decision)

    def _with_proposal_guidance(self, decision: ValidationDecision) -> ValidationDecision:
        """Publish the Position 0 proposal instructions once, at the point they are usable."""
        if not decision.accepted or decision.next_state is None or decision.position_completed:
            return decision
        guidance = position_zero_proposal_guidance(decision.next_state, self.definition)
        if guidance is None:
            return decision
        shown = list(decision.next_state.get("shown_guidance", []))
        if "position_zero_proposal_ready" in shown:
            return decision
        state = copy.deepcopy(decision.next_state)
        state["shown_guidance"] = [*shown, "position_zero_proposal_ready"]
        public_data = dict(decision.public_data)
        existing = str(public_data.get("public_text", "")).strip()
        public_data["public_text"] = f"{existing}\n\n{guidance}" if existing else guidance
        return replace(decision, next_state=state, public_data=public_data)

    def _orient_local(
        self, action: OrientLocalAction, context: ValidationContext
    ) -> ValidationDecision:
        del action
        orientation = self.definition.orientation
        assert orientation is not None
        public_text = f"{orientation.local_response} {orientation.specificity_invitation}"
        return ValidationDecision(
            True,
            "local_orientation",
            public_data={"public_text": public_text, "reveal_scope": "local_only"},
            next_state=copy.deepcopy(context.state),
            event_type="orientation.local",
            narration_key=self.definition.narration_keys["orient_local"],
        )

    def _awaken_vessel(
        self, action: AwakenVesselAction, context: ValidationContext
    ) -> ValidationDecision:
        existing = context.state.get("settlement_scar")
        if existing:
            return self._reject(
                "invalid_action",
                "The rootglass seed has already answered. "
                + str(existing.get("public_text", "Its mark remains in the settlement.")),
            )

        name = " ".join(action.name.split())
        outcomes = {
            "plant": (
                "rootglass_garden_crack",
                f"{name} is pressed into the common ground. It roots at once: a green-lit "
                "crack runs across the paving and ends in a new patch of shade.",
            ),
            "open": (
                "rootglass_rain_sail",
                f"{name} is opened over the empty cistern. Its shell unfolds into a pale "
                "rain-sail, riveted permanently above the settlement court.",
            ),
            "keep": (
                "rootglass_empty_socket",
                f"{name} is lifted from the common ground and kept by its finder. The warm, "
                "root-shaped socket it leaves behind will not close.",
            ),
        }
        effect, public_text = outcomes[action.fate]
        state = copy.deepcopy(context.state)
        state["settlement_scar"] = {
            "artifact_id": "rootglass_seed",
            "name": name,
            "fate": action.fate,
            "effect": effect,
            "named_by_participant_id": context.participant_id,
            "public_text": public_text,
        }
        effects = list(state.get("persistent_effects", []))
        if effect not in effects:
            effects.append(effect)
        state["persistent_effects"] = effects
        state["world_flags"] = {
            **state.get("world_flags", {}),
            "rootglass_fate": action.fate,
        }
        return ValidationDecision(
            True,
            "settlement_scar_created",
            public_data={
                "public_text": (
                    f"The rootglass seed accepts the name **{name}**. {public_text}\n"
                    "The settlement will remember this choice."
                )
            },
            next_state=state,
            event_type="settlement.scar_created",
            narration_key=self.definition.narration_keys["action_accepted"],
            contribution_function="first_finder",
            relation_type=f"rootglass_{action.fate}",
        )

    def _observe(self, action: ObserveAction, context: ValidationContext) -> ValidationDecision:
        entity_id = self._resolve(action.entity_id)
        if entity_id is None or entity_id not in self.observations_by_entity:
            return self._reject("invalid_action", "No public observation matches that entity.")
        observation = self.observations_by_entity[entity_id]
        unlocked = list(context.state["unlocked_observations"])
        is_new = observation.id not in unlocked
        state = (
            self._state_with_contribution(
                context.state,
                context.participant_id,
                observation.contribution_function,
                "observe",
            )
            if is_new
            else copy.deepcopy(context.state)
        )
        unlocked = list(state["unlocked_observations"])
        facts = list(state["confirmed_facts"])
        if is_new:
            unlocked.append(observation.id)
            facts.append(
                {
                    "observation_id": observation.id,
                    "fact_key": observation.fact_key,
                    "public_text": observation.public_text,
                }
            )
        state["unlocked_observations"] = unlocked
        state["confirmed_facts"] = facts
        if is_new and observation.id == "eastern_viability_deficit":
            self._append_trigger(
                state,
                context,
                kind="inspect_capacity",
                source_participant_id=context.participant_id,
                observation_id="northern_usable_capacity",
            )
        return ValidationDecision(
            True,
            "observation_unlocked" if is_new else "observation_corroborated",
            public_data={
                "public_text": observation.public_text,
                "observation_id": observation.id,
                "is_new": is_new,
            },
            next_state=state,
            event_type="observation.unlocked" if is_new else "observation.corroborated",
            narration_key=(
                self.definition.narration_keys["observe_new"]
                if is_new
                else self.definition.narration_keys["observe_repeat"]
            ),
            contribution_function=observation.contribution_function if is_new else None,
            unlocked_observation_key=observation.id if is_new else None,
        )

    def _connect(self, action: ConnectAction, context: ValidationContext) -> ValidationDecision:
        constraints = self.definition.sustainability
        assert constraints is not None
        source = self._resolve(action.source_entity_id)
        target = self._resolve(action.target_entity_id)
        pair = {source, target}
        expected = {constraints.donor_entity_id, constraints.recipient_entity_id}
        if pair != expected or "circulation_break" not in context.state["unlocked_observations"]:
            return self._reject(
                "invalid_action", "No confirmed public pathway supports that connection yet."
            )
        state = self._state_with_contribution(
            context.state, context.participant_id, "binder", "connect"
        )
        connection = {
            "source": constraints.donor_entity_id,
            "target": constraints.recipient_entity_id,
            "pathway_id": constraints.pathway_entity_id,
            "pathway_action": "repair",
            "participant_id": context.participant_id,
        }
        state["connections"] = [*state["connections"], connection]
        self._append_trigger(
            state,
            context,
            kind="test_route",
            source_participant_id=context.participant_id,
            pathway_id=constraints.pathway_entity_id,
        )
        return ValidationDecision(
            True,
            "accepted",
            public_data={"public_text": "A repair relation for the damaged path is recorded."},
            next_state=state,
            event_type="pathway.repair_contributed",
            narration_key=self.definition.narration_keys["action_accepted"],
            contribution_function="binder",
            relational_target=constraints.recipient_entity_id,
            relation_type="pathway_repair",
        )

    def _offer(self, action: OfferAction, context: ValidationContext) -> ValidationDecision:
        constraints = self.definition.sustainability
        assert constraints is not None
        target = self._resolve(action.target_entity_id or "")
        if action.resource_id.lower() != constraints.resource_id or target != (
            constraints.recipient_entity_id
        ):
            return self._reject("invalid_action", "That offer does not match a confirmed need.")
        required = {"northern_usable_capacity", "eastern_viability_deficit"}
        if not required.issubset(context.state["unlocked_observations"]):
            return self._reject(
                "invalid_action", "Capacity and need must be publicly observed before an offer."
            )
        donor_units = context.state["resources"][constraints.donor_entity_id][
            constraints.resource_id
        ]
        if donor_units - action.amount < constraints.minimum_donor_reserve:
            return self._reject(
                "proposal_rejected", "The offered amount would exhaust maintained donor reserve."
            )
        state = self._state_with_contribution(
            context.state, context.participant_id, "carrier", "offer"
        )
        state["offers"] = [
            *state["offers"],
            {
                "donor_id": constraints.donor_entity_id,
                "recipient_id": target,
                "resource_id": constraints.resource_id,
                "amount": action.amount,
                "participant_id": context.participant_id,
            },
        ]
        return ValidationDecision(
            True,
            "accepted",
            public_data={"public_text": "A sustainable resource offer is recorded publicly."},
            next_state=state,
            event_type="resource.offer_recorded",
            narration_key=self.definition.narration_keys["action_accepted"],
            contribution_function="carrier",
            relational_target=target,
            relation_type="resource_offer",
        )

    def _request_support(
        self, action: RequestSupportAction, context: ValidationContext
    ) -> ValidationDecision:
        accepted_ids = {"eastern_viability_deficit", "eastern_growth", "east", "growth"}
        if (
            action.need_id.lower() not in accepted_ids
            or "eastern_viability_deficit" not in (context.state["unlocked_observations"])
        ):
            return self._reject("invalid_action", "That need is not in the confirmed record.")
        state = self._state_with_contribution(
            context.state, context.participant_id, "cultivator", "request_support"
        )
        state["support_requests"] = [
            *state["support_requests"],
            {
                "need_id": "eastern_viability_deficit",
                "amount": action.amount,
                "participant_id": context.participant_id,
            },
        ]
        return ValidationDecision(
            True,
            "accepted",
            public_data={"public_text": "The eastern viability need is named publicly."},
            next_state=state,
            event_type="support.requested",
            narration_key=self.definition.narration_keys["action_accepted"],
            contribution_function="cultivator",
        )

    def _summarize(self, action: SummarizeAction, context: ValidationContext) -> ValidationDecision:
        del action
        facts = context.state["confirmed_facts"]
        if not facts:
            return self._reject(
                "invalid_action", "There are no confirmed discoveries to summarize."
            )
        public_text = " ".join(fact["public_text"] for fact in facts)
        state = self._state_with_contribution(
            context.state, context.participant_id, "witness", "summarize"
        )
        state["summaries"] = [
            *state["summaries"],
            {"public_text": public_text, "participant_id": context.participant_id},
        ]
        return ValidationDecision(
            True,
            "accepted",
            public_data={"public_text": public_text},
            next_state=state,
            event_type="summary.recorded",
            narration_key=self.definition.narration_keys["action_accepted"],
            contribution_function="witness",
            summary_projection={"summary_kind": "confirmed_public", "public_text": public_text},
        )

    def _begin_stack(
        self, action: BeginStackAction, context: ValidationContext
    ) -> ValidationDecision:
        tactical = self.definition.tactical
        constraints = self.definition.sustainability
        assert tactical and constraints
        current = context.state.get("public_stack")
        if current and current.get("status") == "open":
            return self._reject("invalid_action", "A public stack is already open.")
        proposal = dict(action.proposal)
        required = {
            "donor_id",
            "recipient_id",
            "resource_id",
            "amount",
            "pathway_id",
            "pathway_action",
            "maintenance_condition",
        }
        if required - proposal.keys():
            return self._reject("invalid_action", "The base proposal is incomplete.")
        if (
            self._resolve(str(proposal["donor_id"])) != constraints.donor_entity_id
            or self._resolve(str(proposal["recipient_id"])) != constraints.recipient_entity_id
            or self._resolve(str(proposal["pathway_id"])) != constraints.pathway_entity_id
            or str(proposal["resource_id"]).lower() != constraints.resource_id
        ):
            return self._reject(
                "invalid_action", "The base proposal does not use known public entities."
            )
        try:
            amount = float(proposal["amount"])
        except (TypeError, ValueError):
            return self._reject("invalid_action", "The proposed amount must be numeric.")
        if not math.isfinite(amount) or amount <= 0:
            return self._reject("invalid_action", "The proposed amount must be positive.")
        proposal["amount"] = amount
        stack_id = self._public_id("s", context.session_id, context.action_id)
        state = self._state_with_contribution(
            context.state, context.participant_id, "synthesizer", "begin_stack"
        )
        state["public_stack"] = {
            "stack_id": stack_id,
            "status": "open",
            "base": {
                "participant_id": context.participant_id,
                "proposal": proposal,
            },
            "entries": [
                {
                    "kind": "proposal",
                    "participant_id": context.participant_id,
                    "label": "attempt transfer",
                }
            ],
        }
        return ValidationDecision(
            True,
            "stack_opened",
            public_data={
                "public_text": (
                    f"Public stack `{stack_id}` is open (1/{tactical.max_stack_depth}). "
                    "The proposal is entering resolution; one objection, amendment, or "
                    "safeguard may be added at a time."
                ),
                "stack_id": stack_id,
            },
            next_state=state,
            event_type="stack.opened",
            narration_key=self.definition.narration_keys["action_accepted"],
            contribution_function="synthesizer",
        )

    def _react_to_stack(
        self, action: ReactToStackAction, context: ValidationContext
    ) -> ValidationDecision:
        tactical = self.definition.tactical
        assert tactical
        stack = context.state.get("public_stack")
        if not stack or stack.get("status") != "open" or stack.get("stack_id") != action.stack_id:
            return self._reject("invalid_action", "No open public stack matches that ID.")
        entries = list(stack["entries"])
        if len(entries) >= tactical.max_stack_depth:
            return self._reject("invalid_action", "The public stack has reached its depth limit.")
        if action.reaction not in tactical.allowed_stack_reactions:
            return self._reject("invalid_action", "That reaction is unavailable here.")
        if any(item["participant_id"] == context.participant_id for item in entries):
            return self._reject(
                "invalid_action", "Each participant may add only one entry to this stack."
            )
        if action.reaction in {"object_pathway", "repair_pathway", "reassess_pathway"} and (
            "circulation_break" not in context.state["unlocked_observations"]
        ):
            return self._reject(
                "invalid_action", "The damaged pathway must be confirmed before that reaction."
            )
        if action.reaction == "sustain" and not self._is_maintenance(action.detail):
            return self._reject(
                "invalid_action", "Sustain must name a monitoring or reassessment condition."
            )
        functions = {
            "object_pathway": "auditor",
            "repair_pathway": "maintainer",
            "reassess_pathway": "observer",
            "sustain": "maintainer",
            "mitigate_donor": "counterweight",
        }
        labels = {
            "object_pathway": "reassess route objection",
            "repair_pathway": "repair route",
            "reassess_pathway": "reassess route",
            "sustain": "add monitoring",
            "mitigate_donor": "protect donor",
        }
        state = self._state_with_contribution(
            context.state,
            context.participant_id,
            functions[action.reaction],
            "react_to_stack",
        )
        updated_stack = copy.deepcopy(stack)
        updated_stack["entries"] = [
            *entries,
            {
                "kind": "reaction",
                "participant_id": context.participant_id,
                "reaction": action.reaction,
                "detail": action.detail.strip(),
                "label": labels[action.reaction],
            },
        ]
        state["public_stack"] = updated_stack
        remaining = tactical.max_stack_depth - len(updated_stack["entries"])
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
        constraints = self.definition.sustainability
        assert constraints
        stack = context.state.get("public_stack")
        if not stack or stack.get("status") != "open" or stack.get("stack_id") != action.stack_id:
            return self._reject("invalid_action", "No open public stack matches that ID.")
        working = copy.deepcopy(context.state)
        updated_stack = copy.deepcopy(stack)
        resolution_labels: list[str] = []
        repaired = any(
            item.get("pathway_id") == constraints.pathway_entity_id
            for item in working["connections"]
        )
        blocked: str | None = None
        stack_kickers: list[dict[str, str]] = []
        for entry in reversed(stack["entries"][1:]):
            reaction = entry["reaction"]
            if reaction == "repair_pathway":
                repaired = True
                resolution_labels.append("repair route")
                if not any(
                    item.get("pathway_id") == constraints.pathway_entity_id
                    for item in working["connections"]
                ):
                    working["connections"] = [
                        *working["connections"],
                        {
                            "source": constraints.donor_entity_id,
                            "target": constraints.recipient_entity_id,
                            "pathway_id": constraints.pathway_entity_id,
                            "pathway_action": "repair",
                            "participant_id": entry["participant_id"],
                        },
                    ]
                    self._append_trigger(
                        working,
                        context,
                        kind="test_route",
                        source_participant_id=entry["participant_id"],
                        pathway_id=constraints.pathway_entity_id,
                    )
            elif reaction == "object_pathway":
                resolution_labels.append("reassess route")
                if not repaired:
                    blocked = "The route objection resolved before any repair."
            elif reaction == "reassess_pathway":
                resolution_labels.append("reassess route")
                if not repaired:
                    blocked = "The route could not be reassessed as functional before repair."
            elif reaction == "sustain":
                resolution_labels.append("add monitoring")
                stack_kickers.append(
                    {
                        "kicker": "monitoring",
                        "participant_id": entry["participant_id"],
                        "detail": entry["detail"],
                    }
                )
            elif reaction == "mitigate_donor":
                resolution_labels.append("protect donor")
                stack_kickers.append(
                    {
                        "kicker": "protect_donor",
                        "participant_id": entry["participant_id"],
                        "detail": entry["detail"],
                    }
                )
        resolution_labels.append("attempt transfer")
        summary = "Resolution order: " + " -> ".join(resolution_labels) + "."
        if blocked:
            return self._failed_stack_resolution(working, updated_stack, context, summary, blocked)

        base = stack["base"]
        proposal = dict(base["proposal"])
        if stack_kickers and not self._is_maintenance(str(proposal["maintenance_condition"])):
            proposal["maintenance_condition"] = (
                stack_kickers[0]["detail"] or "monitor after transfer"
            )
        synthetic_context = ValidationContext(
            environment=context.environment,
            session_id=context.session_id,
            participant_id=base["participant_id"],
            action_id=f"{context.action_id}:stack-proposal",
            current_position=context.current_position,
            response_profile=context.response_profile,
            state=working,
        )
        proposed = self._propose(
            ProposeReconstructionAction(action="propose_reconstruction", proposal=proposal),
            synthetic_context,
        )
        if not proposed.accepted or proposed.next_state is None:
            feedback = str(proposed.public_data.get("feedback", "The proposal could not resolve."))
            return self._failed_stack_resolution(working, updated_stack, context, summary, feedback)
        state = proposed.next_state
        if state["contributions"] and state["contributions"][-1].get("action") == (
            "propose_reconstruction"
        ):
            state["contributions"] = state["contributions"][:-1]
        projection = copy.deepcopy(proposed.proposal_projection)
        assert projection is not None
        proposal_id = str(projection["id"])
        normalized = dict(state["proposals"][proposal_id])
        normalized["kickers"] = stack_kickers
        state["proposals"] = {**state["proposals"], proposal_id: normalized}
        projection["proposal_data"] = normalized
        updated_stack["status"] = "resolved"
        updated_stack["resolution_order"] = resolution_labels
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
            proposal_projection=projection,
        )

    def _failed_stack_resolution(
        self,
        state: dict[str, Any],
        stack: dict[str, Any],
        context: ValidationContext,
        summary: str,
        feedback: str,
    ) -> ValidationDecision:
        stack["status"] = "failed"
        stack["resolution_order"] = (
            summary.removeprefix("Resolution order: ").removesuffix(".").split(" -> ")
        )
        state["public_stack"] = stack
        counters = copy.deepcopy(state.get("counters", {}))
        counters["instability"] = int(counters.get("instability", 0)) + 1
        state["counters"] = counters
        missing = next(
            (
                item
                for item in self.definition.reconstruction.required_observations
                if item not in state["unlocked_observations"]
            ),
            None,
        )
        self._append_trigger(
            state,
            context,
            kind="salvage_observation",
            source_participant_id=context.participant_id,
            observation_id=missing,
        )
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
        tactical = self.definition.tactical
        assert tactical
        proposal = context.state["proposals"].get(action.proposal_id)
        if proposal is None or proposal.get("status") != "pending":
            return self._reject("invalid_action", "No pending public proposal matches that ID.")
        if action.kicker not in tactical.allowed_kickers:
            return self._reject("invalid_action", "That optional proposal cost is unavailable.")
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
        functions = {
            "monitoring": "maintainer",
            "protect_donor": "counterweight",
            "document": "archivist",
        }
        state = self._state_with_contribution(
            context.state,
            context.participant_id,
            functions[action.kicker],
            "add_proposal_kicker",
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
        state["proposals"] = {**state["proposals"], action.proposal_id: updated}
        return ValidationDecision(
            True,
            "kicker_added",
            public_data={
                "public_text": (
                    f"{action.kicker.replace('_', ' ').title()} is attached to "
                    f"proposal `{action.proposal_id}`."
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

    def _propose(
        self, action: ProposeReconstructionAction, context: ValidationContext
    ) -> ValidationDecision:
        constraints = self.definition.sustainability
        reconstruction = self.definition.reconstruction
        relational = self.definition.relational_requirements
        assert constraints and reconstruction and relational
        proposal = dict(action.proposal)
        missing_fields = set(reconstruction.required_fields) - proposal.keys()
        if missing_fields:
            return self._reject(
                "proposal_rejected", "The proposal omits one or more required public relations."
            )
        if not set(reconstruction.required_observations).issubset(
            context.state["unlocked_observations"]
        ):
            return self._reject(
                "proposal_rejected", "Need, capacity, and pathway must all be publicly observed."
            )
        donor = self._resolve(str(proposal["donor_id"]))
        recipient = self._resolve(str(proposal["recipient_id"]))
        pathway = self._resolve(str(proposal["pathway_id"]))
        resource = str(proposal["resource_id"]).lower()
        pathway_action = str(proposal["pathway_action"]).lower()
        try:
            amount = float(proposal["amount"])
        except (TypeError, ValueError):
            return self._reject("proposal_rejected", "The proposed amount must be numeric.")
        if not math.isfinite(amount) or amount <= 0:
            return self._reject("proposal_rejected", "The proposed amount must be positive.")
        if (
            donor != constraints.donor_entity_id
            or recipient != constraints.recipient_entity_id
            or pathway != constraints.pathway_entity_id
            or resource != constraints.resource_id
        ):
            return self._reject(
                "proposal_rejected",
                "The proposal does not align with the confirmed public relation.",
            )
        if pathway_action not in constraints.allowed_pathway_actions:
            return self._reject(
                "proposal_rejected", "The damaged pathway is not repaired or accounted for."
            )
        connection_exists = any(
            connection["pathway_id"] == constraints.pathway_entity_id
            for connection in context.state["connections"]
        )
        if not connection_exists:
            return self._reject(
                "proposal_rejected", "A public pathway-repair contribution is still missing."
            )
        donor_before = context.state["resources"][donor][resource]
        recipient_before = context.state["resources"][recipient][resource]
        donor_after = donor_before - amount
        recipient_after = recipient_before + amount
        tactical = self.definition.tactical
        assert tactical
        strain = int(context.state.get("counters", {}).get("strain", {}).get(donor, 0))
        reserve_penalty = (strain // tactical.strain_threshold) * tactical.strain_reserve_penalty
        effective_reserve = constraints.minimum_donor_reserve + reserve_penalty
        if donor_after < effective_reserve:
            return self._reject(
                "proposal_rejected",
                "The transfer would exhaust the donor's strain-adjusted maintained reserve.",
            )
        if recipient_after < constraints.minimum_recipient_viability:
            return self._reject(
                "proposal_rejected", "The recipient would remain below minimum viability."
            )
        maintenance = str(proposal["maintenance_condition"]).strip()
        if len(maintenance) > 500:
            return self._reject("proposal_rejected", "The maintenance condition is too long.")
        if not any(term in maintenance.lower() for term in reconstruction.maintenance_terms):
            return self._reject(
                "proposal_rejected",
                "The proposal needs a future reassessment condition. Set `maintenance` to "
                "`monitor` (or reassess, check, review, measure, revisit, or maintain); one "
                "word is enough.",
            )
        contributions = current_cycle_contributions(context.state)
        participants = {item["participant_id"] for item in contributions}
        functions = {item["function"] for item in contributions}
        participants.add(context.participant_id)
        functions.add("synthesizer")
        if len(participants) < relational.minimum_distinct_users:
            return self._reject(
                "proposal_rejected", "At least three distinct public participants are required."
            )
        if len(functions) < relational.minimum_distinct_functions:
            return self._reject(
                "proposal_rejected", "At least three distinct contribution functions are required."
            )
        proposal_seed = f"{context.session_id}:{context.action_id}"
        proposal_id = "p-" + hashlib.sha256(proposal_seed.encode()).hexdigest()[:12]
        normalized = {
            "proposal_id": proposal_id,
            "author_participant_id": context.participant_id,
            "donor_id": donor,
            "recipient_id": recipient,
            "resource_id": resource,
            "amount": amount,
            "pathway_id": pathway,
            "pathway_action": pathway_action,
            "maintenance_condition": maintenance,
            "donor_after": donor_after,
            "recipient_after": recipient_after,
            "status": "pending",
            "kickers": [],
        }
        state = self._state_with_contribution(
            context.state, context.participant_id, "synthesizer", "propose_reconstruction"
        )
        proposals = dict(state["proposals"])
        proposals[proposal_id] = normalized
        state["proposals"] = proposals
        return ValidationDecision(
            True,
            "proposal_accepted",
            public_data={
                "public_text": (
                    f"Proposal `{proposal_id}` preserves {donor_after:g} donor units, restores "
                    f"the recipient to {recipient_after:g}, accounts for the pathway, and awaits "
                    "non-author confirmation."
                ),
                "proposal_id": proposal_id,
            },
            next_state=state,
            event_type="reconstruction.proposed",
            narration_key=self.definition.narration_keys["proposal_accepted"],
            contribution_function="synthesizer",
            proposal_projection={
                "id": proposal_id,
                "author_participant_id": context.participant_id,
                "status": "pending",
                "proposal_data": normalized,
            },
        )

    def _confirm(
        self, action: ConfirmReconstructionAction, context: ValidationContext
    ) -> ValidationDecision:
        proposals = dict(context.state["proposals"])
        proposal = proposals.get(action.proposal_id)
        if proposal is None or proposal["status"] != "pending":
            return self._reject("invalid_action", "No pending public proposal matches that ID.")
        if proposal["author_participant_id"] == context.participant_id:
            return self._reject(
                "invalid_action", "A reconstruction must be confirmed by a non-author."
            )
        if any(
            item["proposal_id"] == action.proposal_id
            and item["participant_id"] == context.participant_id
            for item in context.state["confirmations"]
        ):
            return self._reject(
                "invalid_action", "That participant already confirmed this proposal."
            )
        state = self._state_with_contribution(
            context.state, context.participant_id, "witness", "confirm_reconstruction"
        )
        confirmation = {
            "proposal_id": action.proposal_id,
            "participant_id": context.participant_id,
        }
        state["confirmations"] = [*state["confirmations"], confirmation]
        proposal = dict(proposal)
        proposal["status"] = "confirmed"
        proposals[action.proposal_id] = proposal
        state["proposals"] = proposals
        resources = copy.deepcopy(state["resources"])
        resources[proposal["donor_id"]][proposal["resource_id"]] = proposal["donor_after"]
        resources[proposal["recipient_id"]][proposal["resource_id"]] = proposal["recipient_after"]
        state["resources"] = resources
        kicker_types = {item["kicker"] for item in proposal.get("kickers", [])}
        counters = copy.deepcopy(state.get("counters", {}))
        strain = dict(counters.get("strain", {}))
        strain_delta = 0 if "protect_donor" in kicker_types else 1
        strain[proposal["donor_id"]] = int(strain.get(proposal["donor_id"], 0)) + strain_delta
        counters["strain"] = strain
        if "document" in kicker_types:
            counters["coherence"] = int(counters.get("coherence", 0)) + 1
        state["counters"] = counters
        effects = list(state.get("persistent_effects", []))
        if "monitoring" in kicker_types and "moisture_monitoring_mesh" not in effects:
            effects.append("moisture_monitoring_mesh")
        tactical = self.definition.tactical
        assert tactical
        if (
            int(counters.get("coherence", 0)) >= tactical.coherence_threshold
            and "shared_archive" not in effects
        ):
            effects.append("shared_archive")
        state["persistent_effects"] = effects
        self._append_trigger(
            state,
            context,
            kind="risk_check",
            source_participant_id=proposal["author_participant_id"],
            donor_id=proposal["donor_id"],
            excluded_participant_ids=(
                proposal["author_participant_id"],
                context.participant_id,
            ),
        )
        flags = dict(state["world_flags"])
        flags.update(self.definition.completion.world_flags)
        state["world_flags"] = flags
        state["position_completed"] = True
        return ValidationDecision(
            True,
            "position_completed",
            public_data={
                "public_text": (
                    "Position 0 complete. Need, sustainable capacity, repaired circulation, "
                    "shared contribution, and future reassessment now form one maintained relation."
                    + (
                        " Optional safeguards persist: "
                        + ", ".join(sorted(item.replace("_", " ") for item in kicker_types))
                        + "."
                        if kicker_types
                        else ""
                    )
                )
            },
            next_state=state,
            event_type="position.completed",
            narration_key=self.definition.narration_keys["position_completed"],
            contribution_function="witness",
            position_completed=True,
            next_position=self.definition.completion.next_position,
            next_response_profile=self.definition.completion.response_profile,
            confirmation_projection=confirmation,
            proposal_status_update={
                "proposal_id": action.proposal_id,
                "status": "confirmed",
            },
            world_flag_projections=self.definition.completion.world_flags,
        )

    def _use_trigger(
        self, action: UseTriggeredReactionAction, context: ValidationContext
    ) -> ValidationDecision:
        reactions = list(context.state.get("triggered_reactions", []))
        trigger = next(
            (
                item
                for item in reactions
                if item["trigger_id"] == action.trigger_id and not item.get("consumed", False)
            ),
            None,
        )
        if trigger is None:
            return self._reject("invalid_action", "No available public trigger matches that ID.")
        excluded = set(trigger.get("excluded_participant_ids", []))
        excluded.add(trigger["source_participant_id"])
        if context.participant_id in excluded:
            return self._reject(
                "invalid_action", "This reaction must be taken by another participant."
            )
        kind = trigger["kind"]
        if kind in {"inspect_capacity", "salvage_observation"} and trigger.get("observation_id"):
            observation = next(
                item
                for item in self.definition.observations
                if item.id == trigger["observation_id"]
            )
            observed = self._observe(
                ObserveAction(action="observe", entity_id=observation.entity_id), context
            )
            assert observed.next_state is not None
            state = observed.next_state
            self._consume_trigger(state, action.trigger_id, context.participant_id)
            prefix = (
                "Triggered capacity inspection: "
                if kind == "inspect_capacity"
                else "A failed proposal yields one useful observation: "
            )
            return ValidationDecision(
                True,
                "trigger_resolved",
                public_data={"public_text": prefix + observation.public_text},
                next_state=state,
                event_type="trigger.resolved",
                narration_key=self.definition.narration_keys["action_accepted"],
                contribution_function=observed.contribution_function,
                unlocked_observation_key=observed.unlocked_observation_key,
            )
        state = copy.deepcopy(context.state)
        self._consume_trigger(state, action.trigger_id, context.participant_id)
        if kind == "test_route":
            tactical = self.definition.tactical
            assert tactical
            pathway_id = trigger["pathway_id"]
            counters = copy.deepcopy(state.get("counters", {}))
            repair = dict(counters.get("repair", {}))
            repair[pathway_id] = int(repair.get(pathway_id, 0)) + 1
            counters["repair"] = repair
            state["counters"] = counters
            effects = list(state.get("persistent_effects", []))
            reinforced = repair[pathway_id] >= tactical.repair_threshold
            if reinforced and "route_reinforced" not in effects:
                effects.append("route_reinforced")
            state["persistent_effects"] = effects
            text = f"The repaired route passes public test {repair[pathway_id]}."
            if reinforced:
                text += " Its maintenance threshold is met; Route Reinforced persists."
            function = "observer"
        elif kind == "risk_check":
            donor_id = trigger["donor_id"]
            strain = int(state.get("counters", {}).get("strain", {}).get(donor_id, 0))
            text = f"Risk check: `{donor_id}` currently carries {strain} strain counter(s)."
            function = "auditor"
        else:
            text = "The failed sequence is preserved as a useful public timing observation."
            function = "archivist"
        state = self._state_with_contribution(
            state, context.participant_id, function, "use_triggered_reaction"
        )
        return ValidationDecision(
            True,
            "trigger_resolved",
            public_data={"public_text": text},
            next_state=state,
            event_type="trigger.resolved",
            narration_key=self.definition.narration_keys["action_accepted"],
            contribution_function=function,
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
        donor_id: str | None = None,
        excluded_participant_ids: tuple[str, ...] = (),
    ) -> None:
        reactions = list(state.get("triggered_reactions", []))
        del context
        observation = self.observations.get(observation_id or "")
        subject = observation.entity_id if observation is not None else pathway_id or donor_id
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
                "excluded_participant_ids": list(excluded_participant_ids),
                "observation_id": observation_id,
                "pathway_id": pathway_id,
                "donor_id": donor_id,
                "consumed": False,
            }
        )
        state["triggered_reactions"] = reactions

    @staticmethod
    def _consume_trigger(state: dict[str, Any], trigger_id: str, participant_id: str) -> None:
        reactions = []
        for item in state.get("triggered_reactions", []):
            updated = dict(item)
            if updated["trigger_id"] == trigger_id:
                updated["consumed"] = True
                updated["consumed_by"] = participant_id
            reactions.append(updated)
        state["triggered_reactions"] = reactions

    def _is_maintenance(self, detail: str) -> bool:
        reconstruction = self.definition.reconstruction
        assert reconstruction
        lowered = detail.strip().lower()
        return bool(lowered) and any(term in lowered for term in reconstruction.maintenance_terms)

    @staticmethod
    def _public_id(prefix: str, *parts: str) -> str:
        seed = ":".join(parts)
        return f"{prefix}-" + hashlib.sha256(seed.encode()).hexdigest()[:12]

    def _resolve(self, value: str) -> str | None:
        return self.aliases.get(value.strip().lower())

    @staticmethod
    def _state_with_contribution(
        state: dict[str, Any], participant_id: str, function: str, action: str
    ) -> dict[str, Any]:
        updated = copy.deepcopy(state)
        updated["contributions"] = [
            *updated["contributions"],
            {"participant_id": participant_id, "function": function, "action": action},
        ]
        return updated

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
