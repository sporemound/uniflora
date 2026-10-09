from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from uniflora.content.v2.schema import V2PositionDefinition
from uniflora.content.v2.validation import (
    V2PackValidationError,
    validate_pack,
)


class V2ContentValidationError(ValueError):
    """Raised when a v2 content file or pack is invalid."""


class V2PuzzleRegistry:
    """Registry of v2 positions indexed independently by ID and ordinal."""

    def __init__(self, definitions: Iterable[V2PositionDefinition]) -> None:
        try:
            items = validate_pack(definitions)
        except V2PackValidationError as exc:
            raise V2ContentValidationError(str(exc)) from exc

        self._by_id = {definition.id: definition for definition in items}
        self._by_ordinal = {definition.ordinal: definition for definition in items}

    @classmethod
    def load_directory(cls, path: Path) -> V2PuzzleRegistry:
        if not path.is_dir():
            raise V2ContentValidationError(f"v2 content directory does not exist: {path}")

        paths = sorted(
            (
                *path.glob("*.yaml"),
                *path.glob("*.yml"),
            ),
            key=lambda item: item.name,
        )

        if not paths:
            raise V2ContentValidationError(f"v2 content directory contains no YAML files: {path}")

        definitions: list[V2PositionDefinition] = []

        for item in paths:
            try:
                text = item.read_text(encoding="utf-8")
                raw: Any = yaml.safe_load(text)

                if not isinstance(raw, dict):
                    raise TypeError("top-level YAML value must be a mapping")

                definition = V2PositionDefinition.model_validate(raw)
            except (
                OSError,
                UnicodeError,
                TypeError,
                yaml.YAMLError,
                ValidationError,
            ) as exc:
                raise V2ContentValidationError(
                    f"invalid v2 content file {item.name}: {exc}"
                ) from exc

            definitions.append(definition)

        return cls(definitions)

    def get(self, position_id: str) -> V2PositionDefinition:
        try:
            return self._by_id[position_id]
        except KeyError as exc:
            raise V2ContentValidationError(f"v2 position is not defined: {position_id}") from exc

    def get_ordinal(self, ordinal: int) -> V2PositionDefinition:
        try:
            return self._by_ordinal[ordinal]
        except KeyError as exc:
            raise V2ContentValidationError(
                f"v2 position ordinal is not defined: {ordinal}"
            ) from exc

    def all(self) -> tuple[V2PositionDefinition, ...]:
        return tuple(self._by_ordinal[ordinal] for ordinal in sorted(self._by_ordinal))

    def __len__(self) -> int:
        return len(self._by_id)
