from __future__ import annotations

import copy
from dataclasses import dataclass
from pathlib import Path

import pytest

from uniflora.content.loader import PuzzleRegistry
from uniflora.engine.actions import (
    AddProposalKickerAction,
    ConfirmReconstructionAction,
    ConnectAction,
    ObserveAction,
    OfferAction,
    OrientLocalAction,
    ProposeReconstructionAction,
)
from uniflora.engine.core import DeterministicEngine, EngineOutcome
from uniflora.engine.cycles import (
    CycleActionKind,
    apply_cycle_decision,
    ensure_cycle_state,
    prepare_cycle_action,
)
from uniflora.engine.position_zero import EnvironmentPositionValidator
from uniflora.engine.validation import ValidationContext, ValidationDecision
from uniflora.game_service import GameService
from uniflora.narration import FallbackNarrator
from uniflora.runtime import Environment, RoutingSnapshot, SessionMode
from uniflora.storage.database import Database
from uniflora.storage.repository import GameRepository, SessionRef


@dataclass
class CycleFixture:
    database: Database
    repository: GameRepository
    ref: SessionRef
    engine: DeterministicEngine
    game: GameService
    environment: Environment
    serial: int = 0

    def participant_id(self, participant: str) -> str:
        if self.environment is Environment.TEST:
            return participant
        label = participant.removeprefix("test:")
        return f"discord:{int.from_bytes(label.encode(), 'big')}"

    async def act(self, participant: str, action: object) -> EngineOutcome:
        self.serial += 1
        return await self.engine.process(
            self.ref,
            participant_id=self.participant_id(participant),
            action=action,  # type: ignore[arg-type]
            idempotency_key=f"cycle:{self.serial}",
        )


async def build_cycle_fixture(
    path: Path, environment: Environment = Environment.TEST
) -> CycleFixture:
    database = Database(f"sqlite+aiosqlite:///{path.as_posix()}")
    await database.create_schema_for_tests()
    repository = GameRepository(database)
    _, refs = await repository.bootstrap(RoutingSnapshot(1, 10, 20, 30, frozenset({99})))
    ref = refs[environment]
    registry = PuzzleRegistry.load_packaged()
    await repository.initialize_content(ref, registry.get(0).initial_state())
    await repository.transition(
        ref, SessionMode.RUNNING, {SessionMode.LOCKED}, "system:cycle-test"
    )
    validator = EnvironmentPositionValidator(registry)
    engine = DeterministicEngine(repository, validator)
    game = GameService(
        repository,
        refs,
        registry,
        engine,
        FallbackNarrator(),
        validator,
    )
    return CycleFixture(database, repository, ref, engine, game, environment)


def proposal() -> ProposeReconstructionAction:
    return ProposeReconstructionAction(
        action="propose_reconstruction",
        proposal={
            "donor_id": "north",
            "recipient_id": "east",
            "resource_id": "water",
            "amount": 5,
            "pathway_id": "path",
            "pathway_action": "repair",
            "maintenance_condition": "monitor and reassess next cycle",
        },
    )


def test_legacy_cycle_upgrade_preserves_progress_and_reopens_response() -> None:
    state = PuzzleRegistry.load_packaged().get(0).initial_state()
    state.pop("cycle")
    state.pop("cycle_history")
    state["unlocked_observations"] = ["northern_capacity"]
    state["contributions"] = [
        {"participant_id": "test:one", "function": "observer", "action": "observe"}
    ]
    state["proposals"] = {
        "proposal-legacy": {
            "proposal_id": "proposal-legacy",
            "author_participant_id": "test:author",
            "status": "pending",
        }
    }

    upgraded = ensure_cycle_state(state, 0)
    assert upgraded["cycle"]["phase"] == "response"
    assert upgraded["cycle"]["response_window_id"] == "proposal-legacy"
    assert upgraded["cycle"]["observation_count"] == 1
    assert upgraded["contributions"][0]["cycle_index"] == 1
    assert state.get("cycle") is None


def test_state_based_checks_reject_an_invalid_resource_total() -> None:
    state = PuzzleRegistry.load_packaged().get(0).initial_state()
    invalid = copy.deepcopy(state)
    invalid["resources"]["northern_reservoir"]["water"] = -1
    action = OfferAction(action="offer", resource_id="water", amount=5, target_entity_id="east")
    context = ValidationContext(
        environment=Environment.LIVE,
        session_id="test-session",
        participant_id="test:one",
        action_id="test-action",
        current_position=0,
        response_profile="surface_noise",
        state=state,
    )
    decision = ValidationDecision(
        True,
        "accepted",
        public_data={"public_text": "invalid mutation"},
        next_state=invalid,
        event_type="test.invalid",
    )

    checked = apply_cycle_decision(
        action, context, CycleActionKind.PRIMARY_COORDINATION, decision
    )
    assert not checked.accepted
    assert checked.reason_key == "state_invariant_failed"


def test_duplicate_observation_refreshes_record_without_spending_primary_action() -> None:
    state = ensure_cycle_state(PuzzleRegistry.load_packaged().get(0).initial_state(), 0)
    refreshed = copy.deepcopy(state)
    refreshed["confirmed_facts"] = [
        {
            "observation_id": "northern_usable_capacity",
            "public_text": "Refreshed public amount.",
        }
    ]
    context = ValidationContext(
        environment=Environment.LIVE,
        session_id="test-session",
        participant_id="test:one",
        action_id="duplicate-observation",
        current_position=0,
        response_profile="surface_noise",
        state=state,
    )
    decision = ValidationDecision(
        True,
        "observation_corroborated",
        public_data={"public_text": "Refreshed public amount."},
        next_state=refreshed,
        event_type="observation.corroborated",
    )

    checked = apply_cycle_decision(
        ObserveAction(action="observe", entity_id="north"),
        context,
        CycleActionKind.PRIMARY_ORIENTATION,
        decision,
    )

    assert checked.accepted
    assert checked.contribution_function is None
    assert checked.next_state is not None
    assert checked.next_state["cycle"]["primary_contributors"] == {}
    assert checked.next_state["cycle"]["observation_count"] == 0
    assert checked.next_state["contributions"] == []
    assert checked.next_state["confirmed_facts"][0]["public_text"] == (
        "Refreshed public amount."
    )


def test_spent_primary_message_lists_exact_eligible_trigger_command() -> None:
    state = ensure_cycle_state(PuzzleRegistry.load_packaged().get(0).initial_state(), 0)
    state["cycle"]["observation_count"] = 1
    state["cycle"]["primary_contributors"] = {
        "test:one": {"action": "observe", "function": "observer"}
    }
    state["triggered_reactions"] = [
        {
            "trigger_id": "eligible-route-test",
            "kind": "test_route",
            "source_participant_id": "test:other",
            "excluded_participant_ids": [],
            "consumed": False,
        },
        {
            "trigger_id": "excluded-risk-check",
            "kind": "risk_check",
            "source_participant_id": "test:one",
            "excluded_participant_ids": [],
            "consumed": False,
        },
    ]
    context = ValidationContext(
        environment=Environment.LIVE,
        session_id="test-session",
        participant_id="test:one",
        action_id="test-action",
        current_position=0,
        response_profile="surface_noise",
        state=state,
    )
    action = OfferAction(action="offer", resource_id="water", amount=5, target_entity_id="east")

    _, _, rejected = prepare_cycle_action(action, context)

    assert rejected is not None
    feedback = str(rejected.public_data["feedback"])
    assert "/interior act trigger trigger_id:eligible-route-test" in feedback
    assert "excluded-risk-check" not in feedback


def test_preparation_actions_can_return_from_calculation() -> None:
    state = ensure_cycle_state(PuzzleRegistry.load_packaged().get(1).initial_state(), 1)
    state["cycle"]["phase"] = "calculation"
    state["cycle"]["observation_count"] = 1
    context = ValidationContext(
        environment=Environment.LIVE,
        session_id="test-session",
        participant_id="test:fresh",
        action_id="interleaved-preparation",
        current_position=1,
        response_profile="surface_noise",
        state=state,
    )

    _, observation_kind, observation_rejection = prepare_cycle_action(
        ObserveAction(action="observe", entity_id="pale_nursery"), context
    )
    _, coordination_kind, coordination_rejection = prepare_cycle_action(
        OfferAction(action="offer", resource_id="water", amount=5, target_entity_id="east"),
        context,
    )

    assert observation_kind is CycleActionKind.PRIMARY_ORIENTATION
    assert observation_rejection is None
    assert coordination_kind is CycleActionKind.PRIMARY_COORDINATION
    assert coordination_rejection is None


def test_existing_contributor_can_assemble_at_the_primary_minimum() -> None:
    state = ensure_cycle_state(PuzzleRegistry.load_packaged().get(0).initial_state(), 0)
    state["cycle"]["observation_count"] = 1
    state["cycle"]["primary_contributors"] = {
        "test:one": {"action": "observe", "function": "observer"},
        "test:two": {"action": "connect", "function": "binder"},
        "test:three": {"action": "offer", "function": "carrier"},
    }
    context = ValidationContext(
        environment=Environment.LIVE,
        session_id="test-session",
        participant_id="test:one",
        action_id="proposal-assembly",
        current_position=0,
        response_profile="surface_noise",
        state=state,
    )

    _, kind, rejection = prepare_cycle_action(proposal(), context)

    assert kind is CycleActionKind.PROPOSAL_ASSEMBLY
    assert rejection is None


def test_position_six_cycle_uses_its_four_contributor_minimum() -> None:
    state = ensure_cycle_state({}, 6)

    assert state["cycle"]["primary_minimum"] == 4


@pytest.mark.asyncio
async def test_cycle_requires_observation_and_limits_primary_contributions(tmp_path: Path) -> None:
    fixture = await build_cycle_fixture(tmp_path / "allowance.db", Environment.LIVE)

    assert "Cycle 1 — Preparation" in await fixture.game.position(Environment.LIVE)
    assert "Latest activity: Orientation" in await fixture.game.recall(Environment.LIVE)
    assert "one accepted primary command" in (
        await fixture.game.accessibility(Environment.LIVE)
    ).lower()

    next_steps = await fixture.game.next_steps(Environment.LIVE, 12345)
    assert "You can help now by doing one of these" in next_steps
    assert "/interior act observe" in next_steps
    assert "Your Cycle 1 primary action is available" in next_steps
    assert "Waiting is valid" in next_steps

    blocked = await fixture.act(
        "test:one",
        OfferAction(action="offer", resource_id="water", amount=5, target_entity_id="east"),
    )
    assert not blocked.accepted
    assert blocked.reason_key == "cycle_action_unavailable"
    assert "observational contribution" in str(blocked.public_data["feedback"])

    first_orient = await fixture.act(
        "test:one", OrientLocalAction(action="orient_local", atmospheric_text="bearing")
    )
    second_orient = await fixture.act(
        "test:one", OrientLocalAction(action="orient_local", atmospheric_text="closer bearing")
    )
    assert first_orient.accepted and second_orient.accepted
    assert "No primary or reaction moves are currently available" in str(
        second_orient.public_data["public_text"]
    )

    spent = await fixture.act(
        "test:one", ObserveAction(action="observe", entity_id="north")
    )
    assert not spent.accepted
    assert "already spent" in str(spent.public_data["feedback"])
    assert "No trigger reaction is currently eligible" in str(
        spent.public_data["feedback"]
    )

    state = await fixture.repository.state(fixture.ref)
    assert state["data"]["cycle"]["observation_count"] == 1
    assert state["data"]["cycle"]["primary_contributors"] == {
        fixture.participant_id("test:one"): {
            "action": "orient_local",
            "function": "observer",
        }
    }
    await fixture.database.dispose()


@pytest.mark.asyncio
async def test_test_surface_keeps_primary_command_allowance_open(tmp_path: Path) -> None:
    fixture = await build_cycle_fixture(tmp_path / "unlimited-test-allowance.db")

    assert (
        await fixture.act(
            "test:one", OrientLocalAction(action="orient_local", atmospheric_text="bearing")
        )
    ).accepted
    assert (
        await fixture.act(
            "test:one",
            OrientLocalAction(action="orient_local", atmospheric_text="closer bearing"),
        )
    ).accepted
    northern = await fixture.act(
        "test:one", ObserveAction(action="observe", entity_id="north")
    )
    eastern = await fixture.act(
        "test:one", ObserveAction(action="observe", entity_id="east")
    )

    assert northern.accepted and eastern.accepted
    assert "command allowance remains open" in str(eastern.public_data["public_text"])
    assert "Test override:" in await fixture.game.accessibility(Environment.TEST)
    state = await fixture.repository.state(fixture.ref)
    assert state["data"]["cycle"]["observation_count"] == 3
    assert len(state["data"]["contributions"]) >= 3
    await fixture.database.dispose()


@pytest.mark.asyncio
async def test_failed_proposal_reassesses_and_refreshes_the_next_cycle(tmp_path: Path) -> None:
    fixture = await build_cycle_fixture(tmp_path / "failed-proposal.db")
    assert (
        await fixture.act("test:one", ObserveAction(action="observe", entity_id="north"))
    ).accepted
    assert (
        await fixture.act("test:two", ObserveAction(action="observe", entity_id="east"))
    ).accepted
    assert (
        await fixture.act("test:three", ObserveAction(action="observe", entity_id="path"))
    ).accepted

    failed = await fixture.act("test:four", proposal())
    assert failed.accepted
    assert failed.reason_key == "cycle_reassessed"
    assert "Cycle 2 begins" in str(failed.public_data["public_text"])

    state = await fixture.repository.state(fixture.ref)
    data = state["data"]
    assert data["cycle"]["index"] == 2
    assert data["cycle"]["phase"] == "orientation"
    assert data["cycle"]["primary_contributors"] == {}
    assert data["counters"]["instability"] == 1
    assert len(data["unlocked_observations"]) == 3
    assert data["cycle_history"][-1]["outcome"] == "proposal_failed"

    refreshed = await fixture.act(
        "test:one", ObserveAction(action="observe", entity_id="north")
    )
    assert refreshed.accepted
    await fixture.database.dispose()


@pytest.mark.asyncio
async def test_admin_can_emergency_close_an_abandoned_cycle_without_erasing_discoveries(
    tmp_path: Path,
) -> None:
    fixture = await build_cycle_fixture(tmp_path / "admin-close.db")
    assert (
        await fixture.act("test:one", ObserveAction(action="observe", entity_id="north"))
    ).accepted
    assert (
        await fixture.act("test:two", ObserveAction(action="observe", entity_id="east"))
    ).accepted
    assert (
        await fixture.act("test:three", ObserveAction(action="observe", entity_id="path"))
    ).accepted

    closed = await fixture.game.close_cycle(
        Environment.TEST,
        99,
        "Facilitator aborted an abandoned rehearsal after participants left.",
    )
    assert closed.accepted
    assert "Cycle 2 begins" in closed.text
    state = await fixture.repository.state(fixture.ref)
    assert state["data"]["cycle"]["index"] == 2
    assert len(state["data"]["unlocked_observations"]) == 3
    assert state["data"]["cycle_history"][-1]["outcome"] == "admin_closed"
    await fixture.database.dispose()


@pytest.mark.asyncio
async def test_successful_cycle_allows_one_reaction_then_advances_position(tmp_path: Path) -> None:
    fixture = await build_cycle_fixture(tmp_path / "successful-cycle.db", Environment.LIVE)
    assert (
        await fixture.act("test:one", ObserveAction(action="observe", entity_id="north"))
    ).accepted
    assert (
        await fixture.act("test:two", ObserveAction(action="observe", entity_id="path"))
    ).accepted
    connected = await fixture.act(
        "test:three",
        ConnectAction(action="connect", source_entity_id="north", target_entity_id="east"),
    )
    assert connected.accepted
    assert "Cycle 1 — Preparation (latest activity: Coordination)" in str(
        connected.public_data["public_text"]
    )
    late_observation = await fixture.act(
        "test:late", ObserveAction(action="observe", entity_id="east")
    )
    assert late_observation.accepted
    assert late_observation.reason_key == "observation_unlocked"
    assert (
        await fixture.act(
            "test:four",
            OfferAction(action="offer", resource_id="water", amount=5, target_entity_id="east"),
        )
    ).accepted
    proposed = await fixture.act("test:one", proposal())
    assert proposed.accepted
    assert "Cycle 1 — Response" in str(proposed.public_data["public_text"])

    state = await fixture.repository.state(fixture.ref)
    proposal_id = next(iter(state["data"]["proposals"]))
    assert state["data"]["cycle"]["phase"] == "response"
    assert state["data"]["cycle"]["response_window_id"] == proposal_id
    assert state["data"]["cycle"]["primary_contributors"][fixture.participant_id("test:one")][
        "action"
    ] == "observe"

    blocked_observation = await fixture.act(
        "test:blocked", ObserveAction(action="observe", entity_id="north")
    )
    assert not blocked_observation.accepted
    assert "public response window" in str(blocked_observation.public_data["feedback"])

    options, _, _ = fixture.game._participant_navigation(
        Environment.LIVE,
        state["data"],
        0,
        fixture.participant_id("test:blocked"),
    )
    joined_options = "\n".join(options)
    assert "/interior act observe" not in joined_options
    assert "/interior act calculate" not in joined_options
    assert "/interior act summarize" not in joined_options
    assert all("(reaction)" in option or "(response)" in option for option in options)

    kicker = await fixture.act(
        "test:three",
        AddProposalKickerAction(
            action="add_proposal_kicker",
            proposal_id=proposal_id,
            kicker="monitoring",
            detail="monitor the repaired route",
        ),
    )
    assert kicker.accepted
    second_response = await fixture.act(
        "test:three",
        ConfirmReconstructionAction(action="confirm_reconstruction", proposal_id=proposal_id),
    )
    assert not second_response.accepted
    assert "only one reaction" in str(second_response.public_data["feedback"])

    completed = await fixture.act(
        "test:two",
        ConfirmReconstructionAction(action="confirm_reconstruction", proposal_id=proposal_id),
    )
    assert completed.accepted and completed.position_completed
    final_state = await fixture.repository.state(fixture.ref)
    assert final_state["current_position"] == 1
    assert final_state["data"]["cycle"] == {
        "position": 1,
        "index": 1,
        "primary_minimum": 3,
        "phase": "orientation",
        "observation_count": 0,
        "orientation_participants": [],
        "primary_contributors": {},
        "response_actions": {},
        "response_window_id": None,
        "proposal_author_id": None,
    }
    assert final_state["data"]["cycle_history"][-1]["outcome"] == "position_completed"
    await fixture.database.dispose()
