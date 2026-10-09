from __future__ import annotations

from pydantic import ValidationError

from uniflora.content.v2.investigation_schema import (
    V2InvestigationPack,
    V2PlayerRoleAssignmentDefinition,
    V2RoleDefinition,
)


class V2PlayerRoleError(ValueError):
    """Raised when a player-defined role cannot be created or resolved."""


def available_player_role_templates(
    pack: V2InvestigationPack,
    *,
    location_id: str | None = None,
) -> tuple[V2RoleDefinition, ...]:
    """Return canonical functions that permit a player-authored public title."""

    result: list[V2RoleDefinition] = []

    for role in pack.roles:
        if not role.allow_player_defined_name:
            continue
        if (
            location_id is not None
            and role.allowed_location_ids
            and location_id not in role.allowed_location_ids
        ):
            continue
        result.append(role)

    return tuple(result)


def create_player_role_assignment(
    pack: V2InvestigationPack,
    *,
    identity: str,
    canonical_role_id: str,
    display_name: str,
    description: str | None = None,
    position_id: str | None = None,
    current_location_id: str | None = None,
) -> V2PlayerRoleAssignmentDefinition:
    """Validate a public role title mapped to a canonical mechanical function.

    The player-authored text never becomes a mechanical role ID. Existing
    action prerequisites continue to compare against ``canonical_role_id``.
    """

    role = _get_role(pack, canonical_role_id)

    if not role.allow_player_defined_name:
        raise V2PlayerRoleError(
            f"role {canonical_role_id!r} does not allow a player-defined name"
        )

    if description is not None and not role.allow_player_defined_description:
        raise V2PlayerRoleError(
            f"role {canonical_role_id!r} does not allow a player-defined description"
        )

    if (
        current_location_id is not None
        and role.allowed_location_ids
        and current_location_id not in role.allowed_location_ids
    ):
        allowed = ", ".join(role.allowed_location_ids)
        raise V2PlayerRoleError(
            f"role {canonical_role_id!r} is not available at "
            f"{current_location_id!r}; allowed locations: {allowed}"
        )

    if position_id is not None and position_id not in {
        item.id for item in pack.positions
    }:
        raise V2PlayerRoleError(f"v2 position is not defined: {position_id}")

    try:
        return V2PlayerRoleAssignmentDefinition(
            identity=identity,
            canonical_role_id=canonical_role_id,
            display_name=display_name,
            description=description,
            position_id=position_id,
        )
    except ValidationError as exc:
        messages: list[str] = []
        for error in exc.errors(include_url=False):
            location = ".".join(str(item) for item in error.get("loc", ()))
            message = str(error.get("msg", "invalid player-defined role"))
            if message.startswith("Value error, "):
                message = message.removeprefix("Value error, ")
            messages.append(f"{location}: {message}" if location else message)
        raise V2PlayerRoleError("; ".join(messages)) from exc


def assignment_satisfies_required_role(
    assignment: V2PlayerRoleAssignmentDefinition | None,
    required_role_id: str,
) -> bool:
    """Return whether an assignment satisfies a canonical action role gate."""

    return (
        assignment is not None
        and assignment.canonical_role_id == required_role_id
    )


def render_player_role(
    pack: V2InvestigationPack,
    assignment: V2PlayerRoleAssignmentDefinition,
) -> str:
    """Render a safe, concise public description of a custom role."""

    canonical = _get_role(pack, assignment.canonical_role_id)
    rendered = f"{assignment.display_name} — function: {canonical.name}"
    if assignment.description:
        rendered += f"\n{assignment.description}"
    return rendered


def _get_role(pack: V2InvestigationPack, role_id: str) -> V2RoleDefinition:
    for role in pack.roles:
        if role.id == role_id:
            return role

    raise V2PlayerRoleError(f"v2 role is not defined: {role_id}")
