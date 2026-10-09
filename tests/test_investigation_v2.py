from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
import yaml

from uniflora.content.v2 import (
    V2InvestigationContentError,
    load_investigation_pack,
)

FIXTURE_PATH = (
    Path(__file__).parent / "fixtures" / "v2" / "boundary_array_investigation" / "pack.yaml"
)


def _fixture_payload() -> dict[str, Any]:
    payload = yaml.safe_load(FIXTURE_PATH.read_text(encoding="utf-8"))

    assert isinstance(payload, dict)

    return payload


def _write_pack(
    tmp_path: Path,
    payload: dict[str, Any],
) -> Path:
    path = tmp_path / "pack.yaml"
    path.write_text(
        yaml.safe_dump(payload, sort_keys=False),
        encoding="utf-8",
    )
    return path


def test_loads_boundary_array_investigation_pack() -> None:
    pack = load_investigation_pack(FIXTURE_PATH)

    assert pack.pack.id == "boundary_array_synthetic"
    assert pack.pack.initial_position_id == "boundary_event"

    assert len(pack.locations) == 1
    assert pack.locations[0].id == "boundary_array"

    assert len(pack.positions) == 1
    assert pack.positions[0].focus_location_id == "boundary_array"

    assert {role.id for role in pack.roles} == {
        "instrument_operator",
        "protocol_auditor",
    }

    assert {source.id for source in pack.evidence_sources} == {
        "optical_record",
        "radio_return",
        "receiver_diagnostic",
        "weather_record",
    }

    initially_available = {
        source.id for source in pack.evidence_sources if source.initially_available
    }

    assert initially_available == {
        "optical_record",
        "radio_return",
    }


def test_rejects_unknown_initial_position(tmp_path: Path) -> None:
    payload = _fixture_payload()
    payload["pack"]["initial_position_id"] = "missing_position"

    path = _write_pack(tmp_path, payload)

    with pytest.raises(
        V2InvestigationContentError,
        match="initial position references an unknown position",
    ):
        load_investigation_pack(path)


def test_rejects_duplicate_location_ids(tmp_path: Path) -> None:
    payload = _fixture_payload()
    duplicate = deepcopy(payload["locations"][0])
    payload["locations"].append(duplicate)

    path = _write_pack(tmp_path, payload)

    with pytest.raises(
        V2InvestigationContentError,
        match="duplicate location IDs",
    ):
        load_investigation_pack(path)


def test_rejects_role_with_unknown_location(tmp_path: Path) -> None:
    payload = _fixture_payload()
    payload["roles"][0]["allowed_location_ids"] = [
        "missing_location",
    ]

    path = _write_pack(tmp_path, payload)

    with pytest.raises(
        V2InvestigationContentError,
        match="role 'instrument_operator' references unknown locations",
    ):
        load_investigation_pack(path)


def test_rejects_focus_location_that_is_not_initially_available(
    tmp_path: Path,
) -> None:
    payload = _fixture_payload()
    payload["positions"][0]["initially_available_location_ids"] = []

    path = _write_pack(tmp_path, payload)

    with pytest.raises(
        V2InvestigationContentError,
        match="focus location 'boundary_array' must be initially available",
    ):
        load_investigation_pack(path)


def test_rejects_evidence_instrument_location_mismatch(
    tmp_path: Path,
) -> None:
    payload = _fixture_payload()

    payload["locations"].append(
        {
            "id": "remote_archive",
            "name": "Remote Archive",
            "description": "A synthetic second location for reference testing.",
        }
    )

    payload["evidence_sources"][0]["origin_location_id"] = "remote_archive"

    path = _write_pack(tmp_path, payload)

    with pytest.raises(
        V2InvestigationContentError,
        match="does not match instrument 'optical_array' location",
    ):
        load_investigation_pack(path)
