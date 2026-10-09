from __future__ import annotations

from pathlib import Path

import pytest

from uniflora.content.v2 import (
    V2InvestigationPack,
    load_investigation_pack,
)
from uniflora.engine.v2 import (
    assign_role,
    examine_evidence,
    initialize_investigation,
    move_player,
    release_role,
)

FIXTURE_PATH = (
    Path(__file__).parent / "fixtures" / "v2" / "boundary_array_investigation" / "pack.yaml"
)


@pytest.fixture
def pack() -> V2InvestigationPack:
    return load_investigation_pack(FIXTURE_PATH)


def test_initializes_investigation_state(
    pack: V2InvestigationPack,
) -> None:
    state = initialize_investigation(
        pack,
        ["player_a", "player_b"],
    )

    assert state.pack_id == "boundary_array_synthetic"
    assert state.current_position_id == "boundary_event"
    assert state.available_location_ids == {"boundary_array"}
    assert state.available_evidence_ids == {
        "optical_record",
        "radio_return",
    }
    assert state.examined_evidence_ids == set()
    assert state.revision == 0

    assert tuple(player.player_id for player in state.players) == (
        "player_a",
        "player_b",
    )

    assert all(player.current_location_id == "boundary_array" for player in state.players)

    assert all(player.active_role_id is None for player in state.players)


def test_rejects_duplicate_player_ids(
    pack: V2InvestigationPack,
) -> None:
    with pytest.raises(
        ValueError,
        match="player IDs must be unique",
    ):
        initialize_investigation(
            pack,
            ["player_a", "player_a"],
        )


def test_assigns_role_without_mutating_original_state(
    pack: V2InvestigationPack,
) -> None:
    original = initialize_investigation(
        pack,
        ["player_a", "player_b"],
    )

    result = assign_role(
        pack,
        original,
        player_id="player_a",
        role_id="instrument_operator",
    )

    assert result.accepted is True
    assert result.code == "role_assigned"
    assert result.state is not original
    assert result.state.revision == 1

    assert original.get_player("player_a") is not None
    assert original.get_player("player_a").active_role_id is None

    updated_player = result.state.get_player("player_a")

    assert updated_player is not None
    assert updated_player.active_role_id == "instrument_operator"


def test_rejected_action_preserves_same_state_object(
    pack: V2InvestigationPack,
) -> None:
    state = initialize_investigation(
        pack,
        ["player_a"],
    )

    result = assign_role(
        pack,
        state,
        player_id="player_a",
        role_id="missing_role",
    )

    assert result.accepted is False
    assert result.code == "unknown_role"
    assert result.state is state
    assert state.revision == 0


def test_releases_temporary_role(
    pack: V2InvestigationPack,
) -> None:
    state = initialize_investigation(
        pack,
        ["player_a"],
    )

    assigned = assign_role(
        pack,
        state,
        player_id="player_a",
        role_id="protocol_auditor",
    )

    released = release_role(
        assigned.state,
        player_id="player_a",
    )

    assert released.accepted is True
    assert released.code == "role_released"
    assert released.state.revision == 2

    player = released.state.get_player("player_a")

    assert player is not None
    assert player.active_role_id is None


def test_rejects_movement_to_unknown_location(
    pack: V2InvestigationPack,
) -> None:
    state = initialize_investigation(
        pack,
        ["player_a"],
    )

    result = move_player(
        pack,
        state,
        player_id="player_a",
        location_id="missing_location",
    )

    assert result.accepted is False
    assert result.code == "unknown_location"
    assert result.state is state


def test_examines_available_evidence_once(
    pack: V2InvestigationPack,
) -> None:
    state = initialize_investigation(
        pack,
        ["player_a"],
    )

    first = examine_evidence(
        pack,
        state,
        player_id="player_a",
        evidence_id="optical_record",
    )

    assert first.accepted is True
    assert first.code == "evidence_examined"
    assert first.state.examined_evidence_ids == {
        "optical_record",
    }
    assert first.state.revision == 1
    assert state.examined_evidence_ids == set()

    second = examine_evidence(
        pack,
        first.state,
        player_id="player_a",
        evidence_id="optical_record",
    )

    assert second.accepted is True
    assert second.code == "evidence_reopened"
    assert second.state is first.state
    assert second.state.revision == first.state.revision


def test_rejects_unavailable_evidence(
    pack: V2InvestigationPack,
) -> None:
    state = initialize_investigation(
        pack,
        ["player_a"],
    )

    result = examine_evidence(
        pack,
        state,
        player_id="player_a",
        evidence_id="weather_record",
    )

    assert result.accepted is False
    assert result.code == "evidence_unavailable"
    assert result.state is state
