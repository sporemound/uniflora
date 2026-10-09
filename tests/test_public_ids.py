from uniflora.engine.public_ids import resolve_trigger_id, semantic_trigger_aliases


def test_legacy_trigger_ids_receive_readable_aliases_and_remain_resolvable() -> None:
    reactions = [
        {
            "trigger_id": "t-0f3291b5d50b",
            "kind": "inspect_capacity",
            "observation_id": "northern_usable_capacity",
        },
        {
            "trigger_id": "t-cf2d2d01e3c8",
            "kind": "test_route",
            "pathway_id": "damaged_circulation",
        },
    ]
    observation_entities = {"northern_usable_capacity": "northern_reservoir"}

    aliases = semantic_trigger_aliases(reactions, observation_entities)

    assert aliases == {
        "t-0f3291b5d50b": "inspect-capacity-northern-reservoir",
        "t-cf2d2d01e3c8": "test-route-damaged-circulation",
    }
    assert (
        resolve_trigger_id("inspect-capacity-northern-reservoir", reactions, observation_entities)
        == "t-0f3291b5d50b"
    )
    assert resolve_trigger_id("t-cf2d2d01e3c8", reactions, observation_entities) == "t-cf2d2d01e3c8"


def test_repeated_legacy_trigger_aliases_get_simple_numeric_suffixes() -> None:
    reactions = [
        {"trigger_id": "t-111111111111", "kind": "test_route", "pathway_id": "route_07"},
        {"trigger_id": "t-222222222222", "kind": "test_route", "pathway_id": "route_07"},
    ]

    aliases = semantic_trigger_aliases(reactions, {})

    assert list(aliases.values()) == ["test-route-07", "test-route-07-2"]
