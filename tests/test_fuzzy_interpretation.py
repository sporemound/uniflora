from __future__ import annotations

from hypothesis import given, strategies as st

from uniflora.engine.actions import ConnectAction, ObserveAction
from uniflora.interpretation import (
    _normalize_fuzzy_text,
    _resolve_fuzzy_entity,
    infer_deterministic_observe,
    infer_deterministic_question,
)


class FakeDefinition:
    allowed_actions = ("observe", "connect")

    def entity_aliases(self) -> dict[str, str]:
        return {
            "circulation ledger": "circulation_ledger",
            "sent ledger": "circulation_ledger",
            "nursery intake sensor": "nursery_intake_sensor",
            "intake sensor": "nursery_intake_sensor",
            "southwest": "southwest_route",
            "upper branch": "upper_branch",
            "lower branch": "lower_branch",
        }


def definition() -> FakeDefinition:
    return FakeDefinition()


def test_typo_resolves_to_public_entity() -> None:
    action = infer_deterministic_observe(
        "inspect the circulaton ledger",
        definition(),  # type: ignore[arg-type]
    )

    assert isinstance(action, ObserveAction)
    assert action.entity_id == "circulation_ledger"


def test_observe_synonym_resolves() -> None:
    action = infer_deterministic_observe(
        "check the nursery intke sensor",
        definition(),  # type: ignore[arg-type]
    )

    assert isinstance(action, ObserveAction)
    assert action.entity_id == "nursery_intake_sensor"

def test_observation_is_not_classified_as_relationship_question() -> None:
    action = infer_deterministic_question(
        "inspect the northern reservoir",
        definition(),  # type: ignore[arg-type]
    )

    assert action is None

@given(separator=st.sampled_from(["", " ", "-", "_", "  "]))
def test_compound_direction_variants_resolve(separator: str) -> None:
    action = infer_deterministic_observe(
        f"observe south{separator}west",
        definition(),  # type: ignore[arg-type]
    )

    assert isinstance(action, ObserveAction)
    assert action.entity_id == "southwest_route"


def test_ambiguous_short_target_is_not_guessed() -> None:
    entity_id = _resolve_fuzzy_entity(
        "branch",
        definition(),  # type: ignore[arg-type]
    )

    assert entity_id is None


def test_existing_relationship_question_still_works() -> None:
    action = infer_deterministic_question(
        "is the circulation ledger connected to the nursery intake sensor?",
        definition(),  # type: ignore[arg-type]
    )

    assert isinstance(action, ConnectAction)
    assert action.source_entity_id == "circulation_ledger"
    assert action.target_entity_id == "nursery_intake_sensor"


@given(value=st.text(max_size=200))
def test_normalization_is_idempotent(value: str) -> None:
    once = _normalize_fuzzy_text(value)
    twice = _normalize_fuzzy_text(once)

    assert twice == once


@given(value=st.text(max_size=200))
def test_resolver_never_crashes_on_arbitrary_unicode(value: str) -> None:
    result = _resolve_fuzzy_entity(
        value,
        definition(),  # type: ignore[arg-type]
    )

    assert result is None or result in {
        "circulation_ledger",
        "nursery_intake_sensor",
        "southwest_route",
        "upper_branch",
        "lower_branch",
    }