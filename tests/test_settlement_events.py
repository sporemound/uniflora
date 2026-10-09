from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from uniflora.content.loader import PuzzleRegistry
from uniflora.engine.actions import (
    ConfirmReconstructionAction,
    ConnectAction,
    ObserveAction,
    ProposeReconstructionAction,
    RelayAction,
)
from uniflora.engine.core import DeterministicEngine
from uniflora.engine.position_zero import EnvironmentPositionValidator
from uniflora.engine.settlement_events import apply_settlement_event
from uniflora.engine.validation import ValidationContext, ValidationDecision
from uniflora.game_service import GameService
from uniflora.narration import FallbackNarrator
from uniflora.runtime import Environment, RoutingSnapshot, SessionMode
from uniflora.storage.database import Database
from uniflora.storage.repository import GameRepository, MutationPlan


def _context(state: dict[str, object], action_id: str) -> ValidationContext:
    return ValidationContext(
        environment=Environment.LIVE,
        session_id="live-session",
        participant_id="discord:101",
        action_id=action_id,
        current_position=1,
        response_profile="local_correlation",
        state=state,
    )


def _accepted(state: dict[str, object]) -> ValidationDecision:
    return ValidationDecision(
        True,
        "accepted",
        public_data={"public_text": "Relay accepted."},
        next_state=state,
        event_type="relay.recorded",
    )


def _relay() -> RelayAction:
    return RelayAction(
        action="relay",
        source_entity_id="condensation_veil",
        via_entity_id="central_relay",
        target_entity_id="pale_nursery",
        resource_id="water",
        amount=1,
    )


def test_action_triggered_event_is_stable_and_guaranteed_by_threshold() -> None:
    state = PuzzleRegistry.load_packaged().get(1).initial_state()
    state["settlement_event_trigger_after"] = 1
    now = datetime(2026, 7, 18, 12, tzinfo=UTC)
    first = apply_settlement_event(
        _relay(), _context(state, "action:stable"), _accepted(state), now=now
    )
    repeated = apply_settlement_event(
        _relay(), _context(state, "action:stable"), _accepted(state), now=now
    )

    assert first.next_state is not None
    assert repeated.next_state is not None
    event = first.next_state["settlement_event"]
    assert event["status"] == "active"
    assert event["expires_at"] == (now + timedelta(minutes=120)).isoformat()
    assert event["event_id"] == repeated.next_state["settlement_event"]["event_id"]
    assert set(event["choices"]) == {"brace", "divert", "release"}
    assert all(
        event["choices"][method]["label"] in first.public_data["public_text"]
        for method in ("brace", "divert", "release")
    )
    assert "WHOLE SETTLEMENT UPDATE" in first.public_data["public_text"]
    assert "/interior intervene" in first.public_data["public_text"]


def test_other_actions_do_not_shorten_active_event_clock() -> None:
    state = PuzzleRegistry.load_packaged().get(1).initial_state()
    state["settlement_event"] = {
        "event_id": "se-test",
        "status": "active",
        "title": "The route moves",
        "consequence": "The route moves again.",
        "expires_at": "2026-07-18T14:00:00+00:00",
    }
    state["settlement_escalation"] = 2

    waiting = apply_settlement_event(_relay(), _context(state, "action:one"), _accepted(state))
    assert waiting.next_state is not None
    assert waiting.next_state["settlement_event"] == state["settlement_event"]
    assert waiting.next_state["settlement_escalation"] == 2


async def _live_position_one(tmp_path: Path) -> tuple[Database, GameService, GameRepository]:
    database = Database(f"sqlite+aiosqlite:///{(tmp_path / 'events.db').as_posix()}")
    await database.create_schema_for_tests()
    repository = GameRepository(database)
    _, refs = await repository.bootstrap(
        RoutingSnapshot(1, 10, 20, 30, frozenset({99}))
    )
    registry = PuzzleRegistry.load_packaged()
    validator = EnvironmentPositionValidator(
        registry, enforce_cycles=False, settlement_events=True
    )
    engine = DeterministicEngine(repository, validator)
    game = GameService(repository, refs, registry, engine, FallbackNarrator(), validator)
    await game.initialize()
    await repository.transition(
        refs[Environment.LIVE], SessionMode.RUNNING, {SessionMode.LOCKED}, "discord:99"
    )

    async def act(user_id: int, action: object, serial: int) -> None:
        result = await game.act(
            Environment.LIVE,
            user_id,
            action,  # type: ignore[arg-type]
            f"setup:{serial}",
        )
        assert result.accepted

    await act(101, ObserveAction(action="observe", entity_id="north"), 1)
    await act(102, ObserveAction(action="observe", entity_id="east"), 2)
    await act(103, ObserveAction(action="observe", entity_id="path"), 3)
    await act(
        103,
        ConnectAction(action="connect", source_entity_id="north", target_entity_id="east"),
        4,
    )
    await act(
        101,
        ProposeReconstructionAction(
            action="propose_reconstruction",
            proposal={
                "donor_id": "north",
                "recipient_id": "east",
                "resource_id": "water",
                "amount": 5,
                "pathway_id": "path",
                "pathway_action": "repair",
                "maintenance_condition": "monitor",
            },
        ),
        5,
    )
    state = await repository.state(refs[Environment.LIVE])
    proposal_id = next(iter(state["data"]["proposals"]))
    await act(
        102,
        ConfirmReconstructionAction(
            action="confirm_reconstruction", proposal_id=proposal_id
        ),
        6,
    )
    assert (await repository.state(refs[Environment.LIVE]))["current_position"] == 1
    return database, game, repository

@pytest.mark.asyncio
async def test_game_act_opens_settlement_event_at_threshold(tmp_path: Path) -> None:
    database, game, repository = await _live_position_one(tmp_path)
    ref = game.refs[Environment.LIVE]

    def lower_threshold(state: dict[str, object]) -> MutationPlan:
        after = dict(state)
        data = dict(after["data"])

        sustained_targets = list(data.get("sustained_targets", []))
        if "condensation_veil" not in sustained_targets:
            sustained_targets.append("condensation_veil")
        data["sustained_targets"] = sustained_targets

        sustains = list(data.get("sustains", []))
        sustains.append(
            {
                "target": "condensation_veil",
                "condition": "maintain",
                "participant_id": "test:threshold-fixture",
            }
        )
        data["sustains"] = sustains

        data["settlement_event_actions_since_last"] = 0
        data["settlement_event_trigger_after"] = 1
        data["settlement_event"] = None
        after["data"] = data
        return MutationPlan(
            event_type="test.lower_event_threshold",
            state_after=after,
            payload={},
        )

    await repository.mutate(
        ref,
        actor_id="test",
        idempotency_key="threshold:1",
        planner=lower_threshold,
    )

    result = await game.act(
        Environment.LIVE,
        104,
        RelayAction(
            action="relay",
            source_entity_id="condensation_veil",
            via_entity_id="central_relay",
            target_entity_id="pale_nursery",
            resource_id="water",
            amount=1,
        ),
        "trigger-through-service:1",
    )

    assert result.accepted

    state = await repository.state(ref)
    event = state["data"].get("settlement_event")

    assert event is not None
    assert event["status"] == "active"

    await database.dispose()

@pytest.mark.asyncio
async def test_first_myctroph_stabilizes_and_a_different_one_shapes_the_scar(
    tmp_path: Path,
) -> None:
    database, game, repository = await _live_position_one(tmp_path)
    ref = game.refs[Environment.LIVE]

    def open_event(state: dict[str, object]) -> MutationPlan:
        after = dict(state)
        data = dict(after["data"])  # type: ignore[arg-type]
        data["settlement_event"] = {
            "event_id": "se-live",
            "status": "active",
            "title": "Central Relay reverses",
            "consequence": "Pressure reaches another district.",
            "expires_at": "2026-07-18T14:00:00+00:00",
        }
        after["data"] = data
        return MutationPlan(event_type="test.event_opened", state_after=after, payload={})

    await repository.mutate(
        ref, actor_id="test", idempotency_key="open:1", planner=open_event
    )
    first = await game.intervene_settlement_event(
        Environment.LIVE, 101, "@riverglass", "brace", "intervene:1"
    )
    state = await repository.state(ref)
    assert first.accepted
    assert "RIVERGLASS" in first.text
    assert "@" not in first.text
    assert "Catastrophe is prevented" in first.text
    assert state["data"]["settlement_strain"] == 0
    assert state["data"]["settlement_event"]["status"] == "stabilized"

    repeated = await game.intervene_settlement_event(
        Environment.LIVE, 101, "riverglass", "divert", "intervene:2"
    )
    supported = await game.intervene_settlement_event(
        Environment.LIVE, 102, "mosslight", "brace", "intervene:3"
    )
    state = await repository.state(ref)
    assert not repeated.accepted
    assert "different Mycotroph" in repeated.text
    assert supported.accepted
    assert "SCAR SOFTENED" in supported.text
    assert state["data"]["settlement_strain"] == 0
    assert state["data"]["settlement_event"] is None
    assert state["data"]["settlement_event_history"][-1]["response"] == "supported"

    await repository.mutate(
        ref, actor_id="test", idempotency_key="open:2", planner=open_event
    )
    rotated = await game.intervene_settlement_event(
        Environment.LIVE, 101, "riverglass", "divert", "intervene:4"
    )
    stabilized = await game.intervene_settlement_event(
        Environment.LIVE, 102, "mosslight", "divert", "intervene:5"
    )
    redirected = await game.intervene_settlement_event(
        Environment.LIVE, 103, "lichenwake", "release", "intervene:6"
    )
    state = await repository.state(ref)
    assert not rotated.accepted
    assert stabilized.accepted
    assert redirected.accepted
    assert "SCAR REDIRECTED" in redirected.text
    assert state["data"]["settlement_lost_capacity"] == 1
    assert state["data"]["settlement_event_history"][-1]["response"] == "redirected"
    await database.dispose()


@pytest.mark.asyncio
async def test_manual_test_event_is_interactive_and_cannot_change_live_state(
    tmp_path: Path,
) -> None:
    database, game, repository = await _live_position_one(tmp_path)
    live_ref = game.refs[Environment.LIVE]
    test_ref = game.refs[Environment.TEST]
    live_before = await repository.state(live_ref)

    opened = await game.open_test_settlement_event(99, "manual-test-event")
    test_state = await repository.state(test_ref)
    live_after_open = await repository.state(live_ref)
    assert opened.accepted
    assert "no deadline" in opened.text
    assert test_state["data"]["settlement_event"]["manual_test"] is True
    assert live_after_open == live_before

    resolved = await game.intervene_settlement_event(
        Environment.TEST, 99, "operator", "brace", "manual-test-intervention"
    )
    assert resolved.accepted
    supported = await game.intervene_settlement_event(
        Environment.TEST, 100, "witness", "brace", "manual-test-support"
    )
    test_state = await repository.state(test_ref)
    assert supported.accepted
    assert test_state["data"]["settlement_strain"] == 0
    assert test_state["data"]["settlement_event"] is None
    assert test_state["data"]["settlement_event_history"][-1]["response"] == "supported"
    assert (await repository.state(live_ref)) == live_before
    await database.dispose()


@pytest.mark.asyncio
async def test_unanswered_stabilized_choice_becomes_a_persistent_scar(tmp_path: Path) -> None:
    database, game, repository = await _live_position_one(tmp_path)
    ref = game.refs[Environment.LIVE]

    def open_event(state: dict[str, object]) -> MutationPlan:
        after = dict(state)
        data = dict(after["data"])  # type: ignore[arg-type]
        data["settlement_event"] = {
            "event_id": "se-stabilized-expiry",
            "status": "active",
            "title": "The Veil rings",
            "threatened_asset": "the Condensation Veil seam",
            "consequence": "The Veil seam parts.",
            "expires_at": "2026-07-18T10:00:00+00:00",
        }
        after["data"] = data
        return MutationPlan(event_type="test.event_opened", state_after=after, payload={})

    await repository.mutate(
        ref, actor_id="test", idempotency_key="open:stabilized", planner=open_event
    )
    stabilized = await game.intervene_settlement_event(
        Environment.LIVE, 101, "riverglass", "brace", "intervene:stabilize"
    )
    finalized = await game.expire_settlement_event(
        Environment.LIVE, now=datetime(2026, 7, 18, 12, tzinfo=UTC)
    )
    state = await repository.state(ref)

    assert stabilized.accepted
    assert finalized.accepted
    assert "STABILIZED CHOICE BECOMES FINAL" in finalized.text
    assert state["data"]["settlement_escalation"] == 0
    assert state["data"]["settlement_strain"] == 1
    assert state["data"]["settlement_event"] is None
    assert state["data"]["settlement_event_history"][-1]["response"] == "unanswered"
    assert state["data"]["settlement_event_history"][-1]["scar"]
    await database.dispose()


@pytest.mark.asyncio
async def test_restart_restores_recorded_position_one_beginning(tmp_path: Path) -> None:
    database, game, repository = await _live_position_one(tmp_path)
    ref = game.refs[Environment.LIVE]

    def progress(state: dict[str, object]) -> MutationPlan:
        after = dict(state)
        data = dict(after["data"])  # type: ignore[arg-type]
        data["confirmed_facts"] = [{"public_text": "temporary Position 1 fact"}]
        data["settlement_event_history"] = [{"event_id": "se-missed"}]
        data["unlocked_observations"] = [
            "condensation_shared_output",
            "veil_requires_maintenance",
        ]
        data["settlement_event"] = {
            "event_id": "se-final",
            "status": "active",
            "title": "The Veil rings",
            "consequence": "The Veil seam parts.",
            "expires_at": "2026-07-18T10:00:00+00:00",
        }
        data["settlement_escalation"] = 2
        after["data"] = data
        return MutationPlan(event_type="test.position_progress", state_after=after, payload={})

    await repository.mutate(
        ref, actor_id="test", idempotency_key="progress", planner=progress
    )
    result = await game.expire_settlement_event(
        Environment.LIVE, now=datetime(2026, 7, 18, 12, tzinfo=UTC)
    )
    state = await repository.state(ref)

    assert result.accepted
    assert "POSITION 1 RESTARTED" in result.text
    assert state["current_position"] == 1
    assert state["mode"] == SessionMode.RUNNING.value
    assert state["data"]["content_key"] == "interrupted_current"
    assert state["data"]["confirmed_facts"] == []
    assert [
        item["event_id"] for item in state["data"]["settlement_event_history"]
    ] == ["se-missed", "se-final"]
    assert state["data"]["settlement_event_history"][-1]["status"] == "unmitigated"
    assert state["data"]["settlement_restart_count"] == 1
    assert state["data"]["world_flags"]["eastern_growth_viable"] is True
    await database.dispose()
