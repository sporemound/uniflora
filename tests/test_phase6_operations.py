from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from uniflora.backup import BackupService
from uniflora.config import Settings
from uniflora.content.loader import PuzzleRegistry
from uniflora.engine.actions import (
    BeginStackAction,
    ConfirmReconstructionAction,
    ConnectAction,
    ObserveAction,
    ProposeReconstructionAction,
)
from uniflora.engine.core import DeterministicEngine
from uniflora.engine.position_zero import EnvironmentPositionValidator
from uniflora.game_service import GameService
from uniflora.narration import FallbackNarrator
from uniflora.operations import OperationsService
from uniflora.persistent_runtime import PersistentRouting, PersistentRuntimeSessions
from uniflora.runtime import Environment, RoutingSnapshot, SessionMode
from uniflora.storage.database import Database
from uniflora.storage.models import NarrationHistory, UnlockedObservation
from uniflora.storage.repository import (
    GameRepository,
    MutationPlan,
    SessionRef,
    SessionScopeError,
    StorageError,
    UnsafeImport,
)


def settings(tmp_path: Path, **changes: Any) -> Settings:
    values: dict[str, Any] = {
        "discord_token": "fake",
        "discord_guild_id": 1,
        "live_puzzle_channel_id": 10,
        "test_puzzle_channel_id": 20,
        "mycotroph_role_id": 30,
        "admin_user_ids": "99",
        "diagnostic_channel_id": 40,
        "database_url": f"sqlite+aiosqlite:///{(tmp_path / 'game.db').as_posix()}",
        "backup_directory": str(tmp_path / "backups"),
    }
    return Settings(_env_file=None, **(values | changes))  # type: ignore[arg-type]


class Fixture:
    def __init__(
        self,
        database: Database,
        repository: GameRepository,
        refs: dict[Environment, SessionRef],
        game: GameService,
        sessions: PersistentRuntimeSessions,
        routing: PersistentRouting,
        operations: OperationsService,
        config: Settings,
    ) -> None:
        self.database = database
        self.repository = repository
        self.refs = refs
        self.game = game
        self.sessions = sessions
        self.routing = routing
        self.operations = operations
        self.config = config
        self.serial = 0

    async def act(self, slug: str, action: object) -> Any:
        await self.repository.select_test_identity(self.refs[Environment.TEST], slug, 99)
        self.serial += 1
        return await self.game.act(
            Environment.TEST,
            99,
            action,  # type: ignore[arg-type]
            f"phase6:{self.serial}",
        )


async def build_fixture(tmp_path: Path, **changes: Any) -> Fixture:
    config = settings(tmp_path, **changes)
    database = Database(config.database_url)
    await database.create_schema_for_tests()
    repository = GameRepository(database)
    persisted, refs = await repository.bootstrap(
        RoutingSnapshot(1, 10, 20, 30, frozenset({99}), 40)
    )
    registry = PuzzleRegistry.load_packaged()
    fallback = FallbackNarrator()
    validator = EnvironmentPositionValidator(registry.get(0), enforce_cycles=False)
    game = GameService(
        repository,
        refs,
        registry,
        DeterministicEngine(repository, validator),
        fallback,
        validator,
        None,
        config.player_action_cooldown_seconds,
    )
    await game.initialize()
    sessions = PersistentRuntimeSessions(repository, refs)
    routing = PersistentRouting(persisted, repository)
    operations = OperationsService(config, database, repository, refs, game, sessions, routing)
    return Fixture(database, repository, refs, game, sessions, routing, operations, config)


def reconstruction() -> ProposeReconstructionAction:
    return ProposeReconstructionAction(
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


async def complete_clean_test(fixture: Fixture) -> None:
    await fixture.sessions.start(Environment.TEST, "discord:99")
    assert (
        await fixture.act("observer", ObserveAction(action="observe", entity_id="north"))
    ).accepted
    assert (
        await fixture.act("carrier", ObserveAction(action="observe", entity_id="east"))
    ).accepted
    assert (await fixture.act("binder", ObserveAction(action="observe", entity_id="path"))).accepted
    assert (
        await fixture.act(
            "binder",
            ConnectAction(action="connect", source_entity_id="north", target_entity_id="east"),
        )
    ).accepted
    assert (await fixture.act("observer", reconstruction())).accepted
    state = await fixture.repository.state(fixture.refs[Environment.TEST])
    proposal_id = next(iter(state["data"]["proposals"]))
    assert (
        await fixture.act(
            "carrier",
            ConfirmReconstructionAction(action="confirm_reconstruction", proposal_id=proposal_id),
        )
    ).accepted


@pytest.mark.asyncio
async def test_readiness_requires_clean_test_backup_and_pristine_live(tmp_path: Path) -> None:
    fixture = await build_fixture(tmp_path)
    await fixture.routing.set_diagnostic_channel(None)
    initial = await fixture.operations.live_readiness()
    assert not initial.ready
    assert not initial.checks["channels"]
    assert not initial.checks["clean_test_completion"]
    assert not initial.checks["backup"]

    await fixture.routing.set_diagnostic_channel(40)
    await complete_clean_test(fixture)
    await fixture.game.reset_test(99)
    backup = BackupService(
        fixture.database,
        fixture.repository,
        Path(fixture.config.backup_directory),
        enabled=True,
        interval_hours=24,
    )
    result = await backup.run_once()
    assert result.successful and result.path is not None
    assert await asyncio.to_thread(Path(result.path).exists)
    report = await fixture.operations.live_readiness()
    assert report.ready
    assert report.checks["clean_test_completion"]
    assert report.checks["live_initial"]
    assert "Live readiness: READY" in report.text

    cancelled = await fixture.operations.start_live(99, confirm=False)
    assert not cancelled.accepted
    assert (await fixture.sessions.snapshot(Environment.LIVE)).mode is SessionMode.LOCKED
    launched = await fixture.operations.start_live(99, confirm=True)
    assert launched.accepted
    assert (await fixture.sessions.snapshot(Environment.LIVE)).mode is SessionMode.RUNNING
    await fixture.database.dispose()


@pytest.mark.asyncio
async def test_readiness_rejects_force_modified_test_and_changed_live(tmp_path: Path) -> None:
    fixture = await build_fixture(tmp_path)
    await complete_clean_test(fixture)
    await fixture.game.reset_test(99)
    await fixture.game.force_observation("western_loss", 99)
    await fixture.repository.mutate(
        fixture.refs[Environment.LIVE],
        actor_id="audit-contamination",
        idempotency_key="contaminate-live",
        planner=lambda state: MutationPlan(
            event_type="test.live_contaminated",
            state_after={
                **state,
                "data": {**state["data"], "unlocked_observations": ["unexpected"]},
            },
            payload={},
        ),
    )
    report = await fixture.operations.live_readiness()
    assert not report.ready
    assert not report.checks["test_not_force_modified"]
    assert not report.checks["live_initial"]
    assert "test modified by force: yes" in report.text
    await fixture.database.dispose()


@pytest.mark.asyncio
async def test_runtime_controls_are_environment_scoped_and_persistent(tmp_path: Path) -> None:
    fixture = await build_fixture(tmp_path)
    await fixture.operations.set_model(Environment.TEST, "narration", "test-model", 99)
    await fixture.operations.set_api_budget(Environment.TEST, "daily", 0.5, 1.0, 99)
    await fixture.operations.fallback_mode(Environment.TEST, True, 99)
    await fixture.operations.set_feature(Environment.TEST, "tactical_stack", False, 99)
    test = await fixture.repository.runtime_control(fixture.refs[Environment.TEST])
    live = await fixture.repository.runtime_control(fixture.refs[Environment.LIVE])
    assert test["narration_model"] == "test-model"
    assert test["budget_overrides"]["hard_daily"] == 1.0
    assert test["fallback_mode"] is True
    assert test["feature_flags"]["tactical_stack"] is False
    assert live["narration_model"] is None
    assert live["budget_overrides"] == {}
    assert live["fallback_mode"] is False
    assert live["feature_flags"]["tactical_stack"] is True
    await fixture.database.dispose()


@pytest.mark.asyncio
async def test_repeated_api_failures_activate_only_the_selected_environment(
    tmp_path: Path,
) -> None:
    fixture = await build_fixture(tmp_path)
    for _ in range(3):
        await fixture.repository.record_api_result(
            fixture.refs[Environment.TEST], success=False, failure_threshold=3
        )
    test = await fixture.repository.runtime_control(fixture.refs[Environment.TEST])
    live = await fixture.repository.runtime_control(fixture.refs[Environment.LIVE])
    assert test["fallback_mode"] is True
    assert test["consecutive_api_failures"] == 3
    assert live["fallback_mode"] is False
    await fixture.database.dispose()


@pytest.mark.asyncio
async def test_invalidation_rebuilds_projections_and_retry_is_typed(tmp_path: Path) -> None:
    fixture = await build_fixture(tmp_path)
    await fixture.sessions.start(Environment.TEST, "discord:99")
    observed = await fixture.act("observer", ObserveAction(action="observe", entity_id="north"))
    assert observed.accepted and observed.event_id
    await fixture.sessions.pause(Environment.TEST, "discord:99")
    invalidated = await fixture.operations.invalidate(
        Environment.TEST, observed.event_id, 99, confirm=True
    )
    assert invalidated.accepted
    state = await fixture.repository.state(fixture.refs[Environment.TEST])
    assert state["mode"] == SessionMode.PAUSED.value
    assert state["data"]["unlocked_observations"] == []
    assert (
        await fixture.repository.count_rows(fixture.refs[Environment.TEST], UnlockedObservation)
        == 0
    )
    await fixture.sessions.resume(Environment.TEST, "discord:99")
    retried = await fixture.operations.retry_event(
        Environment.TEST, observed.event_id, 99, confirm=True
    )
    assert retried.accepted
    state = await fixture.repository.state(fixture.refs[Environment.TEST])
    assert state["data"]["unlocked_observations"] == ["northern_usable_capacity"]
    await fixture.database.dispose()


@pytest.mark.asyncio
async def test_retry_requires_prior_invalidation(tmp_path: Path) -> None:
    fixture = await build_fixture(tmp_path)
    await fixture.sessions.start(Environment.TEST, "discord:99")
    observed = await fixture.act("observer", ObserveAction(action="observe", entity_id="north"))
    with pytest.raises(StorageError, match="invalidate"):
        await fixture.operations.retry_event(
            Environment.TEST,
            observed.event_id,
            99,
            confirm=True,  # type: ignore[arg-type]
        )
    await fixture.database.dispose()


@pytest.mark.asyncio
async def test_feature_flag_and_player_cooldown_are_enforced(tmp_path: Path) -> None:
    fixture = await build_fixture(tmp_path, player_action_cooldown_seconds=30)
    await fixture.sessions.start(Environment.TEST, "discord:99")
    await fixture.operations.set_feature(Environment.TEST, "tactical_stack", False, 99)
    stack = await fixture.act(
        "observer",
        BeginStackAction(
            action="begin_stack",
            proposal={
                "donor_id": "north",
                "recipient_id": "east",
                "resource_id": "water",
                "amount": 5,
                "pathway_id": "path",
                "pathway_action": "repair",
                "maintenance_condition": "monitor next cycle",
            },
        ),
    )
    assert not stack.accepted and "disabled" in stack.text
    first = await fixture.act("carrier", ObserveAction(action="observe", entity_id="north"))
    second = await fixture.act("carrier", ObserveAction(action="observe", entity_id="east"))
    assert first.accepted
    assert second.accepted

    await fixture.sessions.start(Environment.LIVE, "discord:99")
    live_first = await fixture.game.act(
        Environment.LIVE,
        101,
        ObserveAction(action="observe", entity_id="north"),
        "phase6:live-cooldown:1",
    )
    live_second = await fixture.game.act(
        Environment.LIVE,
        101,
        ObserveAction(action="observe", entity_id="east"),
        "phase6:live-cooldown:2",
    )
    assert live_first.accepted
    assert not live_second.accepted and "settling" in live_second.text
    await fixture.database.dispose()


@pytest.mark.asyncio
async def test_checkpoint_and_forced_test_controls_preserve_live_isolation(tmp_path: Path) -> None:
    fixture = await build_fixture(tmp_path)
    await fixture.sessions.start(Environment.TEST, "discord:99")
    assert (
        await fixture.act("observer", ObserveAction(action="observe", entity_id="north"))
    ).accepted
    checkpoint = await fixture.operations.test_checkpoint("after-north", 99)
    assert checkpoint.accepted and checkpoint.event_id
    assert (
        await fixture.act("carrier", ObserveAction(action="observe", entity_id="east"))
    ).accepted
    await fixture.sessions.pause(Environment.TEST, "discord:99")
    restored = await fixture.operations.test_rollback_checkpoint(
        checkpoint.event_id, 99, confirm=True
    )
    assert restored.accepted
    state = await fixture.repository.state(fixture.refs[Environment.TEST])
    assert state["data"]["unlocked_observations"] == ["northern_usable_capacity"]

    position = await fixture.operations.set_test_position(1, 99, confirm=True)
    profile = await fixture.operations.set_test_profile("local_correlation", 99, confirm=True)
    forced = await fixture.operations.force_test_event(
        "fixture.marker", "exercise an administrative fixture", 99, confirm=True
    )
    gpt = await fixture.operations.set_test_gpt(False, 99)
    assert all(item.accepted for item in (position, profile, forced, gpt))
    state = await fixture.repository.state(fixture.refs[Environment.TEST])
    assert state["current_position"] == 1
    assert state["response_profile"] == "local_correlation"
    assert state["modified_by_force"] is True
    live = await fixture.repository.state(fixture.refs[Environment.LIVE])
    assert live["current_position"] == 0
    assert live["response_profile"] == "surface_noise"
    live_control = await fixture.repository.runtime_control(fixture.refs[Environment.LIVE])
    assert live_control["feature_flags"]["natural_language"] is True
    with pytest.raises(SessionScopeError):
        await fixture.repository.force_test_event(
            fixture.refs[Environment.LIVE],
            label="invalid.live",
            note="must not enter live",
            actor_id="discord:99",
        )
    await fixture.database.dispose()


@pytest.mark.asyncio
async def test_test_import_is_paused_scoped_modified_and_rebuilds_projections(
    tmp_path: Path,
) -> None:
    fixture = await build_fixture(tmp_path)
    await fixture.sessions.start(Environment.TEST, "discord:99")
    assert (
        await fixture.act("observer", ObserveAction(action="observe", entity_id="north"))
    ).accepted
    await fixture.sessions.pause(Environment.TEST, "discord:99")
    document = await fixture.repository.export_state(fixture.refs[Environment.TEST])

    await fixture.game.reset_test(99)
    await fixture.sessions.start(Environment.TEST, "discord:99")
    await fixture.sessions.pause(Environment.TEST, "discord:99")
    imported = await fixture.operations.import_test(document, 99, confirm=True)
    assert imported.accepted
    state = await fixture.repository.state(fixture.refs[Environment.TEST])
    assert state["modified_by_force"] is True
    assert state["data"]["unlocked_observations"] == ["northern_usable_capacity"]
    assert (
        await fixture.repository.count_rows(fixture.refs[Environment.TEST], UnlockedObservation)
        == 1
    )

    live_document = await fixture.repository.export_state(fixture.refs[Environment.LIVE])
    with pytest.raises(UnsafeImport, match="refusing"):
        await fixture.operations.import_test(live_document, 99, confirm=True)
    await fixture.database.dispose()


@pytest.mark.asyncio
async def test_clear_test_history_preserves_events_and_live_history(tmp_path: Path) -> None:
    fixture = await build_fixture(tmp_path)
    for environment in Environment:
        ref = fixture.refs[environment]
        await fixture.repository.record_narration(
            ref,
            event_id=f"event:{environment.value}",
            profile="surface_noise",
            public_text="public fixture",
            generated_by="fallback",
        )
    result = await fixture.operations.clear_test_history(99, confirm=True)
    assert result.accepted
    assert (
        await fixture.repository.count_rows(fixture.refs[Environment.TEST], NarrationHistory) == 0
    )
    events = await fixture.repository.list_events(fixture.refs[Environment.TEST])
    assert events[-1]["event_type"] == "admin.test_history.cleared"
    await fixture.database.dispose()
