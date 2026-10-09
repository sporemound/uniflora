from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from uniflora.content.v2 import (
    V2InvestigationContentError,
    V2InvestigationPack,
    load_investigation_pack,
)
from uniflora.engine.v2 import (
    assign_role,
    examine_evidence,
    initialize_investigation,
    perform_action,
    release_role,
)

FIXTURE_PATH = (
    Path(__file__).parent / "fixtures" / "v2" / "boundary_array_investigation" / "pack.yaml"
)


@pytest.fixture
def pack() -> V2InvestigationPack:
    return load_investigation_pack(FIXTURE_PATH)


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


def test_loads_declarative_actions_and_investigation_items(
    pack: V2InvestigationPack,
) -> None:
    assert {action.id for action in pack.actions} == {
        "calibrate_receiver",
        "compare_optical_radio_timing",
        "document_upper_atmosphere_gap",
        "inspect_optical_record",
        "inspect_radio_return",
        "request_weather_record",
        "test_atmospheric_propagation",
    }
    assert {item.id for item in pack.ordinary_explanations} == {"atmospheric_propagation"}
    assert {item.id for item in pack.contradictions} == {"optical_radio_timing_offset"}
    assert {item.id for item in pack.information_gaps} == {"upper_atmosphere_conditions"}


def test_rejects_action_with_unknown_dependency(
    tmp_path: Path,
) -> None:
    payload = _fixture_payload()
    payload["actions"][0]["prerequisites"]["required_completed_action_ids"] = ["missing_action"]

    path = _write_pack(tmp_path, payload)

    with pytest.raises(
        V2InvestigationContentError,
        match="requires unknown actions",
    ):
        load_investigation_pack(path)


def test_rejects_cyclic_action_dependencies(
    tmp_path: Path,
) -> None:
    payload = _fixture_payload()
    actions = {action["id"]: action for action in payload["actions"]}
    actions["inspect_optical_record"]["prerequisites"]["required_completed_action_ids"] = [
        "inspect_radio_return"
    ]
    actions["inspect_radio_return"]["prerequisites"]["required_completed_action_ids"] = [
        "inspect_optical_record"
    ]

    path = _write_pack(tmp_path, payload)

    with pytest.raises(
        V2InvestigationContentError,
        match="cyclic action dependency",
    ):
        load_investigation_pack(path)


def test_rejects_action_when_required_role_is_missing(
    pack: V2InvestigationPack,
) -> None:
    state = initialize_investigation(pack, ["player_a"])

    result = perform_action(
        pack,
        state,
        player_id="player_a",
        action_id="request_weather_record",
    )

    assert result.accepted is False
    assert result.code == "required_role_missing"
    assert result.state is state
    assert state.revision == 0


def test_action_unlocks_evidence_after_prerequisites(
    pack: V2InvestigationPack,
) -> None:
    state = initialize_investigation(pack, ["player_a"])

    examined = examine_evidence(
        pack,
        state,
        player_id="player_a",
        evidence_id="radio_return",
    )
    inspected = perform_action(
        pack,
        examined.state,
        player_id="player_a",
        action_id="inspect_radio_return",
    )
    assigned = assign_role(
        pack,
        inspected.state,
        player_id="player_a",
        role_id="instrument_operator",
    )
    calibrated = perform_action(
        pack,
        assigned.state,
        player_id="player_a",
        action_id="calibrate_receiver",
    )

    assert calibrated.accepted is True
    assert calibrated.code == "action_completed"
    assert "receiver_diagnostic" in calibrated.state.available_evidence_ids
    assert "calibrate_receiver" in calibrated.state.completed_action_ids
    assert state.available_evidence_ids == {
        "optical_record",
        "radio_return",
    }


def test_rejects_action_when_examined_evidence_is_missing(
    pack: V2InvestigationPack,
) -> None:
    state = initialize_investigation(pack, ["player_a"])

    result = perform_action(
        pack,
        state,
        player_id="player_a",
        action_id="inspect_optical_record",
    )

    assert result.accepted is False
    assert result.code == "required_evidence_missing"
    assert result.state is state


def test_actions_record_contradiction_explanation_and_gap(
    pack: V2InvestigationPack,
) -> None:
    state = initialize_investigation(pack, ["player_a"])

    for evidence_id in ("optical_record", "radio_return"):
        state = examine_evidence(
            pack,
            state,
            player_id="player_a",
            evidence_id=evidence_id,
        ).state

    for action_id in (
        "inspect_optical_record",
        "inspect_radio_return",
        "compare_optical_radio_timing",
    ):
        state = perform_action(
            pack,
            state,
            player_id="player_a",
            action_id=action_id,
        ).state

    assert state.preserved_contradiction_ids == {"optical_radio_timing_offset"}

    state = assign_role(
        pack,
        state,
        player_id="player_a",
        role_id="protocol_auditor",
    ).state
    state = perform_action(
        pack,
        state,
        player_id="player_a",
        action_id="request_weather_record",
    ).state
    state = release_role(
        state,
        player_id="player_a",
    ).state
    state = examine_evidence(
        pack,
        state,
        player_id="player_a",
        evidence_id="weather_record",
    ).state
    state = perform_action(
        pack,
        state,
        player_id="player_a",
        action_id="test_atmospheric_propagation",
    ).state
    state = perform_action(
        pack,
        state,
        player_id="player_a",
        action_id="document_upper_atmosphere_gap",
    ).state

    assert state.tested_ordinary_explanation_ids == {"atmospheric_propagation"}
    assert state.documented_information_gap_ids == {"upper_atmosphere_conditions"}


def test_rejects_repeating_nonrepeatable_action(
    pack: V2InvestigationPack,
) -> None:
    state = initialize_investigation(pack, ["player_a"])
    state = examine_evidence(
        pack,
        state,
        player_id="player_a",
        evidence_id="optical_record",
    ).state
    completed = perform_action(
        pack,
        state,
        player_id="player_a",
        action_id="inspect_optical_record",
    )

    repeated = perform_action(
        pack,
        completed.state,
        player_id="player_a",
        action_id="inspect_optical_record",
    )

    assert repeated.accepted is False
    assert repeated.code == "action_already_completed"
    assert repeated.state is completed.state
