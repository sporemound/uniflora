from __future__ import annotations

import copy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from uniflora.content.loader import PuzzleRegistry
from uniflora.engine.actions import (
    AddProposalKickerAction,
    BeginStackAction,
    CandidateAction,
    ClassifyContradictionAction,
    CompareRecordsAction,
    ConfirmReconstructionAction,
    ObserveAction,
    ProposeTranslationAction,
    ReactToStackAction,
    RelayRecordAction,
    ResolveStackAction,
    UseTriggeredReactionAction,
)
from uniflora.engine.core import DeterministicEngine
from uniflora.engine.position_two import PositionTwoValidator
from uniflora.engine.position_zero import EnvironmentPositionValidator
from uniflora.engine.validation import ValidationContext, ValidationDecision
from uniflora.game_service import GameService
from uniflora.narration import FallbackNarrator
from uniflora.runtime import Environment, RoutingSnapshot
from uniflora.storage.database import Database
from uniflora.storage.repository import GameRepository, MutationPlan


def prior_circulation_state() -> dict[str, Any]:
    return {
        "resources": {"pale_nursery": {"water": 11.0}},
        "counters": {"strain": {}, "repair": {}, "coherence": 0, "instability": 0},
        "persistent_effects": ["adaptive_circulation_protocol"],
        "triggered_reactions": [],
        "world_flags": {"adaptive_circulation_protocol": True},
        "confirmed_facts": [{"public_text": "Circulation was confirmed."}],
        "proposals": {
            "c-prior": {
                "kind": "circulation",
                "status": "confirmed",
                "source_amount": 9.0,
                "delivered_amount": 9.0,
            }
        },
    }


@dataclass
class TranslationRun:
    validator: PositionTwoValidator
    state: dict[str, Any]
    serial: int = 0

    def act(self, participant: str, action: CandidateAction) -> ValidationDecision:
        self.serial += 1
        decision = self.validator.validate(
            action,
            ValidationContext(
                environment=Environment.TEST,
                session_id="translation-test",
                participant_id=participant,
                action_id=f"translation:{self.serial}",
                current_position=2,
                response_profile="conditional_memory",
                state=self.state,
            ),
        )
        if decision.accepted and decision.next_state is not None:
            self.state = decision.next_state
        return decision


def build_run() -> TranslationRun:
    validator = PositionTwoValidator(PuzzleRegistry.load_packaged().get(2))
    return TranslationRun(validator, validator.initialize_from_previous(prior_circulation_state()))


def establish_public_translation(run: TranslationRun) -> None:
    observations = (
        ("reader-a", "ledger"),
        ("reader-b", "intake"),
        ("reader-c", "survey"),
        ("terminologist", "glossary"),
        ("auditor", "provenance"),
        ("archivist", "margin"),
    )
    for participant, entity in observations:
        assert run.act(participant, ObserveAction(action="observe", entity_id=entity)).accepted
    assert run.act(
        "comparator",
        CompareRecordsAction(action="compare_records", record_a="ledger", record_b="intake"),
    ).accepted
    assert run.act(
        "comparator",
        CompareRecordsAction(action="compare_records", record_a="intake", record_b="survey"),
    ).accepted
    assert run.act(
        "classifier",
        ClassifyContradictionAction(
            action="classify_contradiction",
            record_a="intake",
            record_b="survey",
            classification="different_stages",
        ),
    ).accepted
    assert run.act(
        "relay",
        RelayRecordAction(
            action="relay_record", record_id="ledger", summary="Ledger records sent 9."
        ),
    ).accepted


def valid_proposal() -> ProposeTranslationAction:
    return ProposeTranslationAction(
        action="propose_translation",
        record_a="ledger",
        record_b="intake",
        record_c="survey",
        classification="different_stages",
        mapping=(
            "sent means source departure; delivered means boundary arrival; retained means the "
            "later remainder"
        ),
        shared_summary="sent 9; delivered 9; retained 8 after one use interval",
        preserved_difference="preserve the minority difference between delivery and retention",
    )


def test_translation_initialization_derives_records_without_erasing_inherited_state() -> None:
    run = build_run()
    assert run.state["content_key"] == "translation"
    assert run.state["record_values"] == {
        "circulation_ledger": 9.0,
        "nursery_intake_sensor": 9.0,
        "nursery_retention_survey": 8.0,
    }
    assert run.state["resources"]["pale_nursery"]["water"] == 11.0
    assert "adaptive_circulation_protocol" in run.state["persistent_effects"]
    assert run.state["contributions"] == []


def test_translation_content_upgrade_preserves_public_progress() -> None:
    run = build_run()
    assert run.act("reader", ObserveAction(action="observe", entity_id="ledger")).accepted
    before = copy.deepcopy(run.state)
    before["content_version"] = "0.3.0"

    upgraded = run.validator.upgrade_existing_state(before)

    assert upgraded["content_version"] == "2.1.1"
    assert upgraded["unlocked_observations"] == before["unlocked_observations"]
    assert upgraded["confirmed_facts"] == before["confirmed_facts"]
    assert upgraded["contributions"] == before["contributions"]
    assert upgraded["record_values"] == before["record_values"]


def test_translation_cues_gate_the_unresolved_upper_branch() -> None:
    run = build_run()

    observed = run.act(
        "reader",
        ObserveAction(action="observe", entity_id="Nursery Intake Sieve — DELIVERED"),
    )
    assert observed.accepted
    assert "intake_delivered_measurement" in run.state["unlocked_observations"]

    early = run.act(
        "reader",
        ObserveAction(
            action="observe",
            entity_id="Metered upper branch — destination not recorded",
        ),
    )
    assert not early.accepted

    for participant, cue in (
        ("reader-a", "Circulation Ledger — SENT"),
        ("reader-c", "Nursery Retention Survey — RETAINED LATER"),
        ("terminologist", "CONCORDANCE, NOT CORRECTION inset"),
        ("auditor", "Three equal record seals"),
        ("archivist", "Later-retention margin note"),
    ):
        assert run.act(
            participant,
            ObserveAction(action="observe", entity_id=cue),
        ).accepted

    discovered = run.act(
        "production-reader",
        ObserveAction(
            action="observe",
            entity_id="Metered upper branch — destination not recorded",
        ),
    )
    assert discovered.accepted
    assert "provision_works_named" in run.state["unlocked_observations"]


def test_triggered_provenance_reaction_requires_another_participant() -> None:
    run = build_run()
    assert run.act("reader", ObserveAction(action="observe", entity_id="ledger")).accepted
    trigger_id = next(
        item["trigger_id"]
        for item in run.state["triggered_reactions"]
        if item["kind"] == "inspect_provenance"
    )
    assert trigger_id == "inspect-provenance-index"
    rejected = run.act(
        "reader", UseTriggeredReactionAction(action="use_triggered_reaction", trigger_id=trigger_id)
    )
    assert not rejected.accepted
    resolved = run.act(
        "auditor",
        UseTriggeredReactionAction(action="use_triggered_reaction", trigger_id=trigger_id),
    )
    assert resolved.accepted
    assert "records_have_distinct_provenance" in run.state["unlocked_observations"]


def test_translation_rejects_false_consensus_then_completes_with_preserved_difference() -> None:
    run = build_run()
    establish_public_translation(run)
    invalid = valid_proposal().model_copy(update={"classification": "terminology"})
    rejected = run.act("editor", invalid)
    assert not rejected.accepted
    assert "different_stages" in rejected.public_data["feedback"]

    proposed = run.act("editor", valid_proposal())
    assert proposed.accepted
    proposal_id = str(proposed.public_data["proposal_id"])
    assert proposal_id == "translation-stage-concordance"
    self_confirmation = run.act(
        "editor",
        ConfirmReconstructionAction(action="confirm_reconstruction", proposal_id=proposal_id),
    )
    assert not self_confirmation.accepted

    assert run.act(
        "auditor",
        AddProposalKickerAction(
            action="add_proposal_kicker",
            proposal_id=proposal_id,
            kicker="cite_provenance",
            detail="cite all three instruments",
        ),
    ).accepted
    completed = run.act(
        "reader-a",
        ConfirmReconstructionAction(action="confirm_reconstruction", proposal_id=proposal_id),
    )
    assert completed.accepted and completed.position_completed
    assert completed.next_position == 3
    assert run.state["counters"]["coherence"] == 2
    assert "translation_concordance" in run.state["persistent_effects"]
    assert run.state["world_flags"]["plural_records_preserved"] is True


def test_repeated_translation_proposals_use_readable_numeric_suffixes() -> None:
    run = build_run()
    establish_public_translation(run)

    first = run.act("editor", valid_proposal())
    second = run.act("editor", valid_proposal())

    assert first.accepted and second.accepted
    assert list(run.state["proposals"]) == [
        "translation-stage-concordance",
        "translation-stage-concordance-2",
    ]


def test_translation_stack_is_shallow_and_resolves_last_in_first_out() -> None:
    run = build_run()
    establish_public_translation(run)
    opened = run.act(
        "editor", BeginStackAction(action="begin_stack", proposal=valid_proposal().model_dump())
    )
    assert opened.accepted
    stack_id = run.state["public_stack"]["stack_id"]
    assert run.act(
        "auditor",
        ReactToStackAction(
            action="react_to_stack",
            stack_id=stack_id,
            reaction="request_provenance",
            detail="retain instrument signatures",
        ),
    ).accepted
    assert run.act(
        "archivist",
        ReactToStackAction(
            action="react_to_stack",
            stack_id=stack_id,
            reaction="preserve_difference",
            detail="retain the minority note",
        ),
    ).accepted
    resolved = run.act("resolver", ResolveStackAction(action="resolve_stack", stack_id=stack_id))
    assert resolved.accepted
    assert (
        "preserve the difference -> request provenance -> attempt translation"
        in resolved.public_data["public_text"]
    )
    assert run.state["public_stack"]["status"] == "resolved"


@pytest.mark.asyncio
async def test_startup_upgrades_legacy_position_two_state_once(tmp_path: Path) -> None:
    database = Database(f"sqlite+aiosqlite:///{(tmp_path / 'upgrade.db').as_posix()}")
    await database.create_schema_for_tests()
    repository = GameRepository(database)
    _, refs = await repository.bootstrap(RoutingSnapshot(1, 10, 20, 30, frozenset({99})))
    registry = PuzzleRegistry.load_packaged()
    validator = EnvironmentPositionValidator(registry, enforce_cycles=False)
    game = GameService(
        repository,
        refs,
        registry,
        DeterministicEngine(repository, validator),
        FallbackNarrator(),
        validator,
    )
    await game.initialize()
    ref = refs[Environment.TEST]

    def planner(state: dict[str, object]) -> MutationPlan:
        after = dict(state)
        after["current_position"] = 2
        after["response_profile"] = "conditional_memory"
        after["data"] = prior_circulation_state()
        return MutationPlan(event_type="test.legacy_position_two", state_after=after, payload={})

    await repository.mutate(
        ref,
        actor_id="test:legacy",
        idempotency_key="legacy-position-two",
        planner=planner,
    )
    await game.initialize()
    upgraded = await repository.state(ref)
    assert upgraded["current_position"] == 2
    assert upgraded["data"]["content_key"] == "translation"
    assert upgraded["data"]["record_values"]["nursery_retention_survey"] == 8

    await game.initialize()
    assert await repository.state(ref) == upgraded
    await database.dispose()
