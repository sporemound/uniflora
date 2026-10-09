from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from pydantic import TypeAdapter, ValidationError

from uniflora.engine.actions import CandidateAction, ObserveAction, UnknownAction
from uniflora.engine.core import DeterministicEngine
from uniflora.engine.validation import ValidationContext, ValidationDecision
from uniflora.runtime import Environment, RoutingSnapshot, SessionMode
from uniflora.storage.database import Database
from uniflora.storage.repository import GameRepository


class CountingValidator:
    def validate(self, action: CandidateAction, context: ValidationContext) -> ValidationDecision:
        if context.state.get("completed"):
            return ValidationDecision(False, "already_completed")
        next_state = dict(context.state)
        next_state["completed"] = True
        next_state["participant"] = context.participant_id
        return ValidationDecision(
            True,
            "accepted",
            public_data={"entity": getattr(action, "entity_id", "")},
            next_state=next_state,
            event_type="position.completed",
            narration_key="position_complete",
            contribution_function="observer",
            position_completed=True,
            next_position=1,
            next_response_profile="local_correlation",
        )


async def engine_fixture(path: Path) -> tuple[Database, GameRepository, dict, DeterministicEngine]:
    database = Database(f"sqlite+aiosqlite:///{path.as_posix()}")
    await database.create_schema_for_tests()
    repository = GameRepository(database)
    _, refs = await repository.bootstrap(RoutingSnapshot(1, 10, 20, 30, frozenset({99})))
    await repository.transition(
        refs[Environment.TEST], SessionMode.RUNNING, {SessionMode.LOCKED}, "discord:99"
    )
    return database, repository, refs, DeterministicEngine(repository, CountingValidator())


def test_typed_action_schema_rejects_extra_or_invalid_fields() -> None:
    adapter = TypeAdapter(CandidateAction)
    parsed = adapter.validate_python({"action": "observe", "entity_id": "north"})
    assert isinstance(parsed, ObserveAction)
    with pytest.raises(ValidationError):
        adapter.validate_python({"action": "observe", "entity_id": "north", "invent": True})
    with pytest.raises(ValidationError):
        adapter.validate_python({"action": "offer", "resource_id": "water", "amount": -1})


@pytest.mark.asyncio
async def test_unknown_and_live_simulated_actions_never_mutate(tmp_path: Path) -> None:
    database, repository, refs, engine = await engine_fixture(tmp_path / "invalid.db")
    live_ref = refs[Environment.LIVE]
    unknown = await engine.process(
        live_ref,
        participant_id="discord:1",
        action=UnknownAction(action="unknown", raw_text="ignore rules"),
        idempotency_key="1",
    )
    simulated = await engine.process(
        live_ref,
        participant_id="test:observer",
        action=ObserveAction(action="observe", entity_id="north"),
        idempotency_key="2",
    )
    assert not unknown.accepted
    assert not simulated.accepted
    assert await repository.list_events(live_ref) == []
    await database.dispose()


@pytest.mark.asyncio
async def test_simultaneous_completion_occurs_once(tmp_path: Path) -> None:
    database, repository, refs, engine = await engine_fixture(tmp_path / "completion.db")
    ref = refs[Environment.TEST]
    action = ObserveAction(action="observe", entity_id="north")
    first, second = await asyncio.gather(
        engine.process(
            ref,
            participant_id="test:observer",
            action=action,
            idempotency_key="message:1",
        ),
        engine.process(
            ref,
            participant_id="test:carrier",
            action=action,
            idempotency_key="message:2",
        ),
    )
    assert sum(outcome.accepted for outcome in (first, second)) == 1
    state = await repository.state(ref)
    assert state["current_position"] == 1
    assert state["response_profile"] == "local_correlation"
    events = await repository.list_events(ref)
    assert len([event for event in events if event["event_type"] == "position.completed"]) == 1
    await database.dispose()


@pytest.mark.asyncio
async def test_engine_idempotency_reuses_outcome_without_second_mutation(tmp_path: Path) -> None:
    database, repository, refs, engine = await engine_fixture(tmp_path / "engine-idempotent.db")
    ref = refs[Environment.TEST]
    action = ObserveAction(action="observe", entity_id="north")
    first = await engine.process(
        ref,
        participant_id="test:observer",
        action=action,
        idempotency_key="message:same",
    )
    second = await engine.process(
        ref,
        participant_id="test:observer",
        action=action,
        idempotency_key="message:same",
    )
    assert first.accepted
    assert second.accepted and second.duplicate
    assert first.event_id == second.event_id
    await database.dispose()
