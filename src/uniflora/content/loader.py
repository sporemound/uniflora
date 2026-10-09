from __future__ import annotations

from importlib.resources import files
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from uniflora.content.schema import ExpansionMechanic, PositionStatus, PuzzleDefinition


class ContentValidationError(ValueError):
    pass


class PuzzleRegistry:
    def __init__(self, definitions: dict[int, PuzzleDefinition]) -> None:
        self._definitions = definitions

    @classmethod
    def load_packaged(cls) -> PuzzleRegistry:
        package_root = files("uniflora.content")
        root = package_root.joinpath("puzzles")
        payloads: list[tuple[str, str]] = []
        for item in root.iterdir():
            if item.name.endswith((".yaml", ".yml")):
                payloads.append((item.name, item.read_text(encoding="utf-8")))
        registry = cls._load_payloads(payloads)
        registry.validate_presentation_assets(package_root)
        return registry

    @classmethod
    def load_directory(cls, path: Path) -> PuzzleRegistry:
        payloads = [
            (item.name, item.read_text(encoding="utf-8")) for item in sorted(path.glob("*.y*ml"))
        ]
        registry = cls._load_payloads(payloads)
        registry.validate_presentation_assets(path.parent)
        return registry

    @classmethod
    def _load_payloads(cls, payloads: list[tuple[str, str]]) -> PuzzleRegistry:
        definitions: dict[int, PuzzleDefinition] = {}
        for name, text in payloads:
            try:
                raw: Any = yaml.safe_load(text)
                definition = PuzzleDefinition.model_validate(raw)
            except (yaml.YAMLError, ValidationError, TypeError) as exc:
                raise ContentValidationError(f"invalid puzzle file {name}: {exc}") from exc
            if definition.position in definitions:
                raise ContentValidationError(f"duplicate position {definition.position} in {name}")
            definitions[definition.position] = definition
        expected = set(range(7))
        if set(definitions) != expected:
            raise ContentValidationError(
                f"content must define positions 0-6; missing={sorted(expected - set(definitions))}"
            )
        if definitions[0].status is not PositionStatus.COMPLETE:
            raise ContentValidationError("Position 0 must be complete")
        reveal_ids = [
            presentation.id
            for definition in definitions.values()
            for presentation in definition.triggered_presentations
        ]
        if len(set(reveal_ids)) != len(reveal_ids):
            raise ContentValidationError("triggered presentation IDs must be globally unique")
        registry = cls(definitions)
        registry.validate_expansion_coverage()
        return registry

    def get(self, position: int) -> PuzzleDefinition:
        try:
            return self._definitions[position]
        except KeyError as exc:
            raise ContentValidationError(f"position is not defined: {position}") from exc

    def all(self) -> tuple[PuzzleDefinition, ...]:
        return tuple(self._definitions[position] for position in sorted(self._definitions))

    def validate_narration_keys(self, templates: dict[str, dict[str, list[str]]]) -> None:
        available = set().union(*(profile.keys() for profile in templates.values()))
        missing: dict[int, set[str]] = {}
        for definition in self.all():
            absent = set(definition.narration_keys.values()) - available
            if absent:
                missing[definition.position] = absent
        if missing:
            raise ContentValidationError(f"missing deterministic narration keys: {missing}")

    def validate_presentation_assets(self, package_root: Any) -> None:
        for definition in self.all():
            presentations = (
                *((definition.presentation,) if definition.presentation is not None else ()),
                *definition.triggered_presentations,
            )
            for presentation in presentations:
                images = (presentation, *getattr(presentation, "additional_images", ()))
                for image in images:
                    asset = package_root.joinpath(*image.image_asset.split("/"))
                    if not asset.is_file():
                        raise ContentValidationError(
                            f"missing Position {definition.position} presentation asset: "
                            f"{image.image_asset}"
                        )
                    payload = asset.read_bytes()
                    if not payload or len(payload) > 10 * 1024 * 1024:
                        raise ContentValidationError(
                            f"Position {definition.position} presentation asset must be "
                            "1 byte-10 MiB"
                        )
                    suffix = image.image_asset.rsplit(".", 1)[-1]
                    valid_signature = (
                        suffix == "png"
                        and payload.startswith(b"\x89PNG\r\n\x1a\n")
                        or suffix in {"jpg", "jpeg"}
                        and payload.startswith(b"\xff\xd8\xff")
                        or suffix == "webp"
                        and payload.startswith(b"RIFF")
                        and payload[8:12] == b"WEBP"
                    )
                    if not valid_signature:
                        raise ContentValidationError(
                            f"Position {definition.position} presentation asset signature is "
                            "invalid"
                        )

    def validate_expansion_coverage(self) -> None:
        later_positions = tuple(
            item for item in self.all()[1:] if item.status is PositionStatus.STUB
        )
        if not later_positions:
            return
        represented = {
            mechanic
            for definition in later_positions
            if definition.expansion is not None
            for mechanic in definition.expansion.mechanics
        }
        missing = set(ExpansionMechanic) - represented
        if missing:
            names = sorted(item.value for item in missing)
            raise ContentValidationError(f"expansion fixtures do not cover mechanics: {names}")
