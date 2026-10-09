from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from uniflora.content.loader import PuzzleRegistry
from uniflora.engine.actions import (
    AddProposalKickerAction,
    BeginStackAction,
    BranchProposalAction,
    CalculateFlowAction,
    ConfirmReconstructionAction,
    ConnectAction,
    MitigateAction,
    ObserveAction,
    ProposeCirculationAction,
    ProposeReconstructionAction,
    ReactToStackAction,
    RelayAction,
    ResolveStackAction,
    SustainAction,
)
from uniflora.engine.core import DeterministicEngine
from uniflora.engine.position_one import PositionOneValidator
from uniflora.engine.position_zero import EnvironmentPositionValidator
from uniflora.game_service import GameService, PublicResult
from uniflora.narration import FallbackNarrator
from uniflora.runtime import Environment, RoutingSnapshot, SessionMode
from uniflora.storage.database import Database
from uniflora.storage.repository import GameRepository, MutationPlan, SessionRef


@dataclass
class CirculationFixture:
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
            f"circulation:{self.serial}",
        )


async def build_game(path: Path) -> CirculationFixture:
    database = Database(f"sqlite+aiosqlite:///{path.as_posix()}")
    await database.create_schema_for_tests()
    repository = GameRepository(database)
    _, refs = await repository.bootstrap(RoutingSnapshot(1, 10, 20, 30, frozenset({99})))
    registry = PuzzleRegistry.load_packaged()
    narrator = FallbackNarrator()
    validator = EnvironmentPositionValidator(registry, enforce_cycles=False)
    engine = DeterministicEngine(repository, validator)
    game = GameService(repository, refs, registry, engine, narrator, validator)
    await game.initialize()
    for identity in ("maintainer", "router", "planner"):
        await repository.create_test_identity(refs[Environment.TEST], identity, 99)
    await repository.transition(
        refs[Environment.TEST], SessionMode.RUNNING, {SessionMode.LOCKED}, "discord:99"
    )
    return CirculationFixture(database, repository, refs, game)


async def complete_position_zero(fixture: CirculationFixture) -> None:
    await fixture.select("observer")
    assert (await fixture.act(ObserveAction(action="observe", entity_id="north"))).accepted
    await fixture.select("carrier")
    assert (await fixture.act(ObserveAction(action="observe", entity_id="east"))).accepted
    await fixture.select("binder")
    assert (await fixture.act(ObserveAction(action="observe", entity_id="path"))).accepted
    assert (
        await fixture.act(
            ConnectAction(action="connect", source_entity_id="north", target_entity_id="east")
        )
    ).accepted
    await fixture.select("observer")
    proposed = await fixture.act(
        ProposeReconstructionAction(
            action="propose_reconstruction",
            proposal={
                "donor_id": "north",
                "recipient_id": "east",
                "resource_id": "water",
                "amount": 5,
                "pathway_id": "path",
                "pathway_action": "repair",
                "maintenance_condition": "reassess after the next cycle",
            },
        )
    )
    assert proposed.accepted
    state = await fixture.repository.state(fixture.refs[Environment.TEST])
    proposal_id = next(iter(state["data"]["proposals"]))
    await fixture.select("carrier")
    assert (
        await fixture.act(
            ConfirmReconstructionAction(action="confirm_reconstruction", proposal_id=proposal_id)
        )
    ).accepted


async def establish_circulation_record(fixture: CirculationFixture) -> None:
    await fixture.select("observer")
    assert (await fixture.act(ObserveAction(action="observe", entity_id="nursery"))).accepted
    assert (await fixture.act(ObserveAction(action="observe", entity_id="north"))).accepted
    assert (await fixture.act(ObserveAction(action="observe", entity_id="basin"))).accepted

    await fixture.select("maintainer")
    assert (await fixture.act(ObserveAction(action="observe", entity_id="veil"))).accepted
    assert (await fixture.act(ObserveAction(action="observe", entity_id="veil"))).accepted
    assert (
        await fixture.act(
            SustainAction(
                action="sustain",
                target_entity_id="veil",
                condition="maintain and clean the collection surface each cycle",
            )
        )
    ).accepted

    await fixture.select("router")
    assert (await fixture.act(ObserveAction(action="observe", entity_id="route seven"))).accepted
    assert (
        await fixture.act(
            SustainAction(
                action="sustain",
                target_entity_id="route seven",
                condition="reassess the route before delivery",
            )
        )
    ).accepted
    assert (await fixture.act(ObserveAction(action="observe", entity_id="relay"))).accepted
    assert (
        await fixture.act(
            CalculateFlowAction(
                action="calculate_flow", source_amount=9, pathway_entity_id="route seven"
            )
        )
    ).accepted


async def establish_lossy_record(
    fixture: CirculationFixture,
    *,
    source_amount: float,
    support_source: str = "",
    support_amount: float = 0,
) -> None:
    await fixture.select("observer")
    assert (await fixture.act(ObserveAction(action="observe", entity_id="nursery"))).accepted
    assert (await fixture.act(ObserveAction(action="observe", entity_id="basin"))).accepted
    if support_source:
        assert (
            await fixture.act(ObserveAction(action="observe", entity_id=support_source))
        ).accepted

    await fixture.select("maintainer")
    assert (await fixture.act(ObserveAction(action="observe", entity_id="veil"))).accepted
    assert (await fixture.act(ObserveAction(action="observe", entity_id="veil"))).accepted
    assert (
        await fixture.act(
            SustainAction(
                action="sustain",
                target_entity_id="veil",
                condition="maintain the shared collection surface",
            )
        )
    ).accepted

    await fixture.select("router")
    assert (await fixture.act(ObserveAction(action="observe", entity_id="route seven"))).accepted
    assert (await fixture.act(ObserveAction(action="observe", entity_id="relay"))).accepted
    if support_source:
        assert (
            await fixture.act(
                SustainAction(
                    action="sustain",
                    target_entity_id="relay",
                    condition="maintain same-cycle combined inflow",
                )
            )
        ).accepted
    assert (
        await fixture.act(
            CalculateFlowAction(
                action="calculate_flow",
                source_amount=source_amount,
                pathway_entity_id="route seven",
                support_amount=support_amount,
            )
        )
    ).accepted


@pytest.mark.asyncio
async def test_position_zero_atomically_initializes_circulation(tmp_path: Path) -> None:
    fixture = await build_game(tmp_path / "transition.db")
    await complete_position_zero(fixture)
    state = await fixture.repository.state(fixture.refs[Environment.TEST])

    assert state["current_position"] == 1
    assert state["data"]["content_key"] == "interrupted_current"
    assert state["data"]["position_completed"] is False
    assert state["data"]["resources"]["northern_reservoir"]["water"] == 7
    assert state["data"]["resources"]["eastern_growth"]["water"] == 6
    assert state["data"]["counters"]["strain"]["northern_reservoir"] == 1
    assert state["data"]["contributions"] == []
    assert state["data"]["prior_confirmed_facts"]
    assert all(
        item["kind"] not in {"inspect_capacity", "salvage_observation", "test_route"}
        for item in state["data"]["triggered_reactions"]
    )
    await fixture.database.dispose()


@pytest.mark.asyncio
async def test_startup_upgrades_legacy_position_one_state_without_reset(tmp_path: Path) -> None:
    fixture = await build_game(tmp_path / "legacy-upgrade.db")
    ref = fixture.refs[Environment.TEST]

    def legacy_planner(state: dict[str, object]) -> MutationPlan:
        after = dict(state)
        data = fixture.game.registries[Environment.TEST].get(0).initial_state()
        data["resources"]["northern_reservoir"]["water"] = 7
        data["resources"]["eastern_growth"]["water"] = 6
        data["counters"]["strain"]["northern_reservoir"] = 1
        data["position_completed"] = True
        after["current_position"] = 1
        after["response_profile"] = "local_correlation"
        after["data"] = data
        return MutationPlan(
            event_type="test.legacy_position_one",
            state_after=after,
            payload={},
        )

    await fixture.repository.mutate(
        ref,
        actor_id="test:legacy",
        idempotency_key="legacy-position-one",
        planner=legacy_planner,
    )
    await fixture.game.initialize()
    upgraded = await fixture.repository.state(ref)
    assert upgraded["current_position"] == 1
    assert upgraded["data"]["content_key"] == "interrupted_current"
    assert upgraded["data"]["resources"]["northern_reservoir"]["water"] == 7
    assert upgraded["data"]["resources"]["eastern_growth"]["water"] == 6
    assert upgraded["data"]["counters"]["strain"]["northern_reservoir"] == 1

    await fixture.game.initialize()
    repeated = await fixture.repository.state(ref)
    assert repeated == upgraded
    await fixture.database.dispose()


@pytest.mark.asyncio
async def test_content_version_upgrade_preserves_position_one_progress(tmp_path: Path) -> None:
    fixture = await build_game(tmp_path / "version-upgrade.db")
    await complete_position_zero(fixture)
    ref = fixture.refs[Environment.TEST]

    def stale_planner(state: dict[str, object]) -> MutationPlan:
        after = dict(state)
        data = dict(after["data"])  # type: ignore[arg-type]
        data["content_version"] = "1.1.0"
        resources = dict(data["resources"])  # type: ignore[arg-type]
        resources.pop("first_bloom_basin", None)
        data["resources"] = resources
        data["contributions"] = [
            {"participant_id": "test:reader", "function": "need_observer", "action": "observe"}
        ]
        data["triggered_reactions"] = [
            {"trigger_id": "old-route", "kind": "test_route", "consumed": False},
            {"trigger_id": "current-risk", "kind": "risk_check", "consumed": False},
        ]
        after["data"] = data
        return MutationPlan(event_type="test.stale_position_one", state_after=after, payload={})

    await fixture.repository.mutate(
        ref,
        actor_id="test:stale",
        idempotency_key="stale-position-one",
        planner=stale_planner,
    )
    await fixture.game.initialize()

    upgraded = await fixture.repository.state(ref)
    assert upgraded["data"]["content_version"] == "3.3.1"
    assert upgraded["data"]["resources"]["first_bloom_basin"]["water"] == 0
    assert upgraded["data"]["contributions"] == [
        {"participant_id": "test:reader", "function": "need_observer", "action": "observe"}
    ]
    assert [item["trigger_id"] for item in upgraded["data"]["triggered_reactions"]] == [
        "current-risk"
    ]
    await fixture.database.dispose()


@pytest.mark.asyncio
async def test_visible_map_cue_discovers_and_names_pale_nursery(tmp_path: Path) -> None:
    fixture = await build_game(tmp_path / "map-cue-discovery.db")
    await complete_position_zero(fixture)
    await fixture.select("observer")

    observed = await fixture.act(
        ObserveAction(action="observe", entity_id="Shaded Planting Surface")
    )

    assert observed.accepted
    assert "Identified target: **Pale Nursery**" in observed.text
    assert "Pale Nursery" in observed.text
    assert "6 additional water units" in observed.text
    state = await fixture.repository.state(fixture.refs[Environment.TEST])
    assert "nursery_projected_need" in state["data"]["unlocked_observations"]
    await fixture.database.dispose()


@pytest.mark.asyncio
async def test_circulation_calculation_reflects_route_reassessment(tmp_path: Path) -> None:
    fixture = await build_game(tmp_path / "calculate.db")
    await complete_position_zero(fixture)
    await fixture.select("observer")
    assert (await fixture.act(ObserveAction(action="observe", entity_id="route seven"))).accepted

    before = await fixture.act(
        CalculateFlowAction(
            action="calculate_flow", source_amount=9, pathway_entity_id="route seven"
        )
    )
    assert before.accepted and "6.75" in before.text
    assert (
        await fixture.act(
            SustainAction(
                action="sustain",
                target_entity_id="route seven",
                condition="reassess route efficiency",
            )
        )
    ).accepted
    after = await fixture.act(
        CalculateFlowAction(
            action="calculate_flow", source_amount=9, pathway_entity_id="route seven"
        )
    )
    assert after.accepted and "deliver 9" in after.text
    await fixture.database.dispose()


@pytest.mark.asyncio
async def test_calculation_cannot_exceed_confirmed_veil_output(tmp_path: Path) -> None:
    fixture = await build_game(tmp_path / "calculate-source-limit.db")
    await complete_position_zero(fixture)
    await fixture.select("observer")
    assert (await fixture.act(ObserveAction(action="observe", entity_id="route seven"))).accepted
    assert (await fixture.act(ObserveAction(action="observe", entity_id="veil"))).accepted

    rejected = await fixture.act(
        CalculateFlowAction(
            action="calculate_flow", source_amount=20, pathway_entity_id="route seven"
        )
    )
    assert not rejected.accepted
    assert "confirmed Condensation Veil output is 9 units" in rejected.text
    assert "does not create source water" in rejected.text

    accepted = await fixture.act(
        CalculateFlowAction(
            action="calculate_flow", source_amount=9, pathway_entity_id="route seven"
        )
    )
    assert accepted.accepted
    assert "Arithmetic only" in accepted.text
    assert "does not confirm source maintenance" in accepted.text
    await fixture.database.dispose()


@pytest.mark.asyncio
async def test_eastern_growth_reports_exact_viability_and_recovery_amounts(tmp_path: Path) -> None:
    fixture = await build_game(tmp_path / "eastern-thresholds.db")
    await complete_position_zero(fixture)
    await fixture.select("observer")

    observed = await fixture.act(ObserveAction(action="observe", entity_id="east"))
    assert observed.accepted
    assert "needs no additional water" in observed.text
    assert "protected recovery level is 12 units" in observed.text
    assert "needs 6 additional units" in observed.text
    assert "can relay 0 now" in observed.text

    recalled = await fixture.game.recall(Environment.TEST)
    assert "Public deficits and operating margins" in recalled
    assert "Eastern Growth: current 6 water" in recalled
    assert "viability deficit 0" in recalled
    assert "protected relay level 12" in recalled
    assert "deficit before relaying 6" in recalled

    sustained = await fixture.act(
        SustainAction(
            action="sustain",
            target_entity_id="east",
            condition="monitor recovery",
        )
    )
    assert sustained.accepted
    assert "records maintenance and moves no water" in sustained.text
    assert "needs no additional water" in sustained.text
    assert "6 additional units" in sustained.text
    assert "12-unit protected" in sustained.text
    await fixture.database.dispose()


def test_indicator_bed_observation_reports_viability_and_capacity_numbers() -> None:
    definition = PuzzleRegistry.load_packaged().get(1)
    validator = PositionOneValidator(definition)
    state = definition.initial_state()

    text = validator._observation_text("indicator_bed_capacity_limited", state)

    assert "viability is 3" in text
    assert "minimum of 2" in text
    assert "saturation is 0" in text
    assert "limit of 3" in text
    assert "3 load(s) of headroom" in text


@pytest.mark.asyncio
async def test_loss_accounted_flow_is_a_viable_fast_strategy(tmp_path: Path) -> None:
    fixture = await build_game(tmp_path / "loss-accounted.db")
    await complete_position_zero(fixture)
    await establish_lossy_record(fixture, source_amount=8)

    await fixture.select("planner")
    proposed = await fixture.act(
        ProposeCirculationAction(
            action="propose_circulation",
            source_entity_id="veil",
            recipient_entity_id="nursery",
            resource_id="water",
            source_amount=8,
            pathway_entity_id="route seven",
            relay_entity_id="relay",
            delivered_amount=6,
            maintenance="maintain the Veil collection surface",
            reassessment="reassess Nursery demand before the next cycle",
            branch_condition="if Nursery demand or Veil output changes",
            branch_action="revise delivery and release unused condensation",
        )
    )
    assert proposed.accepted and "rapid_loss_accounted_route" in proposed.text
    state = await fixture.repository.state(fixture.refs[Environment.TEST])
    proposal_id = next(iter(state["data"]["proposals"]))
    assert proposal_id == "circulation-loss-accounted"

    await fixture.select("observer")
    completed = await fixture.act(
        ConfirmReconstructionAction(action="confirm_reconstruction", proposal_id=proposal_id)
    )
    assert completed.accepted
    state = await fixture.repository.state(fixture.refs[Environment.TEST])
    assert state["current_position"] == 2
    assert state["data"]["resources"]["pale_nursery"]["water"] == 8
    assert state["data"]["world_flags"]["circulation_strategy"] == ("rapid_loss_accounted_route")
    await fixture.database.dispose()


@pytest.mark.asyncio
async def test_archive_support_preserves_a_distinct_resource_consequence(tmp_path: Path) -> None:
    fixture = await build_game(tmp_path / "archive-support.db")
    await complete_position_zero(fixture)
    await establish_lossy_record(
        fixture, source_amount=6, support_source="archive", support_amount=1.5
    )

    await fixture.select("planner")
    proposed = await fixture.act(
        ProposeCirculationAction(
            action="propose_circulation",
            source_entity_id="veil",
            recipient_entity_id="nursery",
            resource_id="water",
            source_amount=6,
            pathway_entity_id="route seven",
            relay_entity_id="relay",
            delivered_amount=6,
            maintenance="maintain the Veil collection surface",
            reassessment="reassess Nursery demand before the next cycle",
            branch_condition="if Nursery demand changes",
            branch_action="revise support and protect the Archive",
            support_source_entity_id="archive",
            support_amount=1.5,
        )
    )
    assert proposed.accepted and "shared_archive_support" in proposed.text
    state = await fixture.repository.state(fixture.refs[Environment.TEST])
    proposal_id = next(iter(state["data"]["proposals"]))
    assert proposal_id == "circulation-archive-support"

    await fixture.select("observer")
    assert (
        await fixture.act(
            ConfirmReconstructionAction(action="confirm_reconstruction", proposal_id=proposal_id)
        )
    ).accepted
    state = await fixture.repository.state(fixture.refs[Environment.TEST])
    assert state["data"]["resources"]["lower_archive_bed"]["water"] == 5.5
    assert state["data"]["world_flags"]["circulation_strategy"] == "shared_archive_support"
    assert "archive_support_recorded" in state["data"]["persistent_effects"]
    await fixture.database.dispose()


@pytest.mark.asyncio
async def test_northern_support_requires_mitigation_and_adds_strain(tmp_path: Path) -> None:
    fixture = await build_game(tmp_path / "northern-support.db")
    await complete_position_zero(fixture)
    await establish_lossy_record(
        fixture, source_amount=6, support_source="north", support_amount=1.5
    )

    await fixture.select("planner")
    assert (
        await fixture.act(
            ProposeCirculationAction(
                action="propose_circulation",
                source_entity_id="veil",
                recipient_entity_id="nursery",
                resource_id="water",
                source_amount=6,
                pathway_entity_id="route seven",
                relay_entity_id="relay",
                delivered_amount=6,
                maintenance="maintain the Veil collection surface",
                reassessment="reassess Nursery demand before the next cycle",
                branch_condition="if Nursery demand changes",
                branch_action="reduce support and protect the Northern reserve",
                support_source_entity_id="north",
                support_amount=1.5,
            )
        )
    ).accepted
    state = await fixture.repository.state(fixture.refs[Environment.TEST])
    proposal_id = next(iter(state["data"]["proposals"]))
    assert proposal_id == "circulation-northern-support"

    await fixture.select("observer")
    rejected = await fixture.act(
        ConfirmReconstructionAction(action="confirm_reconstruction", proposal_id=proposal_id)
    )
    assert not rejected.accepted and "needs a public mitigation" in rejected.text
    assert (
        await fixture.act(
            MitigateAction(
                action="mitigate",
                target_entity_id="north",
                risk="repeated extraction",
                detail="protect the civic reserve and document strain",
            )
        )
    ).accepted
    assert (
        await fixture.act(
            ConfirmReconstructionAction(action="confirm_reconstruction", proposal_id=proposal_id)
        )
    ).accepted
    state = await fixture.repository.state(fixture.refs[Environment.TEST])
    assert state["data"]["resources"]["northern_reservoir"]["water"] == 5.5
    assert state["data"]["counters"]["strain"]["northern_reservoir"] == 2
    assert state["data"]["world_flags"]["circulation_strategy"] == "shared_northern_support"
    await fixture.database.dispose()


@pytest.mark.asyncio
async def test_stack_demand_reassessment_changes_state_and_can_defeat_base(tmp_path: Path) -> None:
    fixture = await build_game(tmp_path / "demand-reassessment.db")
    await complete_position_zero(fixture)
    await establish_lossy_record(fixture, source_amount=8)
    base = {
        "kind": "circulation",
        "source_entity_id": "veil",
        "recipient_entity_id": "nursery",
        "resource_id": "water",
        "source_amount": 8,
        "pathway_entity_id": "route seven",
        "relay_entity_id": "relay",
        "delivered_amount": 6,
        "maintenance": "maintain the Veil each cycle",
        "reassessment": "reassess demand before the next cycle",
    }
    await fixture.select("planner")
    opened = await fixture.act(BeginStackAction(action="begin_stack", proposal=base))
    assert opened.accepted
    state = await fixture.repository.state(fixture.refs[Environment.TEST])
    stack_id = state["data"]["public_stack"]["stack_id"]

    await fixture.select("observer")
    assert (
        await fixture.act(
            ReactToStackAction(
                action="react_to_stack",
                stack_id=stack_id,
                reaction="reassess_demand",
                detail="the planted court enters accelerated growth",
            )
        )
    ).accepted
    await fixture.select("router")
    resolved = await fixture.act(ResolveStackAction(action="resolve_stack", stack_id=stack_id))
    assert resolved.accepted and "requires 9 delivered units" in resolved.text
    state = await fixture.repository.state(fixture.refs[Environment.TEST])
    assert state["current_position"] == 1
    assert state["data"]["forecast_branch"] == "accelerated"
    assert state["data"]["public_stack"]["status"] == "failed"
    assert state["data"]["counters"]["instability"] == 1
    await fixture.database.dispose()


@pytest.mark.asyncio
async def test_slash_equivalent_circulation_path_completes_position_one(tmp_path: Path) -> None:
    fixture = await build_game(tmp_path / "complete.db")
    await complete_position_zero(fixture)
    await establish_circulation_record(fixture)

    await fixture.select("router")
    assert (
        await fixture.act(
            RelayAction(
                action="relay",
                source_entity_id="veil",
                via_entity_id="relay",
                target_entity_id="nursery",
                resource_id="water",
                amount=9,
            )
        )
    ).accepted

    await fixture.select("planner")
    proposed = await fixture.act(
        ProposeCirculationAction(
            action="propose_circulation",
            source_entity_id="veil",
            recipient_entity_id="nursery",
            resource_id="water",
            source_amount=9,
            pathway_entity_id="route seven",
            relay_entity_id="relay",
            delivered_amount=9,
            maintenance="maintain the Veil collection surface",
            reassessment="reassess Nursery demand and Veil output before the next cycle",
        )
    )
    assert proposed.accepted and "still needs a contingency branch" in proposed.text
    state = await fixture.repository.state(fixture.refs[Environment.TEST])
    proposal_id = next(
        key for key, item in state["data"]["proposals"].items() if item.get("kind") == "circulation"
    )
    assert proposal_id == "circulation-maintained-route"

    await fixture.select("maintainer")
    incomplete = await fixture.act(
        ConfirmReconstructionAction(action="confirm_reconstruction", proposal_id=proposal_id)
    )
    assert not incomplete.accepted and "contingency branch" in incomplete.text

    await fixture.select("observer")
    assert (
        await fixture.act(
            BranchProposalAction(
                action="branch_proposal",
                proposal_id=proposal_id,
                condition="if Nursery demand or Veil output changes",
                branch_action="send only the confirmed need and release unused condensation",
            )
        )
    ).accepted
    completed = await fixture.act(
        ConfirmReconstructionAction(action="confirm_reconstruction", proposal_id=proposal_id)
    )
    assert completed.accepted and "Position 1 complete" in completed.text

    state = await fixture.repository.state(fixture.refs[Environment.TEST])
    assert state["current_position"] == 2
    assert state["response_profile"] == "conditional_memory"
    assert state["data"]["resources"]["pale_nursery"]["water"] == 11
    assert state["data"]["resources"]["central_relay"]["water"] == 0
    assert "adaptive_circulation_protocol" in state["data"]["persistent_effects"]
    await fixture.database.dispose()


@pytest.mark.asyncio
async def test_repeated_circulation_proposals_use_readable_numeric_suffixes(
    tmp_path: Path,
) -> None:
    fixture = await build_game(tmp_path / "proposal-ids.db")
    await complete_position_zero(fixture)
    await establish_lossy_record(fixture, source_amount=8)
    await fixture.select("planner")
    action = ProposeCirculationAction(
        action="propose_circulation",
        source_entity_id="veil",
        recipient_entity_id="nursery",
        resource_id="water",
        source_amount=8,
        pathway_entity_id="route seven",
        relay_entity_id="relay",
        delivered_amount=6,
        maintenance="maintain the Veil collection surface",
        reassessment="reassess Nursery demand before the next cycle",
        branch_condition="if Nursery demand changes",
        branch_action="revise delivery and release unused condensation",
    )

    assert (await fixture.act(action)).accepted
    assert (await fixture.act(action)).accepted
    state = await fixture.repository.state(fixture.refs[Environment.TEST])
    assert list(state["data"]["proposals"]) == [
        "circulation-loss-accounted",
        "circulation-loss-accounted-2",
    ]
    await fixture.database.dispose()


@pytest.mark.asyncio
async def test_circulation_stack_resolves_last_in_first_out(tmp_path: Path) -> None:
    fixture = await build_game(tmp_path / "stack.db")
    await complete_position_zero(fixture)
    await establish_circulation_record(fixture)
    base = {
        "kind": "circulation",
        "source_entity_id": "veil",
        "recipient_entity_id": "nursery",
        "resource_id": "water",
        "source_amount": 9,
        "pathway_entity_id": "route seven",
        "relay_entity_id": "relay",
        "delivered_amount": 9,
        "maintenance": "maintain the Veil each cycle",
        "reassessment": "reassess demand and output before the next cycle",
        "branch_condition": "",
        "branch_action": "",
    }
    await fixture.select("planner")
    opened = await fixture.act(BeginStackAction(action="begin_stack", proposal=base))
    assert opened.accepted
    state = await fixture.repository.state(fixture.refs[Environment.TEST])
    stack_id = state["data"]["public_stack"]["stack_id"]

    await fixture.select("observer")
    assert (
        await fixture.act(
            ReactToStackAction(
                action="react_to_stack",
                stack_id=stack_id,
                reaction="reassess_demand",
                detail="branch when Nursery demand changes",
            )
        )
    ).accepted
    await fixture.select("maintainer")
    assert (
        await fixture.act(
            ReactToStackAction(
                action="react_to_stack",
                stack_id=stack_id,
                reaction="stabilize_relay",
                detail="maintain same-cycle forwarding",
            )
        )
    ).accepted
    await fixture.select("router")
    resolved = await fixture.act(ResolveStackAction(action="resolve_stack", stack_id=stack_id))
    assert resolved.accepted
    assert (
        "stabilize Central Relay -> reassess Nursery demand -> attempt circulation" in resolved.text
    )
    state = await fixture.repository.state(fixture.refs[Environment.TEST])
    assert state["data"]["public_stack"]["status"] == "resolved"
    proposal_id = state["data"]["public_stack"]["proposal_id"]
    assert state["data"]["proposals"][proposal_id]["branch_condition"]
    await fixture.database.dispose()


@pytest.mark.asyncio
async def test_circulation_kickers_add_branch_and_documentation(tmp_path: Path) -> None:
    fixture = await build_game(tmp_path / "kickers.db")
    await complete_position_zero(fixture)
    await establish_circulation_record(fixture)
    await fixture.select("router")
    assert (
        await fixture.act(
            CalculateFlowAction(
                action="calculate_flow", source_amount=6, pathway_entity_id="route seven"
            )
        )
    ).accepted
    await fixture.select("planner")
    assert (
        await fixture.act(
            ProposeCirculationAction(
                action="propose_circulation",
                source_entity_id="veil",
                recipient_entity_id="nursery",
                resource_id="water",
                source_amount=6,
                pathway_entity_id="route seven",
                relay_entity_id="relay",
                delivered_amount=6,
                maintenance="maintain the collection surface",
                reassessment="reassess Nursery demand before the next cycle",
            )
        )
    ).accepted
    state = await fixture.repository.state(fixture.refs[Environment.TEST])
    proposal_id = next(
        key for key, item in state["data"]["proposals"].items() if item.get("kind") == "circulation"
    )
    await fixture.select("observer")
    assert (
        await fixture.act(
            AddProposalKickerAction(
                action="add_proposal_kicker",
                proposal_id=proposal_id,
                kicker="adaptive_branch",
                detail="if Nursery demand or Veil output changes",
            )
        )
    ).accepted
    await fixture.select("maintainer")
    assert (
        await fixture.act(
            AddProposalKickerAction(
                action="add_proposal_kicker",
                proposal_id=proposal_id,
                kicker="document_flow",
                detail="record source, delivery, and reassessment",
            )
        )
    ).accepted
    await fixture.select("router")
    assert (
        await fixture.act(
            AddProposalKickerAction(
                action="add_proposal_kicker",
                proposal_id=proposal_id,
                kicker="monitoring",
                detail="monitor unused output at the dried central basin",
            )
        )
    ).accepted
    await fixture.select("observer")
    assert (
        await fixture.act(
            ConfirmReconstructionAction(action="confirm_reconstruction", proposal_id=proposal_id)
        )
    ).accepted
    state = await fixture.repository.state(fixture.refs[Environment.TEST])
    assert state["data"]["counters"]["coherence"] == 1
    assert state["data"]["resources"]["first_bloom_basin"]["water"] == 3
    assert "first_bloom_monitoring" in state["data"]["persistent_effects"]
    await fixture.database.dispose()
