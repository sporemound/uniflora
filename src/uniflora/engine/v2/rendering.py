from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from uniflora.engine.v2.application import (
    V2ApplicationCommandResult,
    V2SessionView,
)
from uniflora.content.v2.investigation_schema import V2InvestigationPack
from uniflora.engine.v2.commands import V2InvestigationCommand
from uniflora.engine.v2.delivery import (
    next_requirement,
    relevant_actions,
    relevant_evidence_ids,
    render_command_delivery,
)
from uniflora.engine.v2.parsing import V2CommandParseError
from uniflora.engine.v2.state import V2InvestigationState


@dataclass(frozen=True, slots=True)
class V2RenderedResponse:
    kind: Literal["command_result", "parse_error", "session"]
    accepted: bool
    code: str
    summary: str
    details: tuple[str, ...] = ()
    stream_id: str | None = None
    sequence: int | None = None

    def to_text(self) -> str:
        lines = [self.summary, *self.details]
        return "\n".join(lines)


def _sorted_items(values: frozenset[str]) -> str:
    if not values:
        return "none"
    return ", ".join(sorted(values))


def _player_lines(session: V2SessionView) -> tuple[str, ...]:
    lines: list[str] = []
    for player in sorted(
        session.state.players,
        key=lambda item: item.player_id,
    ):
        if player.active_role_id is None:
            role = "no role"
        elif player.active_role_display_name is None:
            role = player.active_role_id
        else:
            role = (
                f"{player.active_role_display_name} "
                f"(function: {player.active_role_id})"
            )
        lines.append(f"Player {player.player_id}: {player.current_location_id}; {role}.")
    return tuple(lines)


def render_application_result(
    result: V2ApplicationCommandResult,
    *,
    pack: V2InvestigationPack | None = None,
    command: V2InvestigationCommand | None = None,
    previous_state: V2InvestigationState | None = None,
) -> V2RenderedResponse:
    """Render an application result without assuming Discord or another UI.

    When the pack, typed command, and pre-command state are supplied, use the
    pack-driven delivery layer. The optional arguments retain compatibility with
    older transport callers while keeping rich v2 output centralized.
    """

    if pack is not None and command is not None and previous_state is not None:
        delivery = render_command_delivery(
            pack,
            previous_state,
            result.session.state,
            command,
            accepted=result.accepted,
            code=result.code,
            message=result.message,
        )
        return V2RenderedResponse(
            kind="command_result",
            accepted=result.accepted,
            code=result.code,
            summary=delivery.summary,
            details=delivery.details,
            stream_id=result.session.stream_id,
            sequence=result.session.sequence,
        )

    status = "Accepted" if result.accepted else "Rejected"
    event_name = type(result.event).__name__ if result.event is not None else "none"
    details = (
        f"Stream: {result.session.stream_id}",
        f"Sequence: {result.session.sequence}",
        f"Position: {result.session.state.current_position_id}",
        f"Event: {event_name}",
    )
    return V2RenderedResponse(
        kind="command_result",
        accepted=result.accepted,
        code=result.code,
        summary=f"{status}: {result.message}",
        details=details,
        stream_id=result.session.stream_id,
        sequence=result.session.sequence,
    )

def render_parse_error(error: V2CommandParseError) -> V2RenderedResponse:
    details = (f"Usage: {error.usage}",) if error.usage else ()
    return V2RenderedResponse(
        kind="parse_error",
        accepted=False,
        code=error.code,
        summary=f"Command not accepted: {error.message}",
        details=details,
    )


def render_session_view(
    session: V2SessionView,
    *,
    pack: V2InvestigationPack | None = None,
    player_id: str | None = None,
) -> V2RenderedResponse:
    """Render a compact player-facing status or a legacy diagnostic fallback."""

    state = session.state

    # Preserve the old neutral fallback for internal callers that do not
    # provide a content pack.
    if pack is None:
        details = (
            f"Position: {state.current_position_id}",
            f"Available locations: {_sorted_items(state.available_location_ids)}",
            f"Available evidence: {_sorted_items(state.available_evidence_ids)}",
            f"Examined evidence: {_sorted_items(state.examined_evidence_ids)}",
            f"Completed actions: {_sorted_items(state.completed_action_ids)}",
            f"Assessments: {len(state.assessments)}",
            *_player_lines(session),
        )
        return V2RenderedResponse(
            kind="session",
            accepted=True,
            code="session_state",
            summary=(
                f"Investigation stream {session.stream_id!r} "
                f"at sequence {session.sequence}."
            ),
            details=details,
            stream_id=session.stream_id,
            sequence=session.sequence,
        )

    position = next(
        (
            item
            for item in pack.positions
            if item.id == state.current_position_id
        ),
        None,
    )

    if position is None:
        raise ValueError(
            f"current position is absent from the loaded pack: "
            f"{state.current_position_id!r}"
        )

    evidence_ids = relevant_evidence_ids(pack, state)
    actions = relevant_actions(pack, state)
    action_ids = frozenset(action.id for action in actions)

    examined_count = len(
        evidence_ids & state.examined_evidence_ids
    )
    completed_action_count = len(
        action_ids & state.completed_action_ids
    )

    def progress_mark(completed: int, total: int) -> str:
        if total > 0 and completed >= total:
            return "\u2713"
        if completed > 0:
            return "\u25d0"
        return "\u25cb"

    selected_player = (
        state.get_player(player_id)
        if player_id is not None
        else next(
            (
                player
                for player in state.players
                if player.player_id.startswith(("discord:", "web:"))
            ),
            state.players[0] if state.players else None,
        )
    )

    if selected_player is None:
        function_line = "No participant assignment is recorded."
        selected_player_id = player_id
    else:
        selected_player_id = selected_player.player_id

        location = next(
            (
                item
                for item in pack.locations
                if item.id == selected_player.current_location_id
            ),
            None,
        )
        location_name = (
            location.name
            if location is not None
            else selected_player.current_location_id.replace("_", " ").title()
        )

        role = next(
            (
                item
                for item in pack.roles
                if item.id == selected_player.active_role_id
            ),
            None,
        )

        if selected_player.active_role_id is None:
            role_name = "No active function"
        elif selected_player.active_role_display_name is not None:
            role_name = selected_player.active_role_display_name
            if (
                role is not None
                and role.name.casefold() != role_name.casefold()
            ):
                role_name += f" ({role.name})"
        elif role is not None:
            role_name = role.name
        else:
            role_name = (
                selected_player.active_role_id
                .replace("_", " ")
                .title()
            )

        function_line = f"{role_name} \u00b7 {location_name}"

    next_step = next_requirement(
        pack,
        state,
        selected_player_id,
    )

    if any(
        assessment.status == "draft"
        for assessment in state.assessments
    ):
        assessment_line = (
            "\u25d0 Assessment drafted; awaiting independent confirmation"
        )
    elif "Draft an assessment" in next_step:
        assessment_line = "\u25cb Assessment not yet drafted"
    elif (
        next_step.startswith("Complete ")
        or "confirmed assessment" in next_step.casefold()
    ):
        assessment_line = "\u2713 Assessment confirmed"
    else:
        assessment_line = "\u25cb Assessment pending"

    progress_lines = (
        f"{progress_mark(examined_count, len(evidence_ids))} "
        f"Evidence {examined_count}/{len(evidence_ids)}",
        f"{progress_mark(completed_action_count, len(action_ids))} "
        f"Actions {completed_action_count}/{len(action_ids)}",
        assessment_line,
    )

    return V2RenderedResponse(
        kind="session",
        accepted=True,
        code="session_state",
        summary=f"**Position {position.ordinal} \u2014 {position.title}**",
        details=(
            "",
            "**Progress**",
            *progress_lines,
            "",
            "**Your current function**",
            function_line,
            "",
            "**Next step**",
            next_step,
            "",
            f"*Sequence {session.sequence} \u00b7 shared authoritative state*",
        ),
        stream_id=session.stream_id,
        sequence=session.sequence,
    )
