from __future__ import annotations

import copy
import math
from dataclasses import replace
from enum import StrEnum
from typing import Any

from uniflora.engine.actions import CandidateAction
from uniflora.engine.validation import ValidationContext, ValidationDecision
from uniflora.runtime import Environment


class CycleActionKind(StrEnum):
    FREE_INFORMATION = "free_information"
    PRIMARY_ORIENTATION = "primary_orientation"
    PRIMARY_COORDINATION = "primary_coordination"
    FREE_VERIFICATION = "free_verification"
    PRIMARY_PROPOSAL = "primary_proposal"
    PROPOSAL_ASSEMBLY = "proposal_assembly"
    RESPONSE = "response"
    CONTROL = "control"


PRIMARY_ORIENTATION_ACTIONS = {"observe", "inspect"}
PRIMARY_COORDINATION_ACTIONS = {
    "connect",
    "offer",
    "request_support",
    "sustain",
    "relay",
    "mitigate",
    "clarify_record",
    "classify_contradiction",
    "relay_record",
    "annotate_difference",
    "sample",
    "separate",
    "inoculate",
    "slow",
    "contain",
    "rest",
    "replace",
    "refuse",
    "reduce",
    "redesign",
    "document",
}
FREE_VERIFICATION_ACTIONS = {"calculate_flow", "audit", "compare_records"}
PROPOSAL_ACTIONS = {
    "propose_circulation",
    "propose_translation",
    "propose_reciprocity",
    "propose_remediation_protocol",
    "propose_memory_archive",
    "propose_production_reform",
    "propose_reconstruction",
    "begin_stack",
}
RESPONSE_ACTIONS = {
    "branch_proposal",
    "react_to_stack",
    "add_proposal_kicker",
    "use_triggered_reaction",
    "confirm_reconstruction",
}
CONTROL_ACTIONS = {"resolve_stack"}
TEMPORARY_STATE_KEYS = {
    "connections",
    "offers",
    "support_requests",
    "sustains",
    "relays",
    "mitigations",
    "branches",
    "calculations",
    "sustained_targets",
    "reassessed_pathways",
}
PREPARATION_ACTIVITIES = {"orientation", "coordination", "calculation"}
DEFAULT_PRIMARY_MINIMUM = 3
POSITION_PRIMARY_MINIMUMS = {6: 4}


def initial_cycle(position: int, index: int = 1) -> dict[str, Any]:
    return {
        "position": position,
        "index": index,
        "primary_minimum": POSITION_PRIMARY_MINIMUMS.get(
            position, DEFAULT_PRIMARY_MINIMUM
        ),
        "phase": "orientation",
        "observation_count": 0,
        "orientation_participants": [],
        "primary_contributors": {},
        "response_actions": {},
        "response_window_id": None,
        "proposal_author_id": None,
    }


def ensure_cycle_state(state: dict[str, Any], position: int) -> dict[str, Any]:
    """Return a cycle-aware copy, upgrading an in-progress pre-cycle state safely."""

    updated = copy.deepcopy(state)
    cycle = copy.deepcopy(updated.get("cycle") or initial_cycle(position))
    defaults = initial_cycle(position, max(1, int(cycle.get("index", 1))))
    cycle = {**defaults, **cycle, "position": position}

    contributions = list(updated.get("contributions", []))
    has_scoped_contributions = any("cycle_index" in item for item in contributions)
    if not has_scoped_contributions:
        scoped: list[dict[str, Any]] = []
        for item in contributions:
            entry = dict(item)
            entry["cycle_index"] = int(cycle["index"])
            entry["action_kind"] = _kind_for_name(str(entry.get("action", ""))).value
            scoped.append(entry)
        contributions = scoped
        updated["contributions"] = contributions

    if not cycle.get("primary_contributors"):
        primary: dict[str, dict[str, str]] = {}
        for item in current_cycle_contributions({**updated, "cycle": cycle}):
            kind = str(item.get("action_kind", ""))
            if kind not in {
                CycleActionKind.PRIMARY_ORIENTATION.value,
                CycleActionKind.PRIMARY_COORDINATION.value,
                CycleActionKind.PRIMARY_PROPOSAL.value,
            }:
                continue
            participant_id = str(item.get("participant_id", ""))
            if participant_id:
                primary.setdefault(
                    participant_id,
                    {
                        "action": str(item.get("action", "unknown")),
                        "function": str(item.get("function", "contributor")),
                    },
                )
        cycle["primary_contributors"] = primary

    if int(cycle.get("observation_count", 0)) == 0 and updated.get("unlocked_observations"):
        cycle["observation_count"] = 1

    window_id, author_id = _open_response_window(updated)
    if window_id is not None:
        cycle["phase"] = "response"
        cycle["response_window_id"] = window_id
        cycle["proposal_author_id"] = author_id

    updated["cycle"] = cycle
    updated.setdefault("cycle_history", [])
    return updated


def current_cycle_contributions(state: dict[str, Any]) -> list[dict[str, Any]]:
    cycle_index = int((state.get("cycle") or {}).get("index", 1))
    contributions = list(state.get("contributions", []))
    scoped = [
        item
        for item in contributions
        if int(item.get("cycle_index", -1)) == cycle_index
    ]
    if scoped or any("cycle_index" in item for item in contributions):
        return scoped
    return contributions


def prepare_cycle_action(
    action: CandidateAction, context: ValidationContext
) -> tuple[ValidationContext, CycleActionKind, ValidationDecision | None]:
    state = ensure_cycle_state(context.state, context.current_position)
    context = replace(context, state=state)
    cycle = state["cycle"]
    kind = _classify_for_participant(action, cycle, context.participant_id)
    primary = cycle.get("primary_contributors", {})
    open_window_id, _ = _open_response_window(state)

    if open_window_id is not None and kind not in {
        CycleActionKind.RESPONSE,
        CycleActionKind.CONTROL,
    }:
        return context, kind, _reject_cycle(
            "A public response window is open. Ordinary contributions resume after resolution."
        )

    if kind in {
        CycleActionKind.PRIMARY_COORDINATION,
        CycleActionKind.FREE_VERIFICATION,
        CycleActionKind.PRIMARY_PROPOSAL,
        CycleActionKind.PROPOSAL_ASSEMBLY,
    } and int(cycle.get("observation_count", 0)) < 1:
        return context, kind, _reject_cycle(
            "This cycle needs an accepted observational contribution before intervention."
        )

    if kind in {
        CycleActionKind.PRIMARY_PROPOSAL,
        CycleActionKind.PROPOSAL_ASSEMBLY,
    }:
        prospective = {*primary, context.participant_id}
        required = int(cycle.get("primary_minimum", DEFAULT_PRIMARY_MINIMUM))
        if len(prospective) < required:
            return context, kind, _reject_cycle(
                f"A proposal requires at least {required} distinct primary contributors "
                "in this cycle."
            )

    if kind in {
        CycleActionKind.PRIMARY_ORIENTATION,
        CycleActionKind.PRIMARY_COORDINATION,
        CycleActionKind.PRIMARY_PROPOSAL,
    } and context.environment is Environment.LIVE and context.participant_id in primary:
        used = str(primary[context.participant_id].get("action", "a primary contribution"))
        eligible_triggers = _eligible_trigger_ids(context.state, context.participant_id)
        reaction_guidance = (
            "Eligible trigger reactions:\n"
            + "\n".join(
                f"• `/interior act trigger trigger_id:{trigger_id}`"
                for trigger_id in eligible_triggers
            )
            if eligible_triggers
            else "No trigger reaction is currently eligible for you."
        )
        return context, kind, _reject_cycle(
            f"Your primary contribution for Cycle {cycle['index']} is already spent on `{used}`. "
            f"You may still use information commands.\n{reaction_guidance}"
        )

    if kind is CycleActionKind.RESPONSE and context.environment is Environment.LIVE:
        window_id = _response_window_for_action(action, cycle, open_window_id)
        response = cycle.get("response_actions", {}).get(context.participant_id)
        if response and str(response.get("window_id")) == window_id:
            return context, kind, _reject_cycle(
                "Each participant may add only one reaction to the current public response window."
            )

    return context, kind, None


def apply_cycle_decision(
    action: CandidateAction,
    context: ValidationContext,
    kind: CycleActionKind,
    decision: ValidationDecision,
) -> ValidationDecision:
    if not decision.accepted or decision.next_state is None:
        if kind in {
            CycleActionKind.PRIMARY_PROPOSAL,
            CycleActionKind.PROPOSAL_ASSEMBLY,
        } and decision.reason_key == "proposal_rejected":
            return _failed_proposal_cycle(action, context, kind, decision)
        return decision

    previous_phase = str(context.state["cycle"].get("phase", "orientation"))
    state = ensure_cycle_state(decision.next_state, context.current_position)
    if decision.reason_key == "observation_corroborated":
        # Re-reading a confirmed condition may refresh its live wording, but it does not
        # create a new contribution or spend the participant's primary action.
        return replace(decision, next_state=state, contribution_function=None)
    cycle = copy.deepcopy(state["cycle"])
    function = decision.contribution_function or _default_function(action.action)
    before_count = len(context.state.get("contributions", []))
    contributions = list(state.get("contributions", []))
    new_entries = contributions[before_count:]
    for entry in new_entries:
        entry["cycle_index"] = int(cycle["index"])
        entry["action_kind"] = kind.value
    if not any(
        str(item.get("participant_id")) == context.participant_id
        and str(item.get("action")) == action.action
        for item in new_entries
    ) and kind is not CycleActionKind.FREE_INFORMATION:
        contributions.append(
            {
                "participant_id": context.participant_id,
                "function": function,
                "action": action.action,
                "cycle_index": int(cycle["index"]),
                "action_kind": kind.value,
            }
        )
    state["contributions"] = contributions

    if kind is CycleActionKind.FREE_INFORMATION and action.action == "orient_local":
        oriented = list(cycle.get("orientation_participants", []))
        if context.participant_id not in oriented:
            oriented.append(context.participant_id)
        cycle["orientation_participants"] = oriented

    if kind in {
        CycleActionKind.PRIMARY_ORIENTATION,
        CycleActionKind.PRIMARY_COORDINATION,
        CycleActionKind.PRIMARY_PROPOSAL,
    }:
        primary = dict(cycle.get("primary_contributors", {}))
        primary[context.participant_id] = {"action": action.action, "function": function}
        cycle["primary_contributors"] = primary

    if kind is CycleActionKind.PRIMARY_ORIENTATION:
        cycle["observation_count"] = int(cycle.get("observation_count", 0)) + 1
        cycle["phase"] = "orientation"
    elif kind is CycleActionKind.PRIMARY_COORDINATION:
        cycle["phase"] = "coordination"
    elif kind is CycleActionKind.FREE_VERIFICATION:
        cycle["phase"] = "calculation"
    elif kind in {
        CycleActionKind.PRIMARY_PROPOSAL,
        CycleActionKind.PROPOSAL_ASSEMBLY,
    }:
        cycle["phase"] = "response"
        window_id, author_id = _open_response_window(state)
        cycle["response_window_id"] = window_id
        cycle["proposal_author_id"] = author_id or context.participant_id
    elif kind is CycleActionKind.RESPONSE:
        if cycle.get("response_window_id"):
            cycle["phase"] = "response"
        window_id = _response_window_for_action(
            action, cycle, cycle.get("response_window_id")
        )
        responses = dict(cycle.get("response_actions", {}))
        responses[context.participant_id] = {"action": action.action, "window_id": window_id}
        cycle["response_actions"] = responses

    state["cycle"] = cycle
    contribution_function = decision.contribution_function
    if contribution_function is None and kind is not CycleActionKind.FREE_INFORMATION:
        contribution_function = function

    if decision.position_completed:
        state = _finish_cycle(state, "position_completed", context.current_position)
    elif action.action == "resolve_stack":
        stack = state.get("public_stack") or {}
        if stack.get("status") == "failed":
            state = advance_cycle(
                state,
                context.current_position,
                "proposal_failed",
                str(decision.public_data.get("public_text", "Stack resolution failed.")),
            )
            decision = _with_cycle_transition_text(decision, state)
        else:
            state["cycle"]["phase"] = "response"
            window_id, author_id = _open_response_window(state)
            if window_id is not None:
                state["cycle"]["response_window_id"] = window_id
                state["cycle"]["proposal_author_id"] = author_id

    current_phase = str(state["cycle"].get("phase", previous_phase))
    cycle_advanced = int(state["cycle"].get("index", 1)) != int(
        context.state["cycle"].get("index", 1)
    )
    if current_phase != previous_phase and not decision.position_completed and not cycle_advanced:
        decision = _with_phase_text(decision, state["cycle"])
    if not decision.position_completed and kind in {
        CycleActionKind.PRIMARY_ORIENTATION,
        CycleActionKind.PRIMARY_COORDINATION,
        CycleActionKind.PRIMARY_PROPOSAL,
        CycleActionKind.PROPOSAL_ASSEMBLY,
        CycleActionKind.RESPONSE,
    }:
        decision = (
            _with_test_availability_text(decision)
            if context.environment is Environment.TEST
            else _with_availability_text(decision, state, context.participant_id, kind)
        )

    invariant_failure = _state_invariant_failure(state)
    if invariant_failure is not None:
        return ValidationDecision(
            False,
            "state_invariant_failed",
            public_data={"feedback": invariant_failure},
            narration_key="invalid_action",
        )

    return replace(
        decision,
        next_state=state,
        contribution_function=contribution_function,
    )


def advance_cycle(
    state: dict[str, Any], position: int, outcome: str, summary: str
) -> dict[str, Any]:
    updated = _finish_cycle(state, outcome, position, summary)
    previous_index = int(updated["cycle"]["index"])
    for key in TEMPORARY_STATE_KEYS:
        if key in updated:
            updated[key] = []
    updated["public_stack"] = None
    updated["cycle"] = initial_cycle(position, previous_index + 1)
    return updated


def initialize_next_position_cycle(
    initialized: dict[str, Any], completed: dict[str, Any], position: int
) -> dict[str, Any]:
    state = copy.deepcopy(initialized)
    state["cycle_history"] = copy.deepcopy(completed.get("cycle_history", []))
    state["cycle"] = initial_cycle(position)
    return state


def cycle_status_text(state: dict[str, Any], position: int) -> str:
    cycle = ensure_cycle_state(state, position)["cycle"]
    phase, activity = public_cycle_phase(cycle)
    primary_count = len(cycle.get("primary_contributors", {}))
    primary_minimum = int(cycle.get("primary_minimum", DEFAULT_PRIMARY_MINIMUM))
    observations = int(cycle.get("observation_count", 0))
    activity_text = f"\nLatest activity: {activity}" if activity is not None else ""
    text = f"Cycle {cycle['index']} — {phase}{activity_text}\n"
    text += (
        f"Primary contributors: {primary_count}/{primary_minimum} minimum · "
        f"observational contributions: {observations}"
    )
    if cycle.get("response_window_id"):
        text += f"\nPublic response window: `{cycle['response_window_id']}`"
    return text


def public_cycle_phase(cycle: dict[str, Any]) -> tuple[str, str | None]:
    """Return the public gate and, during preparation, the latest activity family."""

    raw = str(cycle.get("phase", "orientation"))
    label = raw.replace("_", " ").title()
    if raw in PREPARATION_ACTIVITIES:
        return "Preparation", label
    return label, None


def cycle_rules_help() -> str:
    return (
        "Cycle rules: one accepted primary command per participant; the Position's distinct-"
        "contributor minimum must be met before proposal; once it is met, an existing contributor "
        "may assemble the proposal without spending another primary action; one reaction per "
        "participant per response window. "
        "Position, recall, accessibility, first orient, summaries, and calculations are free. "
        "Before a proposal opens Response, observation, coordination, and calculation may "
        "interleave wherever the Position's evidence prerequisites permit. "
        "A failed proposal enters reassessment and opens the next cycle without erasing "
        "discoveries."
    )


def _classify_for_participant(
    action: CandidateAction, cycle: dict[str, Any], participant_id: str
) -> CycleActionKind:
    if action.action == "orient_local":
        oriented = set(str(item) for item in cycle.get("orientation_participants", []))
        return (
            CycleActionKind.PRIMARY_ORIENTATION
            if participant_id in oriented
            else CycleActionKind.FREE_INFORMATION
        )
    if action.action in PROPOSAL_ACTIONS:
        primary = cycle.get("primary_contributors", {})
        required = int(cycle.get("primary_minimum", DEFAULT_PRIMARY_MINIMUM))
        if participant_id in primary and len(primary) >= required:
            return CycleActionKind.PROPOSAL_ASSEMBLY
    return _kind_for_name(action.action)


def _kind_for_name(action_name: str) -> CycleActionKind:
    if action_name in PRIMARY_ORIENTATION_ACTIONS:
        return CycleActionKind.PRIMARY_ORIENTATION
    if action_name in PRIMARY_COORDINATION_ACTIONS:
        return CycleActionKind.PRIMARY_COORDINATION
    if action_name in FREE_VERIFICATION_ACTIONS:
        return CycleActionKind.FREE_VERIFICATION
    if action_name in PROPOSAL_ACTIONS:
        return CycleActionKind.PRIMARY_PROPOSAL
    if action_name in RESPONSE_ACTIONS:
        return CycleActionKind.RESPONSE
    if action_name in CONTROL_ACTIONS:
        return CycleActionKind.CONTROL
    return CycleActionKind.FREE_INFORMATION


def _eligible_trigger_ids(state: dict[str, Any], participant_id: str) -> list[str]:
    eligible: list[str] = []
    for trigger in state.get("triggered_reactions", []):
        trigger_id = str(trigger.get("trigger_id", ""))
        if not trigger_id or trigger.get("consumed", False):
            continue
        excluded = {str(trigger.get("source_participant_id", ""))}
        excluded.update(str(item) for item in trigger.get("excluded_participant_ids", []))
        if participant_id not in excluded:
            eligible.append(trigger_id)
    return eligible


def _open_response_window(state: dict[str, Any]) -> tuple[str | None, str | None]:
    stack = state.get("public_stack") or {}
    if stack.get("status") == "open":
        return str(stack.get("stack_id")), str(stack.get("author_participant_id", "")) or None
    pending = [
        item for item in state.get("proposals", {}).values() if item.get("status") == "pending"
    ]
    if pending:
        proposal = pending[-1]
        return str(proposal.get("proposal_id")), str(proposal.get("author_participant_id", ""))
    return None, None


def _response_window_for_action(
    action: CandidateAction, cycle: dict[str, Any], open_window_id: object
) -> str:
    if open_window_id:
        return str(open_window_id)
    if action.action == "use_triggered_reaction":
        return f"trigger:{getattr(action, 'trigger_id', 'unknown')}"
    return f"cycle:{cycle['index']}"


def _failed_proposal_cycle(
    action: CandidateAction,
    context: ValidationContext,
    kind: CycleActionKind,
    decision: ValidationDecision,
) -> ValidationDecision:
    state = ensure_cycle_state(context.state, context.current_position)
    cycle = state["cycle"]
    if kind is CycleActionKind.PRIMARY_PROPOSAL:
        primary = dict(cycle.get("primary_contributors", {}))
        primary[context.participant_id] = {
            "action": action.action,
            "function": "proposal_author",
        }
        cycle["primary_contributors"] = primary
    state["cycle"] = cycle
    state.setdefault("contributions", []).append(
        {
            "participant_id": context.participant_id,
            "function": "proposal_author",
            "action": action.action,
            "cycle_index": int(cycle["index"]),
            "action_kind": kind.value,
        }
    )
    counters = copy.deepcopy(state.get("counters", {}))
    counters["instability"] = int(counters.get("instability", 0)) + 1
    state["counters"] = counters
    feedback = str(decision.public_data.get("feedback", "The proposal did not resolve."))
    state = advance_cycle(state, context.current_position, "proposal_failed", feedback)
    next_cycle = state["cycle"]["index"]
    return ValidationDecision(
        True,
        "cycle_reassessed",
        public_data={
            "public_text": (
                f"Proposal attempt did not resolve: {feedback}\n"
                f"Reassessment records one instability. Cycle {next_cycle} begins; "
                "primary allowances refresh and Preparation is open."
            )
        },
        next_state=state,
        event_type="cycle.proposal_failed",
        narration_key=decision.narration_key or "proposal_rejected",
        contribution_function="proposal_author",
    )


def _finish_cycle(
    state: dict[str, Any], outcome: str, position: int, summary: str = ""
) -> dict[str, Any]:
    updated = copy.deepcopy(state)
    cycle = copy.deepcopy(updated.get("cycle") or initial_cycle(position))
    cycle["phase"] = "reassessment"
    history = list(updated.get("cycle_history", []))
    history.append(
        {
            "position": position,
            "cycle_index": int(cycle.get("index", 1)),
            "outcome": outcome,
            "primary_contributors": sorted(cycle.get("primary_contributors", {})),
            "response_participants": sorted(cycle.get("response_actions", {})),
            "observation_count": int(cycle.get("observation_count", 0)),
            "summary": summary,
        }
    )
    updated["cycle_history"] = history
    updated["cycle"] = cycle
    return updated


def _with_cycle_transition_text(
    decision: ValidationDecision, state: dict[str, Any]
) -> ValidationDecision:
    public_data = dict(decision.public_data)
    base = str(public_data.get("public_text", "Resolution recorded."))
    public_data["public_text"] = (
        f"{base}\nReassessment completes. Cycle {state['cycle']['index']} begins; "
        "primary allowances refresh and Preparation is open."
    )
    return replace(decision, public_data=public_data)


def _with_phase_text(
    decision: ValidationDecision, cycle: dict[str, Any]
) -> ValidationDecision:
    public_data = dict(decision.public_data)
    base = str(public_data.get("public_text", "Contribution accepted."))
    phase, activity = public_cycle_phase(cycle)
    activity_text = f" (latest activity: {activity})" if activity is not None else ""
    public_data["public_text"] = (
        f"{base}\nCycle {cycle['index']} — {phase}{activity_text}."
    )
    return replace(decision, public_data=public_data)


def _with_availability_text(
    decision: ValidationDecision,
    state: dict[str, Any],
    participant_id: str,
    kind: CycleActionKind,
) -> ValidationDecision:
    cycle = state["cycle"]
    public_data = dict(decision.public_data)
    base = str(public_data.get("public_text", "Contribution accepted."))
    eligible_triggers = _eligible_trigger_ids(state, participant_id)
    open_window_id, _ = _open_response_window(state)

    if kind is CycleActionKind.RESPONSE and open_window_id is not None:
        notice = (
            f"Your response for `{open_window_id}` is spent. No further reaction is available "
            "to you in this response window."
        )
    elif eligible_triggers:
        commands = "\n".join(
            f"• `/interior act trigger trigger_id:{trigger_id}`"
            for trigger_id in eligible_triggers
        )
        notice = f"Eligible trigger reactions still available to you:\n{commands}"
    elif open_window_id is not None:
        notice = (
            f"Your primary action is spent. Public response window `{open_window_id}` is open; "
            "use `/interior recall` to review its available response tools."
        )
    elif (
        participant_id in cycle.get("primary_contributors", {})
        and len(cycle.get("primary_contributors", {}))
        >= int(cycle.get("primary_minimum", DEFAULT_PRIMARY_MINIMUM))
    ):
        notice = (
            "Your primary contribution remains recorded. The contributor minimum is met, so "
            "you may still assemble the proposal when its public prerequisites are ready."
        )
    else:
        notice = (
            f"No primary or reaction moves are currently available to you in Cycle "
            f"{cycle['index']}. Free information and verification commands remain available."
        )

    public_data["public_text"] = f"{base}\n{notice}"
    return replace(decision, public_data=public_data)


def _with_test_availability_text(decision: ValidationDecision) -> ValidationDecision:
    public_data = dict(decision.public_data)
    base = str(public_data.get("public_text", "Contribution accepted."))
    public_data["public_text"] = (
        f"{base}\n[TEST SURFACE] Your command allowance remains open; "
        "distinct-participant and evidence requirements still apply."
    )
    return replace(decision, public_data=public_data)


def _default_function(action_name: str) -> str:
    return {
        "observe": "observer",
        "inspect": "observer",
        "orient_local": "observer",
        "begin_stack": "proposal_author",
    }.get(action_name, action_name.removeprefix("propose_"))


def _state_invariant_failure(state: dict[str, Any]) -> str | None:
    for entity_id, resources in state.get("resources", {}).items():
        for resource_id, raw_value in resources.items():
            if not isinstance(raw_value, (int, float)):
                continue
            value = float(raw_value)
            if not math.isfinite(value) or value < 0:
                return (
                    f"State-based check stopped the action: {entity_id}.{resource_id} "
                    "would become an invalid resource total."
                )

    flags = state.get("world_flags", {})
    for key, value in flags.items():
        if not value or not str(key).endswith("_clean"):
            continue
        subject = str(key).removesuffix("_clean")
        if flags.get(f"{subject}_contaminated"):
            return (
                f"State-based check stopped the action: {subject} cannot be marked both "
                "clean and contaminated."
            )
    return None


def _reject_cycle(feedback: str) -> ValidationDecision:
    return ValidationDecision(
        False,
        "cycle_action_unavailable",
        public_data={"feedback": feedback},
        narration_key="invalid_action",
    )
