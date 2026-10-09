from __future__ import annotations

import copy
import hashlib
from typing import Any

from uniflora.content.schema import ObservationDefinition, PuzzleDefinition
from uniflora.engine.actions import (
    AddProposalKickerAction,
    AnnotateDifferenceAction,
    BeginStackAction,
    CandidateAction,
    ClarifyRecordAction,
    ClassifyContradictionAction,
    CompareRecordsAction,
    ConfirmReconstructionAction,
    ObserveAction,
    OrientLocalAction,
    ProposeTranslationAction,
    ReactToStackAction,
    RelayRecordAction,
    ResolveStackAction,
    SummarizeAction,
    UseTriggeredReactionAction,
)
from uniflora.engine.cycles import current_cycle_contributions
from uniflora.engine.public_ids import semantic_trigger_aliases, semantic_trigger_id
from uniflora.engine.validation import ValidationContext, ValidationDecision


class PositionTwoValidator:
    """Deterministic public-record translation rules for Position 2."""

    _record_observations = {
        "circulation_ledger": "source_sent_measurement",
        "nursery_intake_sensor": "intake_delivered_measurement",
        "nursery_retention_survey": "survey_retained_measurement",
    }
    _record_terms = {
        "circulation_ledger": "sent",
        "nursery_intake_sensor": "delivered",
        "nursery_retention_survey": "retained",
    }

    def __init__(self, definition: PuzzleDefinition) -> None:
        if definition.position != 2 or definition.translation is None:
            raise ValueError("PositionTwoValidator requires complete Position 2 content")
        self.definition = definition
        self.constraints = definition.translation
        self.aliases = definition.entity_aliases()
        self.observations = {item.id: item for item in definition.observations}
        self.observations_by_entity: dict[str, list[ObservationDefinition]] = {}
        for observation in definition.observations:
            self.observations_by_entity.setdefault(observation.entity_id, []).append(observation)

    def initialize_from_previous(self, previous: dict[str, Any]) -> dict[str, Any]:
        state = self.definition.initial_state()
        state["session_generation"] = int(previous.get("session_generation", 0))
        state["resources"] = {
            **copy.deepcopy(previous.get("resources", {})),
            **state["resources"],
        }
        proposal = next(
            (
                item
                for item in previous.get("proposals", {}).values()
                if item.get("kind") == "circulation" and item.get("status") == "confirmed"
            ),
            {},
        )
        sent = float(proposal.get("source_amount", 9.0))
        support = float(proposal.get("support_amount", 0.0))
        delivered = float(proposal.get("delivered_amount", sent))
        retained = max(0.0, delivered - 1.0)
        state["record_values"] = {
            "circulation_ledger": sent,
            "nursery_intake_sensor": delivered,
            "nursery_retention_survey": retained,
        }
        state["record_provenance"] = {
            "circulation_ledger": {"stage": "source departure", "sequence": 1},
            "nursery_intake_sensor": {"stage": "boundary arrival", "sequence": 2},
            "nursery_retention_survey": {"stage": "post-use remainder", "sequence": 3},
        }
        state["circulation_support_amount"] = support
        state["circulation_strategy"] = str(proposal.get("strategy", "legacy_circulation"))
        counters = copy.deepcopy(state["counters"])
        for key, value in previous.get("counters", {}).items():
            if isinstance(value, dict) and isinstance(counters.get(key), dict):
                counters[key] = {**counters[key], **copy.deepcopy(value)}
            else:
                counters[key] = copy.deepcopy(value)
        state["counters"] = counters
        state["counters"].setdefault("trust", 0)
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
        ]
        state["world_flags"] = {
            **copy.deepcopy(previous.get("world_flags", {})),
            **state["world_flags"],
        }
        state["prior_confirmed_facts"] = copy.deepcopy(previous.get("confirmed_facts", []))
        state["position_history"] = [
            *copy.deepcopy(previous.get("position_history", [])),
            {
                "position": 1,
                "confirmed_facts": copy.deepcopy(previous.get("confirmed_facts", [])),
                "world_flags": copy.deepcopy(previous.get("world_flags", {})),
            },
        ]
        state["prior_position_summary"] = (
            f"Position 1 recorded {sent:g} Veil units, {support:g} protected support units, "
            f"and {delivered:g} delivered units through a maintained, reassessable circulation."
        )
        state["inherited_position"] = 1
        return state

    def upgrade_existing_state(self, previous: dict[str, Any]) -> dict[str, Any]:
        """Apply additive Position 2 content changes without erasing public progress."""

        state = copy.deepcopy(previous)
        fresh = self.definition.initial_state()
        state["content_key"] = self.definition.key
        state["content_version"] = self.definition.content_version
        for key, value in fresh.items():
            state.setdefault(key, copy.deepcopy(value))
        resources = copy.deepcopy(fresh.get("resources", {}))
        for entity_id, values in state.get("resources", {}).items():
            resources[entity_id] = copy.deepcopy(values)
        state["resources"] = resources
        state["world_flags"] = {
            **copy.deepcopy(fresh.get("world_flags", {})),
            **copy.deepcopy(state.get("world_flags", {})),
        }
        counters = copy.deepcopy(fresh.get("counters", {}))
        for key, value in state.get("counters", {}).items():
            counters[key] = copy.deepcopy(value)
        state["counters"] = counters
        return state

    def validate(self, action: CandidateAction, context: ValidationContext) -> ValidationDecision:
        if context.current_position != 2:
            return self._reject(
                "content_not_loaded", "No complete validator matches this position."
            )
        if action.action not in self.definition.allowed_actions:
            return self._reject("invalid_action", "That action is unavailable in Translation.")
        if isinstance(action, OrientLocalAction):
            return self._orient(context)
        if isinstance(action, ObserveAction):
            return self._observe(action, context)
        if isinstance(action, SummarizeAction):
            return self._summarize(action, context)
        if isinstance(action, CompareRecordsAction):
            return self._compare(action, context)
        if isinstance(action, ClarifyRecordAction):
            return self._clarify(action, context)
        if isinstance(action, ClassifyContradictionAction):
            return self._classify(action, context)
        if isinstance(action, RelayRecordAction):
            return self._relay(action, context)
        if isinstance(action, AnnotateDifferenceAction):
            return self._annotate(action, context)
        if isinstance(action, ProposeTranslationAction):
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
        return self._reject("invalid_action", "That action cannot alter Translation yet.")

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
            return self._reject(
                "invalid_action", "No public record or reference matches that name."
            )
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
        state = (
            self._contribute(
                context.state, context.participant_id, observation.contribution_function, "observe"
            )
            if is_new
            else copy.deepcopy(context.state)
        )
        text = self._observation_text(observation.id, state)
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
                    "public_text": text,
                    "classification": self._fact_classification(observation.id),
                    "entity_id": observation.entity_id,
                },
            ]
            if observation.id in self._record_observations.values() and not any(
                item.get("kind") == "inspect_provenance" and not item.get("consumed", False)
                for item in state.get("triggered_reactions", [])
            ):
                self._append_trigger(
                    state,
                    context,
                    "inspect_provenance",
                    context.participant_id,
                    "records_have_distinct_provenance",
                )
        return ValidationDecision(
            True,
            "observation_unlocked" if is_new else "observation_corroborated",
            public_data={"public_text": text, "observation_id": observation.id},
            next_state=state,
            event_type="translation.observation_unlocked" if is_new else "translation.corroborated",
            narration_key=self.definition.narration_keys[
                "observe_new" if is_new else "observe_repeat"
            ],
            contribution_function=observation.contribution_function if is_new else None,
            unlocked_observation_key=observation.id if is_new else None,
        )

    def _summarize(self, action: SummarizeAction, context: ValidationContext) -> ValidationDecision:
        del action
        facts = context.state.get("confirmed_facts", [])
        if not facts:
            return self._reject("invalid_action", "No Translation observations are public yet.")
        text = "Public Translation record:\n" + "\n".join(
            f"• {item['public_text']}" for item in facts
        )
        state = self._contribute(
            context.state, context.participant_id, "public_editor", "summarize"
        )
        state["summaries"] = [
            *state.get("summaries", []),
            {"participant_id": context.participant_id, "public_text": text},
        ]
        return ValidationDecision(
            True,
            "accepted",
            public_data={"public_text": text},
            next_state=state,
            event_type="translation.summarized",
            narration_key=self.definition.narration_keys["action_accepted"],
            contribution_function="public_editor",
            summary_projection={"public_text": text, "source_event_ids": []},
        )

    def _compare(
        self, action: CompareRecordsAction, context: ValidationContext
    ) -> ValidationDecision:
        pair = self._record_pair(action.record_a, action.record_b)
        if pair is None:
            return self._reject("invalid_action", "Compare two distinct Translation records.")
        if not self._records_public(context.state, pair):
            return self._reject(
                "invalid_action", "Both records must be observed before comparison."
            )
        prior_pairs = {tuple(item["records"]) for item in context.state.get("comparisons", [])}
        if pair in prior_pairs:
            return self._reject("invalid_action", "That record pair is already compared publicly.")
        state = self._contribute(
            context.state, context.participant_id, "record_comparator", "compare_records"
        )
        values = state["record_values"]
        first, second = pair
        item = {
            "records": list(pair),
            "participant_id": context.participant_id,
            "values": [float(values[first]), float(values[second])],
        }
        state["comparisons"] = [*state.get("comparisons", []), item]
        return self._accepted(
            state,
            f"Comparison retained: {self._record_terms[first]}={values[first]:g}; "
            f"{self._record_terms[second]}={values[second]:g}. Their provenance remains distinct.",
            "translation.records_compared",
            "record_comparator",
        )

    def _clarify(
        self, action: ClarifyRecordAction, context: ValidationContext
    ) -> ValidationDecision:
        record = self._record(action.record_id)
        term = action.term.strip().lower()
        if record is None or term not in self.constraints.mapping_terms:
            return self._reject(
                "invalid_action", "Clarify a known record with sent, delivered, or retained."
            )
        if self._record_observations[record] not in context.state.get("unlocked_observations", []):
            return self._reject("invalid_action", "Observe that record before clarifying its term.")
        if "stage_term_mapping" not in context.state.get("unlocked_observations", []):
            return self._reject("invalid_action", "The Archive Glossary must be public first.")
        expected = self._record_terms[record]
        if term != expected:
            return self._reject(
                "invalid_action",
                f"Provenance identifies this record as `{expected}`, not `{term}`.",
            )
        state = self._contribute(
            context.state, context.participant_id, "terminologist", "clarify_record"
        )
        state["clarifications"] = [
            *state.get("clarifications", []),
            {"record_id": record, "term": term, "participant_id": context.participant_id},
        ]
        return self._accepted(
            state,
            f"Terminology clarified: `{record}` measures `{term}` at its own stage.",
            "translation.term_clarified",
            "terminologist",
        )

    def _classify(
        self, action: ClassifyContradictionAction, context: ValidationContext
    ) -> ValidationDecision:
        pair = self._record_pair(action.record_a, action.record_b)
        classification = action.classification.strip().lower()
        if pair is None or classification not in self.constraints.allowed_classifications:
            return self._reject(
                "invalid_action", "Use two distinct records and a listed classification."
            )
        if pair not in {tuple(item["records"]) for item in context.state.get("comparisons", [])}:
            return self._reject(
                "invalid_action", "Compare that pair before classifying its difference."
            )
        state = self._contribute(
            context.state, context.participant_id, "difference_classifier", "classify_contradiction"
        )
        state["classifications"] = [
            *state.get("classifications", []),
            {
                "records": list(pair),
                "classification": classification,
                "participant_id": context.participant_id,
            },
        ]
        if classification == self.constraints.correct_classification:
            self._append_trigger(state, context, "relay_finding", context.participant_id)
            text = "The apparent contradiction is classified as measurements from different stages."
        else:
            text = (
                f"`{classification}` remains a public interpretation; it does not erase the "
                "records or establish the final concordance."
            )
        return self._accepted(
            state, text, "translation.difference_classified", "difference_classifier"
        )

    def _relay(self, action: RelayRecordAction, context: ValidationContext) -> ValidationDecision:
        record = self._record(action.record_id)
        if record is None or not self._records_public(context.state, (record,)):
            return self._reject("invalid_action", "Relay an observed Translation record.")
        term = self._record_terms[record]
        value = float(context.state["record_values"][record])
        summary = action.summary.strip()
        if term not in summary.lower() or f"{value:g}" not in summary:
            return self._reject(
                "invalid_action", f"The relay must preserve `{term}` and `{value:g}`."
            )
        state = self._contribute(
            context.state, context.participant_id, "record_relay", "relay_record"
        )
        state["relays"] = [
            *state.get("relays", []),
            {"record_id": record, "summary": summary, "participant_id": context.participant_id},
        ]
        return self._accepted(
            state,
            f"Accurate relay recorded for `{record}`: {summary}",
            "translation.record_relayed",
            "record_relay",
        )

    def _annotate(
        self, action: AnnotateDifferenceAction, context: ValidationContext
    ) -> ValidationDecision:
        record = self._record(action.record_id)
        if record is None or not self._records_public(context.state, (record,)):
            return self._reject("invalid_action", "Annotate an observed Translation record.")
        if "retention_minor_report" not in context.state.get("unlocked_observations", []):
            return self._reject(
                "invalid_action", "Inspect the Margin Recorder before annotating a difference."
            )
        if not self._contains(action.note, self.constraints.preservation_terms):
            return self._reject(
                "invalid_action", "The annotation must explicitly preserve a difference."
            )
        state = self._contribute(
            context.state, context.participant_id, "dissent_archivist", "annotate_difference"
        )
        state["annotations"] = [
            *state.get("annotations", []),
            {
                "record_id": record,
                "note": action.note.strip(),
                "participant_id": context.participant_id,
            },
        ]
        return self._accepted(
            state,
            f"A non-erasing annotation is attached to `{record}`.",
            "translation.difference_annotated",
            "dissent_archivist",
        )

    def _propose(
        self, action: ProposeTranslationAction, context: ValidationContext
    ) -> ValidationDecision:
        unlocked = set(context.state.get("unlocked_observations", []))
        missing = set(self.constraints.required_observations) - unlocked
        if missing:
            return self._reject(
                "proposal_rejected",
                "All three records, glossary, provenance, and minority note must be public.",
            )
        records = tuple(
            self._record(value) for value in (action.record_a, action.record_b, action.record_c)
        )
        if None in records or set(records) != set(self.constraints.record_entity_ids):
            return self._reject(
                "proposal_rejected", "The proposal must include all three distinct records."
            )
        comparisons = context.state.get("comparisons", [])
        if len(comparisons) < self.constraints.required_comparisons:
            return self._reject(
                "proposal_rejected", "At least two distinct record comparisons are required."
            )
        compared_records = {record for item in comparisons for record in item["records"]}
        if not set(self.constraints.record_entity_ids).issubset(compared_records):
            return self._reject(
                "proposal_rejected", "The comparisons must collectively include all three records."
            )
        classification = action.classification.strip().lower()
        if classification != self.constraints.correct_classification:
            return self._reject(
                "proposal_rejected",
                "The provenance supports `different_stages`; no record is false.",
            )
        if not any(
            item.get("classification") == classification
            for item in context.state.get("classifications", [])
        ):
            return self._reject(
                "proposal_rejected", "Classify a compared difference publicly first."
            )
        if len(context.state.get("relays", [])) < self.constraints.required_public_relays:
            return self._reject(
                "proposal_rejected", "At least one accurate public record relay is required."
            )
        if not all(term in action.mapping.lower() for term in self.constraints.mapping_terms):
            return self._reject(
                "proposal_rejected", "The mapping must define sent, delivered, and retained."
            )
        values = context.state["record_values"]
        summary = action.shared_summary.strip()
        for record in self.constraints.record_entity_ids:
            term = self._record_terms[record]
            value = float(values[record])
            if term not in summary.lower() or f"{value:g}" not in summary:
                return self._reject(
                    "proposal_rejected", f"The shared summary must preserve {term}={value:g}."
                )
        if not self._contains(action.preserved_difference, self.constraints.preservation_terms):
            return self._reject(
                "proposal_rejected",
                "Name the difference or minority report that remains preserved.",
            )
        contributions = current_cycle_contributions(context.state)
        participants = {item["participant_id"] for item in contributions} | {context.participant_id}
        functions = {item["function"] for item in contributions} | {"translation_editor"}
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
        proposal_id = self._proposal_id(context.state.get("proposals", {}))
        proposal = {
            "proposal_id": proposal_id,
            "kind": "translation",
            "author_participant_id": context.participant_id,
            "records": list(records),
            "classification": classification,
            "mapping": action.mapping.strip(),
            "shared_summary": summary,
            "preserved_difference": action.preserved_difference.strip(),
            "status": "pending",
            "kickers": [],
        }
        state = self._contribute(
            context.state, context.participant_id, "translation_editor", "propose_translation"
        )
        state["proposals"] = {**state.get("proposals", {}), proposal_id: proposal}
        return ValidationDecision(
            True,
            "proposal_accepted",
            public_data={
                "public_text": (
                    f"Translation proposal `{proposal_id}` preserves "
                    f"sent={values['circulation_ledger']:g}, "
                    f"delivered={values['nursery_intake_sensor']:g}, and "
                    f"retained={values['nursery_retention_survey']:g}; it awaits "
                    "non-author confirmation."
                ),
                "proposal_id": proposal_id,
            },
            next_state=state,
            event_type="translation.proposed",
            narration_key=self.definition.narration_keys["proposal_accepted"],
            contribution_function="translation_editor",
            proposal_projection={
                "id": proposal_id,
                "author_participant_id": context.participant_id,
                "status": "pending",
                "proposal_data": proposal,
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
            or proposal.get("kind") != "translation"
        ):
            return self._reject(
                "invalid_action", "No pending Translation proposal matches that ID."
            )
        author = str(proposal["author_participant_id"])
        if author == context.participant_id:
            return self._reject("invalid_action", "A non-author must confirm the translation.")
        supporting = {
            item["participant_id"]
            for item in [*context.state.get("relays", []), *context.state.get("annotations", [])]
            if item.get("participant_id") != author
        }
        if not supporting:
            return self._reject(
                "proposal_rejected", "A non-author relay or preservation annotation is required."
            )
        state = self._contribute(
            context.state, context.participant_id, "record_verifier", "confirm_reconstruction"
        )
        proposal = dict(proposal)
        proposal["status"] = "confirmed"
        proposals[action.proposal_id] = proposal
        state["proposals"] = proposals
        confirmation = {"proposal_id": action.proposal_id, "participant_id": context.participant_id}
        state["confirmations"] = [*state.get("confirmations", []), confirmation]
        counters = copy.deepcopy(state.get("counters", {}))
        counters["coherence"] = int(counters.get("coherence", 0)) + 1
        counters["trust"] = int(counters.get("trust", 0)) + 1
        kicker_types = {item["kicker"] for item in proposal.get("kickers", [])}
        effects = list(state.get("persistent_effects", []))
        if "cite_provenance" in kicker_types:
            counters["coherence"] += 1
        if "preserve_minority" in kicker_types:
            counters["trust"] += 1
        for effect in ("translation_concordance", "plural_glossary"):
            if effect not in effects:
                effects.append(effect)
        if "Material Terms Ledger" not in effects:
            effects.append("Material Terms Ledger")
        state["material_terms_ledger"] = [
            {
                "original_term": "sent",
                "source_group": "circulation source ledger",
                "measurement_boundary": "source departure",
                "compatible_meaning": "quantity withdrawn from the source",
                "unresolved_disagreement": "withdrawn is not yet delivered or usable",
            },
            {
                "original_term": "delivered",
                "source_group": "boundary intake maintainers",
                "measurement_boundary": "arrival across the intake boundary",
                "compatible_meaning": "quantity arriving at a destination",
                "unresolved_disagreement": "arrival does not prove later retention or usability",
            },
            {
                "original_term": "retained",
                "source_group": "later public survey",
                "measurement_boundary": "post-use remainder",
                "compatible_meaning": "quantity remaining after one interval",
                "unresolved_disagreement": "the dissent record preserves the later loss",
            },
            {
                "original_term": "treated",
                "source_group": "Provision Works and treatment-yard records",
                "measurement_boundary": "process claim",
                "compatible_meaning": "a named filtration, transformation, or immobilization step",
                "unresolved_disagreement": "visible clarification alone is not evidence of safety",
            },
        ]
        if "accessibility_glossary" in kicker_types and "accessible_concordance" not in effects:
            effects.append("accessible_concordance")
        state["counters"] = counters
        state["persistent_effects"] = effects
        state["world_flags"] = {
            **state.get("world_flags", {}),
            **self.definition.completion.world_flags,
            "material_terms_ledger": True,
            "remediation_processes_distinguished": "fungal_processes_are_distinct"
            in state.get("unlocked_observations", []),
            "returned_water_not_automatically_usable": "warm_return_volume_not_usability"
            in state.get("unlocked_observations", []),
        }
        state["position_completed"] = True
        return ValidationDecision(
            True,
            "position_completed",
            public_data={
                "public_text": (
                    "Position 2 complete. Sent, delivered, and retained remain "
                    "separately accurate, "
                    "with provenance and the minority record preserved in a shared concordance."
                )
            },
            next_state=state,
            event_type="position.completed",
            narration_key=self.definition.narration_keys["position_completed"],
            contribution_function="record_verifier",
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
            return self._reject("invalid_action", "A public stack is already open.")
        try:
            proposal_action = self._translation_action(dict(action.proposal))
        except (KeyError, TypeError, ValueError):
            return self._reject("invalid_action", "The Translation stack base is incomplete.")
        records = {
            self._record(proposal_action.record_a),
            self._record(proposal_action.record_b),
            self._record(proposal_action.record_c),
        }
        if records != set(self.constraints.record_entity_ids):
            return self._reject("invalid_action", "The stack base must include all three records.")
        stack_id = self._public_id("s", context.session_id, context.action_id)
        state = self._contribute(
            context.state, context.participant_id, "translation_editor", "begin_stack"
        )
        state["public_stack"] = {
            "stack_id": stack_id,
            "status": "open",
            "position": 2,
            "base": {
                "participant_id": context.participant_id,
                "proposal": proposal_action.model_dump(mode="json"),
            },
            "entries": [
                {
                    "kind": "proposal",
                    "participant_id": context.participant_id,
                    "label": "attempt translation",
                }
            ],
        }
        return self._accepted(
            state,
            f"Translation stack `{stack_id}` is open (1/{tactical.max_stack_depth}).",
            "stack.opened",
            "translation_editor",
        )

    def _react_to_stack(
        self, action: ReactToStackAction, context: ValidationContext
    ) -> ValidationDecision:
        stack = context.state.get("public_stack")
        tactical = self.definition.tactical
        assert tactical is not None
        if (
            not stack
            or stack.get("status") != "open"
            or stack.get("stack_id") != action.stack_id
            or stack.get("position") != 2
        ):
            return self._reject("invalid_action", "No open Translation stack matches that ID.")
        entries = list(stack.get("entries", []))
        if len(entries) >= tactical.max_stack_depth:
            return self._reject("invalid_action", "The public stack has reached its depth limit.")
        if action.reaction not in tactical.allowed_stack_reactions:
            return self._reject("invalid_action", "That reaction is unavailable in Translation.")
        if any(item.get("participant_id") == context.participant_id for item in entries):
            return self._reject("invalid_action", "Each participant may add only one stack entry.")
        labels = {
            "challenge_mapping": "challenge the mapping",
            "request_provenance": "request provenance",
            "preserve_difference": "preserve the difference",
            "clarify_scale": "clarify the scale",
            "relay_summary": "relay the summary",
        }
        state = self._contribute(
            context.state, context.participant_id, "stack_responder", "react_to_stack"
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
        return self._accepted(
            state,
            f"Stack `{action.stack_id}` now resolves in reverse: "
            + " -> ".join(item["label"] for item in reversed(updated["entries"])),
            "stack.reaction_added",
            "stack_responder",
        )

    def _resolve_stack(
        self, action: ResolveStackAction, context: ValidationContext
    ) -> ValidationDecision:
        stack = context.state.get("public_stack")
        if (
            not stack
            or stack.get("status") != "open"
            or stack.get("stack_id") != action.stack_id
            or stack.get("position") != 2
        ):
            return self._reject("invalid_action", "No open Translation stack matches that ID.")
        working = copy.deepcopy(context.state)
        labels = [item["label"] for item in reversed(stack.get("entries", [])[1:])]
        for entry in stack.get("entries", [])[1:]:
            working = self._contribute(
                working, str(entry["participant_id"]), "stack_responder", "resolved_stack_reaction"
            )
        labels.append("attempt translation")
        summary = "Resolution order: " + " -> ".join(labels) + "."
        proposal_action = self._translation_action(dict(stack["base"]["proposal"]))
        synthetic = ValidationContext(
            environment=context.environment,
            session_id=context.session_id,
            participant_id=str(stack["base"]["participant_id"]),
            action_id=f"{context.action_id}:stack-proposal",
            current_position=2,
            response_profile=context.response_profile,
            state=working,
        )
        proposed = self._propose(proposal_action, synthetic)
        if not proposed.accepted or proposed.next_state is None:
            failed = copy.deepcopy(stack)
            failed["status"] = "failed"
            working["public_stack"] = failed
            counters = copy.deepcopy(working.get("counters", {}))
            counters["instability"] = int(counters.get("instability", 0)) + 1
            working["counters"] = counters
            return ValidationDecision(
                True,
                "stack_resolved_failed",
                public_data={
                    "public_text": (
                        f"{summary} Resolution stops: "
                        f"{proposed.public_data.get('feedback', 'base rejected')}."
                    )
                },
                next_state=working,
                event_type="stack.resolved_failed",
                narration_key=self.definition.narration_keys["proposal_rejected"],
            )
        state = proposed.next_state
        resolved = copy.deepcopy(stack)
        resolved["status"] = "resolved"
        resolved["resolution_order"] = labels
        resolved["proposal_id"] = proposed.public_data["proposal_id"]
        state["public_stack"] = resolved
        return ValidationDecision(
            True,
            "stack_resolved",
            public_data={
                "public_text": f"{summary} {proposed.public_data['public_text']}",
                "proposal_id": proposed.public_data["proposal_id"],
            },
            next_state=state,
            event_type="stack.resolved",
            narration_key=self.definition.narration_keys["proposal_accepted"],
            proposal_projection=proposed.proposal_projection,
        )

    def _add_kicker(
        self, action: AddProposalKickerAction, context: ValidationContext
    ) -> ValidationDecision:
        proposal = context.state.get("proposals", {}).get(action.proposal_id)
        tactical = self.definition.tactical
        assert tactical is not None
        if (
            proposal is None
            or proposal.get("status") != "pending"
            or proposal.get("kind") != "translation"
        ):
            return self._reject(
                "invalid_action", "No pending Translation proposal matches that ID."
            )
        if action.kicker not in tactical.allowed_kickers:
            return self._reject("invalid_action", "That kicker is unavailable in Translation.")
        kickers = list(proposal.get("kickers", []))
        if proposal["author_participant_id"] == context.participant_id or any(
            item["participant_id"] == context.participant_id for item in kickers
        ):
            return self._reject(
                "invalid_action", "A kicker must come from a distinct non-author contributor."
            )
        if any(item["kicker"] == action.kicker for item in kickers):
            return self._reject("invalid_action", "That kicker is already attached.")
        functions = {
            "cite_provenance": "provenance_auditor",
            "preserve_minority": "dissent_archivist",
            "accessibility_glossary": "accessibility_editor",
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
            proposal_data_update={"proposal_id": action.proposal_id, "proposal_data": updated},
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
        if context.participant_id == str(trigger.get("source_participant_id", "")):
            return self._reject(
                "invalid_action", "This reaction must be taken by another participant."
            )
        if trigger.get("kind") == "inspect_provenance":
            observed = self._observe(
                ObserveAction(action="observe", entity_id=self.constraints.provenance_entity_id),
                context,
            )
            assert observed.next_state is not None
            state = observed.next_state
            text = "Triggered provenance inspection: " + str(observed.public_data["public_text"])
            function = str(observed.contribution_function)
            unlocked = observed.unlocked_observation_key
        else:
            state = self._contribute(
                context.state, context.participant_id, "record_relay", "use_triggered_reaction"
            )
            text = (
                "Triggered relay window opened; use `/interior act relay-record` "
                "to preserve one finding."
            )
            function = "record_relay"
            unlocked = None
        self._consume_trigger(state, action.trigger_id, context.participant_id)
        return ValidationDecision(
            True,
            "trigger_resolved",
            public_data={"public_text": text},
            next_state=state,
            event_type="trigger.resolved",
            narration_key=self.definition.narration_keys["action_accepted"],
            contribution_function=function,
            unlocked_observation_key=unlocked,
        )

    def _observation_text(self, observation_id: str, state: dict[str, Any]) -> str:
        values = state.get("record_values", {})
        if observation_id == "source_sent_measurement":
            value = float(values["circulation_ledger"])
            return (
                f"The signed Circulation Ledger records {value:g} water units sent from the source."
            )
        if observation_id == "intake_delivered_measurement":
            value = float(values["nursery_intake_sensor"])
            return (
                f"The calibrated Nursery Intake Sensor records {value:g} water units "
                "delivered across the boundary."
            )
        if observation_id == "survey_retained_measurement":
            value = float(values["nursery_retention_survey"])
            return (
                f"The later Nursery Retention Survey records {value:g} water units "
                "retained after one use interval."
            )
        return self.observations[observation_id].public_text

    def _fact_classification(self, observation_id: str) -> str:
        configured = self.observations[observation_id].classification
        if configured != "confirmed":
            return configured
        if observation_id in {"records_have_distinct_provenance", "chronology_resolves_difference"}:
            return "provenance"
        if observation_id in {"retention_minor_report", "receipt_term_ambiguity"}:
            return "preserved_difference"
        return "confirmed"

    def _record(self, value: str) -> str | None:
        resolved = self._resolve(value)
        return resolved if resolved in self.constraints.record_entity_ids else None

    def _record_pair(self, first: str, second: str) -> tuple[str, str] | None:
        a, b = self._record(first), self._record(second)
        if a is None or b is None or a == b:
            return None
        order = {item: index for index, item in enumerate(self.constraints.record_entity_ids)}
        return tuple(sorted((a, b), key=order.__getitem__))  # type: ignore[return-value]

    def _records_public(self, state: dict[str, Any], records: tuple[str, ...]) -> bool:
        unlocked = set(state.get("unlocked_observations", []))
        return all(self._record_observations[item] in unlocked for item in records)

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
    def _proposal_id(proposals: dict[str, Any]) -> str:
        base = "translation-stage-concordance"
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
        self, state: dict[str, Any], text: str, event_type: str, function: str
    ) -> ValidationDecision:
        return ValidationDecision(
            True,
            "accepted",
            public_data={"public_text": text},
            next_state=state,
            event_type=event_type,
            narration_key=self.definition.narration_keys["action_accepted"],
            contribution_function=function,
        )

    def _append_trigger(
        self,
        state: dict[str, Any],
        context: ValidationContext,
        kind: str,
        source_participant_id: str,
        observation_id: str | None = None,
    ) -> None:
        reactions = list(state.get("triggered_reactions", []))
        del context
        observation = self.observations.get(observation_id or "")
        subject = observation.entity_id if observation is not None else None
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
                "observation_id": observation_id,
                "consumed": False,
            }
        )
        state["triggered_reactions"] = reactions

    @staticmethod
    def _consume_trigger(state: dict[str, Any], trigger_id: str, participant_id: str) -> None:
        updated_reactions = []
        for item in state.get("triggered_reactions", []):
            updated = dict(item)
            if updated.get("trigger_id") == trigger_id:
                updated["consumed"] = True
                updated["consumed_by"] = participant_id
            updated_reactions.append(updated)
        state["triggered_reactions"] = updated_reactions

    @staticmethod
    def _translation_action(proposal: dict[str, Any]) -> ProposeTranslationAction:
        return ProposeTranslationAction(
            action="propose_translation",
            record_a=str(proposal["record_a"]),
            record_b=str(proposal["record_b"]),
            record_c=str(proposal["record_c"]),
            classification=str(proposal["classification"]),
            mapping=str(proposal["mapping"]),
            shared_summary=str(proposal["shared_summary"]),
            preserved_difference=str(proposal["preserved_difference"]),
        )

    @staticmethod
    def _reject(reason_key: str, feedback: str) -> ValidationDecision:
        return ValidationDecision(
            False,
            reason_key,
            public_data={"feedback": feedback},
            narration_key="proposal_rejected"
            if reason_key == "proposal_rejected"
            else "invalid_action",
        )
