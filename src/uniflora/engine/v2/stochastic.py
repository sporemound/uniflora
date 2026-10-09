from __future__ import annotations

import hashlib
import hmac
import secrets
from collections.abc import Sequence
from dataclasses import replace
from typing import Protocol, TypeVar

from uniflora.content.v2.investigation_schema import (
    V2InvestigationActionDefinition,
    V2StochasticLikelihoodDefinition,
    V2StochasticOutcomeDefinition,
    V2StochasticProcessDefinition,
    V2StochasticStateDefinition,
    V2StrategicTagModifierDefinition,
)
from uniflora.engine.v2.serialization import canonical_json_bytes
from uniflora.engine.v2.state import (
    V2InvestigationState,
    V2ModelProbabilityState,
    V2StochasticDatumState,
    V2StochasticDrawState,
    V2StochasticModelSupportState,
    V2StochasticObservationState,
    V2StochasticProcessState,
    V2StochasticResolutionState,
    V2StrategicDriftResolutionState,
)

_T = TypeVar("_T")


class V2RandomSource(Protocol):
    """Narrow source used only while constructing a new authoritative event."""

    def randbelow(self, upper_bound: int, *, context: str) -> int: ...


class V2SecretsRandomSource:
    """Production entropy. Outcomes become deterministic once persisted in an event."""

    def randbelow(self, upper_bound: int, *, context: str) -> int:
        del context
        if upper_bound <= 0:
            raise ValueError("random upper bound must be positive")
        return secrets.randbelow(upper_bound)


class V2SeededRandomSource:
    """Reproducible HMAC stream for tests, simulations, and disclosed replays."""

    def __init__(self, seed: bytes | str) -> None:
        material = seed.encode() if isinstance(seed, str) else bytes(seed)
        if not material:
            raise ValueError("stochastic seed must not be empty")
        self._seed = material
        self._counter = 0

    def randbelow(self, upper_bound: int, *, context: str) -> int:
        if upper_bound <= 0:
            raise ValueError("random upper bound must be positive")
        while True:
            message = f"{context}|{self._counter}".encode()
            self._counter += 1
            candidate = int.from_bytes(
                hmac.new(self._seed, message, hashlib.sha256).digest(), "big"
            )
            # Rejection sampling avoids modulo bias without floating-point math.
            limit = (1 << 256) - ((1 << 256) % upper_bound)
            if candidate < limit:
                return candidate % upper_bound


class V2ContextHashRandomSource(V2SeededRandomSource):
    """Stable fallback for pure-kernel calls that do not inject entropy."""

    def __init__(self, context: str) -> None:
        super().__init__(hashlib.sha256(context.encode()).digest())


def _weighted_choice(
    items: Sequence[_T],
    weights: Sequence[int],
    *,
    purpose: str,
    random_source: V2RandomSource,
    context: str,
) -> tuple[_T, V2StochasticDrawState]:
    if not items or len(items) != len(weights):
        raise ValueError("weighted choice requires equally sized nonempty items and weights")
    if any(weight <= 0 for weight in weights):
        raise ValueError("weighted choice requires positive integer weights")
    total = sum(weights)
    raw = random_source.randbelow(total, context=f"{context}|{purpose}")
    cursor = 0
    for index, (item, weight) in enumerate(zip(items, weights, strict=True)):
        cursor += weight
        if raw < cursor:
            return item, V2StochasticDrawState(
                purpose=purpose,
                upper_bound=total,
                raw_value=raw,
                selected_index=index,
                selected_weight=weight,
            )
    raise AssertionError("weighted selection did not resolve")


def _normalize_to_total(
    weight_by_id: dict[str, int],
    *,
    total_points: int,
) -> dict[str, int]:
    if not weight_by_id or any(value < 0 for value in weight_by_id.values()):
        raise ValueError("model weights must be nonnegative and nonempty")
    total = sum(weight_by_id.values())
    if total <= 0:
        weight_by_id = {key: 1 for key in weight_by_id}
        total = len(weight_by_id)
    floors: dict[str, int] = {}
    remainders: list[tuple[int, str]] = []
    allocated = 0
    for model_id, weight in sorted(weight_by_id.items()):
        numerator = weight * total_points
        quotient, remainder = divmod(numerator, total)
        floors[model_id] = quotient
        remainders.append((remainder, model_id))
        allocated += quotient
    for _, model_id in sorted(remainders, key=lambda item: (-item[0], item[1]))[
        : total_points - allocated
    ]:
        floors[model_id] += 1
    return floors


def _normalize_basis_points(
    weight_by_id: dict[str, int],
    *,
    minimum_basis_points: int = 0,
) -> tuple[V2ModelProbabilityState, ...]:
    if minimum_basis_points < 0:
        raise ValueError("minimum model support must be nonnegative")
    model_count = len(weight_by_id)
    reserved = minimum_basis_points * model_count
    if reserved >= 10_000:
        raise ValueError("minimum model support leaves no allocatable probability")
    distributed = _normalize_to_total(
        weight_by_id,
        total_points=10_000 - reserved,
    )
    return tuple(
        V2ModelProbabilityState(
            model_id=model_id,
            basis_points=minimum_basis_points + distributed[model_id],
        )
        for model_id in sorted(distributed)
    )


def _initial_support(process: V2StochasticProcessDefinition) -> V2StochasticModelSupportState:
    models = _normalize_basis_points(
        {item.model_id: item.weight for item in process.initial_model_weights},
        minimum_basis_points=process.minimum_model_support_basis_points,
    )
    return V2StochasticModelSupportState(process_id=process.id, models=models)


def _updated_support(
    process: V2StochasticProcessDefinition,
    prior: V2StochasticModelSupportState,
    likelihoods: tuple[V2StochasticLikelihoodDefinition, ...],
) -> V2StochasticModelSupportState:
    if not likelihoods:
        return prior
    likelihood_by_model = {item.model_id: item.weight for item in likelihoods}
    posterior = _normalize_basis_points(
        {
            item.model_id: item.basis_points * likelihood_by_model.get(item.model_id, 0)
            for item in prior.models
        },
        minimum_basis_points=0,
    )
    posterior_by_id = {item.model_id: item.basis_points for item in posterior}
    learning_rate = process.posterior_learning_rate_basis_points
    retained_rate = 10_000 - learning_rate
    mixed_weights = {
        item.model_id: (
            item.basis_points * retained_rate
            + posterior_by_id[item.model_id] * learning_rate
        )
        for item in prior.models
    }
    return V2StochasticModelSupportState(
        process_id=prior.process_id,
        models=_normalize_basis_points(
            mixed_weights,
            minimum_basis_points=process.minimum_model_support_basis_points,
        ),
    )

def _state_by_id(
    process: V2StochasticProcessDefinition, state_id: str
) -> V2StochasticStateDefinition:
    state = next((item for item in process.states if item.id == state_id), None)
    if state is None:
        raise ValueError(f"unknown stochastic state {state_id!r} for process {process.id!r}")
    return state



def _inferred_tags(identifier: str, declared: tuple[str, ...]) -> frozenset[str]:
    tags = set(declared)
    normalized = identifier.casefold()
    rules = {
        "ordinary": ("ordinary",),
        "mixed": ("mixed",),
        "coherent": ("coherent", "high_information"),
        "convergent": ("coherent", "high_information"),
        "stable": ("coherent", "high_information"),
        "discontinuous": ("discontinuous", "low_information"),
        "underconstrained": ("discontinuous", "low_information"),
        "fragmentary": ("discontinuous", "low_information"),
        "quiet": ("quiet",),
        "background": ("quiet",),
        "intermittent": ("intermittent",),
        "split": ("split", "unstable"),
        "divergent": ("split", "unstable"),
        "burst": ("unstable",),
        "contaminated": ("unstable",),
        "decoher": ("unstable",),
    }
    for needle, values in rules.items():
        if needle in normalized:
            tags.update(values)
    return frozenset(tags)


def _modifier_active(
    modifier: V2StrategicTagModifierDefinition,
    state: V2InvestigationState,
) -> bool:
    board = state.strategic_board
    conditions = (
        {item.condition_id for item in board.conditions}
        if board is not None
        else set()
    )
    if modifier.when_condition is not None and modifier.when_condition not in conditions:
        return False
    if modifier.unless_condition is not None and modifier.unless_condition in conditions:
        return False
    return True


def _modified_weights(
    identifiers: Sequence[str],
    declared_tags: Sequence[tuple[str, ...]],
    base_weights: Sequence[int],
    modifiers: tuple[V2StrategicTagModifierDefinition, ...],
    state: V2InvestigationState,
) -> tuple[int, ...]:
    result: list[int] = []
    for identifier, declared, base in zip(
        identifiers, declared_tags, base_weights, strict=True
    ):
        numerator = base
        denominator = 1
        tags = _inferred_tags(identifier, declared)
        for modifier in modifiers:
            if not _modifier_active(modifier, state):
                continue
            if tags.intersection(modifier.target_tags):
                numerator *= modifier.multiplier_basis_points
                denominator *= 10_000
        # Preserve a positive integer table even for strong down-weighting.
        result.append(max(1, (numerator + denominator // 2) // denominator))
    return tuple(result)


def _outcome_for_channel(
    stochastic_state: V2StochasticStateDefinition,
    channel_id: str,
    *,
    process_id: str,
    action_id: str,
    random_source: V2RandomSource,
    context: str,
    investigation_state: V2InvestigationState,
    modifiers: tuple[V2StrategicTagModifierDefinition, ...] = (),
) -> tuple[V2StochasticOutcomeDefinition, V2StochasticDrawState, tuple[int, ...]]:
    emission = next(
        (item for item in stochastic_state.emissions if item.channel_id == channel_id),
        None,
    )
    if emission is None:
        raise ValueError(
            f"state {stochastic_state.id!r} does not expose channel {channel_id!r} "
            f"for process {process_id!r}"
        )
    weights = _modified_weights(
        tuple(item.id for item in emission.outcomes),
        tuple(item.tags for item in emission.outcomes),
        tuple(item.weight for item in emission.outcomes),
        modifiers,
        investigation_state,
    )
    outcome, draw = _weighted_choice(
        emission.outcomes,
        weights,
        purpose=f"emission:{process_id}:{channel_id}:{action_id}",
        random_source=random_source,
        context=context,
    )
    return outcome, draw, weights


def _replace_process(
    values: tuple[V2StochasticProcessState, ...],
    updated: V2StochasticProcessState,
) -> tuple[V2StochasticProcessState, ...]:
    replaced = False
    result: list[V2StochasticProcessState] = []
    for item in values:
        if item.process_id == updated.process_id:
            result.append(updated)
            replaced = True
        else:
            result.append(item)
    if not replaced:
        result.append(updated)
    return tuple(result)


def _replace_support(
    values: tuple[V2StochasticModelSupportState, ...],
    updated: V2StochasticModelSupportState,
) -> tuple[V2StochasticModelSupportState, ...]:
    replaced = False
    result: list[V2StochasticModelSupportState] = []
    for item in values:
        if item.process_id == updated.process_id:
            result.append(updated)
            replaced = True
        else:
            result.append(item)
    if not replaced:
        result.append(updated)
    return tuple(result)


def resolve_stochastic_action(
    state: V2InvestigationState,
    action: V2InvestigationActionDefinition,
    process: V2StochasticProcessDefinition,
    *,
    random_source: V2RandomSource | None = None,
) -> tuple[V2InvestigationState, V2StochasticResolutionState, frozenset[str]]:
    """Resolve one action, returning state data that can be committed as an event.

    The function may draw entropy. Reducers must never call it; they apply the
    complete resolution stored in ``V2ActionPerformedEvent`` instead.
    """

    if action.stochastic_channel_id is None or action.stochastic_process_id != process.id:
        raise ValueError("action does not carry a valid stochastic binding")
    source = random_source or V2ContextHashRandomSource(
        f"{state.pack_id}|{state.current_position_id}|{state.revision + 1}|{action.id}"
    )
    previous = state.get_stochastic_process(process.id) or V2StochasticProcessState(
        process_id=process.id,
        state_id=process.initial_state_id,
    )
    prior_support = state.get_stochastic_support(process.id) or _initial_support(process)
    previous_definition = _state_by_id(process, previous.state_id)
    transition_draw: V2StochasticDrawState | None = None
    next_definition = previous_definition
    profile = action.strategic
    if state.strategic_board is not None or state.campaign_tracks:
        advanced = bool(
            profile is not None
            and profile.stochastic_mode == "intervention_then_emit"
        )
    else:
        advanced = bool(action.advance_stochastic_state)
    context = f"{state.pack_id}|{state.revision + 1}|{process.id}|{action.id}"
    transition_weights = tuple(item.weight for item in previous_definition.transitions)
    if advanced:
        transition_modifiers = profile.transition_modifiers if profile is not None else ()
        transition_weights = _modified_weights(
            tuple(item.state_id for item in previous_definition.transitions),
            tuple(
                _state_by_id(process, item.state_id).tags
                for item in previous_definition.transitions
            ),
            tuple(item.weight for item in previous_definition.transitions),
            transition_modifiers,
            state,
        )
        transition, transition_draw = _weighted_choice(
            previous_definition.transitions,
            transition_weights,
            purpose=f"transition:{process.id}:{action.id}",
            random_source=source,
            context=context,
        )
        next_definition = _state_by_id(process, transition.state_id)
    emission_modifiers = profile.emission_modifiers if profile is not None else ()
    outcome, outcome_draw, outcome_weights = _outcome_for_channel(
        next_definition,
        action.stochastic_channel_id,
        process_id=process.id,
        action_id=action.id,
        random_source=source,
        context=context,
        investigation_state=state,
        modifiers=emission_modifiers,
    )
    support_after = _updated_support(process, prior_support, outcome.likelihoods)
    measurements = tuple(
        V2StochasticDatumState(
            key=item.key,
            value=item.value,
            unit=item.unit,
            uncertainty=item.uncertainty,
        )
        for item in outcome.measurements
    )
    sequence = state.revision + 1
    public_state_label = next_definition.public_label if process.reveal_latent_state else None
    observation = V2StochasticObservationState(
        process_id=process.id,
        action_id=action.id,
        channel_id=action.stochastic_channel_id,
        outcome_id=outcome.id,
        public_summary=outcome.public_summary,
        measurements=measurements,
        sequence=sequence,
        observed_state_label=public_state_label,
    )
    process_after = V2StochasticProcessState(
        process_id=process.id,
        state_id=next_definition.id,
        observation_count=previous.observation_count + 1,
        dwell_count=(
            previous.dwell_count + 1
            if next_definition.id == previous.state_id
            else 1
        ),
        last_sequence=sequence,
    )
    weight_manifest = {
        "algorithm": process.algorithm,
        "algorithmVersion": process.algorithm_version,
        "previousState": previous_definition.id,
        "nextState": next_definition.id,
        "transitions": [
            {"state": item.state_id, "weight": weight}
            for item, weight in zip(
                previous_definition.transitions, transition_weights, strict=True
            )
        ],
        "channel": action.stochastic_channel_id,
        "outcomes": [
            {"id": item.id, "weight": weight}
            for emission in next_definition.emissions
            if emission.channel_id == action.stochastic_channel_id
            for item, weight in zip(emission.outcomes, outcome_weights, strict=True)
        ],
    }
    resolution = V2StochasticResolutionState(
        process_id=process.id,
        action_id=action.id,
        channel_id=action.stochastic_channel_id,
        algorithm=process.algorithm,
        algorithm_version=process.algorithm_version,
        previous_state_id=previous_definition.id,
        next_state_id=next_definition.id,
        state_advanced=advanced,
        observed_state_label=public_state_label,
        transition_draw=transition_draw,
        outcome_draw=outcome_draw,
        outcome_id=outcome.id,
        public_summary=outcome.public_summary,
        measurements=measurements,
        model_support_after=support_after,
        weight_table_hash=hashlib.sha256(canonical_json_bytes(weight_manifest)).hexdigest(),
    )
    updated = replace(
        state,
        stochastic_processes=_replace_process(state.stochastic_processes, process_after),
        stochastic_observations=state.stochastic_observations + (observation,),
        stochastic_model_support=_replace_support(state.stochastic_model_support, support_after),
        revision=sequence,
        serialization_schema=max(state.serialization_schema, 3),
    )
    return updated, resolution, frozenset(outcome.unlock_evidence_ids)



def resolve_natural_drift(
    state: V2InvestigationState,
    process: V2StochasticProcessDefinition,
    *,
    random_source: V2RandomSource | None = None,
    context: str,
) -> tuple[V2InvestigationState, V2StrategicDriftResolutionState]:
    """Advance one hidden process without emitting a public observation."""

    source = random_source or V2ContextHashRandomSource(context)
    previous = state.get_stochastic_process(process.id) or V2StochasticProcessState(
        process_id=process.id,
        state_id=process.initial_state_id,
    )
    previous_definition = _state_by_id(process, previous.state_id)
    transition, draw = _weighted_choice(
        previous_definition.transitions,
        tuple(item.weight for item in previous_definition.transitions),
        purpose=f"natural-drift:{process.id}",
        random_source=source,
        context=context,
    )
    next_definition = _state_by_id(process, transition.state_id)
    process_after = V2StochasticProcessState(
        process_id=process.id,
        state_id=next_definition.id,
        observation_count=previous.observation_count,
        dwell_count=(
            previous.dwell_count + 1
            if next_definition.id == previous.state_id
            else 1
        ),
        last_sequence=state.revision,
    )
    manifest = {
        "algorithm": process.algorithm,
        "algorithmVersion": process.algorithm_version,
        "previousState": previous_definition.id,
        "transitions": [
            {"state": item.state_id, "weight": item.weight}
            for item in previous_definition.transitions
        ],
    }
    resolution = V2StrategicDriftResolutionState(
        process_id=process.id,
        previous_state_id=previous_definition.id,
        next_state_id=next_definition.id,
        transition_draw=draw,
        weight_table_hash=hashlib.sha256(canonical_json_bytes(manifest)).hexdigest(),
    )
    return (
        replace(
            state,
            stochastic_processes=_replace_process(
                state.stochastic_processes, process_after
            ),
            serialization_schema=max(state.serialization_schema, 4),
        ),
        resolution,
    )


def apply_natural_drift(
    state: V2InvestigationState,
    resolution: V2StrategicDriftResolutionState,
    *,
    sequence: int,
) -> V2InvestigationState:
    previous = state.get_stochastic_process(resolution.process_id)
    process_after = V2StochasticProcessState(
        process_id=resolution.process_id,
        state_id=resolution.next_state_id,
        observation_count=previous.observation_count if previous else 0,
        dwell_count=(
            previous.dwell_count + 1
            if previous is not None and previous.state_id == resolution.next_state_id
            else 1
        ),
        last_sequence=sequence,
    )
    return replace(
        state,
        stochastic_processes=_replace_process(state.stochastic_processes, process_after),
        revision=sequence,
        serialization_schema=max(state.serialization_schema, 4),
    )


def apply_stochastic_resolution(
    state: V2InvestigationState,
    resolution: V2StochasticResolutionState,
    *,
    sequence: int,
) -> V2InvestigationState:
    """Apply an already-recorded result during replay without drawing entropy."""

    previous = state.get_stochastic_process(resolution.process_id)
    observation_count = (previous.observation_count if previous else 0) + 1
    dwell_count = (
        (previous.dwell_count + 1)
        if previous is not None and previous.state_id == resolution.next_state_id
        else 1
    )
    process_after = V2StochasticProcessState(
        process_id=resolution.process_id,
        state_id=resolution.next_state_id,
        observation_count=observation_count,
        dwell_count=dwell_count,
        last_sequence=sequence,
    )
    observation = V2StochasticObservationState(
        process_id=resolution.process_id,
        action_id=resolution.action_id,
        channel_id=resolution.channel_id,
        outcome_id=resolution.outcome_id,
        public_summary=resolution.public_summary,
        measurements=resolution.measurements,
        sequence=sequence,
        observed_state_label=resolution.observed_state_label,
    )
    return replace(
        state,
        stochastic_processes=_replace_process(state.stochastic_processes, process_after),
        stochastic_observations=state.stochastic_observations + (observation,),
        stochastic_model_support=_replace_support(
            state.stochastic_model_support, resolution.model_support_after
        ),
        revision=sequence,
        serialization_schema=max(state.serialization_schema, 3),
    )


__all__ = [
    "V2ContextHashRandomSource",
    "V2RandomSource",
    "V2SecretsRandomSource",
    "V2SeededRandomSource",
    "apply_natural_drift",
    "apply_stochastic_resolution",
    "resolve_natural_drift",
    "resolve_stochastic_action",
]
