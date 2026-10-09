from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

import pytest

from uniflora.content.loader import PuzzleRegistry
from uniflora.engine.actions import (
    AddProposalKickerAction,
    AwakenVesselAction,
    BeginStackAction,
    ConfirmReconstructionAction,
    ConnectAction,
    ObserveAction,
    OfferAction,
    OrientLocalAction,
    ProposeReconstructionAction,
    ReactToStackAction,
    ResolveStackAction,
    UseTriggeredReactionAction,
)
from uniflora.engine.core import DeterministicEngine
from uniflora.engine.position_zero import PositionZeroValidator
from uniflora.engine.validation import ValidationContext
from uniflora.game_service import GameService, PublicResult
from uniflora.narration import FallbackNarrator
from uniflora.runtime import Environment, RoutingSnapshot, SessionMode
from uniflora.storage.database import Database
from uniflora.storage.models import (
    Confirmation,
    Contribution,
    ReconstructionProposal,
    UnlockedObservation,
    WorldFlag,
)
from uniflora.storage.repository import GameRepository, SessionRef


@dataclass
class GameFixture:
    database: Database
    repository: GameRepository
    refs: dict[Environment, SessionRef]
    game: GameService
    serial: int = 0

    async def select(self, slug: str) -> None:
        await self.repository.select_test_identity(self.refs[Environment.TEST], slug, 99)

    async def act(self, action: object) -> PublicResult:
        self.serial += 1
        return await self.game.act(
            Environment.TEST,
            99,
            action,  # type: ignore[arg-type]
            f"test-interaction:{self.serial}",
        )


async def build_game(path: Path) -> GameFixture:
    database = Database(f"sqlite+aiosqlite:///{path.as_posix()}")
    await database.create_schema_for_tests()
    repository = GameRepository(database)
    _, refs = await repository.bootstrap(RoutingSnapshot(1, 10, 20, 30, frozenset({99})))
    registry = PuzzleRegistry.load_packaged()
    narrator = FallbackNarrator()
    registry.validate_narration_keys(narrator.templates)
    engine = DeterministicEngine(repository, PositionZeroValidator(registry.get(0)))
    game = GameService(repository, refs, registry, engine, narrator)
    await game.initialize()
    await repository.transition(
        refs[Environment.TEST], SessionMode.RUNNING, {SessionMode.LOCKED}, "discord:99"
    )
    return GameFixture(database, repository, refs, game)


def proposal(
    amount: float = 5, maintenance: str = "reassess after the next cycle"
) -> ProposeReconstructionAction:
    return ProposeReconstructionAction(
        action="propose_reconstruction",
        proposal={
            "donor_id": "northern_reservoir",
            "recipient_id": "eastern_growth",
            "resource_id": "water",
            "amount": amount,
            "pathway_id": "damaged_circulation",
            "pathway_action": "repair",
            "maintenance_condition": maintenance,
        },
    )


def stack_proposal(maintenance: str = "reassess after the next cycle") -> BeginStackAction:
    return BeginStackAction(
        action="begin_stack", proposal=proposal(maintenance=maintenance).proposal
    )


async def establish_three_participant_record(game: GameFixture, *, connect: bool = True) -> None:
    await game.select("observer")
    assert (
        await game.act(ObserveAction(action="observe", entity_id="northern_reservoir"))
    ).accepted
    await game.select("carrier")
    assert (await game.act(ObserveAction(action="observe", entity_id="eastern_growth"))).accepted
    await game.select("binder")
    assert (
        await game.act(ObserveAction(action="observe", entity_id="damaged_circulation"))
    ).accepted
    if connect:
        assert (
            await game.act(
                ConnectAction(
                    action="connect",
                    source_entity_id="northern_reservoir",
                    target_entity_id="eastern_growth",
                )
            )
        ).accepted


@pytest.mark.asyncio
async def test_end_to_end_test_completion_isolated_from_live(tmp_path: Path) -> None:
    fixture = await build_game(tmp_path / "simulation.db")
    await establish_three_participant_record(fixture)
    await fixture.select("carrier")
    offer = await fixture.act(
        OfferAction(
            action="offer", resource_id="water", amount=5, target_entity_id="eastern_growth"
        )
    )
    assert offer.accepted
    await fixture.select("observer")
    proposed = await fixture.act(proposal())
    assert proposed.accepted and "awaits non-author confirmation" in proposed.text
    test_state = await fixture.repository.state(fixture.refs[Environment.TEST])
    proposal_id = next(iter(test_state["data"]["proposals"]))

    self_confirmation = await fixture.act(
        ConfirmReconstructionAction(action="confirm_reconstruction", proposal_id=proposal_id)
    )
    assert not self_confirmation.accepted
    await fixture.select("carrier")
    completed = await fixture.act(
        ConfirmReconstructionAction(action="confirm_reconstruction", proposal_id=proposal_id)
    )
    assert completed.accepted and "Position 0 complete" in completed.text

    test_state = await fixture.repository.state(fixture.refs[Environment.TEST])
    live_state = await fixture.repository.state(fixture.refs[Environment.LIVE])
    assert test_state["current_position"] == 1
    assert test_state["response_profile"] == "local_correlation"
    assert test_state["data"]["resources"]["northern_reservoir"]["water"] == 7
    assert test_state["data"]["resources"]["eastern_growth"]["water"] == 6
    assert live_state["current_position"] == 0
    assert live_state["response_profile"] == "surface_noise"
    assert live_state["data"]["unlocked_observations"] == []
    assert (
        await fixture.repository.count_rows(fixture.refs[Environment.TEST], ReconstructionProposal)
        == 1
    )
    assert await fixture.repository.count_rows(fixture.refs[Environment.TEST], Confirmation) == 1
    assert await fixture.repository.count_rows(fixture.refs[Environment.TEST], WorldFlag) == 3
    assert await fixture.repository.count_rows(fixture.refs[Environment.LIVE], WorldFlag) == 0

    await fixture.game.reset_test(99)
    reset_state = await fixture.repository.state(fixture.refs[Environment.TEST])
    unchanged_live = await fixture.repository.state(fixture.refs[Environment.LIVE])
    assert reset_state["current_position"] == 0
    assert reset_state["data"]["unlocked_observations"] == []
    assert reset_state["data"]["resources"]["northern_reservoir"]["water"] == 12
    assert reset_state["data"]["resources"]["eastern_growth"]["water"] == 1
    assert unchanged_live == live_state
    await fixture.database.dispose()


@pytest.mark.asyncio
async def test_reset_session_can_complete_position_zero_again(tmp_path: Path) -> None:
    fixture = await build_game(tmp_path / "repeat-completion.db")

    async def complete_position_zero() -> None:
        await establish_three_participant_record(fixture)
        await fixture.select("observer")
        assert (await fixture.act(proposal())).accepted
        state = await fixture.repository.state(fixture.refs[Environment.TEST])
        proposal_id = next(iter(state["data"]["proposals"]))
        await fixture.select("carrier")
        completed = await fixture.act(
            ConfirmReconstructionAction(action="confirm_reconstruction", proposal_id=proposal_id)
        )
        assert completed.accepted and "Position 0 complete" in completed.text

    await complete_position_zero()
    first = await fixture.repository.state(fixture.refs[Environment.TEST])
    assert first["data"]["session_generation"] == 0

    await fixture.game.reset_test(99)
    reset = await fixture.repository.state(fixture.refs[Environment.TEST])
    assert reset["data"]["session_generation"] == 1
    await fixture.repository.transition(
        fixture.refs[Environment.TEST],
        SessionMode.RUNNING,
        {SessionMode.LOCKED},
        "discord:99",
    )
    await complete_position_zero()

    events = await fixture.repository.list_events(fixture.refs[Environment.TEST])
    completions = [event for event in events if event["event_type"] == "position.completed"]
    assert [event["completion_key"] for event in completions] == [
        "generation:0:position:0:completed",
        "generation:1:position:0:completed",
    ]
    await fixture.database.dispose()


@pytest.mark.asyncio
async def test_one_participant_cannot_satisfy_collaboration(tmp_path: Path) -> None:
    fixture = await build_game(tmp_path / "one-user.db")
    await fixture.select("observer")
    for entity in ("north", "east", "path"):
        assert (await fixture.act(ObserveAction(action="observe", entity_id=entity))).accepted
    assert (
        await fixture.act(
            ConnectAction(action="connect", source_entity_id="north", target_entity_id="east")
        )
    ).accepted
    before = len(await fixture.repository.list_events(fixture.refs[Environment.TEST]))
    rejected = await fixture.act(proposal())
    after = len(await fixture.repository.list_events(fixture.refs[Environment.TEST]))
    assert not rejected.accepted
    assert "three distinct" in rejected.text
    assert after == before
    await fixture.database.dispose()


@pytest.mark.asyncio
async def test_donor_exhaustion_and_low_recipient_viability_fail(tmp_path: Path) -> None:
    fixture = await build_game(tmp_path / "sustainability.db")
    await establish_three_participant_record(fixture)
    await fixture.select("carrier")
    exhausted = await fixture.act(
        OfferAction(action="offer", resource_id="water", amount=9, target_entity_id="east")
    )
    assert not exhausted.accepted and "exhaust" in exhausted.text
    await fixture.select("observer")
    too_little = await fixture.act(proposal(amount=4))
    assert not too_little.accepted and "below minimum viability" in too_little.text
    too_much = await fixture.act(proposal(amount=9))
    assert not too_much.accepted and "exhaust" in too_much.text
    non_finite = await fixture.act(proposal(amount=float("nan")))
    assert not non_finite.accepted and "positive" in non_finite.text
    await fixture.database.dispose()


@pytest.mark.asyncio
async def test_missing_pathway_and_maintenance_remain_incomplete(tmp_path: Path) -> None:
    fixture = await build_game(tmp_path / "pathway.db")
    await establish_three_participant_record(fixture, connect=False)
    await fixture.select("observer")
    missing_path = await fixture.act(proposal())
    assert not missing_path.accepted and "pathway-repair" in missing_path.text
    await fixture.select("binder")
    await fixture.act(
        ConnectAction(action="connect", source_entity_id="north", target_entity_id="east")
    )
    await fixture.select("observer")
    missing_maintenance = await fixture.act(proposal(maintenance="do it once"))
    assert not missing_maintenance.accepted and "future reassessment" in missing_maintenance.text
    assert "maintenance` to `monitor`" in missing_maintenance.text
    await fixture.database.dispose()


@pytest.mark.asyncio
async def test_position_zero_publishes_clear_proposal_help_when_ready(tmp_path: Path) -> None:
    fixture = await build_game(tmp_path / "proposal-guidance.db")
    await fixture.select("observer")
    await fixture.act(ObserveAction(action="observe", entity_id="north"))
    await fixture.select("carrier")
    await fixture.act(ObserveAction(action="observe", entity_id="east"))
    await fixture.select("binder")
    await fixture.act(ObserveAction(action="observe", entity_id="path"))
    ready = await fixture.act(
        ConnectAction(action="connect", source_entity_id="north", target_entity_id="east")
    )

    assert ready.accepted
    assert "Position 0 is ready for a proposal" in ready.text
    assert "Sorry—the valid maintenance choices were not explained earlier" in ready.text
    assert "`maintenance:monitor`" in ready.text
    assert "no sentence is required" in ready.text
    recall = await fixture.game.recall(Environment.TEST)
    assert "Position 0 is ready for a proposal" in recall
    assert "`amount:5`" in recall

    await fixture.select("observer")
    proposed = await fixture.act(proposal(maintenance="monitor"))
    assert proposed.accepted
    assert "Position 0 is ready for a proposal" not in proposed.text
    await fixture.database.dispose()


@pytest.mark.asyncio
async def test_recall_contains_only_confirmed_public_discoveries(tmp_path: Path) -> None:
    fixture = await build_game(tmp_path / "recall.db")
    empty = await fixture.game.recall(Environment.TEST)
    assert "12" not in empty and "6" not in empty
    await fixture.select("observer")
    await fixture.act(ObserveAction(action="observe", entity_id="north"))
    recalled = await fixture.game.recall(Environment.TEST)
    assert "12 water units" in recalled
    assert "Public deficits and operating margins" in recalled
    assert "transferable headroom 8" in recalled
    assert "requires 6" not in recalled
    assert "Eastern Growth:" not in recalled
    assert "salinity" not in recalled
    await fixture.database.dispose()


@pytest.mark.asyncio
async def test_generic_orientation_reveals_only_local_atmosphere(tmp_path: Path) -> None:
    fixture = await build_game(tmp_path / "local-orientation.db")
    await fixture.select("observer")
    before = await fixture.repository.state(fixture.refs[Environment.TEST])
    result = await fixture.act(
        OrientLocalAction(
            action="orient_local",
            atmospheric_text="Mara wakes and tries to get her bearings.",
        )
    )
    after = await fixture.repository.state(fixture.refs[Environment.TEST])

    assert result.accepted
    assert "Dry substrate is detectable nearby" in result.text
    assert "wider network does not yet resolve" in result.text
    for prohibited in (
        "Northern",
        "Eastern",
        "Southern",
        "Western",
        "Reservoir",
        "Mire",
        "Exchange",
        "12",
        "6",
        "salinity",
        "evaporation",
    ):
        assert prohibited not in result.text

    assert after["data"]["confirmed_facts"] == before["data"]["confirmed_facts"] == []
    assert after["data"]["unlocked_observations"] == []
    assert after["data"]["contributions"] == []
    assert "No public discoveries have been confirmed" in await fixture.game.recall(
        Environment.TEST
    )
    events = await fixture.repository.list_events(fixture.refs[Environment.TEST])
    assert events[-1]["event_type"] == "orientation.local"
    await fixture.database.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("fate", "effect", "visible_mark"),
    (
        ("plant", "rootglass_garden_crack", "green-lit crack"),
        ("open", "rootglass_rain_sail", "rain-sail"),
        ("keep", "rootglass_empty_socket", "socket"),
    ),
)
async def test_first_participant_names_rootglass_and_scars_settlement(
    tmp_path: Path, fate: str, effect: str, visible_mark: str
) -> None:
    fixture = await build_game(tmp_path / f"rootglass-{fate}.db")
    await fixture.select("observer")

    result = await fixture.act(
        AwakenVesselAction(action="awaken_vessel", name="Little Weather", fate=fate)
    )
    state = await fixture.repository.state(fixture.refs[Environment.TEST])

    assert result.accepted
    assert "Little Weather" in result.text
    assert visible_mark in result.text
    assert state["data"]["settlement_scar"] == {
        "artifact_id": "rootglass_seed",
        "name": "Little Weather",
        "fate": fate,
        "effect": effect,
        "named_by_participant_id": "test:observer",
        "public_text": state["data"]["settlement_scar"]["public_text"],
    }
    assert effect in state["data"]["persistent_effects"]
    assert state["data"]["world_flags"]["rootglass_fate"] == fate
    assert state["data"]["unlocked_observations"] == []
    assert "Little Weather" in await fixture.game.recall(Environment.TEST)
    assert "Settlement scar" in await fixture.game.recall(Environment.TEST)
    await fixture.database.dispose()


@pytest.mark.asyncio
async def test_rootglass_fate_is_irreversible_and_remembers_first_choice(tmp_path: Path) -> None:
    fixture = await build_game(tmp_path / "rootglass-irreversible.db")
    await fixture.select("observer")
    first = await fixture.act(
        AwakenVesselAction(action="awaken_vessel", name="Rainbone", fate="open")
    )
    await fixture.select("carrier")
    second = await fixture.act(
        AwakenVesselAction(action="awaken_vessel", name="Green Door", fate="plant")
    )
    state = await fixture.repository.state(fixture.refs[Environment.TEST])

    assert first.accepted
    assert not second.accepted
    assert "already answered" in second.text
    assert "Rainbone" in second.text
    assert state["data"]["settlement_scar"]["name"] == "Rainbone"
    assert state["data"]["settlement_scar"]["named_by_participant_id"] == "test:observer"
    await fixture.database.dispose()


@pytest.mark.asyncio
async def test_force_observation_marks_only_test_modified(tmp_path: Path) -> None:
    fixture = await build_game(tmp_path / "force.db")
    forced = await fixture.game.force_observation("western_loss", 99)
    assert forced.accepted and "FORCED DEBUG" in forced.text
    test_state = await fixture.repository.state(fixture.refs[Environment.TEST])
    live_state = await fixture.repository.state(fixture.refs[Environment.LIVE])
    assert test_state["modified_by_force"] is True
    assert "western_loss" in test_state["data"]["unlocked_observations"]
    assert live_state["modified_by_force"] is False
    assert live_state["data"]["unlocked_observations"] == []
    await fixture.database.dispose()


@pytest.mark.asyncio
async def test_copy_live_content_reloads_test_without_copying_progress(tmp_path: Path) -> None:
    fixture = await build_game(tmp_path / "copy-content.db")
    await fixture.select("observer")
    await fixture.act(ObserveAction(action="observe", entity_id="north"))
    live_before = await fixture.repository.state(fixture.refs[Environment.LIVE])
    test_before = await fixture.repository.state(fixture.refs[Environment.TEST])
    result = await fixture.game.copy_live_content_to_test(99)
    live_after = await fixture.repository.state(fixture.refs[Environment.LIVE])
    test_after = await fixture.repository.state(fixture.refs[Environment.TEST])
    assert result.accepted and "no live or test progress was copied" in result.text
    assert live_after == live_before
    assert (
        test_after["data"]["unlocked_observations"] == test_before["data"]["unlocked_observations"]
    )
    assert test_after["data"]["contributions"] == test_before["data"]["contributions"]
    assert (await fixture.repository.list_events(fixture.refs[Environment.TEST]))[-1][
        "event_type"
    ] == "admin.test_content.reloaded"
    await fixture.database.dispose()


@pytest.mark.asyncio
async def test_validate_content_does_not_touch_stored_sessions(tmp_path: Path) -> None:
    fixture = await build_game(tmp_path / "validate-no-state.db")
    live_before = await fixture.repository.state(fixture.refs[Environment.LIVE])
    test_before = await fixture.repository.state(fixture.refs[Environment.TEST])
    result = await fixture.game.validate_content()
    assert result.accepted and "isolated three-participant" in result.text
    assert await fixture.repository.state(fixture.refs[Environment.LIVE]) == live_before
    assert await fixture.repository.state(fixture.refs[Environment.TEST]) == test_before
    await fixture.database.dispose()


@pytest.mark.asyncio
async def test_projection_rows_are_environment_scoped(tmp_path: Path) -> None:
    fixture = await build_game(tmp_path / "projections.db")
    await fixture.select("observer")
    await fixture.act(ObserveAction(action="observe", entity_id="north"))
    assert (
        await fixture.repository.count_rows(fixture.refs[Environment.TEST], UnlockedObservation)
        == 1
    )
    assert await fixture.repository.count_rows(fixture.refs[Environment.TEST], Contribution) == 1
    assert (
        await fixture.repository.count_rows(fixture.refs[Environment.LIVE], UnlockedObservation)
        == 0
    )
    await fixture.database.dispose()


@pytest.mark.asyncio
async def test_three_real_live_users_complete_without_altering_test(tmp_path: Path) -> None:
    fixture = await build_game(tmp_path / "live-simulation.db")
    await fixture.repository.transition(
        fixture.refs[Environment.LIVE],
        SessionMode.RUNNING,
        {SessionMode.LOCKED},
        "discord:99",
    )

    async def live_act(user_id: int, action: object, key: str) -> PublicResult:
        return await fixture.game.act(
            Environment.LIVE,
            user_id,
            action,
            key,  # type: ignore[arg-type]
        )

    await live_act(101, ObserveAction(action="observe", entity_id="north"), "live:1")
    await live_act(202, ObserveAction(action="observe", entity_id="east"), "live:2")
    await live_act(303, ObserveAction(action="observe", entity_id="path"), "live:3")
    await live_act(
        303,
        ConnectAction(action="connect", source_entity_id="north", target_entity_id="east"),
        "live:4",
    )
    proposed = await live_act(101, proposal(), "live:5")
    assert proposed.accepted
    live_state = await fixture.repository.state(fixture.refs[Environment.LIVE])
    proposal_id = next(iter(live_state["data"]["proposals"]))
    completed = await live_act(
        202,
        ConfirmReconstructionAction(action="confirm_reconstruction", proposal_id=proposal_id),
        "live:6",
    )
    assert completed.accepted
    assert (await fixture.repository.state(fixture.refs[Environment.LIVE]))["current_position"] == 1
    test_state = await fixture.repository.state(fixture.refs[Environment.TEST])
    assert test_state["current_position"] == 0
    assert test_state["data"]["unlocked_observations"] == []
    await fixture.database.dispose()


@pytest.mark.asyncio
async def test_one_real_admin_cannot_masquerade_as_multiple_live_users(tmp_path: Path) -> None:
    fixture = await build_game(tmp_path / "live-one-admin.db")
    await fixture.repository.transition(
        fixture.refs[Environment.LIVE],
        SessionMode.RUNNING,
        {SessionMode.LOCKED},
        "discord:99",
    )
    serial = 0

    async def act(action: object) -> PublicResult:
        nonlocal serial
        serial += 1
        return await fixture.game.act(
            Environment.LIVE,
            99,
            action,  # type: ignore[arg-type]
            f"live-admin:{serial}",
        )

    for entity in ("north", "east", "path"):
        assert (await act(ObserveAction(action="observe", entity_id=entity))).accepted
    assert (
        await act(
            ConnectAction(action="connect", source_entity_id="north", target_entity_id="east")
        )
    ).accepted
    rejected = await act(proposal())
    assert not rejected.accepted and "three distinct" in rejected.text
    assert (await fixture.repository.state(fixture.refs[Environment.LIVE]))["current_position"] == 0
    await fixture.database.dispose()


@pytest.mark.asyncio
async def test_simultaneous_non_author_confirmations_complete_once(tmp_path: Path) -> None:
    fixture = await build_game(tmp_path / "simultaneous-confirm.db")
    await establish_three_participant_record(fixture)
    await fixture.select("observer")
    assert (await fixture.act(proposal())).accepted
    state = await fixture.repository.state(fixture.refs[Environment.TEST])
    proposal_id = next(iter(state["data"]["proposals"]))
    action = ConfirmReconstructionAction(action="confirm_reconstruction", proposal_id=proposal_id)
    first, second = await asyncio.gather(
        fixture.game.engine.process(
            fixture.refs[Environment.TEST],
            participant_id="test:carrier",
            action=action,
            idempotency_key="confirm:carrier",
        ),
        fixture.game.engine.process(
            fixture.refs[Environment.TEST],
            participant_id="test:binder",
            action=action,
            idempotency_key="confirm:binder",
        ),
    )
    assert sum(result.position_completed for result in (first, second)) == 1
    events = await fixture.repository.list_events(fixture.refs[Environment.TEST])
    assert len([event for event in events if event["event_type"] == "position.completed"]) == 1
    await fixture.database.dispose()


@pytest.mark.asyncio
async def test_public_stack_resolves_repair_then_reassessment_then_transfer(
    tmp_path: Path,
) -> None:
    fixture = await build_game(tmp_path / "stack-lifo.db")
    await establish_three_participant_record(fixture, connect=False)
    await fixture.select("observer")
    opened = await fixture.act(stack_proposal())
    state = await fixture.repository.state(fixture.refs[Environment.TEST])
    stack_id = state["data"]["public_stack"]["stack_id"]
    assert opened.accepted and "stack" in opened.text.lower()

    await fixture.select("carrier")
    assert (
        await fixture.act(
            ReactToStackAction(
                action="react_to_stack",
                stack_id=stack_id,
                reaction="object_pathway",
                detail="The route is damaged.",
            )
        )
    ).accepted
    await fixture.select("binder")
    assert (
        await fixture.act(
            ReactToStackAction(
                action="react_to_stack",
                stack_id=stack_id,
                reaction="repair_pathway",
                detail="Apply the repair resource.",
            )
        )
    ).accepted
    resolved = await fixture.act(ResolveStackAction(action="resolve_stack", stack_id=stack_id))
    assert resolved.accepted
    assert "repair route -> reassess route -> attempt transfer" in resolved.text
    state = await fixture.repository.state(fixture.refs[Environment.TEST])
    assert state["data"]["public_stack"]["status"] == "resolved"
    assert len(state["data"]["proposals"]) == 1
    assert any(trigger["kind"] == "test_route" for trigger in state["data"]["triggered_reactions"])
    await fixture.database.dispose()


@pytest.mark.asyncio
async def test_stack_depth_is_bounded_and_bad_lifo_can_fail_publicly(tmp_path: Path) -> None:
    fixture = await build_game(tmp_path / "stack-depth.db")
    await establish_three_participant_record(fixture, connect=False)
    await fixture.select("observer")
    await fixture.act(stack_proposal())
    state = await fixture.repository.state(fixture.refs[Environment.TEST])
    stack_id = state["data"]["public_stack"]["stack_id"]
    for slug, reaction, detail in (
        ("carrier", "repair_pathway", "Repair first."),
        ("binder", "object_pathway", "The route remains suspect."),
        ("witness", "mitigate_donor", "Protect the donor reserve."),
    ):
        await fixture.select(slug)
        assert (
            await fixture.act(
                ReactToStackAction(
                    action="react_to_stack",
                    stack_id=stack_id,
                    reaction=reaction,  # type: ignore[arg-type]
                    detail=detail,
                )
            )
        ).accepted
    await fixture.select("counterweight")
    before = await fixture.repository.state(fixture.refs[Environment.TEST])
    rejected = await fixture.act(
        ReactToStackAction(
            action="react_to_stack",
            stack_id=stack_id,
            reaction="reassess_pathway",
            detail="Test once more.",
        )
    )
    after = await fixture.repository.state(fixture.refs[Environment.TEST])
    assert not rejected.accepted and "depth limit" in rejected.text
    assert after["data"] == before["data"]

    failed = await fixture.act(ResolveStackAction(action="resolve_stack", stack_id=stack_id))
    assert failed.accepted and "Resolution stops" in failed.text
    state = await fixture.repository.state(fixture.refs[Environment.TEST])
    assert state["data"]["public_stack"]["status"] == "failed"
    assert state["data"]["counters"]["instability"] == 1
    assert any(
        trigger["kind"] == "salvage_observation" for trigger in state["data"]["triggered_reactions"]
    )
    await fixture.database.dispose()


@pytest.mark.asyncio
async def test_confirmed_events_create_distinct_participant_triggers_and_thresholds(
    tmp_path: Path,
) -> None:
    fixture = await build_game(tmp_path / "triggers.db")
    await fixture.select("carrier")
    await fixture.act(ObserveAction(action="observe", entity_id="east"))
    state = await fixture.repository.state(fixture.refs[Environment.TEST])
    capacity_trigger = next(
        item for item in state["data"]["triggered_reactions"] if item["kind"] == "inspect_capacity"
    )
    assert capacity_trigger["trigger_id"] == "inspect-capacity-northern-reservoir"
    same_player = await fixture.act(
        UseTriggeredReactionAction(
            action="use_triggered_reaction", trigger_id=capacity_trigger["trigger_id"]
        )
    )
    assert not same_player.accepted
    await fixture.select("observer")
    inspection = await fixture.act(
        UseTriggeredReactionAction(
            action="use_triggered_reaction", trigger_id=capacity_trigger["trigger_id"]
        )
    )
    assert inspection.accepted and "Triggered capacity inspection" in inspection.text

    await fixture.select("binder")
    await fixture.act(ObserveAction(action="observe", entity_id="path"))
    for repairer, tester in (("binder", "observer"), ("carrier", "witness")):
        await fixture.select(repairer)
        await fixture.act(
            ConnectAction(action="connect", source_entity_id="north", target_entity_id="east")
        )
        state = await fixture.repository.state(fixture.refs[Environment.TEST])
        route_trigger = next(
            item
            for item in reversed(state["data"]["triggered_reactions"])
            if item["kind"] == "test_route" and not item["consumed"]
        )
        expected_id = "test-route-damaged-circulation" + ("" if repairer == "binder" else "-2")
        assert route_trigger["trigger_id"] == expected_id
        await fixture.select(tester)
        assert (
            await fixture.act(
                UseTriggeredReactionAction(
                    action="use_triggered_reaction", trigger_id=route_trigger["trigger_id"]
                )
            )
        ).accepted
    state = await fixture.repository.state(fixture.refs[Environment.TEST])
    assert state["data"]["counters"]["repair"]["damaged_circulation"] == 2
    assert "route_reinforced" in state["data"]["persistent_effects"]
    recall = await fixture.game.recall(Environment.TEST)
    assert "repair:damaged_circulation=2" in recall
    assert "route reinforced" in recall
    await fixture.database.dispose()


@pytest.mark.asyncio
async def test_route_trigger_during_pending_proposal_preserves_confirmation_window(
    tmp_path: Path,
) -> None:
    fixture = await build_game(tmp_path / "route-trigger-pending-proposal.db")
    await establish_three_participant_record(fixture)

    state = await fixture.repository.state(fixture.refs[Environment.TEST])
    route_trigger = next(
        item
        for item in state["data"]["triggered_reactions"]
        if item["kind"] == "test_route" and not item["consumed"]
    )

    await fixture.select("observer")
    proposed = await fixture.act(proposal(maintenance="monitor"))
    assert proposed.accepted, proposed.text

    state = await fixture.repository.state(fixture.refs[Environment.TEST])
    proposal_id = next(iter(state["data"]["proposals"]))
    assert state["data"]["proposals"][proposal_id]["status"] == "pending"
    assert state["data"]["confirmations"] == []

    await fixture.select("witness")
    tested = await fixture.act(
        UseTriggeredReactionAction(
            action="use_triggered_reaction",
            trigger_id=route_trigger["trigger_id"],
        )
    )
    assert tested.accepted, tested.text

    state = await fixture.repository.state(fixture.refs[Environment.TEST])
    consumed_trigger = next(
        item
        for item in state["data"]["triggered_reactions"]
        if item["trigger_id"] == route_trigger["trigger_id"]
    )
    assert consumed_trigger["consumed"] is True
    assert consumed_trigger["consumed_by"] == "test:witness"
    assert state["data"]["proposals"][proposal_id]["status"] == "pending"
    assert state["data"]["confirmations"] == []

    await fixture.select("carrier")
    completed = await fixture.act(
        ConfirmReconstructionAction(
            action="confirm_reconstruction",
            proposal_id=proposal_id,
        )
    )
    assert completed.accepted, completed.text
    assert "Position 0 complete" in completed.text

    final_state = await fixture.repository.state(fixture.refs[Environment.TEST])
    assert final_state["current_position"] == 1
    await fixture.database.dispose()


@pytest.mark.asyncio
async def test_kickers_persist_and_risk_check_remains_usable_after_completion(
    tmp_path: Path,
) -> None:
    fixture = await build_game(tmp_path / "kickers.db")
    await establish_three_participant_record(fixture)
    await fixture.select("observer")
    assert (await fixture.act(proposal())).accepted
    state = await fixture.repository.state(fixture.refs[Environment.TEST])
    proposal_id = next(iter(state["data"]["proposals"]))
    for slug, kicker in (
        ("carrier", "monitoring"),
        ("binder", "protect_donor"),
        ("witness", "document"),
    ):
        await fixture.select(slug)
        assert (
            await fixture.act(
                AddProposalKickerAction(
                    action="add_proposal_kicker",
                    proposal_id=proposal_id,
                    kicker=kicker,  # type: ignore[arg-type]
                    detail="Maintain and document the public intervention.",
                )
            )
        ).accepted
    await fixture.select("carrier")
    completed = await fixture.act(
        ConfirmReconstructionAction(action="confirm_reconstruction", proposal_id=proposal_id)
    )
    assert completed.accepted
    state = await fixture.repository.state(fixture.refs[Environment.TEST])
    assert state["current_position"] == 1
    assert state["data"]["counters"]["strain"]["northern_reservoir"] == 0
    assert state["data"]["counters"]["coherence"] == 1
    assert "moisture_monitoring_mesh" in state["data"]["persistent_effects"]
    risk = next(
        item for item in state["data"]["triggered_reactions"] if item["kind"] == "risk_check"
    )
    await fixture.select("binder")
    checked = await fixture.act(
        UseTriggeredReactionAction(action="use_triggered_reaction", trigger_id=risk["trigger_id"])
    )
    assert checked.accepted and "0 strain counter" in checked.text
    await fixture.database.dispose()


def test_strain_threshold_raises_the_safe_reserve_requirement() -> None:
    definition = PuzzleRegistry.load_packaged().get(0)
    state = definition.initial_state()
    state["unlocked_observations"] = list(definition.reconstruction.required_observations)
    state["connections"] = [{"pathway_id": "damaged_circulation"}]
    state["contributions"] = [
        {"participant_id": "one", "function": "observer", "action": "observe"},
        {"participant_id": "two", "function": "binder", "action": "connect"},
        {"participant_id": "three", "function": "carrier", "action": "offer"},
    ]
    state["counters"]["strain"]["northern_reservoir"] = 3
    decision = PositionZeroValidator(definition).validate(
        proposal(amount=8),
        ValidationContext(
            environment=Environment.TEST,
            session_id="session",
            participant_id="one",
            action_id="strained-proposal",
            current_position=0,
            response_profile="surface_noise",
            state=state,
        ),
    )
    assert not decision.accepted
    assert "strain-adjusted" in decision.public_data["feedback"]
