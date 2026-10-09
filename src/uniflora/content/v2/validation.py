from __future__ import annotations

from collections.abc import Iterable

from uniflora.content.v2.schema import V2PositionDefinition


class V2PackValidationError(ValueError):
    """Raised when individually valid positions form an invalid pack."""


def validate_pack(
    definitions: Iterable[V2PositionDefinition],
) -> tuple[V2PositionDefinition, ...]:
    items = tuple(definitions)

    if not items:
        raise V2PackValidationError("a v2 content pack must contain at least one position")

    positions_by_id: dict[str, V2PositionDefinition] = {}
    positions_by_ordinal: dict[int, V2PositionDefinition] = {}

    for definition in items:
        previous_id = positions_by_id.get(definition.id)
        if previous_id is not None:
            raise V2PackValidationError(f"duplicate position ID {definition.id!r}")

        previous_ordinal = positions_by_ordinal.get(definition.ordinal)
        if previous_ordinal is not None:
            raise V2PackValidationError(
                f"duplicate position ordinal {definition.ordinal}: "
                f"{previous_ordinal.id!r} and {definition.id!r}"
            )

        positions_by_id[definition.id] = definition
        positions_by_ordinal[definition.ordinal] = definition

    return items
