from __future__ import annotations

import asyncio
import copy
import hashlib
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib.resources import files
from typing import Any

from uniflora.content.loader import PuzzleRegistry
from uniflora.content.validation import validate_packaged_content
from uniflora.engine.actions import CandidateAction, SummarizeAction, UseTriggeredReactionAction
from uniflora.engine.core import DeterministicEngine, EngineOutcome
from uniflora.engine.cycles import (
    PROPOSAL_ACTIONS,
    advance_cycle,
    current_cycle_contributions,
    cycle_rules_help,
    cycle_status_text,
    ensure_cycle_state,
    public_cycle_phase,
)
from uniflora.engine.position_zero import (
    EnvironmentPositionValidator,
    position_zero_proposal_guidance,
)
from uniflora.engine.public_ids import resolve_trigger_id, semantic_trigger_aliases
from uniflora.engine.settlement_events import settlement_choice, settlement_choices_text
from uniflora.narration import FallbackNarrator, NarrationService
from uniflora.runtime import Environment, SessionMode
from uniflora.storage.repository import (
    GameRepository,
    MutationPlan,
    SessionRef,
    StorageError,
)
from .summary_chart import (
    SummarySnapshot,
    render_summary_chart,
)

logger = logging.getLogger(__name__)


def _is_newer_content_version(candidate: str, delivered: str) -> bool:
    try:
        candidate_parts = tuple(int(part) for part in candidate.split("."))
        delivered_parts = tuple(int(part) for part in delivered.split("."))
    except ValueError:
        return candidate != delivered
    return candidate_parts > delivered_parts


_SETTLEMENT_METHOD_COSTS = {
    "brace": "Settlement strain increases by 1.",
    "divert": "Displaced burden increases by 1.",
    "release": "Escalation falls by 1 and one temporary capacity is lost.",
}

_MAP_CUE_ENTITY_IDS: dict[int, tuple[str, ...]] = {
    1: (
        "northern_reservoir",
        "eastern_growth",
        "central_relay",
        "pale_nursery",
        "lower_archive_bed",
        "condensation_veil",
        "route_07",
        "first_bloom_basin",
        "production_intake_channel",
    ),
    2: (
        "circulation_ledger",
        "nursery_intake_sensor",
        "nursery_retention_survey",
        "archive_glossary",
        "provenance_index",
        "margin_recorder",
        "provision_works",
    ),
    3: (
        "provision_works",
        "production_intake_channel",
        "warm_return_channel",
        "treatment_yard",
        "white_rot_beds",
        "spent_substrate_court",
        "public_well_seven",
        "heat_court",
        "provision_burden_ledger",
    ),
    4: (
        "provision_works",
        "production_intake_channel",
        "warm_return_channel",
        "unknown_return_sump",
        "clear_return_channel",
        "treatment_yard",
        "white_rot_beds",
        "culture_archive",
        "upstream_sample_port",
        "downstream_sample_port",
        "nonfood_test_garden",
        "spent_substrate_court",
        "public_discharge_archive",
        "maintenance_cycle_board",
    ),
    5: (
        "provision_works",
        "production_intake_channel",
        "warm_return_channel",
        "treatment_yard",
        "white_rot_beds",
        "blackwater_berm",
        "spent_substrate_court",
        "culture_archive",
        "clear_water_test_garden",
        "public_well_seven",
        "retired_nursery_plot",
        "assurance_archive",
    ),
}


def _settlement_scar(event: dict[str, Any], method: str) -> str:
    scars = event.get("scars", {})
    if isinstance(scars, dict) and scars.get(method):
        return str(scars[method])
    asset = str(event.get("threatened_asset", "The threatened place"))
    fallback = {
        "brace": f"{asset} holds, but continues to carry the pressure.",
        "divert": f"{asset} holds; another district inherits its burden.",
        "release": f"{asset} holds, but one part of its capacity is gone.",
    }
    return fallback[method]


def _apply_settlement_cost(data: dict[str, Any], method: str) -> tuple[str, int]:
    escalation = int(data.get("settlement_escalation", 0))
    if method == "brace":
        data["settlement_strain"] = int(data.get("settlement_strain", 0)) + 1
    elif method == "divert":
        data["settlement_burden"] = int(data.get("settlement_burden", 0)) + 1
    else:
        data["settlement_lost_capacity"] = int(data.get("settlement_lost_capacity", 0)) + 1
        escalation = max(0, escalation - 1)
        data["settlement_escalation"] = escalation
    return _SETTLEMENT_METHOD_COSTS[method], escalation


def _position_cycle_chart(position: int, title: str) -> PositionImage | None:
    filename = f"position_{position}_cycle_flow_chart.png"
    asset = files("uniflora.content").joinpath("assets", filename)
    if not asset.is_file():
        return None
    return PositionImage(
        image_filename=filename,
        image_alt_text=(
            f"High-resolution Position {position} cycle flow chart for {title}, showing the "
            "asynchronous public phases, evidence to establish, proposal requirements, and "
            "completion checks."
        ),
        image_bytes=asset.read_bytes(),
    )


@dataclass(frozen=True, slots=True)
class PublicResult:
    accepted: bool
    text: str
    event_id: str | None = None
    attachment: PositionImage | None = None
    phase_footer: str | None = None


@dataclass(frozen=True, slots=True)
class PositionImage:
    image_filename: str
    image_alt_text: str
    image_bytes: bytes


@dataclass(frozen=True, slots=True)
class PositionAnnouncement(PositionImage):
    position: int
    introduction: str
    additional_images: tuple[PositionImage, ...] = ()


@dataclass(frozen=True, slots=True)
class ArtifactReveal:
    reveal_id: str
    source_position: int
    content_version: str
    introduction: str
    image_filename: str
    image_alt_text: str
    image_bytes: bytes


class GameService:
    def __init__(
        self,
        repository: GameRepository,
        refs: dict[Environment, SessionRef],
        registry: PuzzleRegistry,
        engine: DeterministicEngine,
        narrator: FallbackNarrator,
        environment_validator: EnvironmentPositionValidator | None = None,
        narration_service: NarrationService | None = None,
        action_cooldown_seconds: int = 0,
        disabled_features: frozenset[str] = frozenset(),
        settlement_intervention_excluded_user_ids: frozenset[int] = frozenset(),
    ) -> None:
        self.repository = repository
        self.refs = refs
        self.registries = {environment: registry for environment in Environment}
        self.engine = engine
        self.narrators = {environment: narrator for environment in Environment}
        self.environment_validator = environment_validator
        self.narration_service = narration_service
        self.settings_action_cooldown = action_cooldown_seconds
        self.disabled_features = disabled_features
        self.settlement_intervention_excluded_user_ids = settlement_intervention_excluded_user_ids

    async def initialize(self) -> None:
        for environment, ref in self.refs.items():
            initial = self.registries[environment].get(0).initial_state()
            await self.repository.initialize_content(ref, initial)
            state = await self.repository.state(ref)
            current_position = int(state["current_position"])
            current_definition = self.registries[environment].get(current_position)
            if current_definition.status.value != "complete":
                continue
            if self.environment_validator is None:
                continue
            current_data = dict(state.get("data", {}))
            wrong_content = current_data.get("content_key") != current_definition.key
            stale_version = current_data.get("content_version") != (
                current_definition.content_version
            )
            if wrong_content:
                initialized = self.environment_validator.initialize_position(
                    environment, current_position, current_data
                )
            elif stale_version:
                initialized = self.environment_validator.upgrade_position(
                    environment, current_position, current_data
                )
            else:
                continue
            if initialized is None:
                continue

            def planner(
                current: dict[str, object],
                initialized_data: dict[str, Any] = initialized,
                position: int = current_position,
                content_key: str = current_definition.key,
                content_version: str = current_definition.content_version,
                legacy_upgrade: bool = wrong_content,
                version_upgrade: bool = stale_version,
            ) -> MutationPlan:
                after = dict(current)
                after["data"] = copy.deepcopy(initialized_data)
                return MutationPlan(
                    event_type=f"content.position_{position}.initialized",
                    state_after=after,
                    payload={
                        "position": position,
                        "content_key": content_key,
                        "content_version": content_version,
                        "legacy_state_upgraded": legacy_upgrade,
                        "content_version_upgraded": version_upgrade,
                    },
                )

            await self.repository.mutate(
                ref,
                actor_id="system:content-upgrade",
                idempotency_key=(
                    f"content-upgrade:{environment.value}:{current_position}:"
                    f"{current_definition.content_version}"
                ),
                planner=planner,
            )

    async def record_exterior_weather(
        self,
        environment: Environment,
        event_payload: dict[str, Any],
        actor_user_id: int,
    ) -> None:
        """Persist the latest accepted exterior observation for summaries.

        The Discord adapter owns fetching and deterministic interpretation.
        GameService stores only the latest JSON-safe payload in canonical
        environment state. A newer observation replaces the previous weather
        layer; duplicate observation keys remain idempotent.
        """

        if not isinstance(event_payload, dict):
            raise ValueError("exterior weather payload must be a dictionary")

        observation_key = str(
            event_payload.get("deduplication_key", "")
        ).strip()
        if not observation_key:
            raise ValueError(
                "exterior weather payload lacks a deduplication key"
            )

        ref = self.refs[environment]
        participant_id = await self.repository.resolve_participant(
            ref,
            actor_user_id,
        )

        def planner(state: dict[str, Any]) -> MutationPlan | None:
            data = copy.deepcopy(state.get("data", {}))
            existing = data.get("exterior_weather")
            if (
                isinstance(existing, dict)
                and str(existing.get("deduplication_key", ""))
                == observation_key
            ):
                return None

            data["exterior_weather"] = copy.deepcopy(event_payload)
            after = copy.deepcopy(state)
            after["data"] = data
            return MutationPlan(
                event_type="exterior.weather_observed",
                state_after=after,
                payload=copy.deepcopy(event_payload),
            )

        await self.repository.mutate(
            ref,
            actor_id=participant_id,
            idempotency_key=(
                f"exterior-weather:{environment.value}:{observation_key}"
            ),
            planner=planner,
        )

    async def act(
        self,
        environment: Environment,
        discord_user_id: int,
        action: CandidateAction,
        idempotency_key: str,
    ) -> PublicResult:
        ref = self.refs[environment]
        participant_id = await self.repository.resolve_participant(ref, discord_user_id)
        control = await self.repository.runtime_control(ref)
        feature = (
            "tactical_stack"
            if action.action in {"begin_stack", "react_to_stack", "resolve_stack"}
            else "triggered_reactions"
            if action.action == "use_triggered_reaction"
            else "proposal_kickers"
            if action.action == "add_proposal_kicker"
            else None
        )
        if feature is not None and (
            feature in self.disabled_features or not control["feature_flags"].get(feature, True)
        ):
            return await self.render_outcome(
                ref,
                participant_id,
                EngineOutcome(
                    False,
                    "feature_disabled",
                    public_data={"feedback": f"The `{feature}` mechanic is disabled."},
                ),
                action=action,
            )
        if environment is Environment.LIVE and self.settings_action_cooldown > 0:
            acquired = await self.repository.acquire_api_cooldowns(
                ref,
                participant_id,
                purpose="game-action",
                per_user_seconds=self.settings_action_cooldown,
                global_seconds=0,
            )
            if not acquired:
                return await self.render_outcome(
                    ref,
                    participant_id,
                    EngineOutcome(
                        False,
                        "rate_limited",
                        public_data={
                            "feedback": "The public action surface is settling; try again soon."
                        },
                    ),
                    action=action,
                )
        if isinstance(action, UseTriggeredReactionAction):
            state = await self.repository.state(ref)
            reactions = state.get("data", {}).get("triggered_reactions", [])
            resolved_id = resolve_trigger_id(
                action.trigger_id,
                reactions,
                self._observation_entities(environment),
            )
            if resolved_id != action.trigger_id:
                action = action.model_copy(update={"trigger_id": resolved_id})
        outcome = await self.engine.process(
            ref,
            participant_id=participant_id,
            action=action,
            idempotency_key=idempotency_key,
        )
        summary_snapshot = (
            self._build_summary_snapshot(environment, outcome.state_after)
            if isinstance(action, SummarizeAction)
            and outcome.accepted
            and outcome.state_after is not None
            else None
        )
        rendered = await self.render_outcome(ref, participant_id, outcome, action=action)
        if outcome.accepted:
            state = copy.deepcopy(outcome.state_after)
            if state is None:
                state = await self.repository.state(ref)
            if state.get("data", {}).get("settlement_restart_pending", False):
                restarted = await self.repository.restart_current_position(
                    ref,
                    actor_id="system:settlement-event",
                    reason="three unmitigated whole-settlement events",
                )
                if restarted.accepted:
                    return PublicResult(
                        True,
                        rendered.text + "\n\n**POSITION 1 RESTARTED — THE INTERRUPTED CURRENT**\n"
                        "Temporary Position 1 work has returned to its recorded beginning. "
                        "Earlier completed positions and inherited settlement scars remain.",
                        restarted.event_id,
                    )
        if summary_snapshot is not None:
            try:
                chart = await asyncio.to_thread(render_summary_chart, summary_snapshot)
            except Exception:
                logger.exception(
                    "summary state chart rendering failed",
                    extra={
                        "environment": environment.value,
                        "position": summary_snapshot.position,
                        "cycle": summary_snapshot.cycle,
                    },
                )
                return PublicResult(
                    rendered.accepted,
                    rendered.text
                    + "\n\nThe visual state chart could not be generated for this summary.",
                    rendered.event_id,
                    phase_footer=self._snapshot_phase_footer(summary_snapshot),
                )
            return PublicResult(
                rendered.accepted,
                self._compact_summary_response(
                    environment,
                    summary_snapshot,
                    participant_id,
                    outcome,
                ),
                rendered.event_id,
                attachment=PositionImage(
                    image_filename=chart.filename,
                    image_alt_text=chart.alt_text,
                    image_bytes=chart.png_bytes,
                ),
                phase_footer=self._snapshot_phase_footer(summary_snapshot),
            )
        return rendered

    async def trigger_choices(
        self, environment: Environment, discord_user_id: int
    ) -> list[tuple[str, str]]:
        """Return all active reactions, labeling participant eligibility for autocomplete."""

        ref = self.refs[environment]
        participant_id = await self.repository.resolve_participant(ref, discord_user_id)
        state = await self.repository.state(ref)
        reactions = state.get("data", {}).get("triggered_reactions", [])
        aliases = semantic_trigger_aliases(reactions, self._observation_entities(environment))
        choices: list[tuple[str, str]] = []
        for reaction in reactions:
            stored_id = str(reaction.get("trigger_id", ""))
            if not stored_id or reaction.get("consumed", False):
                continue
            excluded = {str(reaction.get("source_participant_id", ""))}
            excluded.update(str(item) for item in reaction.get("excluded_participant_ids", []))
            public_id = aliases.get(stored_id, stored_id)
            label = public_id.replace("-", " ").capitalize()
            if participant_id in excluded:
                label = f"Another participant required — {label}"
            choices.append((label, public_id))
        return choices
    
        async def maintenance_target_choices(
        self,
        environment: Environment,
        current: str = "",
        ) -> list[tuple[str, str]]:
            # ...build candidate_ids normally...

            choices = public_entity_labels(candidate_ids, current)
            return choices[:25]

        state = await self.repository.state(self.refs[environment])
        data = state["data"]
        current_position = int(state["current_position"])
        query = current.strip().casefold()

        # Begin with the normal, safely revealed current-position choices.
        choices_by_id: dict[str, tuple[str, str]] = {
            value: (label, value)
            for label, value in await self.entity_choices(environment, current)
        }

        resources = data.get("resources", {})
        resource_ids = set(resources) if isinstance(resources, dict) else set()

        inherited_ids: set[str] = set()

        # Include material systems inherited from earlier positions.
        for position in range(current_position):
            definition = self.registries[environment].get(position)

            for entity in definition.entities:
                if entity.id in resource_ids:
                    inherited_ids.add(entity.id)

        # Include targets carrying nonzero targeted counters.
        counters = data.get("counters", {})
        if isinstance(counters, dict):
            for counter_group in counters.values():
                if not isinstance(counter_group, dict):
                    continue

                for target, value in counter_group.items():
                    try:
                        nonzero = float(value) != 0
                    except (TypeError, ValueError):
                        nonzero = False

                    if nonzero:
                        inherited_ids.add(str(target))

        # Include explicitly established maintenance targets.
        sustained_targets = data.get("sustained_targets", [])
        if isinstance(sustained_targets, list):
            for item in sustained_targets:
                if isinstance(item, str):
                    inherited_ids.add(item)
                elif isinstance(item, dict):
                    target = (
                        item.get("target_entity_id")
                        or item.get("target")
                        or item.get("entity_id")
                    )
                    if target:
                        inherited_ids.add(str(target))

        for entity_id in sorted(inherited_ids):
            label = entity_id.replace("_", " ").replace("-", " ").title()

            if query and query not in label.casefold() and query not in entity_id.casefold():
                continue

            choices_by_id.setdefault(entity_id, (label, entity_id))

        return list(choices_by_id.values())[:25]

    async def entity_choices(
        self, environment: Environment, current: str = ""
    ) -> list[tuple[str, str]]:
        """Return only entities established by the environment's public record."""
        state = await self.repository.state(self.refs[environment])
        definition = self.registries[environment].get(int(state["current_position"]))
        data = state["data"]
        known_entity_ids = self._known_current_entity_ids(environment, definition, data)
        query = current.strip().casefold()
        choices: list[tuple[str, str]] = []
        for entity in definition.entities:
            if entity.id not in known_entity_ids:
                continue
            searchable = (entity.id, entity.title, entity.kind, *entity.aliases)
            if query and not any(query in item.casefold() for item in searchable):
                continue
            choices.append((f"{entity.title} — {entity.id}", entity.id))
        return choices[:25]
    
    async def observable_entity_choices(
        self, environment: Environment, current: str = ""
    ) -> list[tuple[str, str]]:
        """Return useful known observations plus spoiler-safe public cues."""
        state = await self.repository.state(self.refs[environment])
        definition = self.registries[environment].get(int(state["current_position"]))
        unlock_actions = {"observe"}
        if "inspect" in definition.allowed_actions:
            unlock_actions.add("inspect")
        return self._actionable_entity_choices(
            environment, definition, state["data"], unlock_actions, current
        )

    async def inspectable_entity_choices(
        self, environment: Environment, current: str = ""
    ) -> list[tuple[str, str]]:
        """Return useful known inspections plus spoiler-safe public cues."""
        state = await self.repository.state(self.refs[environment])
        definition = self.registries[environment].get(int(state["current_position"]))
        return self._actionable_entity_choices(
            environment, definition, state["data"], {"inspect"}, current
        )

    def _known_current_entity_ids(
        self, environment: Environment, definition: Any, data: dict[str, Any]
    ) -> set[str]:
        observation_entities = {
            observation.id: observation.entity_id
            for position in range(definition.position + 1)
            for observation in self.registries[environment].get(position).observations
        }
        known_entity_ids = {
            observation_entities[observation_id]
            for observation_id in data.get("unlocked_observations", [])
            if observation_id in observation_entities
        }
        historical_facts = [
            *data.get("confirmed_facts", []),
            *data.get("prior_confirmed_facts", []),
            *(
                fact
                for position in data.get("position_history", [])
                for fact in position.get("confirmed_facts", [])
            ),
        ]
        for fact in historical_facts:
            observation_id = str(fact.get("observation_id", ""))
            if observation_id in observation_entities:
                known_entity_ids.add(observation_entities[observation_id])
        current_entity_ids = {entity.id for entity in definition.entities}
        return known_entity_ids & current_entity_ids

    async def maintenance_target_choices(
        self,
        environment: Environment,
        current: str = "",
    ) -> list[tuple[str, str]]:
        """Return public current and inherited systems relevant to maintenance."""

        state = await self.repository.state(self.refs[environment])
        data = state.get("data", {})
        current_position = int(state["current_position"])
        query = current.strip().casefold()

        # Preserve the normal spoiler-safe current-position choices.
        choices_by_id: dict[str, tuple[str, str]] = {
            value: (label, value)
            for label, value in await self.entity_choices(environment, "")
        }

        candidate_ids: set[str] = set()

        def add_entity_id(value: object) -> None:
            if isinstance(value, str) and value.strip():
                candidate_ids.add(value.strip())

        def collect_record(record: object) -> None:
            if isinstance(record, str):
                add_entity_id(record)
                return

            if not isinstance(record, dict):
                return

            for key in (
                "target_entity_id",
                "target",
                "entity_id",
                "source_id",
                "source_entity_id",
                "recipient_id",
                "recipient_entity_id",
                "pathway_id",
                "pathway_entity_id",
                "relay_id",
                "relay_entity_id",
            ):
                add_entity_id(record.get(key))

        # Search the current state and preserved prior-position snapshots.
        snapshots: list[dict[str, object]] = [data]

        position_history = data.get("position_history", [])
        if isinstance(position_history, list):
            snapshots.extend(
                item
                for item in position_history
                if isinstance(item, dict)
            )

        for snapshot in snapshots:
            # Only targeted counters relevant to maintenance continuity.
            # Do not expose every resource in state because that can reveal
            # unobserved current-position entities.
            counters = snapshot.get("counters", {})
            if isinstance(counters, dict):
                for counter_name in ("maintenance", "repair", "strain"):
                    counter_group = counters.get(counter_name, {})
                    if not isinstance(counter_group, dict):
                        continue

                    for target, raw_value in counter_group.items():
                        try:
                            active = float(raw_value) != 0
                        except (TypeError, ValueError):
                            active = bool(raw_value)

                        if active:
                            add_entity_id(target)

            for collection_name in (
                "sustained_targets",
                "sustains",
                "maintenance_protocol",
            ):
                collection = snapshot.get(collection_name, [])

                if isinstance(collection, list):
                    for item in collection:
                        collect_record(item)

            # Public proposals can establish ongoing source, route, relay,
            # recipient, and reassessment obligations.
            proposals = snapshot.get("proposals", {})

            if isinstance(proposals, dict):
                proposal_records = proposals.values()
            elif isinstance(proposals, list):
                proposal_records = proposals
            else:
                proposal_records = ()

            for proposal in proposal_records:
                if not isinstance(proposal, dict):
                    continue

                has_maintenance_obligation = any(
                    proposal.get(key)
                    for key in (
                        "maintenance",
                        "maintenance_condition",
                        "reassessment",
                        "branch_condition",
                    )
                )

                if has_maintenance_obligation:
                    collect_record(proposal)

        # Resolve proper public titles across every reached position.
        title_by_id: dict[str, str] = {}

        for position_index in range(current_position + 1):
            definition = self.registries[environment].get(position_index)

            for entity in definition.entities:
                title_by_id.setdefault(entity.id, entity.title)

        for entity_id in candidate_ids:
            if entity_id in choices_by_id:
                continue

            title = title_by_id.get(
                entity_id,
                entity_id.replace("_", " ").replace("-", " ").title(),
            )

            choices_by_id[entity_id] = (
                f"{title} — {entity_id}",
                entity_id,
            )

        choices = [
            choice
            for choice in choices_by_id.values()
            if not query
            or query in choice[0].casefold()
            or query in choice[1].casefold()
        ]

        choices.sort(key=lambda item: item[0].casefold())
        return choices[:25]
    
    def _actionable_entity_choices(
        self,
        environment: Environment,
        definition: Any,
        data: dict[str, Any],
        unlock_actions: set[str],
        current: str = "",
    ) -> list[tuple[str, str]]:
        known_entity_ids = self._known_current_entity_ids(environment, definition, data)
        unlocked = {str(item) for item in data.get("unlocked_observations", [])}
        available_observations = {
            observation.entity_id: observation
            for observation in definition.observations
            if observation.unlock.action in unlock_actions
            and observation.id not in unlocked
            and set(observation.unlock.requires_observations).issubset(unlocked)
        }
        required_observation_ids: set[str] = set()
        for requirements in (
            definition.reconstruction,
            definition.circulation,
            definition.translation,
            definition.provision_requirements,
        ):
            if requirements is not None:
                required_observation_ids.update(requirements.required_observations)
        query = current.strip().casefold()
        choices: list[tuple[str, str]] = []
        entities = sorted(
            enumerate(definition.entities),
            key=lambda item: (
                available_observations.get(item[1].id).id not in required_observation_ids
                if item[1].id in available_observations
                else True,
                item[0],
            ),
        )
        for _, entity in entities:
            if entity.id not in available_observations:
                continue
            if entity.id in known_entity_ids:
                label = f"{entity.title} — {entity.id}"
                value = entity.id
                searchable = (entity.id, entity.title, entity.kind, *entity.aliases)
            elif entity.discovery_label is not None:
                label = f"Inspect: {entity.discovery_label}"
                value = entity.discovery_label
                searchable = (entity.discovery_label,)
            else:
                continue
            if query and not any(query in item.casefold() for item in searchable):
                continue
            choices.append((label, value))
        return choices[:25]

    async def configured_choices(
        self, environment: Environment, field: str, current: str = ""
    ) -> list[tuple[str, str]]:
        """Return position-specific fixed values for otherwise textual Discord fields."""
        state = await self.repository.state(self.refs[environment])
        definition = self.registries[environment].get(int(state["current_position"]))
        arc = definition.provision_arc
        if arc is None:
            return []
        values: list[tuple[str, str]]
        if field == "sample_measure":
            values = [
                (value.replace("_", " ").title(), value)
                for value in (*arc.evidence_measures, *arc.visual_only_measures)
            ]
        elif field == "contaminant_class":
            values = [(item.public_label, item.id) for item in arc.contaminant_classes]
        elif field == "culture":
            values = [(item.public_label, item.id) for item in arc.fungal_cultures]
        elif field == "substrate":
            values = [(item.public_label, item.id) for item in arc.substrates]
        elif field == "maintenance_condition":
            values = [
                (value.replace("_", " ").title(), value) for value in arc.maintenance_conditions
            ]
        elif field == "reduction_measure":
            values = [(value.replace("_", " ").title(), value) for value in arc.reduction_measures]
        elif field == "redesign_change":
            values = [(value.replace("_", " ").title(), value) for value in arc.redesign_changes]
        elif field == "mitigation_risk":
            values = [(value.replace("_", " ").title(), value) for value in arc.mitigation_risks]
        else:
            return []
        query = current.strip().casefold()
        return [
            (label, value)
            for label, value in values
            if not query or query in label.casefold() or query in value.casefold()
        ][:25]

    async def intervene_settlement_event(
        self,
        environment: Environment,
        discord_user_id: int,
        actor_label: str,
        method: str,
        idempotency_key: str,
    ) -> PublicResult:
        if (
            environment is Environment.LIVE
            and discord_user_id in self.settlement_intervention_excluded_user_ids
        ):
            return PublicResult(False, "This operator is excluded from settlement intervention.")
        if method not in {"brace", "divert", "release"}:
            return PublicResult(False, "Method must be brace, divert, or release.")
        ref = self.refs[environment]
        participant_id = await self.repository.resolve_participant(ref, discord_user_id)
        safe_label = " ".join(actor_label.split())[:40]
        safe_label = safe_label.replace("@", "＠").replace("`", "'") or "A Mycotroph"
        outcome: dict[str, str] = {}

        def planner(state: dict[str, Any]) -> MutationPlan | None:
            if environment is Environment.LIVE and int(state.get("current_position", -1)) != 1:
                outcome["feedback"] = "Whole-settlement intervention is available in Position 1."
                return None
            data = copy.deepcopy(state.get("data", {}))
            event = data.get("settlement_event")
            if not event or event.get("status") not in {"active", "stabilized"}:
                outcome["feedback"] = "No whole-settlement event currently needs intervention."
                return None
            escalation = int(data.get("settlement_escalation", 0))
            if event.get("status") == "active":
                if data.get("settlement_last_intervener") == participant_id:
                    outcome["feedback"] = (
                        "A different Mycotroph must stabilize the next settlement event."
                    )
                    return None
                scar = _settlement_scar(event, method)
                choice = settlement_choice(event, method)
                stabilized = {
                    **event,
                    "status": "stabilized",
                    "primary_method": method,
                    "primary_participant_id": participant_id,
                    "primary_label": safe_label,
                    "proposed_scar": scar,
                }
                data["settlement_event"] = stabilized
                data.setdefault("settlement_interventions", []).append(
                    {
                        "event_id": event["event_id"],
                        "participant_id": participant_id,
                        "label": safe_label,
                        "method": method,
                        "stage": "stabilized",
                    }
                )
                after = copy.deepcopy(state)
                after["data"] = data
                outcome["text"] = (
                    f"**STABILIZED BY {safe_label.upper()} — {event['title']}**\n"
                    f"Catastrophe is prevented. **{choice['label']}** would leave this scar:\n"
                    f"*{scar}*\n\n"
                    "One different Mycotroph may respond before the deadline: press "
                    f"**{choice['label']}** to support and soften its cost, or choose another "
                    "method to redirect the scar. If nobody responds, this choice becomes final."
                )
                return MutationPlan(
                    event_type="settlement.event_stabilized",
                    state_after=after,
                    payload={
                        "event_id": event["event_id"],
                        "method": method,
                        "intervening_participant_id": participant_id,
                        "proposed_scar": scar,
                    },
                )

            primary_participant_id = str(event.get("primary_participant_id", ""))
            if participant_id == primary_participant_id:
                outcome["feedback"] = "A different Mycotroph must answer the stabilized event."
                return None
            primary_method = str(event.get("primary_method", "brace"))
            supported = method == primary_method
            final_method = primary_method if supported else method
            scar = _settlement_scar(event, final_method)
            if supported:
                cost = "A second account supports the choice; its pressure cost is softened."
            else:
                cost, escalation = _apply_settlement_cost(data, final_method)
            resolved = {
                **event,
                "status": "mitigated",
                "method": final_method,
                "response": "supported" if supported else "redirected",
                "responding_participant_id": participant_id,
                "responding_label": safe_label,
                "scar": scar,
                "cost": cost,
                "resolved_at": datetime.now(UTC).isoformat(),
            }
            data["settlement_event_history"] = [
                *data.get("settlement_event_history", []),
                resolved,
            ]
            data["settlement_event"] = None
            data["settlement_event_actions_since_last"] = 0
            data["settlement_event_trigger_after"] = 0
            data["settlement_last_intervener"] = primary_participant_id
            data.setdefault("settlement_interventions", []).append(
                {
                    "event_id": event["event_id"],
                    "participant_id": participant_id,
                    "label": safe_label,
                    "method": method,
                    "stage": "supported" if supported else "redirected",
                }
            )
            after = copy.deepcopy(state)
            after["data"] = data
            outcome["text"] = (
                f"**SCAR {'SOFTENED' if supported else 'REDIRECTED'} BY "
                f"{safe_label.upper()} — {event['title']}**\n"
                f"*{scar}*\n{cost}\n"
                f"Settlement escalation is {escalation}/3. The settlement will remember this."
            )
            return MutationPlan(
                event_type="settlement.event_mitigated",
                state_after=after,
                payload={
                    "event_id": event["event_id"],
                    "method": final_method,
                    "response": "supported" if supported else "redirected",
                    "primary_participant_id": primary_participant_id,
                    "responding_participant_id": participant_id,
                    "scar": scar,
                    "cost": cost,
                },
            )

        result = await self.repository.mutate(
            ref,
            actor_id=participant_id,
            idempotency_key=idempotency_key,
            planner=planner,
        )
        if not result.accepted:
            return PublicResult(False, outcome.get("feedback", "Intervention was not accepted."))
        if result.duplicate:
            return PublicResult(True, "That intervention was already recorded.", result.event_id)
        return PublicResult(True, outcome["text"], result.event_id)

    async def expire_settlement_event(
        self, environment: Environment, *, now: datetime | None = None
    ) -> PublicResult:
        """Apply one expired live event; a concurrent intervention wins atomically."""
        if environment is not Environment.LIVE:
            return PublicResult(False, "")
        ref = self.refs[environment]
        current_time = now or datetime.now(UTC)
        outcome: dict[str, str | bool] = {}

        def planner(state: dict[str, Any]) -> MutationPlan | None:
            if (
                state.get("mode") != SessionMode.RUNNING.value
                or int(state.get("current_position", -1)) != 1
            ):
                return None
            data = copy.deepcopy(state.get("data", {}))
            event = data.get("settlement_event")
            if not event or event.get("status") not in {"active", "stabilized"}:
                return None
            expires_at = datetime.fromisoformat(str(event["expires_at"]))
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=UTC)
            if expires_at > current_time:
                return None

            if event.get("status") == "stabilized":
                method = str(event.get("primary_method", "brace"))
                scar = _settlement_scar(event, method)
                cost, escalation = _apply_settlement_cost(data, method)
                resolved = {
                    **event,
                    "status": "mitigated",
                    "method": method,
                    "response": "unanswered",
                    "scar": scar,
                    "cost": cost,
                    "resolved_at": current_time.isoformat(),
                }
                data["settlement_event_history"] = [
                    *data.get("settlement_event_history", []),
                    resolved,
                ]
                data.update(
                    {
                        "settlement_event": None,
                        "settlement_event_actions_since_last": 0,
                        "settlement_event_trigger_after": 0,
                        "settlement_last_intervener": event.get("primary_participant_id"),
                    }
                )
                after = copy.deepcopy(state)
                after["data"] = data
                outcome["text"] = (
                    f"**THE STABILIZED CHOICE BECOMES FINAL — {event['title']}**\n"
                    f"*{scar}*\n{cost}\n"
                    f"Settlement escalation is {escalation}/3. The settlement will remember this."
                )
                outcome["event_id"] = str(event["event_id"])
                return MutationPlan(
                    event_type="settlement.event_scar_finalized",
                    state_after=after,
                    payload={
                        "event_id": event["event_id"],
                        "method": method,
                        "response": "unanswered",
                        "scar": scar,
                        "cost": cost,
                        "resolved_at": current_time.isoformat(),
                    },
                )

            missed = {**event, "status": "unmitigated", "resolved_at": current_time.isoformat()}
            escalation = int(data.get("settlement_escalation", 0)) + 1
            data["settlement_event_history"] = [
                *data.get("settlement_event_history", []),
                missed,
            ]
            data.update(
                {
                    "settlement_event": None,
                    "settlement_escalation": escalation,
                    "settlement_event_actions_since_last": 0,
                    "settlement_event_trigger_after": 0,
                    "settlement_last_intervener": None,
                }
            )
            consequence = str(event["consequence"])
            if escalation >= 3:
                data["settlement_restart_pending"] = True
                consequence += (
                    f" Escalation is now {escalation}/3; the interrupted current folds back."
                )
                outcome["restart"] = True
            else:
                consequence += f" Escalation is now {escalation}/3."
            after = copy.deepcopy(state)
            after["data"] = data
            outcome["text"] = f"**UNMITIGATED — {consequence}**"
            outcome["event_id"] = str(event["event_id"])
            return MutationPlan(
                event_type="settlement.event_unmitigated",
                state_after=after,
                payload={
                    "event_id": event["event_id"],
                    "escalation": escalation,
                    "expired_at": current_time.isoformat(),
                },
            )

        state = await self.repository.state(ref)
        active = state.get("data", {}).get("settlement_event") or {}
        event_id = str(active.get("event_id", "none"))
        result = await self.repository.mutate(
            ref,
            actor_id="system:settlement-event",
            idempotency_key=f"settlement-expiry:{event_id}",
            planner=planner,
        )
        if not result.accepted or result.duplicate:
            return PublicResult(False, "", result.event_id)
        text = str(outcome["text"])
        if outcome.get("restart"):
            restarted = await self.repository.restart_current_position(
                ref,
                actor_id="system:settlement-event",
                reason="three expired whole-settlement events",
            )
            if restarted.accepted:
                text += (
                    "\n\n**POSITION 1 RESTARTED — THE INTERRUPTED CURRENT**\n"
                    "Temporary Position 1 work has returned to its recorded beginning. "
                    "Earlier completed positions and inherited settlement scars remain."
                )
                return PublicResult(True, text, restarted.event_id)
        return PublicResult(True, text, result.event_id)

    async def position(self, environment: Environment, discord_user_id: int | None = None) -> str:
        state = await self.repository.state(self.refs[environment])
        definition = self.registries[environment].get(int(state["current_position"]))
        data = state["data"]
        cycle = cycle_status_text(data, definition.position)
        facts = data.get("confirmed_facts", [])
        known = [str(item.get("public_text", "")) for item in facts[-3:]]
        margins = self._public_resource_status(
            environment, current_position=definition.position, data=data
        )
        participant_id = (
            await self.repository.resolve_participant(self.refs[environment], discord_user_id)
            if discord_user_id is not None
            else None
        )
        sections = [f"Position {definition.position} — {definition.title}", cycle]
        sections.append(
            "What is known:\n"
            + (
                "\n".join(f"• {item}" for item in known)
                if known
                else "• No current-position observation is public yet."
            )
        )
        sections.append(
            "What currently matters:\n"
            + (
                "\n".join(f"• {item}" for item in margins[:4])
                if margins
                else "• Establish one local observation before intervention."
            )
        )
        if participant_id is not None:
            since = self._since_last_contribution(data, participant_id)
            sections.append(
                "Since your last contribution:\n"
                + (
                    "\n".join(f"• {item}" for item in since)
                    if since
                    else "• No later contribution is recorded in this cycle."
                )
            )
            options, waiting, allowance = self._participant_navigation(
                environment, data, definition.position, participant_id
            )
            sections.append(f"Your available role now:\n• {allowance}")
            sections.append(
                "What can be acted on now:\n" + "\n".join(f"• {item}" for item in options)
            )
            sections.append(f"Waiting on:\n• {waiting}")
        else:
            sections.append(
                "What can be acted on now:\n• Use `/interior next` for personal options."
            )
        sections.append("Full public ledger: `/interior recall`")
        return "\n\n".join(sections)

    async def next_steps(self, environment: Environment, discord_user_id: int) -> str:
        ref = self.refs[environment]
        participant_id = await self.repository.resolve_participant(ref, discord_user_id)
        state = await self.repository.state(ref)
        position = int(state["current_position"])
        options, waiting, allowance = self._participant_navigation(
            environment, state["data"], position, participant_id
        )
        return (
            "You can help now by doing one of these:\n"
            + "\n".join(f"• {item}" for item in options)
            + f"\n\nYour available role now:\n• {allowance}"
            + f"\n\nWaiting on:\n• {waiting}"
        )

    async def current_phase_footer(self, environment: Environment) -> str:
        """Return a compact phase marker for Discord replies."""
        state = await self.repository.state(self.refs[environment])
        position = int(state["current_position"])
        cycle = ensure_cycle_state(state["data"], position)["cycle"]
        phase, activity = public_cycle_phase(cycle)
        activity_text = f" · Latest activity: **{activity}**" if activity is not None else ""
        return (
            f"_Current phase: **{phase}**{activity_text} · Position {position} · "
            f"Cycle {int(cycle.get('index', 1))}_"
        )

    def _build_summary_snapshot(
        self, environment: Environment, session_state: dict[str, Any]
    ) -> SummarySnapshot:
        state = copy.deepcopy(session_state)
        position = int(state["current_position"])
        definition = self.registries[environment].get(position)
        resource_lines = self._public_resource_status(
            environment,
            current_position=position,
            data=state["data"],
            definition=definition,
        )
        return SummarySnapshot.capture(
            environment=environment.value,
            session_state=state,
            definition=definition.model_dump(mode="json"),
            public_resource_lines=tuple(resource_lines),
        )

    @staticmethod
    def _snapshot_phase_footer(snapshot: SummarySnapshot) -> str:
        activity_text = (
            f" · Latest activity: **{snapshot.activity}**" if snapshot.activity is not None else ""
        )
        return (
            f"_Current phase: **{snapshot.phase}**{activity_text} · "
            f"Position {snapshot.position} · "
            f"Cycle {snapshot.cycle}_"
        )

    def _compact_summary_response(
        self,
        environment: Environment,
        snapshot: SummarySnapshot,
        participant_id: str,
        outcome: EngineOutcome,
    ) -> str:
        data = snapshot.session_state()["data"]
        cycle = data["cycle"]
        primary_count = len(cycle.get("primary_contributors", {}))
        primary_minimum = int(cycle.get("primary_minimum", 3))
        remaining = max(0, primary_minimum - primary_count)
        _, waiting, _ = self._participant_navigation(
            environment,
            data,
            snapshot.position,
            participant_id,
        )
        recorded = (
            "No new archive entry; the existing interaction was replayed."
            if outcome.duplicate
            else "A confirmed public summary was archived."
        )
        cost = (
            "None; this interaction was already recorded."
            if outcome.duplicate
            else "Free information action; no primary action consumed."
        )
        participation = (
            "the primary contributor minimum is met."
            if remaining == 0
            else f"{remaining} more primary contribution"
            + ("" if remaining == 1 else "s")
            + " required."
        )
        activity_text = (
            f" · latest activity {snapshot.activity}" if snapshot.activity is not None else ""
        )
        return (
            f"Current state chart generated from Position {snapshot.position} · "
            f"Cycle {snapshot.cycle} · {snapshot.phase}{activity_text}.\n\n"
            f"Recorded: {recorded}\n"
            f"Cost: {cost}\n"
            f"Cycle effect: {primary_count}/{primary_minimum} primary contributors; "
            f"{participation}\n"
            "Available next: `/interior next` for personalized options.\n"
            f"Waiting on: {waiting}\n"
            "Full public ledger: `/interior recall`"
        )

    async def current_map(self, environment: Environment) -> PositionImage | None:
        """Return the optional public-awareness map for the current position."""
        state = await self.repository.state(self.refs[environment])
        position = int(state["current_position"])
        definition = self.registries[environment].get(position)
        assets = files("uniflora.content").joinpath("assets")
        for suffix in ("png", "jpg", "jpeg", "webp"):
            asset = assets.joinpath(f"position_{position}_map.{suffix}")
            if not asset.is_file():
                continue
            payload = asset.read_bytes()
            if not payload or len(payload) > 10 * 1024 * 1024:
                logger.warning(
                    "current map asset has invalid size",
                    extra={"environment": environment.value, "position": position},
                )
                return None
            map_entity_ids = set(_MAP_CUE_ENTITY_IDS.get(position, ()))
            labels = [
                entity.discovery_label
                for entity in definition.entities
                if entity.id in map_entity_ids and entity.discovery_label is not None
            ]
            inspection_cues = (
                " Inspectable labels include " + ", ".join(labels) + "." if labels else ""
            )
            return PositionImage(
                image_filename=asset.name,
                image_alt_text=(
                    f"Current partial public-awareness map for Position {position}. "
                    "Solid blue marks confirmed water routes, broken blue marks visible water "
                    "with unknown destinations, ochre paths indicate pedestrian passages, and "
                    f"faded marks indicate unresolved features.{inspection_cues}"
                ),
                image_bytes=payload,
            )
        return None

    async def current_cycle_chart(self, environment: Environment) -> PositionImage | None:
        """Return the command-cycle chart for the current position, when packaged."""
        state = await self.repository.state(self.refs[environment])
        position = int(state["current_position"])
        definition = self.registries[environment].get(position)
        return _position_cycle_chart(position, definition.title)

    async def has_active_settlement_event(self, environment: Environment) -> bool:
        state = await self.repository.state(self.refs[environment])
        event = state.get("data", {}).get("settlement_event")
        return bool(
            (environment is Environment.TEST or int(state.get("current_position", -1)) == 1)
            and event
            and event.get("status") in {"active", "stabilized"}
        )

    async def settlement_intervention_labels(self, environment: Environment) -> dict[str, str]:
        """Return contextual button labels, with legacy-event fallbacks."""
        state = await self.repository.state(self.refs[environment])
        event = state.get("data", {}).get("settlement_event")
        if not isinstance(event, dict):
            event = {}
        costs = {
            "brace": "+strain",
            "divert": "+burden",
            "release": "-escalation, -capacity",
        }
        return {
            method: f"{settlement_choice(event, method)['label']} ({costs[method]})"
            for method in ("brace", "divert", "release")
        }

    async def open_test_settlement_event(
        self, actor_user_id: int, idempotency_key: str
    ) -> PublicResult:
        ref = self.refs[Environment.TEST]
        seed = hashlib.sha256(idempotency_key.encode()).hexdigest()[:10]
        event_id = f"se-test-{seed}"
        outcome: dict[str, str] = {}

        def planner(state: dict[str, Any]) -> MutationPlan | None:
            data = copy.deepcopy(state.get("data", {}))
            active = data.get("settlement_event")
            if active and active.get("status") in {"active", "stabilized"}:
                outcome["feedback"] = (
                    f"Test event `{active['event_id']}` is already awaiting intervention."
                )
                return None
            event = {
                "event_id": event_id,
                "kind": "relay_reversal_test",
                "title": "Central Relay is returning pressure into the household lines",
                "description": (
                    "Pale Nursery still receives moisture, but Lower Archive hears water "
                    "striking its sealed roof."
                ),
                "consequence": "Test pressure reaches another district.",
                "threatened_asset": "the household water lines",
                "scars": {
                    "brace": "The household lines hold, but knock at every relay.",
                    "divert": "The household lines hold; Lower Archive inherits their pressure.",
                    "release": "The household lines hold, but one branch remains dry.",
                },
                "choices": {
                    "brace": {
                        "label": "Dampen the relay",
                        "effect": "hold pressure, add strain",
                    },
                    "divert": {
                        "label": "Reroute the pulse",
                        "effect": "protect these lines, move burden",
                    },
                    "release": {
                        "label": "Close one branch",
                        "effect": "lower escalation, lose capacity",
                    },
                },
                "status": "active",
                "manual_test": True,
                "caused_by_action": "manual_test_event",
                "caused_by_participant_id": f"discord:{actor_user_id}",
                "opened_at": datetime.now(UTC).isoformat(),
                "expires_at": None,
            }
            data["settlement_event"] = event
            after = copy.deepcopy(state)
            after["data"] = data
            after["modified_by_force"] = True
            outcome["text"] = (
                "**WHOLE SETTLEMENT TEST EVENT — Central Relay is returning pressure into "
                "the household lines**\n"
                "Pale Nursery still receives moisture, but Lower Archive hears water striking "
                "its sealed roof.\n\n"
                "Choose one button below:\n"
                f"{settlement_choices_text(event)}\n\n"
                "The first choice prevents catastrophe and proposes a scar. A different "
                "Mycotroph can repeat that choice to soften its cost, or choose another to "
                "redirect it. This isolated test event has no deadline and cannot restart or "
                "alter the live game."
            )
            return MutationPlan(
                event_type="settlement.test_event_opened",
                state_after=after,
                payload={"event_id": event_id, "manual_test": True},
            )

        result = await self.repository.mutate(
            ref,
            actor_id=f"discord:{actor_user_id}",
            idempotency_key=idempotency_key,
            planner=planner,
        )
        if not result.accepted:
            return PublicResult(False, outcome.get("feedback", "Test event was not opened."))
        if result.duplicate:
            return PublicResult(True, "That test event was already opened.", result.event_id)
        return PublicResult(True, outcome["text"], result.event_id)

    async def scheduled_announcement_delivered(self, announcement_id: str) -> bool:
        event = await self.repository.event_by_idempotency(
            self.refs[Environment.LIVE], f"scheduled-announcement:{announcement_id}"
        )
        return event is not None

    async def mark_scheduled_announcement_delivered(
        self, announcement_id: str, channel_id: int, message_id: int
    ) -> bool:
        ref = self.refs[Environment.LIVE]
        result = await self.repository.mutate(
            ref,
            actor_id="system:scheduled-announcement",
            idempotency_key=f"scheduled-announcement:{announcement_id}",
            planner=lambda state: MutationPlan(
                event_type="announcement.delivered",
                state_after=copy.deepcopy(state),
                payload={
                    "announcement_id": announcement_id,
                    "channel_id": int(channel_id),
                    "message_id": int(message_id),
                },
            ),
        )
        return result.accepted

    async def recall(self, environment: Environment) -> str:
        state = await self.repository.state(self.refs[environment])
        data = state["data"]
        facts = data.get("confirmed_facts", [])
        current_position = int(state["current_position"])
        cycle_text = cycle_status_text(data, current_position)
        stack = data.get("public_stack")
        triggers = [
            item for item in data.get("triggered_reactions", []) if not item.get("consumed", False)
        ]
        trigger_aliases = semantic_trigger_aliases(
            data.get("triggered_reactions", []), self._observation_entities(environment)
        )
        effects = data.get("persistent_effects", [])
        settlement_scar = data.get("settlement_scar")
        settlement_event = data.get("settlement_event")
        counters = data.get("counters", {})
        resource_status = self._public_resource_status(
            environment, current_position=current_position, data=data
        )
        visible_counters: list[str] = []
        for name in ("strain", "repair", "maintenance", "saturation", "viability"):
            for target, count in counters.get(name, {}).items():
                if count:
                    visible_counters.append(f"{name}:{target}={count}")
        for name in (
            "coherence",
            "trust",
            "instability",
            "containment",
            "evidence",
            "source_reduction",
            "throughput",
            "extraction",
            "public_benefit",
            "burden",
            "remediation",
            "archival_coherence",
        ):
            if counters.get(name, 0):
                visible_counters.append(f"{name}={counters[name]}")
        proposals = [
            item for item in data.get("proposals", {}).values() if item.get("status") == "pending"
        ]
        prior_summary = data.get("prior_position_summary") if current_position > 0 else None
        sections: list[str] = [cycle_text]
        if not any(
            (
                facts,
                stack,
                triggers,
                effects,
                settlement_scar,
                settlement_event,
                visible_counters,
                proposals,
                prior_summary,
            )
        ):
            sections.append("No public discoveries have been confirmed yet.")
        if settlement_scar:
            scar_text = str(settlement_scar.get("public_text", "The mark remains."))
            sections.append("Settlement scar:\n• " + scar_text)
        if settlement_event and settlement_event.get("status") in {"active", "stabilized"}:
            if settlement_event.get("manual_test", False):
                deadline_line = "• Manual test event; no deadline or automatic restart\n"
            else:
                try:
                    event_deadline = int(
                        datetime.fromisoformat(str(settlement_event["expires_at"])).timestamp()
                    )
                    deadline_text = f"<t:{event_deadline}:R>"
                except (KeyError, TypeError, ValueError):
                    deadline_text = "at its recorded deadline"
                deadline_line = f"• Intervention closes {deadline_text}\n"
            if settlement_event.get("status") == "stabilized":
                primary_method = str(settlement_event.get("primary_method", "brace"))
                primary_choice = settlement_choice(settlement_event, primary_method)
                response_line = (
                    f"• Stabilized with **{primary_choice['label']}**; "
                    "a different Mycotroph may repeat it to soften the cost or choose another "
                    "method to redirect the scar.\n"
                )
            else:
                response_line = "• One Mycotroph can guarantee stabilization.\n"
            sections.append(
                "Active whole-settlement event:\n"
                f"• `{settlement_event['event_id']}` — {settlement_event['title']}\n"
                f"{deadline_line}"
                f"{response_line}"
                f"• {settlement_choices_text(settlement_event).replace(' · ', chr(10) + '• ')}\n"
                "• Use the event buttons, or `/interior intervene` as a fallback."
            )
        if current_position == 1 and any(
            int(data.get(name, 0))
            for name in (
                "settlement_escalation",
                "settlement_strain",
                "settlement_burden",
                "settlement_lost_capacity",
            )
        ):
            sections.append(
                "Whole-settlement pressure: "
                f"escalation {int(data.get('settlement_escalation', 0))}/3 · "
                f"strain {int(data.get('settlement_strain', 0))} · "
                f"displaced burden {int(data.get('settlement_burden', 0))} · "
                f"lost capacity {int(data.get('settlement_lost_capacity', 0))}"
            )
        if prior_summary:
            sections.append("Inherited confirmed state:\n• " + str(prior_summary))
        classified = {
            classification: [
                item for item in facts if item.get("classification", "confirmed") == classification
            ]
            for classification in (
                "historical_baseline",
                "current_measurement",
                "forecast",
                "conditional_projection",
                "obsolete_expectation",
                "unresolved_discrepancy",
                "provenance",
                "preserved_difference",
            )
        }
        confirmed = [
            item
            for item in facts
            if item.get("classification", "confirmed") not in {*classified, "projected"}
        ]
        projected = [
            *[item for item in facts if item.get("classification") == "projected"],
            *classified["forecast"],
            *classified["conditional_projection"],
        ]
        provenance = classified["provenance"]
        preserved = classified["preserved_difference"]
        if confirmed:
            sections.append(
                "Confirmed current conditions:\n"
                + "\n".join(f"• {fact['public_text']}" for fact in confirmed)
            )
        if projected:
            sections.append(
                "Public forecasts:\n" + "\n".join(f"• {fact['public_text']}" for fact in projected)
            )
        if provenance:
            sections.append(
                "Public provenance:\n"
                + "\n".join(f"• {fact['public_text']}" for fact in provenance)
            )
        if preserved:
            sections.append(
                "Preserved differences:\n"
                + "\n".join(f"• {fact['public_text']}" for fact in preserved)
            )
        for classification, title in (
            ("historical_baseline", "Historical baselines"),
            ("current_measurement", "Current measurements"),
            ("obsolete_expectation", "Obsolete expectations"),
            ("unresolved_discrepancy", "Unresolved discrepancies"),
        ):
            entries = classified[classification]
            if entries:
                sections.append(
                    f"{title}:\n" + "\n".join(f"• {fact['public_text']}" for fact in entries)
                )
        if resource_status:
            sections.append(
                "Public deficits and operating margins:\n"
                + "\n".join(f"• {item}" for item in resource_status)
            )
        if proposals:
            sections.append(
                "Pending proposals:\n"
                + "\n".join(
                    f"• `{item['proposal_id']}` ({item.get('kind', 'reconstruction')}): "
                    + self._pending_proposal_summary(item)
                    for item in proposals
                )
            )
        if stack:
            entries = " -> ".join(item["label"] for item in stack.get("entries", []))
            sections.append(
                f"Public stack `{stack['stack_id']}` ({stack['status']}): {entries or 'empty'}"
            )
        if triggers:
            sections.append(
                "Available reactions:\n"
                + "\n".join(
                    f"• `{trigger_aliases[str(item['trigger_id'])]}`: "
                    f"{str(item['kind']).replace('_', ' ')}\n"
                    f"  Use `/interior act trigger trigger_id:"
                    f"{trigger_aliases[str(item['trigger_id'])]}`"
                    for item in triggers
                )
            )
        if effects:
            sections.append(
                "Persistent effects: " + ", ".join(str(item).replace("_", " ") for item in effects)
            )
        if visible_counters:
            sections.append("Visible counters: " + ", ".join(visible_counters))
        material_terms = data.get("material_terms_ledger", [])
        if material_terms:
            sections.append(
                "Material Terms Ledger:\n"
                + "\n".join(
                    f"• {item.get('original_term', item.get('term', 'term'))}: "
                    f"{item.get('compatible_meaning', item.get('meaning', 'preserved'))}"
                    for item in material_terms[-8:]
                )
            )
        versioned_records = data.get("versioned_records", [])
        if versioned_records:
            sections.append(
                "Versioned public archive:\n"
                + "\n".join(
                    f"• `{item.get('record_id', 'record')}` v{item.get('version', '?')} "
                    f"({item.get('record_type', 'record')})"
                    for item in versioned_records[-8:]
                )
            )
        if current_position == 0:
            definition = self.registries[environment].get(0)
            guidance = position_zero_proposal_guidance(data, definition)
            if guidance is not None:
                sections.append(guidance)
        return "\n".join(sections)

    def _public_resource_status(
        self,
        environment: Environment,
        *,
        current_position: int,
        data: dict[str, Any],
        definition: Any | None = None,
    ) -> list[str]:
        """Summarize resource rules only after their observations are public."""
        if definition is None:
            definition = self.registries[environment].get(current_position)
        entities = {entity.id: entity for entity in definition.entities}
        unlocked = {str(item) for item in data.get("unlocked_observations", [])}
        resources = data.get("resources", {})
        counters = data.get("counters", {})
        lines: list[str] = []

        def resource(entity_id: str, resource_id: str = "water") -> float:
            return float(resources.get(entity_id, {}).get(resource_id, 0))

        if current_position == 0 and definition.sustainability is not None:
            rules = definition.sustainability
            if "northern_usable_capacity" in unlocked:
                current = resource(rules.donor_entity_id, rules.resource_id)
                reserve = float(rules.minimum_donor_reserve)
                lines.append(
                    f"Northern Reservoir: current {current:g} water; required reserve "
                    f"{reserve:g}; transferable headroom {max(0.0, current - reserve):g}"
                )
            if "eastern_viability_deficit" in unlocked:
                current = resource(rules.recipient_entity_id, rules.resource_id)
                minimum = float(rules.minimum_recipient_viability)
                lines.append(
                    f"Eastern Growth: current {current:g} water; required minimum "
                    f"{minimum:g}; deficit {max(0.0, minimum - current):g}"
                )

        if current_position == 1 and definition.circulation is not None:
            rules = definition.circulation
            if "nursery_projected_need" in unlocked:
                nursery = entities[rules.recipient_entity_id]
                branch = str(data.get("forecast_branch", "stable"))
                key = "accelerated_minimum" if branch == "accelerated" else "stable_minimum"
                minimum = float(nursery.measurements[key])
                current = resource(rules.recipient_entity_id, rules.resource_id)
                lines.append(
                    f"Pale Nursery ({branch} forecast): current {current:g} water; required "
                    f"{minimum:g}; deficit {max(0.0, minimum - current):g}"
                )
            if "condensation_shared_output" in unlocked:
                output = resource(rules.source_entity_id, rules.resource_id)
                available = rules.source_entity_id in data.get("sustained_targets", [])
                maintenance = "satisfied" if available else "required before use"
                weather = data.get("exterior_weather", {})
                influence = (
                    weather.get("water_system_multipliers")
                    or weather.get("continuous_influence")
                    or weather.get("modifiers")
                    or {}
                    if isinstance(weather, dict)
                    else {}
                )
                multiplier_raw = (
                    influence.get("condensation_veil_multiplier")
                    if isinstance(influence, dict)
                    else None
                )
                weather_detail = ""
                try:
                    multiplier = float(multiplier_raw)
                except (TypeError, ValueError):
                    multiplier = None
                if multiplier is not None:
                    weather_detail = (
                        f"; exterior multiplier ×{multiplier:.4f}; "
                        f"weather-adjusted output {output * multiplier:.2f} water"
                    )
                lines.append(
                    f"Condensation Veil: current-cycle output {output:g} water; maintenance "
                    f"{maintenance}{weather_detail}"
                )
            if "route_07_loss" in unlocked:
                reassessed = rules.source_pathway_id in data.get("reassessed_pathways", [])
                efficiency = (
                    rules.reassessed_efficiency if reassessed else rules.unassessed_efficiency
                )
                lines.append(
                    f"Route 07: delivery efficiency {efficiency * 100:g}%; loss "
                    f"{(1 - efficiency) * 100:g}%"
                )
            if "northern_inherited_burden" in unlocked:
                current = resource(rules.reserve_entity_id, rules.resource_id)
                strain = int(counters.get("strain", {}).get(rules.reserve_entity_id, 0))
                tactical = definition.tactical
                assert tactical is not None
                reserve = (
                    rules.reserve_floor
                    + (strain // tactical.strain_threshold) * tactical.strain_reserve_penalty
                )
                lines.append(
                    f"Northern Reservoir: current {current:g} water; required reserve "
                    f"{reserve:g}; headroom {max(0.0, current - reserve):g}"
                )
            if "eastern_relay_limit" in unlocked:
                current = resource("eastern_growth", rules.resource_id)
                viability = float(entities["eastern_growth"].measurements["minimum_viability"])
                protected = viability + rules.eastern_recovery_buffer
                lines.append(
                    f"Eastern Growth: current {current:g} water; viability deficit "
                    f"{max(0.0, viability - current):g}; protected relay level {protected:g}; "
                    f"deficit before relaying {max(0.0, protected - current):g}"
                )
            if "archive_coherence_cost" in unlocked:
                current = resource(rules.archive_entity_id, rules.resource_id)
                floor = float(rules.archive_coherence_floor)
                lines.append(
                    f"Lower Archive: current {current:g} water; coherence floor {floor:g}; "
                    f"donation headroom {max(0.0, current - floor):g}"
                )
            if "indicator_bed_capacity_limited" in unlocked and definition.provision_arc:
                target = "return_indicator_bed"
                viability = float(counters.get("viability", {}).get(target, 0))
                saturation = float(counters.get("saturation", {}).get(target, 0))
                limits = definition.provision_arc.thresholds
                lines.append(
                    f"Return Indicator Bed: viability {viability:g}/{limits.minimum_viability:g} "
                    f"minimum; saturation {saturation:g}/{limits.saturation_limit:g} limit; "
                    f"headroom {max(0.0, limits.saturation_limit - saturation):g}"
                )

        if current_position == 2:
            values = data.get("record_values", {})
            sent = float(values.get("circulation_ledger", 0))
            delivered = float(values.get("nursery_intake_sensor", 0))
            retained = float(values.get("nursery_retention_survey", 0))
            if {"source_sent_measurement", "intake_delivered_measurement"}.issubset(unlocked):
                lines.append(
                    f"Source to intake: sent {sent:g} water; delivered {delivered:g}; "
                    f"difference {max(0.0, sent - delivered):g}"
                )
            if {"intake_delivered_measurement", "survey_retained_measurement"}.issubset(unlocked):
                lines.append(
                    f"Intake to later survey: delivered {delivered:g} water; retained "
                    f"{retained:g}; difference {max(0.0, delivered - retained):g}"
                )

        if current_position in {3, 4, 6} and definition.provision_arc is not None:
            limits = definition.provision_arc.thresholds
            if "intake_exceeds_dry_limit" in unlocked:
                intake = entities["production_intake_channel"].measurements
                draw = float(intake["average_draw"])
                maximum = float(intake["dry_season_limit"])
                lines.append(
                    f"Production water draw: current {draw:g}; maximum {maximum:g}; "
                    f"excess {max(0.0, draw - maximum):g}"
                )
            if "production_exceeds_capacity" in unlocked:
                throughput = float(counters.get("throughput", 0))
                maximum = float(limits.maximum_throughput)
                lines.append(
                    f"Treatment throughput: current {throughput:g}; maximum {maximum:g}; "
                    f"excess {max(0.0, throughput - maximum):g}"
                )
            if "bed_viability_stressed" in unlocked:
                viability = float(counters.get("viability", {}).get("white_rot_beds", 0))
                minimum = float(limits.minimum_viability)
                lines.append(
                    f"White Rot Bed viability: current {viability:g}; minimum {minimum:g}; "
                    f"deficit {max(0.0, minimum - viability):g}"
                )
            if "bed_saturation_overloaded" in unlocked:
                saturation = float(counters.get("saturation", {}).get("white_rot_beds", 0))
                maximum = float(limits.saturation_limit)
                lines.append(
                    f"White Rot Bed saturation: current {saturation:g}; limit {maximum:g}; "
                    f"headroom {max(0.0, maximum - saturation):g}"
                )
            if unlocked & {"upstream_requires_repetition", "downstream_requires_comparison"}:
                evidence = float(counters.get("evidence", 0))
                minimum = float(limits.minimum_evidence)
                lines.append(
                    f"Paired public evidence: current {evidence:g}; minimum {minimum:g}; "
                    f"deficit {max(0.0, minimum - evidence):g}"
                )
            if "spent_substrate_needs_custody" in unlocked:
                containment = float(counters.get("containment", 0))
                minimum = float(limits.minimum_containment)
                lines.append(
                    f"Containment records: current {containment:g}; minimum {minimum:g}; "
                    f"deficit {max(0.0, minimum - containment):g}"
                )
            if "unnecessary_output_quota" in unlocked:
                output = float(counters.get("throughput", 0))
                need = float(
                    entities["provision_works"].measurements["verified_public_need_output"]
                )
                lines.append(
                    f"Production output: current {output:g}; verified need {need:g}; "
                    f"not established as necessary {max(0.0, output - need):g}; revised output "
                    f"must be below {output:g}"
                )
            if "production_water_competition" in unlocked:
                draw = float(counters.get("extraction", 0))
                recovery = float(entities["public_well_seven"].measurements["current_recovery"])
                lines.append(
                    f"Production water cap: current draw {draw:g}; well recovery "
                    f"{recovery:g}; chosen cap must be below {draw:g}"
                )
            if "returned_water_use_limit" in unlocked:
                returned = float(entities["warm_return_channel"].resources["returned_volume"])
                lines.append(
                    f"Returned water: volume {returned:g}; verified usable now 0; usable-water "
                    f"deficit cannot be offset by the unverified {returned:g}"
                )

        return lines

    @staticmethod
    def _since_last_contribution(data: dict[str, Any], participant_id: str) -> list[str]:
        contributions = current_cycle_contributions(data)
        last_index = next(
            (
                index
                for index in range(len(contributions) - 1, -1, -1)
                if str(contributions[index].get("participant_id")) == participant_id
            ),
            -1,
        )
        if last_index < 0:
            return ["You have not contributed in this cycle yet."]
        later = contributions[last_index + 1 :]
        return [
            f"{str(item.get('action', 'action')).replace('_', ' ')} was recorded by "
            "another participant."
            for item in later[-3:]
        ]

    def _participant_navigation(
        self,
        environment: Environment,
        data: dict[str, Any],
        position: int,
        participant_id: str,
    ) -> tuple[list[str], str, str]:
        cycle = ensure_cycle_state(data, position)["cycle"]
        primary = cycle.get("primary_contributors", {})
        primary_minimum = int(cycle.get("primary_minimum", 3))
        primary_used = participant_id in primary
        test_surface = environment is Environment.TEST
        pending = [
            item for item in data.get("proposals", {}).values() if item.get("status") == "pending"
        ]
        stack = data.get("public_stack") or {}
        response_open = bool(pending) or stack.get("status") == "open"
        if primary_used and not test_surface:
            used = str(primary[participant_id].get("action", "primary action")).replace("_", " ")
            allowance = f"Your Cycle {cycle['index']} primary action was used by {used}."
            if not response_open and len(primary) >= primary_minimum:
                allowance += (
                    " You may still assemble the proposal when its public prerequisites are ready."
                )
        elif primary_used:
            allowance = (
                f"Your Cycle {cycle['index']} primary contribution is recorded; the test "
                "surface leaves command experimentation open."
            )
        else:
            allowance = f"Your Cycle {cycle['index']} primary action is available."

        reactions = [
            item for item in data.get("triggered_reactions", []) if not item.get("consumed", False)
        ]
        aliases = semantic_trigger_aliases(reactions, self._observation_entities(environment))
        eligible_reactions: list[dict[str, Any]] = []
        for reaction in reactions:
            excluded = {str(reaction.get("source_participant_id", ""))}
            excluded.update(str(item) for item in reaction.get("excluded_participant_ids", []))
            if participant_id not in excluded:
                eligible_reactions.append(reaction)

        options: list[str] = []
        for reaction in eligible_reactions[:2]:
            public_id = aliases[str(reaction["trigger_id"])]
            options.append(
                f"Respond to {str(reaction.get('kind', 'reaction')).replace('_', ' ')} "
                f"(reaction): `/interior act trigger trigger_id:{public_id}`"
            )

        for proposal in pending:
            if str(proposal.get("author_participant_id", "")) != participant_id:
                options.append(
                    f"Review proposal `{proposal['proposal_id']}` (response): "
                    f"`/interior act confirm proposal_id:{proposal['proposal_id']}`"
                )
                break

        if not response_open and (not primary_used or test_surface) and len(options) < 3:
            definition = self.registries[environment].get(position)
            unlock_action = "observe" if position <= 2 else "inspect"
            command = (
                "/interior act observe" if unlock_action == "observe" else "/interior works inspect"
            )
            actionable = self._actionable_entity_choices(
                environment, definition, data, {unlock_action}
            )
            unresolved_cue = next(
                (
                    label.removeprefix("Inspect: ")
                    for label, _ in actionable
                    if label.startswith("Inspect: ")
                ),
                None,
            )
            if unresolved_cue is not None:
                options.append(f"Inspect `{unresolved_cue}` (primary): `{command}`")
            else:
                options.append(
                    f"Choose an available inspection target in the popup (primary): `{command}`"
                )
        if (
            not response_open
            and position == 1
            and "route_07_loss" in data.get("unlocked_observations", [])
            and len(options) < 3
        ):
            options.append("Check confirmed flow arithmetic (free): `/interior act calculate`")
        if not response_open and data.get("confirmed_facts") and len(options) < 3:
            options.append("Summarize confirmed discoveries (free): `/interior act summarize`")
        if len(options) < 3:
            options.append("Review the complete public ledger (free): `/interior recall`")
        options = options[:3]

        missing = max(0, primary_minimum - len(primary))
        if pending:
            waiting = "A different participant must confirm or challenge the pending proposal."
        elif missing:
            noun = "account" if missing == 1 else "accounts"
            waiting = f"{missing} primary {noun} from different participants. Waiting is valid."
        elif reactions and not eligible_reactions:
            waiting = "A visible reaction must be answered by a different participant."
        elif not response_open:
            waiting = (
                "No additional account is required for the contributor minimum; an existing "
                "contributor may assemble the proposal when its public prerequisites are ready."
            )
        else:
            waiting = "Nothing mandatory is waiting on you right now."
        return options, waiting, allowance

    def _navigation_footer(
        self,
        environment: Environment,
        data: dict[str, Any],
        position: int,
        participant_id: str,
        outcome: EngineOutcome,
        action: CandidateAction | None,
    ) -> str:
        cycle = ensure_cycle_state(data, position)["cycle"]
        options, waiting, allowance = self._participant_navigation(
            environment, data, position, participant_id
        )
        if action is not None and action.action == "summarize":
            next_guidance = "See your personalized options (free): `/interior next`"
            options = [next_guidance, *options][:3]
        if outcome.accepted and not outcome.duplicate:
            recorded = (
                str(outcome.event_type or outcome.reason_key).replace("_", " ").replace(".", " ")
            )
        elif outcome.duplicate:
            recorded = "No new record; this command was already processed."
        else:
            recorded = "No state change; the command was not accepted."

        if not outcome.accepted or outcome.duplicate:
            cost = "None."
        elif action is None:
            cost = "Recorded by the command's public action class."
        elif action.action == "use_triggered_reaction":
            cost = "Reaction for the current public window."
        elif action.action in {"calculate_flow", "audit", "compare_records", "summarize"}:
            cost = "Free information or verification action."
        elif outcome.reason_key == "observation_corroborated":
            cost = "Free corroboration; no primary action consumed."
        elif action.action in PROPOSAL_ACTIONS and outcome.reason_key == "cycle_reassessed":
            cost = "Proposal attempt; reassessment refreshed the cycle allowances."
        elif (
            action.action in PROPOSAL_ACTIONS
            and str(cycle.get("primary_contributors", {}).get(participant_id, {}).get("action", ""))
            != action.action
        ):
            cost = "Proposal assembly; your existing primary contribution remains recorded."
        elif environment is Environment.TEST:
            cost = "Primary contribution recorded; test command allowance remains open."
        else:
            cost = f"Primary action for Cycle {cycle['index']}."

        primary_minimum = int(cycle.get("primary_minimum", 3))
        effect = (
            f"{len(cycle.get('primary_contributors', {}))}/{primary_minimum} primary "
            f"contributors; {allowance}"
        )
        return (
            f"Recorded: {recorded}\n"
            f"Cost: {cost}\n"
            f"Cycle effect: {effect}\n"
            "Available next:\n"
            + "\n".join(f"• {item}" for item in options)
            + f"\nWaiting on: {waiting}"
        )

    @staticmethod
    def _confusion_reason(outcome: EngineOutcome) -> str:
        feedback = str((outcome.public_data or {}).get("feedback", "")).casefold()
        if "public response window" in feedback:
            return "response_window_open"
        if "distinct" in feedback and "contributor" in feedback:
            return "insufficient_contributors"
        if "already spent" in feedback:
            return "primary_action_already_used"
        if "different participant" in feedback or "another participant" in feedback:
            return "wrong_participant"
        if (
            "earlier public" in feedback
            or "must be public first" in feedback
            or "observational contribution" in feedback
        ):
            return "unresolved_prerequisite"
        if "expired" in feedback or "consumed" in feedback:
            return "expired_reaction"
        if "phase" in feedback or "cycle needs" in feedback:
            return "invalid_phase"
        if outcome.reason_key == "cycle_action_unavailable":
            return "cycle_action_unavailable"
        if "no public" in feedback and ("entity" in feedback or "observation" in feedback):
            return "hidden_entity_attempted"
        if outcome.reason_key == "observation_corroborated" or "already confirmed" in feedback:
            return "duplicate_observation"
        if outcome.reason_key in {"invalid_action", "proposal_rejected"}:
            return "malformed_or_invalid_field"
        return outcome.reason_key

    @staticmethod
    def _pending_proposal_summary(item: dict[str, Any]) -> str:
        if item.get("kind") == "reciprocity":
            return "producer obligations preserve public benefit and local burden separately"
        if item.get("kind") == "remediation_protocol":
            return "source reduction, compatibility, evidence, containment, and shutdown cycle"
        if item.get("kind") == "memory_archive":
            return "versioned claim, evidence, correction, and unresolved conflict"
        if item.get("kind") == "reconstruction":
            current = float(item.get("current_output", 0))
            revised = float(item.get("revised_output", 0))
            return f"production reform {current:g} → {revised:g} with public governance"
        if item.get("kind") == "translation":
            return "plural record mapping awaits confirmation"
        if item.get("kind") == "circulation":
            strategy = str(item.get("strategy", "circulation plan")).replace("_", " ")
            source = float(item.get("source_amount", 0))
            pathway = float(item.get("pathway_delivery", item.get("delivered_amount", 0)))
            support = float(item.get("support_amount", 0))
            delivered = float(item.get("delivered_amount", 0))
            branch = "branch recorded" if item.get("branch_condition") else "branch unresolved"
            return (
                f"{strategy}; {source:g} Veil → {pathway:g} route delivery + "
                f"{support:g} support = {delivered:g}; {branch}"
            )
        return (
            "conditional branch recorded"
            if item.get("branch_condition")
            else "conditional branch unresolved"
        )

    def _observation_entities(self, environment: Environment) -> dict[str, str]:
        return {
            observation.id: observation.entity_id
            for definition in self.registries[environment].all()
            for observation in definition.observations
        }

    async def pending_artifact_reveal(self, environment: Environment) -> ArtifactReveal | None:
        state = await self.repository.state(self.refs[environment])
        current_position = int(state["current_position"])
        data = state["data"]
        revealed = {str(item) for item in data.get("revealed_artifacts", [])}
        for definition in self.registries[environment].all():
            if definition.position > current_position:
                continue
            for presentation in definition.triggered_presentations:
                if presentation.id in revealed or not self._reveal_condition_met(
                    data,
                    presentation.condition.counter,
                    presentation.condition.target,
                    presentation.condition.minimum,
                ):
                    continue
                asset = files("uniflora.content").joinpath(*presentation.image_asset.split("/"))
                return ArtifactReveal(
                    reveal_id=presentation.id,
                    source_position=definition.position,
                    content_version=definition.content_version,
                    introduction=presentation.introduction,
                    image_filename=presentation.image_asset.rsplit("/", 1)[-1],
                    image_alt_text=presentation.image_alt_text,
                    image_bytes=asset.read_bytes(),
                )
        return None

    async def mark_artifact_reveal_delivered(
        self,
        environment: Environment,
        reveal_id: str,
        message_id: int,
    ) -> bool:
        ref = self.refs[environment]
        matched = next(
            (
                (definition, presentation)
                for definition in self.registries[environment].all()
                for presentation in definition.triggered_presentations
                if presentation.id == reveal_id
            ),
            None,
        )
        if matched is None:
            return False
        definition, presentation = matched

        def planner(state: dict[str, Any]) -> MutationPlan | None:
            if int(state["current_position"]) < definition.position:
                return None
            after = copy.deepcopy(state)
            data = after["data"]
            revealed = [str(item) for item in data.get("revealed_artifacts", [])]
            if reveal_id in revealed or not self._reveal_condition_met(
                data,
                presentation.condition.counter,
                presentation.condition.target,
                presentation.condition.minimum,
            ):
                return None
            data["revealed_artifacts"] = [*revealed, reveal_id]
            deliveries = dict(data.get("artifact_reveal_deliveries", {}))
            deliveries[reveal_id] = {
                "message_id": int(message_id),
                "source_position": definition.position,
                "content_version": definition.content_version,
            }
            data["artifact_reveal_deliveries"] = deliveries
            return MutationPlan(
                event_type="artifact.revealed",
                state_after=after,
                payload={
                    "reveal_id": reveal_id,
                    "message_id": int(message_id),
                    "source_position": definition.position,
                    "content_version": definition.content_version,
                },
            )

        result = await self.repository.mutate(
            ref,
            actor_id="system:artifact-reveal",
            idempotency_key=f"artifact-reveal:{environment.value}:{reveal_id}",
            planner=planner,
        )
        return result.accepted

    @staticmethod
    def _reveal_condition_met(
        data: dict[str, Any], counter: str, target: str | None, minimum: float
    ) -> bool:
        value: object = data.get("counters", {}).get(counter, 0)
        if target is not None:
            value = value.get(target, 0) if isinstance(value, dict) else 0
        try:
            return float(value) >= minimum
        except (TypeError, ValueError):
            return False

    async def accessibility(self, environment: Environment) -> str:
        state = await self.repository.state(self.refs[environment])
        definition = self.registries[environment].get(int(state["current_position"]))
        commands = "\n".join(f"• {item}" for item in definition.accessibility.explicit_command_help)
        text = (
            definition.accessibility.summary
            + "\n"
            + cycle_rules_help()
            + (f"\n{commands}" if commands else "")
        )
        if environment is Environment.TEST:
            text += (
                "\nTest override: per-participant primary-command and response-command "
                "allowances remain open, and the game-action cooldown is disabled. "
                "Evidence prerequisites, the proposal/Response boundary, and distinct-"
                "participant requirements still apply."
            )
        return text

    async def close_cycle(
        self, environment: Environment, actor_user_id: int, reason: str
    ) -> PublicResult:
        reason = reason.strip()
        if not reason:
            return PublicResult(False, "A public reason is required to close a cycle.")
        ref = self.refs[environment]
        result_text: dict[str, str] = {}

        def planner(state: dict[str, Any]) -> MutationPlan | None:
            position = int(state["current_position"])
            data = ensure_cycle_state(state.get("data", {}), position)
            if data.get("position_completed"):
                result_text["text"] = "The completed Position has no open cycle to close."
                return None
            closed_index = int(data["cycle"]["index"])
            proposals = copy.deepcopy(data.get("proposals", {}))
            for proposal in proposals.values():
                if proposal.get("status") == "pending":
                    proposal["status"] = "withdrawn"
                    proposal["withdrawal_reason"] = reason
            data["proposals"] = proposals
            data = advance_cycle(data, position, "admin_closed", reason)
            after = copy.deepcopy(state)
            after["data"] = data
            result_text["text"] = (
                f"Cycle {closed_index} closed for reassessment: {reason}\n"
                f"Cycle {data['cycle']['index']} begins; discoveries and persistent state remain."
            )
            return MutationPlan(
                event_type="admin.cycle_closed",
                state_after=after,
                payload={
                    "position": position,
                    "cycle_index": closed_index,
                    "reason": reason,
                },
                rebuild_projections=True,
            )

        result = await self.repository.mutate(
            ref,
            actor_id=f"discord:{actor_user_id}",
            idempotency_key=None,
            planner=planner,
        )
        return PublicResult(
            result.accepted,
            result_text.get("text", result.reason or "Cycle close was not applied."),
            result.event_id,
        )

    async def pending_position_announcement(
        self, environment: Environment
    ) -> PositionAnnouncement | None:
        state = await self.repository.state(self.refs[environment])
        position = int(state["current_position"])
        definition = self.registries[environment].get(position)
        presentation = definition.presentation
        cycle_chart = _position_cycle_chart(position, definition.title)
        announced = {
            int(item) for item in state["data"].get("announced_position_introductions", [])
        }
        delivery = state["data"].get("position_introduction_deliveries", {}).get(str(position), {})
        delivered_version = str(delivery.get("content_version", ""))
        if (presentation is None and cycle_chart is None) or (
            position in announced
            and delivered_version
            and not _is_newer_content_version(definition.content_version, delivered_version)
        ):
            return None
        if presentation is None:
            assert cycle_chart is not None
            return PositionAnnouncement(
                position=position,
                introduction=(
                    f"## POSITION {position} — {definition.title.upper()}\n\n"
                    f"{definition.public_premise}\n\n"
                    "The attached cycle chart is the public reference for this position."
                ),
                image_filename=cycle_chart.image_filename,
                image_alt_text=cycle_chart.image_alt_text,
                image_bytes=cycle_chart.image_bytes,
            )
        asset = files("uniflora.content").joinpath(*presentation.image_asset.split("/"))
        additional_images = tuple(
            PositionImage(
                image_filename=image.image_asset.rsplit("/", 1)[-1],
                image_alt_text=image.image_alt_text,
                image_bytes=files("uniflora.content")
                .joinpath(*image.image_asset.split("/"))
                .read_bytes(),
            )
            for image in presentation.additional_images
        )
        if cycle_chart is not None and cycle_chart.image_filename not in {
            image.image_filename for image in additional_images
        }:
            additional_images = (*additional_images, cycle_chart)
        return PositionAnnouncement(
            position=position,
            introduction=presentation.introduction,
            image_filename=presentation.image_asset.rsplit("/", 1)[-1],
            image_alt_text=presentation.image_alt_text,
            image_bytes=asset.read_bytes(),
            additional_images=additional_images,
        )

    async def mark_position_announcement_delivered(
        self, environment: Environment, position: int, message_id: int
    ) -> bool:
        ref = self.refs[environment]
        definition = self.registries[environment].get(position)

        def planner(state: dict[str, Any]) -> MutationPlan | None:
            if int(state["current_position"]) != position:
                return None
            after = copy.deepcopy(state)
            data = after["data"]
            announced = [int(item) for item in data.get("announced_position_introductions", [])]
            deliveries = dict(data.get("position_introduction_deliveries", {}))
            existing = deliveries.get(str(position), {})
            if (
                position in announced
                and existing.get("content_version") == definition.content_version
            ):
                return None
            data["announced_position_introductions"] = (
                announced if position in announced else [*announced, position]
            )
            deliveries[str(position)] = {
                "message_id": int(message_id),
                "content_version": definition.content_version,
                "pinned": False,
            }
            data["position_introduction_deliveries"] = deliveries
            return MutationPlan(
                event_type="position.introduction_announced",
                state_after=after,
                payload={
                    "position": position,
                    "message_id": int(message_id),
                    "content_version": definition.content_version,
                },
            )

        result = await self.repository.mutate(
            ref,
            actor_id="system:position-announcement",
            idempotency_key=(
                f"position-announcement:{environment.value}:{position}:"
                f"{definition.content_version}:{message_id}"
            ),
            planner=planner,
        )
        return result.accepted

    async def pending_position_pin(self, environment: Environment) -> tuple[int, int] | None:
        state = await self.repository.state(self.refs[environment])
        position = int(state["current_position"])
        definition = self.registries[environment].get(position)
        if (
            definition.presentation is None
            and _position_cycle_chart(position, definition.title) is None
        ):
            return None
        delivery = state["data"].get("position_introduction_deliveries", {}).get(str(position))
        if not delivery or delivery.get("pinned", False):
            return None
        return position, int(delivery["message_id"])

    async def mark_position_announcement_pinned(
        self, environment: Environment, position: int, message_id: int
    ) -> bool:
        ref = self.refs[environment]

        def planner(state: dict[str, Any]) -> MutationPlan | None:
            if int(state["current_position"]) != position:
                return None
            after = copy.deepcopy(state)
            data = after["data"]
            deliveries = dict(data.get("position_introduction_deliveries", {}))
            delivery = dict(deliveries.get(str(position), {}))
            if int(delivery.get("message_id", 0)) != int(message_id) or delivery.get(
                "pinned", False
            ):
                return None
            delivery["pinned"] = True
            deliveries[str(position)] = delivery
            data["position_introduction_deliveries"] = deliveries
            return MutationPlan(
                event_type="position.introduction_pinned",
                state_after=after,
                payload={"position": position, "message_id": int(message_id)},
            )

        result = await self.repository.mutate(
            ref,
            actor_id="system:position-announcement",
            idempotency_key=(
                f"position-announcement-pin:{environment.value}:{position}:{message_id}"
            ),
            planner=planner,
        )
        return result.accepted

    async def mark_position_announcement_missing(
        self, environment: Environment, position: int, message_id: int
    ) -> bool:
        ref = self.refs[environment]

        def planner(state: dict[str, Any]) -> MutationPlan | None:
            if int(state["current_position"]) != position:
                return None
            after = copy.deepcopy(state)
            data = after["data"]
            deliveries = dict(data.get("position_introduction_deliveries", {}))
            delivery = dict(deliveries.get(str(position), {}))
            if int(delivery.get("message_id", 0)) != int(message_id) or delivery.get(
                "pinned", False
            ):
                return None
            delivery["pinned"] = True
            delivery["message_missing"] = True
            deliveries[str(position)] = delivery
            data["position_introduction_deliveries"] = deliveries
            return MutationPlan(
                event_type="position.introduction_missing",
                state_after=after,
                payload={"position": position, "message_id": int(message_id)},
            )

        result = await self.repository.mutate(
            ref,
            actor_id="system:position-announcement",
            idempotency_key=(
                f"position-announcement-missing:{environment.value}:{position}:{message_id}"
            ),
            planner=planner,
        )
        return result.accepted

    async def reset_test(self, actor_user_id: int) -> PublicResult:
        initial = self.registries[Environment.TEST].get(0).initial_state()
        result = await self.repository.reset(
            self.refs[Environment.TEST], f"discord:{actor_user_id}", initial
        )
        return PublicResult(
            result.accepted,
            "Test session reset to a clean, locked Position 0 state.",
            result.event_id,
        )

    async def force_observation(self, observation_id: str, actor_user_id: int) -> PublicResult:
        definition = self.registries[Environment.TEST].get(0)
        observation = next(
            (item for item in definition.observations if item.id == observation_id), None
        )
        if observation is None:
            raise StorageError("unknown Position 0 observation")
        result = await self.repository.force_unlock_observation(
            self.refs[Environment.TEST],
            observation_id=observation.id,
            public_text=observation.public_text,
            fact_key=observation.fact_key,
            actor_id=f"discord:{actor_user_id}",
        )
        if not result.accepted:
            raise StorageError("observation is already unlocked")
        return PublicResult(
            True,
            f"FORCED DEBUG OBSERVATION: {observation.public_text}\nTest session marked modified.",
            result.event_id,
        )

    async def copy_live_content_to_test(self, actor_user_id: int) -> PublicResult:
        reloaded = PuzzleRegistry.load_packaged()
        reloaded_narrator = FallbackNarrator()
        reloaded.validate_narration_keys(reloaded_narrator.templates)
        self.registries[Environment.TEST] = reloaded
        self.narrators[Environment.TEST] = reloaded_narrator
        if self.environment_validator is not None:
            self.environment_validator.set_registry(Environment.TEST, reloaded)
        ref = self.refs[Environment.TEST]
        current_state = await self.repository.state(ref)
        current_position = int(current_state["current_position"])
        definition = reloaded.get(current_position)
        current_data = dict(current_state.get("data", {}))
        upgraded = (
            self.environment_validator.upgrade_position(
                Environment.TEST, current_position, current_data
            )
            if self.environment_validator is not None
            else None
        )

        def planner(state: dict[str, object]) -> MutationPlan:
            after = dict(state)
            data = copy.deepcopy(upgraded or after["data"])
            data["content_key"] = definition.key
            data["content_version"] = definition.content_version
            after["data"] = data
            return MutationPlan(
                event_type="admin.test_content.reloaded",
                state_after=after,
                payload={
                    "content_key": definition.key,
                    "content_version": definition.content_version,
                    "progress_copied": False,
                },
            )

        result = await self.repository.mutate(
            ref,
            actor_id=f"discord:{actor_user_id}",
            idempotency_key=None,
            planner=planner,
        )
        return PublicResult(
            result.accepted,
            "Test content reloaded from validated files; no live or test progress was copied.",
            result.event_id,
        )

    async def validate_content(self) -> PublicResult:
        report = await validate_packaged_content()
        text = "Content validation passed:\n" + "\n".join(f"• {check}" for check in report.checks)
        return PublicResult(report.valid, text)

    async def debug_test_state(self) -> str:
        state = await self.repository.state(self.refs[Environment.TEST])
        data = state["data"]
        contributors = sorted({item["participant_id"] for item in data.get("contributions", [])})
        cycle = data.get("cycle", {})
        return (
            f"position={state['current_position']} profile={state['response_profile']} "
            f"modified={state['modified_by_force']} "
            f"cycle={cycle.get('index', 1)} phase={cycle.get('phase', 'orientation')} "
            f"unlocked={data.get('unlocked_observations', [])} contributors={contributors}"
        )

    async def render_outcome(
        self,
        ref: SessionRef,
        participant_id: str,
        outcome: EngineOutcome,
        *,
        action: CandidateAction | None = None,
    ) -> PublicResult:
        state_snapshot = copy.deepcopy(outcome.state_after)

        async def current_state() -> dict[str, Any]:
            nonlocal state_snapshot
            if state_snapshot is None:
                state_snapshot = await self.repository.state(ref)
            return copy.deepcopy(state_snapshot)

        if not outcome.accepted:
            logger.info(
                "gameplay command rejected",
                extra={
                    "environment": ref.environment.value,
                    "participant_id": participant_id,
                    "reason_key": outcome.reason_key,
                    "confusion_reason": self._confusion_reason(outcome),
                    "action": action.action if action is not None else None,
                },
            )

        async def with_footer(result: PublicResult) -> PublicResult:
            current = await current_state()
            body = result.text
            observation_id = str((outcome.public_data or {}).get("observation_id", ""))
            if (
                result.accepted
                and action is not None
                and action.action in {"observe", "inspect"}
                and observation_id
            ):
                definition = self.registries[ref.environment].get(int(current["current_position"]))
                observation = next(
                    (item for item in definition.observations if item.id == observation_id),
                    None,
                )
                if observation is not None:
                    entity = next(
                        item for item in definition.entities if item.id == observation.entity_id
                    )
                    body = f"Identified target: **{entity.title}**.\n\n{body}"
            footer = self._navigation_footer(
                ref.environment,
                current["data"],
                int(current["current_position"]),
                participant_id,
                outcome,
                action,
            )
            return PublicResult(
                result.accepted,
                f"{body}\n\n{footer}",
                result.event_id,
            )

        if outcome.duplicate:
            state = await current_state()
            text = self.narrators[ref.environment].render(
                profile=state["response_profile"],
                narration_key="duplicate_event",
                event_id=outcome.event_id or "duplicate",
            )
            return await with_footer(PublicResult(True, text, outcome.event_id))
        public_data = outcome.public_data or {}
        if not outcome.accepted:
            feedback = public_data.get("feedback")
            if feedback:
                state = await current_state()
                text = str(feedback)
                reactions = state.get("data", {}).get("triggered_reactions", [])
                aliases = semantic_trigger_aliases(
                    reactions, self._observation_entities(ref.environment)
                )
                for stored_id, public_id in aliases.items():
                    text = text.replace(f"trigger_id:{stored_id}", f"trigger_id:{public_id}")
                return await with_footer(PublicResult(False, text))
        if (
            outcome.accepted
            and isinstance(action, SummarizeAction)
            and public_data.get("public_text")
        ):
            return await with_footer(
                PublicResult(True, str(public_data["public_text"]), outcome.event_id)
            )
        state = await current_state()
        if outcome.accepted and self.narration_service is not None and outcome.event_id:
            facts = tuple(
                str(item["public_text"])
                for item in state["data"].get("confirmed_facts", [])
                if item.get("public_text")
            )
            profile = str(state["response_profile"])
            narration_key = outcome.narration_key or outcome.reason_key
            try:
                text = await self.narration_service.render(
                    ref,
                    participant_id=participant_id,
                    profile=profile,
                    event_id=outcome.event_id,
                    event_type=outcome.event_type or outcome.reason_key,
                    narration_key=narration_key,
                    public_data=public_data,
                    permitted_public_facts=facts,
                    position_completed=outcome.position_completed,
                )
            except Exception:
                logger.exception(
                    "narration transformation failed after confirmed event",
                    extra={"environment": ref.environment.value, "purpose": "narration"},
                )
                canonical = public_data.get("public_text")
                text = (
                    self.narrators[ref.environment].render_confirmed_outcome(
                        profile=profile,
                        event_id=outcome.event_id,
                        outcome=str(canonical),
                    )
                    if canonical
                    else self.narrators[ref.environment].render(
                        profile=profile,
                        narration_key=narration_key,
                        event_id=outcome.event_id,
                        public_data=public_data,
                    )
                )
            return await with_footer(PublicResult(True, text, outcome.event_id))
        public_text = public_data.get("public_text")
        if public_text:
            return await with_footer(
                PublicResult(outcome.accepted, str(public_text), outcome.event_id)
            )
        text = self.narrators[ref.environment].render(
            profile=state["response_profile"],
            narration_key=outcome.narration_key or outcome.reason_key,
            event_id=outcome.event_id or outcome.reason_key,
            public_data=public_data,
        )
        return await with_footer(PublicResult(outcome.accepted, text, outcome.event_id))
