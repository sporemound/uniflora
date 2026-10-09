from __future__ import annotations

import copy
import hashlib
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

from uniflora.engine.actions import CandidateAction
from uniflora.engine.validation import ValidationContext, ValidationDecision
from uniflora.runtime import Environment

ELIGIBLE_ACTIONS = frozenset(
    {
        "connect",
        "offer",
        "request_support",
        "sustain",
        "relay",
        "mitigate",
        "branch_proposal",
        "propose_circulation",
        "begin_stack",
        "react_to_stack",
        "add_proposal_kicker",
        "resolve_stack",
    }
)
_DEFAULT_CHOICES: dict[str, dict[str, str]] = {
    "brace": {"label": "Brace", "effect": "prevent damage, add strain"},
    "divert": {"label": "Divert", "effect": "protect here, move burden"},
    "release": {"label": "Release", "effect": "lower escalation, lose capacity"},
}
_EVENTS: tuple[dict[str, Any], ...] = (
    {
        "kind": "veil_harmonic",
        "title": "The Condensation Veil has begun ringing",
        "description": (
            "Collected water is moving sideways along the roofline toward the workers' court."
        ),
        "threatened_asset": "the Condensation Veil seam",
        "consequence": "A Veil seam parts and settlement escalation increases.",
        "scars": {
            "brace": "The Veil holds, but its seam rings whenever pressure gathers.",
            "divert": "The Veil holds; the workers' court now receives its runoff.",
            "release": "The Veil holds, but one collection span remains permanently dry.",
        },
        "choices": {
            "brace": {"label": "Stitch the seam", "effect": "hold the Veil, add strain"},
            "divert": {
                "label": "Channel the runoff",
                "effect": "protect the seam, move burden",
            },
            "release": {
                "label": "Dry one span",
                "effect": "lower escalation, lose capacity",
            },
        },
    },
    {
        "kind": "relay_reversal",
        "title": "Central Relay is returning pressure into the household lines",
        "description": (
            "Pale Nursery still receives moisture, but Lower Archive hears water striking "
            "its sealed roof."
        ),
        "threatened_asset": "the household water lines",
        "consequence": "The reversed pressure reaches another district and escalation increases.",
        "scars": {
            "brace": "The household lines hold, but knock against their walls at every relay.",
            "divert": "The household lines hold; Lower Archive inherits their pressure.",
            "release": "The household lines hold, but one branch can no longer carry water.",
        },
        "choices": {
            "brace": {"label": "Dampen the relay", "effect": "hold pressure, add strain"},
            "divert": {
                "label": "Reroute the pulse",
                "effect": "protect these lines, move burden",
            },
            "release": {
                "label": "Close one branch",
                "effect": "lower escalation, lose capacity",
            },
        },
    },
    {
        "kind": "route_seven_shudder",
        "title": "Route 07 has shifted under the settlement",
        "description": (
            "The paving remains level, but every open vessel now trembles toward the same wall."
        ),
        "threatened_asset": "Route 07",
        "consequence": "The buried route shifts again and settlement escalation increases.",
        "scars": {
            "brace": "Route 07 stays open, though every vessel carried across it trembles.",
            "divert": "Route 07 stays open; the buried movement passes beneath another district.",
            "release": "Route 07 stays open, but one approach remains unusable.",
        },
        "choices": {
            "brace": {"label": "Shore Route 07", "effect": "hold the route, add strain"},
            "divert": {
                "label": "Shift the underflow",
                "effect": "protect this route, move burden",
            },
            "release": {
                "label": "Close one approach",
                "effect": "lower escalation, lose capacity",
            },
        },
    },
    {
        "kind": "nursery_dryline",
        "title": "A dry line is moving across Pale Nursery",
        "description": (
            "Shade cloth darkens on one side while the adjoining planted beds lose their scent."
        ),
        "threatened_asset": "the next planted bed in Pale Nursery",
        "consequence": "The dry line crosses the next bed and settlement escalation increases.",
        "scars": {
            "brace": "The planted bed survives, but must be tended whenever the cloth darkens.",
            "divert": "The planted bed survives; an adjoining bed inherits the dry line.",
            "release": "The planted bed survives, but one nursery span remains fallow.",
        },
        "choices": {
            "brace": {"label": "Tend the dry line", "effect": "save the bed, add strain"},
            "divert": {
                "label": "Move the water draw",
                "effect": "protect this bed, move burden",
            },
            "release": {
                "label": "Fallow one span",
                "effect": "lower escalation, lose capacity",
            },
        },
    },
)


def settlement_choice(event: dict[str, Any], method: str) -> dict[str, str]:
    """Return an event-specific presentation for a stable intervention method."""
    fallback = _DEFAULT_CHOICES[method]
    choices = event.get("choices", {})
    choice = choices.get(method, {}) if isinstance(choices, dict) else {}
    if not isinstance(choice, dict):
        choice = {}
    return {
        "label": str(choice.get("label") or fallback["label"]),
        "effect": str(choice.get("effect") or fallback["effect"]),
    }


def settlement_choices_text(event: dict[str, Any]) -> str:
    return " · ".join(
        f"**{settlement_choice(event, method)['label']}** — "
        f"{settlement_choice(event, method)['effect']}"
        for method in ("brace", "divert", "release")
    )


def _stable_number(*parts: object) -> int:
    source = ":".join(str(part) for part in parts)
    return int(hashlib.sha256(source.encode()).hexdigest(), 16)


def _next_threshold(context: ValidationContext, state: dict[str, Any]) -> int:
    history_size = len(state.get("settlement_event_history", []))
    generation = int(state.get("session_generation", 0))
    return 4 + (_stable_number(context.session_id, generation, history_size, "threshold") % 3)


def _event_for_action(
    context: ValidationContext,
    action: CandidateAction,
    *,
    response_minutes: int,
    now: datetime,
) -> dict[str, Any]:
    number = _stable_number(context.session_id, context.action_id, action.action)
    template = _EVENTS[number % len(_EVENTS)]
    return {
        **template,
        "event_id": f"se-{number:064x}"[:15],
        "status": "active",
        "caused_by_action": action.action,
        "caused_by_participant_id": context.participant_id,
        "opened_at": now.isoformat(),
        "expires_at": (now + timedelta(minutes=response_minutes)).isoformat(),
    }


def _append_notice(
    decision: ValidationDecision, state: dict[str, Any], notice: str
) -> ValidationDecision:
    public_data = dict(decision.public_data)
    existing = str(public_data.get("public_text", "")).strip()
    public_data["public_text"] = f"{existing}\n\n{notice}" if existing else notice
    return replace(decision, next_state=state, public_data=public_data)


def apply_settlement_event(
    action: CandidateAction,
    context: ValidationContext,
    decision: ValidationDecision,
    *,
    response_minutes: int = 120,
    now: datetime | None = None,
) -> ValidationDecision:
    """Apply stable, action-triggered Position 1 settlement events atomically."""
    if (
        context.current_position != 1
        or context.environment is not Environment.LIVE
        or not decision.accepted
        or decision.next_state is None
        or decision.position_completed
        or decision.reason_key == "cycle_reassessed"
        or action.action not in ELIGIBLE_ACTIONS
    ):
        return decision

    state = copy.deepcopy(decision.next_state)
    active = state.get("settlement_event")
    if active and active.get("status") == "active":
        return decision

    count = int(state.get("settlement_event_actions_since_last", 0)) + 1
    threshold = int(state.get("settlement_event_trigger_after", 0)) or _next_threshold(
        context, state
    )
    roll = _stable_number(context.session_id, context.action_id, "event-roll") % 100
    state["settlement_event_actions_since_last"] = count
    state["settlement_event_trigger_after"] = threshold
    if roll >= 20 and count < threshold:
        return replace(decision, next_state=state)

    current_time = now or datetime.now(UTC)
    event = _event_for_action(
        context,
        action,
        response_minutes=response_minutes,
        now=current_time,
    )
    deadline = int(datetime.fromisoformat(event["expires_at"]).timestamp())
    state["settlement_event"] = event
    state["settlement_event_actions_since_last"] = 0
    state["settlement_event_trigger_after"] = _next_threshold(context, state)
    notice = (
        f"**WHOLE SETTLEMENT UPDATE — {event['title']}**\n"
        f"{event['description']}\n"
        f"**At stake:** {event['threatened_asset']}.\n"
        f"Event `{event['event_id']}` was caused by the settlement's response to "
        f"`{action.action.replace('_', ' ')}`. One eligible Mycotroph may use a button below "
        f"before <t:{deadline}:R>:\n"
        f"{settlement_choices_text(event)}\n"
        "The first choice always prevents catastrophe, but leaves a scar. One different "
        "Mycotroph may then press a button before the same deadline: repeat the choice to "
        "soften its cost, or choose another to redirect the scar. "
        "Slash-command fallback: `/interior intervene`."
    )
    return _append_notice(decision, state, notice)
