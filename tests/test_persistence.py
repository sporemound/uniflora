from __future__ import annotations

from pathlib import Path

import pytest

from uniflora.runtime import Environment, RoutingSnapshot, SessionMode
from uniflora.storage.database import Database
from uniflora.storage.repository import (
    GameRepository,
    MutationPlan,
    SessionRef,
    SessionScopeError,
    StorageError,
    UnsafeImport,
)


def database_url(path: Path) -> str:
    return f"sqlite+aiosqlite:///{path.as_posix()}"


async def initialized_repository(
    path: Path,
) -> tuple[Database, GameRepository, dict[Environment, SessionRef]]:
    database = Database(database_url(path))
    await database.create_schema_for_tests()
    repository = GameRepository(database)
    _, refs = await repository.bootstrap(RoutingSnapshot(1, 10, 20, 30, frozenset({99})))
    return database, repository, refs


def marker_plan(state: dict[str, object], marker: str) -> MutationPlan:
    data = dict(state["data"])  # type: ignore[arg-type]
    data["marker"] = marker
    after = dict(state)
    after["data"] = data
    return MutationPlan("test.marker", after, {"marker": marker}, "observer")


@pytest.mark.asyncio
async def test_live_and_test_survive_restart_independently(tmp_path: Path) -> None:
    path = tmp_path / "restart.db"
    database, repository, refs = await initialized_repository(path)
    await repository.transition(
        refs[Environment.TEST], SessionMode.RUNNING, {SessionMode.LOCKED}, "discord:99"
    )
    live_id = refs[Environment.LIVE].session_id
    test_id = refs[Environment.TEST].session_id
    await database.dispose()

    reopened = Database(database_url(path))
    recovered_repository = GameRepository(reopened)
    recovered_routing, recovered_refs = await recovered_repository.bootstrap(
        RoutingSnapshot(1, 999, 998, 997, frozenset({99}))
    )
    assert recovered_refs[Environment.LIVE].session_id == live_id
    assert recovered_refs[Environment.TEST].session_id == test_id
    assert (await recovered_repository.state(recovered_refs[Environment.LIVE]))["mode"] == "locked"
    assert (await recovered_repository.state(recovered_refs[Environment.TEST]))["mode"] == "running"
    assert recovered_routing.live_channel_id == 10
    assert recovered_routing.test_channel_id == 20
    await reopened.dispose()


@pytest.mark.asyncio
async def test_reset_test_does_not_change_live(tmp_path: Path) -> None:
    database, repository, refs = await initialized_repository(tmp_path / "reset.db")
    await repository.mutate(
        refs[Environment.LIVE],
        actor_id="discord:1",
        idempotency_key="live-1",
        planner=lambda state: marker_plan(state, "live-value"),
    )
    await repository.mutate(
        refs[Environment.TEST],
        actor_id="test:observer",
        idempotency_key="test-1",
        planner=lambda state: marker_plan(state, "test-value"),
    )
    await repository.reset(refs[Environment.TEST], "discord:99")
    assert (await repository.state(refs[Environment.LIVE]))["data"]["marker"] == "live-value"
    assert "marker" not in (await repository.state(refs[Environment.TEST]))["data"]
    await database.dispose()


@pytest.mark.asyncio
async def test_reset_live_does_not_change_test(tmp_path: Path) -> None:
    database, repository, refs = await initialized_repository(tmp_path / "live-reset.db")
    await repository.mutate(
        refs[Environment.TEST],
        actor_id="test:observer",
        idempotency_key="test-marker",
        planner=lambda state: marker_plan(state, "preserved-test"),
    )
    await repository.mutate(
        refs[Environment.LIVE],
        actor_id="discord:1",
        idempotency_key="live-marker",
        planner=lambda state: marker_plan(state, "discarded-live"),
    )
    await repository.reset(refs[Environment.LIVE], "discord:99")
    assert (await repository.state(refs[Environment.TEST]))["data"]["marker"] == ("preserved-test")
    assert "marker" not in (await repository.state(refs[Environment.LIVE]))["data"]
    await database.dispose()


@pytest.mark.asyncio
async def test_idempotency_writes_one_environment_labeled_event(tmp_path: Path) -> None:
    database, repository, refs = await initialized_repository(tmp_path / "idempotency.db")
    ref = refs[Environment.TEST]
    first = await repository.mutate(
        ref,
        actor_id="test:observer",
        idempotency_key="discord-message:123",
        planner=lambda state: marker_plan(state, "once"),
    )
    second = await repository.mutate(
        ref,
        actor_id="test:observer",
        idempotency_key="discord-message:123",
        planner=lambda state: marker_plan(state, "twice"),
    )
    events = await repository.list_events(ref)
    action_events = [event for event in events if event["event_type"] == "test.marker"]
    assert first.event_id == second.event_id
    assert second.duplicate is True
    assert len(action_events) == 1
    assert action_events[0]["environment"] == "test"
    assert action_events[0]["session_id"] == ref.session_id
    await database.dispose()


@pytest.mark.asyncio
async def test_mismatched_environment_ref_is_rejected(tmp_path: Path) -> None:
    database, repository, refs = await initialized_repository(tmp_path / "scope.db")
    forged = SessionRef(refs[Environment.TEST].session_id, Environment.LIVE)
    with pytest.raises(SessionScopeError):
        await repository.state(forged)
    await database.dispose()


@pytest.mark.asyncio
async def test_checkpoint_rollback_restores_state_and_appends_event(tmp_path: Path) -> None:
    database, repository, refs = await initialized_repository(tmp_path / "rollback.db")
    ref = refs[Environment.TEST]
    await repository.mutate(
        ref,
        actor_id="test:observer",
        idempotency_key="marker:first",
        planner=lambda state: marker_plan(state, "first"),
    )
    checkpoint_id = await repository.create_checkpoint(ref, "known-good", "discord:99")
    await repository.mutate(
        ref,
        actor_id="test:carrier",
        idempotency_key="marker:second",
        planner=lambda state: marker_plan(state, "second"),
    )
    await repository.rollback_to_checkpoint(ref, checkpoint_id, "discord:99")
    assert (await repository.state(ref))["data"]["marker"] == "first"
    assert (await repository.list_events(ref))[-1]["event_type"] == "admin.rollback"
    await database.dispose()


@pytest.mark.asyncio
async def test_event_rollback_cannot_target_other_environment(tmp_path: Path) -> None:
    database, repository, refs = await initialized_repository(tmp_path / "event-rollback.db")
    live_result = await repository.mutate(
        refs[Environment.LIVE],
        actor_id="discord:1",
        idempotency_key="live:event",
        planner=lambda state: marker_plan(state, "live"),
    )
    with pytest.raises(StorageError, match="does not exist in this session"):
        await repository.rollback_to_event(
            refs[Environment.TEST], live_result.event_id or "", "discord:99"
        )
    assert "marker" not in (await repository.state(refs[Environment.TEST]))["data"]
    await database.dispose()


@pytest.mark.asyncio
async def test_export_is_labeled_and_cross_environment_import_is_guarded(tmp_path: Path) -> None:
    database, repository, refs = await initialized_repository(tmp_path / "export.db")
    test_export = await repository.export_state(refs[Environment.TEST])
    assert test_export["environment"] == "test"
    assert test_export["session_id"] == refs[Environment.TEST].session_id
    with pytest.raises(UnsafeImport, match="refusing"):
        await repository.import_state(refs[Environment.LIVE], test_export, "discord:99")
    imported = await repository.import_state(
        refs[Environment.LIVE],
        test_export,
        "discord:99",
        allow_cross_environment=True,
    )
    assert imported.accepted
    assert (await repository.state(refs[Environment.LIVE]))["modified_by_force"] is True
    await database.dispose()


@pytest.mark.asyncio
async def test_import_rejects_out_of_range_position(tmp_path: Path) -> None:
    database, repository, refs = await initialized_repository(tmp_path / "invalid-import.db")
    document = await repository.export_state(refs[Environment.TEST])
    document["state"]["current_position"] = 999
    with pytest.raises(UnsafeImport, match="between 0 and 6"):
        await repository.import_state(refs[Environment.TEST], document, "discord:99")
    assert (await repository.state(refs[Environment.TEST]))["current_position"] == 0
    await database.dispose()


@pytest.mark.asyncio
async def test_simulated_identities_are_test_only(tmp_path: Path) -> None:
    database, repository, refs = await initialized_repository(tmp_path / "identity.db")
    test_ref = refs[Environment.TEST]
    identities = await repository.list_test_identities(test_ref)
    assert {item["participant_id"] for item in identities} >= {
        "test:observer",
        "test:carrier",
        "test:binder",
    }
    selected = await repository.select_test_identity(test_ref, "observer", 99)
    assert selected == "test:observer"
    assert await repository.resolve_participant(test_ref, 99) == "test:observer"
    assert await repository.resolve_participant(refs[Environment.LIVE], 99) == "discord:99"
    with pytest.raises(SessionScopeError):
        await repository.create_test_identity(refs[Environment.LIVE], "helper", 99)
    await database.dispose()
