from pathlib import Path

import pytest

from uniflora.content.v2 import (
    V2PlayerRoleError,
    assignment_satisfies_required_role,
    available_player_role_templates,
    create_player_role_assignment,
    load_investigation_pack,
)


PACK_PATH = (
    Path(__file__).parents[1]
    / "src"
    / "uniflora"
    / "content"
    / "v2"
    / "packs"
    / "missing_interior"
    / "pack.yaml"
)


def test_all_missing_interior_roles_allow_player_labels() -> None:
    pack = load_investigation_pack(PACK_PATH)
    assert len(pack.roles) == 38
    assert len(available_player_role_templates(pack)) == 38


def test_custom_label_maps_to_canonical_role() -> None:
    pack = load_investigation_pack(PACK_PATH)
    assignment = create_player_role_assignment(
        pack,
        identity="test:investigator-a",
        canonical_role_id="signal_correlator",
        display_name="Night Radio Listener",
        description="Compares radio and optical timing.",
        position_id="boundary_event",
        current_location_id="boundary_array",
    )

    assert assignment.display_name == "Night Radio Listener"
    assert assignment_satisfies_required_role(assignment, "signal_correlator")
    assert not assignment_satisfies_required_role(assignment, "field_observer")


def test_mentions_are_rejected() -> None:
    pack = load_investigation_pack(PACK_PATH)
    with pytest.raises(V2PlayerRoleError):
        create_player_role_assignment(
            pack,
            identity="test:investigator-a",
            canonical_role_id="field_observer",
            display_name="@everyone observer",
            current_location_id="boundary_array",
        )


def test_role_location_is_enforced() -> None:
    pack = load_investigation_pack(PACK_PATH)
    with pytest.raises(V2PlayerRoleError):
        create_player_role_assignment(
            pack,
            identity="test:investigator-a",
            canonical_role_id="signal_correlator",
            display_name="Signal Listener",
            current_location_id="quantum_state_institute",
        )
