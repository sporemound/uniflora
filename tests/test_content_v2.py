from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from uniflora.content.v2 import (
    V2ContentValidationError,
    V2PuzzleRegistry,
)

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "v2" / "minimal_pack"


def _position_payload(
    *,
    position_id: str,
    ordinal: int,
) -> dict[str, object]:
    entity_id = f"{position_id}_signal"

    return {
        "schema_version": 2,
        "id": position_id,
        "ordinal": ordinal,
        "content_key": f"{position_id}_content",
        "content_version": "2.0.0",
        "title": position_id.replace("_", " ").title(),
        "public_premise": f"Premise for {position_id}.",
        "entities": [
            {
                "id": entity_id,
                "label": entity_id.replace("_", " ").title(),
                "aliases": [],
            }
        ],
        "observations": [
            {
                "id": f"{position_id}_observed",
                "entity_id": entity_id,
                "public_text": f"{position_id} can be observed.",
            }
        ],
        "initial_visible_entity_ids": [entity_id],
    }


def _write_yaml(path: Path, payload: dict[str, object]) -> None:
    path.write_text(
        yaml.safe_dump(payload, sort_keys=False),
        encoding="utf-8",
    )


def test_loads_minimal_v2_pack() -> None:
    registry = V2PuzzleRegistry.load_directory(FIXTURE_ROOT)

    assert len(registry) == 1
    assert registry.get("threshold").ordinal == 0
    assert registry.get_ordinal(0).id == "threshold"
    assert tuple(item.id for item in registry.all()) == ("threshold",)


def test_loads_any_number_of_noncontiguous_positions(tmp_path: Path) -> None:
    _write_yaml(
        tmp_path / "later.yaml",
        _position_payload(position_id="later", ordinal=8),
    )
    _write_yaml(
        tmp_path / "earlier.yaml",
        _position_payload(position_id="earlier", ordinal=3),
    )

    registry = V2PuzzleRegistry.load_directory(tmp_path)

    assert tuple(item.id for item in registry.all()) == (
        "earlier",
        "later",
    )


def test_rejects_wrong_schema_version(tmp_path: Path) -> None:
    payload = _position_payload(position_id="threshold", ordinal=0)
    payload["schema_version"] = 1
    _write_yaml(tmp_path / "threshold.yaml", payload)

    with pytest.raises(
        V2ContentValidationError,
        match="schema_version",
    ):
        V2PuzzleRegistry.load_directory(tmp_path)


def test_rejects_duplicate_position_ids(tmp_path: Path) -> None:
    _write_yaml(
        tmp_path / "first.yaml",
        _position_payload(position_id="threshold", ordinal=0),
    )
    _write_yaml(
        tmp_path / "second.yaml",
        _position_payload(position_id="threshold", ordinal=1),
    )

    with pytest.raises(
        V2ContentValidationError,
        match="duplicate position ID",
    ):
        V2PuzzleRegistry.load_directory(tmp_path)


def test_rejects_duplicate_position_ordinals(tmp_path: Path) -> None:
    _write_yaml(
        tmp_path / "first.yaml",
        _position_payload(position_id="first", ordinal=0),
    )
    _write_yaml(
        tmp_path / "second.yaml",
        _position_payload(position_id="second", ordinal=0),
    )

    with pytest.raises(
        V2ContentValidationError,
        match="duplicate position ordinal",
    ):
        V2PuzzleRegistry.load_directory(tmp_path)


def test_rejects_unknown_entity_references(tmp_path: Path) -> None:
    payload = _position_payload(position_id="threshold", ordinal=0)
    payload["observations"] = [
        {
            "id": "missing_entity_observed",
            "entity_id": "missing_entity",
            "public_text": "This reference should not validate.",
        }
    ]
    _write_yaml(tmp_path / "threshold.yaml", payload)

    with pytest.raises(
        V2ContentValidationError,
        match="unknown entity",
    ):
        V2PuzzleRegistry.load_directory(tmp_path)
