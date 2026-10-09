from __future__ import annotations

import shlex
from dataclasses import dataclass
from typing import Literal

from uniflora.engine.v2.commands import (
    V2AssignRoleCommand,
    V2BeginInvestigationCommand,
    V2CompletePositionCommand,
    V2ConfirmAssessmentCommand,
    V2DraftAssessmentCommand,
    V2ExamineEvidenceCommand,
    V2InvestigationCommand,
    V2MovePlayerCommand,
    V2PassCapacityCommand,
    V2PerformActionCommand,
    V2ProposeActionCommand,
    V2RegisterPromotedFindingCommand,
    V2ReleaseRoleCommand,
    V2SubmitQualityReviewCommand,
    V2SupportActionCommand,
    V2ViewStrategicBoardCommand,
)

_COMMAND_ALIASES = {
    "act": "perform-action",
    "board": "strategic-board",
    "case-board": "strategic-board",
    "pass-capacity": "pass-capacity",
    "pass-round": "pass-capacity",
    "propose": "propose-action",
    "propose-action": "propose-action",
    "strategic-board": "strategic-board",
    "support": "support-action",
    "support-action": "support-action",
    "assign-role": "assign-role",
    "begin": "begin-investigation",
    "begin-investigation": "begin-investigation",
    "complete": "complete-position",
    "complete-position": "complete-position",
    "confirm": "confirm-assessment",
    "confirm-assessment": "confirm-assessment",
    "draft": "draft-assessment",
    "draft-assessment": "draft-assessment",
    "examine": "examine-evidence",
    "examine-evidence": "examine-evidence",
    "go": "move",
    "inspect": "examine-evidence",
    "move": "move",
    "perform": "perform-action",
    "perform-action": "perform-action",
    "release": "release-role",
    "release-role": "release-role",
    "register-promoted-finding": "register-promoted-finding",
    "review": "submit-quality-review",
    "score-review": "submit-quality-review",
    "submit-quality-review": "submit-quality-review",
    "role": "assign-role",
    "take-role": "assign-role",
}

_ASSIGN_ROLE_OPTION_ALIASES = {
    "--description": "description",
    "--display-name": "display_name",
    "--name": "display_name",
}

_DRAFT_OPTION_ALIASES = {
    "--confidence": "confidence",
    "--contradiction": "contradictions",
    "--contradictions": "contradictions",
    "--evidence": "evidence",
    "--gap": "gaps",
    "--gaps": "gaps",
    "--minority": "minority",
    "--minority-view": "minority",
    "--next": "next_collection",
    "--next-collection": "next_collection",
    "--ordinary": "ordinary",
    "--ordinary-explanations": "ordinary",
    "--statement": "statement",
}

_LIST_OPTIONS = frozenset({"evidence", "ordinary", "contradictions", "gaps"})
_SCALAR_OPTIONS = frozenset({"statement", "confidence", "next_collection", "minority"})


class V2CommandParseError(ValueError):
    """Raised when explicit transport text cannot become a typed command."""

    def __init__(self, code: str, message: str, *, usage: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.usage = usage


@dataclass(frozen=True, slots=True)
class V2CommandHelp:
    name: str
    usage: str
    description: str


COMMAND_HELP: tuple[V2CommandHelp, ...] = (
    V2CommandHelp(
        name="begin-investigation",
        usage="begin-investigation",
        description="Complete Position 0 orientation and open Position 1.",
    ),
    V2CommandHelp(
        name="assign-role",
        usage=(
            'assign-role <role_id> [--name "public title"] '
            '[--description "optional public description"]'
        ),
        description="Assume a canonical function with optional public role language.",
    ),
    V2CommandHelp(
        name="release-role",
        usage="release-role",
        description="Release the active temporary role.",
    ),
    V2CommandHelp(
        name="move",
        usage="move <location_id>",
        description="Move to an available investigation location.",
    ),
    V2CommandHelp(
        name="examine-evidence",
        usage="examine-evidence <evidence_id>",
        description="Examine an available evidence source at its location.",
    ),
    V2CommandHelp(
        name="perform-action",
        usage="perform-action <action_id>",
        description="Perform a declared investigation action.",
    ),
    V2CommandHelp(
        name="strategic-board",
        usage="strategic-board",
        description="Show operation capacity, tracks, conditions, and major proposals.",
    ),
    V2CommandHelp(
        name="propose-action",
        usage="propose-action <action_id>",
        description="Open a supported proposal for a major operation.",
    ),
    V2CommandHelp(
        name="support-action",
        usage="support-action <proposal_id>",
        description="Support another participant's major-operation proposal.",
    ),
    V2CommandHelp(
        name="pass-capacity",
        usage="pass-capacity",
        description="Spend the remaining operation capacity and close the round.",
    ),
    V2CommandHelp(
        name="draft-assessment",
        usage=(
            'draft-assessment <assessment_id> --statement "..." '
            "--evidence id[,id...] [--ordinary id[,id...]] "
            "[--contradictions id[,id...]] [--gaps id[,id...]] "
            "[--confidence low|moderate|high] "
            '[--next-collection "..."] [--minority-view "..."]'
        ),
        description="Draft a structured assessment from examined evidence.",
    ),
    V2CommandHelp(
        name="confirm-assessment",
        usage="confirm-assessment <assessment_id>",
        description="Confirm another participant's assessment.",
    ),
    V2CommandHelp(
        name="register-promoted-finding",
        usage="register-promoted-finding <finding_id> <revision> <author_player_id>",
        description="Register an already promotion-eligible immutable finding revision.",
    ),
    V2CommandHelp(
        name="submit-quality-review",
        usage=(
            "submit-quality-review <finding|assessment> <subject_id> <revision> "
            "<evidence 0-2> <alternatives 0-2> <contradictions 0-2> "
            '<confidence 0-2> <reproducibility 0-2> "<rationale>"'
        ),
        description="Submit the five-dimension peer rubric for an exact revision.",
    ),
    V2CommandHelp(
        name="complete-position",
        usage="complete-position <assessment_id>",
        description="Complete the current position using a confirmed assessment.",
    ),
)

_HELP_BY_NAME = {item.name: item for item in COMMAND_HELP}


def _require_player_id(player_id: str) -> str:
    normalized = player_id.strip()
    if not normalized:
        raise V2CommandParseError(
            "missing_player_id",
            "A nonblank player ID is required.",
        )
    return normalized


def _tokenize(text: str) -> list[str]:
    normalized = text.strip()
    if not normalized:
        raise V2CommandParseError(
            "empty_command",
            "No command was provided.",
        )

    try:
        tokens = shlex.split(normalized, posix=True)
    except ValueError as exc:
        raise V2CommandParseError(
            "invalid_quoting",
            f"Command quoting is invalid: {exc}",
        ) from exc

    if not tokens:
        raise V2CommandParseError(
            "empty_command",
            "No command was provided.",
        )

    first = tokens[0]
    if first.startswith("/"):
        tokens[0] = first[1:]

    if tokens[0].casefold() == "v2":
        tokens = tokens[1:]
        if not tokens:
            raise V2CommandParseError(
                "empty_command",
                "No command followed the v2 prefix.",
            )

    return tokens


def _normalize_command_name(value: str) -> str:
    normalized = value.strip().casefold().replace("_", "-")
    command_name = _COMMAND_ALIASES.get(normalized)
    if command_name is None:
        known = ", ".join(item.name for item in COMMAND_HELP)
        raise V2CommandParseError(
            "unknown_command",
            f"Unknown command {value!r}. Known commands: {known}.",
        )
    return command_name


def _expect_exact_arguments(
    command_name: str,
    arguments: list[str],
    *,
    count: int,
) -> None:
    if len(arguments) == count:
        return

    help_item = _HELP_BY_NAME[command_name]
    raise V2CommandParseError(
        "invalid_arguments",
        f"Command {command_name!r} expects {count} argument(s); received {len(arguments)}.",
        usage=help_item.usage,
    )


def _split_ids(values: list[str], *, option: str) -> tuple[str, ...]:
    collected: list[str] = []
    for value in values:
        for item in value.split(","):
            normalized = item.strip()
            if not normalized:
                raise V2CommandParseError(
                    "invalid_option_value",
                    f"Option --{option.replace('_', '-')} contains an empty ID.",
                )
            collected.append(normalized)

    if len(collected) != len(set(collected)):
        raise V2CommandParseError(
            "duplicate_option_value",
            f"Option --{option.replace('_', '-')} contains duplicate IDs.",
        )

    return tuple(collected)


def _parse_assign_role_arguments(
    arguments: list[str],
) -> tuple[str, str | None, str | None]:
    usage = _HELP_BY_NAME["assign-role"].usage
    tokens = list(arguments)
    if tokens and tokens[0].casefold() == "set":
        tokens = tokens[1:]
    if not tokens:
        raise V2CommandParseError(
            "invalid_arguments",
            "assign-role requires a canonical role ID.",
            usage=usage,
        )
    role_id = tokens.pop(0)
    display_name: str | None = None
    description: str | None = None
    if tokens and tokens[0].casefold() == "as":
        tokens.pop(0)
        name_tokens: list[str] = []
        while tokens and not tokens[0].startswith("--"):
            name_tokens.append(tokens.pop(0))
        if not name_tokens:
            raise V2CommandParseError(
                "missing_option_value",
                "The `as` form requires a public role name.",
                usage=usage,
            )
        display_name = " ".join(name_tokens)
    values: dict[str, str] = {}
    index = 0
    while index < len(tokens):
        raw_option = tokens[index]
        option = _ASSIGN_ROLE_OPTION_ALIASES.get(raw_option.casefold())
        if option is None:
            raise V2CommandParseError(
                "unknown_option",
                f"Unknown assign-role option {raw_option!r}.",
                usage=usage,
            )
        if index + 1 >= len(tokens) or tokens[index + 1].startswith("--"):
            raise V2CommandParseError(
                "missing_option_value",
                f"Option {raw_option!r} requires a value.",
                usage=usage,
            )
        if option in values or (option == "display_name" and display_name is not None):
            raise V2CommandParseError(
                "duplicate_option",
                f"Option {raw_option!r} may be provided only once.",
                usage=usage,
            )
        values[option] = tokens[index + 1]
        index += 2
    if "display_name" in values:
        display_name = values["display_name"]
    description = values.get("description")
    if description is not None and display_name is None:
        raise V2CommandParseError(
            "missing_required_option",
            "--description requires --name or the `as` form.",
            usage=usage,
        )
    return role_id, display_name, description


def _parse_draft_options(tokens: list[str]) -> dict[str, object]:
    values: dict[str, list[str]] = {}
    index = 0

    while index < len(tokens):
        raw_option = tokens[index]
        option = _DRAFT_OPTION_ALIASES.get(raw_option.casefold())
        if option is None:
            raise V2CommandParseError(
                "unknown_option",
                f"Unknown draft-assessment option {raw_option!r}.",
                usage=_HELP_BY_NAME["draft-assessment"].usage,
            )

        if index + 1 >= len(tokens):
            raise V2CommandParseError(
                "missing_option_value",
                f"Option {raw_option!r} requires a value.",
                usage=_HELP_BY_NAME["draft-assessment"].usage,
            )

        option_value = tokens[index + 1].strip()
        if not option_value or option_value.startswith("--"):
            raise V2CommandParseError(
                "missing_option_value",
                f"Option {raw_option!r} requires a value.",
                usage=_HELP_BY_NAME["draft-assessment"].usage,
            )

        if option in _SCALAR_OPTIONS and option in values:
            raise V2CommandParseError(
                "duplicate_option",
                f"Option {raw_option!r} may be provided only once.",
            )

        values.setdefault(option, []).append(option_value)
        index += 2

    if "statement" not in values:
        raise V2CommandParseError(
            "missing_required_option",
            "draft-assessment requires --statement.",
            usage=_HELP_BY_NAME["draft-assessment"].usage,
        )

    if "evidence" not in values:
        raise V2CommandParseError(
            "missing_required_option",
            "draft-assessment requires --evidence.",
            usage=_HELP_BY_NAME["draft-assessment"].usage,
        )

    confidence = values.get("confidence", ["low"])[0].casefold()
    if confidence not in {"low", "moderate", "high"}:
        raise V2CommandParseError(
            "invalid_confidence",
            "Assessment confidence must be low, moderate, or high.",
        )

    parsed: dict[str, object] = {
        "statement": values["statement"][0],
        "evidence_ids": _split_ids(values["evidence"], option="evidence"),
        "tested_ordinary_explanation_ids": _split_ids(
            values.get("ordinary", []),
            option="ordinary",
        ),
        "preserved_contradiction_ids": _split_ids(
            values.get("contradictions", []),
            option="contradictions",
        ),
        "documented_information_gap_ids": _split_ids(
            values.get("gaps", []),
            option="gaps",
        ),
        "confidence": confidence,
        "next_collection": values.get(
            "next_collection",
            ["No next collection specified."],
        )[0],
        "minority_view": values.get("minority", [None])[0],
    }
    return parsed


def parse_user_command(
    text: str,
    *,
    player_id: str,
) -> V2InvestigationCommand:
    """Parse strict explicit command text into one typed v2 command."""

    normalized_player_id = _require_player_id(player_id)
    tokens = _tokenize(text)
    raw_command_name = tokens[0].strip().casefold().replace("_", "-")
    command_name = _normalize_command_name(tokens[0])
    arguments = tokens[1:]

    if (
        raw_command_name == "role"
        and len(arguments) == 1
        and arguments[0].casefold() in {"clear", "release"}
    ):
        return V2ReleaseRoleCommand(player_id=normalized_player_id)

    if command_name == "begin-investigation":
        _expect_exact_arguments(command_name, arguments, count=0)
        return V2BeginInvestigationCommand(player_id=normalized_player_id)

    if command_name == "assign-role":
        role_id, display_name, description = _parse_assign_role_arguments(arguments)
        return V2AssignRoleCommand(
            player_id=normalized_player_id,
            role_id=role_id,
            display_name=display_name,
            description=description,
        )

    if command_name == "release-role":
        _expect_exact_arguments(command_name, arguments, count=0)
        return V2ReleaseRoleCommand(player_id=normalized_player_id)

    if command_name == "move":
        _expect_exact_arguments(command_name, arguments, count=1)
        return V2MovePlayerCommand(
            player_id=normalized_player_id,
            location_id=arguments[0],
        )

    if command_name == "examine-evidence":
        _expect_exact_arguments(command_name, arguments, count=1)
        return V2ExamineEvidenceCommand(
            player_id=normalized_player_id,
            evidence_id=arguments[0],
        )

    if command_name == "perform-action":
        _expect_exact_arguments(command_name, arguments, count=1)
        return V2PerformActionCommand(
            player_id=normalized_player_id,
            action_id=arguments[0],
        )

    if command_name == "strategic-board":
        _expect_exact_arguments(command_name, arguments, count=0)
        return V2ViewStrategicBoardCommand(player_id=normalized_player_id)

    if command_name == "propose-action":
        _expect_exact_arguments(command_name, arguments, count=1)
        return V2ProposeActionCommand(
            player_id=normalized_player_id,
            action_id=arguments[0],
        )

    if command_name == "support-action":
        _expect_exact_arguments(command_name, arguments, count=1)
        return V2SupportActionCommand(
            player_id=normalized_player_id,
            proposal_id=arguments[0],
        )

    if command_name == "pass-capacity":
        _expect_exact_arguments(command_name, arguments, count=0)
        return V2PassCapacityCommand(player_id=normalized_player_id)

    if command_name == "confirm-assessment":
        _expect_exact_arguments(command_name, arguments, count=1)
        return V2ConfirmAssessmentCommand(
            player_id=normalized_player_id,
            assessment_id=arguments[0],
        )

    if command_name == "complete-position":
        _expect_exact_arguments(command_name, arguments, count=1)
        return V2CompletePositionCommand(
            player_id=normalized_player_id,
            assessment_id=arguments[0],
        )

    if command_name == "register-promoted-finding":
        _expect_exact_arguments(command_name, arguments, count=3)
        try:
            revision = int(arguments[1])
        except ValueError as exc:
            raise V2CommandParseError(
                "invalid_revision",
                "Finding revision must be a positive integer.",
                usage=_HELP_BY_NAME[command_name].usage,
            ) from exc
        try:
            return V2RegisterPromotedFindingCommand(
                player_id=normalized_player_id,
                finding_id=arguments[0],
                finding_revision=revision,
                author_player_id=arguments[2],
            )
        except ValueError as exc:
            raise V2CommandParseError(
                "invalid_arguments",
                str(exc),
                usage=_HELP_BY_NAME[command_name].usage,
            ) from exc

    if command_name == "submit-quality-review":
        _expect_exact_arguments(command_name, arguments, count=9)
        subject_kind = arguments[0].casefold()
        if subject_kind not in {"finding", "assessment"}:
            raise V2CommandParseError(
                "invalid_subject_kind",
                "Review subject kind must be finding or assessment.",
                usage=_HELP_BY_NAME[command_name].usage,
            )
        try:
            revision = int(arguments[2])
            scores = tuple(int(value) for value in arguments[3:8])
            return V2SubmitQualityReviewCommand(
                player_id=normalized_player_id,
                subject_kind=subject_kind,  # type: ignore[arg-type]
                subject_id=arguments[1],
                subject_revision=revision,
                evidence_support=scores[0],
                ordinary_alternatives=scores[1],
                contradictions_preserved=scores[2],
                confidence_calibration=scores[3],
                reproducibility=scores[4],
                rationale=arguments[8],
            )
        except (ValueError, IndexError) as exc:
            raise V2CommandParseError(
                "invalid_review",
                str(exc),
                usage=_HELP_BY_NAME[command_name].usage,
            ) from exc

    if command_name == "draft-assessment":
        if not arguments:
            raise V2CommandParseError(
                "invalid_arguments",
                "draft-assessment requires an assessment ID.",
                usage=_HELP_BY_NAME[command_name].usage,
            )

        assessment_id = arguments[0]
        options = _parse_draft_options(arguments[1:])
        confidence: Literal["low", "moderate", "high"] = options["confidence"]  # type: ignore[assignment]
        return V2DraftAssessmentCommand(
            player_id=normalized_player_id,
            assessment_id=assessment_id,
            statement=str(options["statement"]),
            evidence_ids=options["evidence_ids"],  # type: ignore[arg-type]
            tested_ordinary_explanation_ids=options["tested_ordinary_explanation_ids"],  # type: ignore[arg-type]
            preserved_contradiction_ids=options["preserved_contradiction_ids"],  # type: ignore[arg-type]
            documented_information_gap_ids=options["documented_information_gap_ids"],  # type: ignore[arg-type]
            confidence=confidence,
            next_collection=str(options["next_collection"]),
            minority_view=options["minority_view"],  # type: ignore[arg-type]
        )

    raise AssertionError(f"unhandled command {command_name!r}")
