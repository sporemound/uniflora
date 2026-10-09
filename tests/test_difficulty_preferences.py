from __future__ import annotations

from pathlib import Path

import pytest

from uniflora.difficulty import DifficultyLevel
from uniflora.runtime import Environment, RoutingSnapshot
from uniflora.storage.database import Database
from uniflora.storage.models import DifficultySelectionEvent
from uniflora.storage.repository import (
    DifficultyBallotConflict,
    DifficultyBallotInactive,
    GameRepository,
    SessionRef,
)


def database_url(path: Path) -> str:
    return f"sqlite+aiosqlite:///{path.as_posix()}"


async def initialized_repository(
    path: Path,
) -> tuple[Database, GameRepository, dict[Environment, SessionRef]]:
    database = Database(database_url(path))
    await database.create_schema_for_tests()
    repository = GameRepository(database)
    _, refs = await repository.bootstrap(
        RoutingSnapshot(
            guild_id=1,
            live_channel_id=10,
            test_channel_id=20,
            mycotroph_role_id=30,
            admin_user_ids=frozenset({99}),
        )
    )
    return database, repository, refs


@pytest.mark.asyncio
async def test_difficulty_defaults_to_standard_and_is_environment_scoped(
    tmp_path: Path,
) -> None:
    database, repository, refs = await initialized_repository(
        tmp_path / "difficulty-default.db"
    )
    test_preference = await repository.difficulty_preference(
        refs[Environment.TEST],
        99,
    )
    live_preference = await repository.difficulty_preference(
        refs[Environment.LIVE],
        99,
    )

    assert test_preference.level is DifficultyLevel.STANDARD
    assert test_preference.revision == 0
    assert live_preference == test_preference
    await database.dispose()


@pytest.mark.asyncio
async def test_live_selection_does_not_change_test_preference(tmp_path: Path) -> None:
    database, repository, refs = await initialized_repository(
        tmp_path / "difficulty-live.db"
    )
    try:
        live_ref = refs[Environment.LIVE]
        await repository.open_difficulty_ballot(
            live_ref, guild_id=1, channel_id=10, message_id=400,
        )
        selection = await repository.record_difficulty_selection(
            live_ref,
            guild_id=1,
            channel_id=10,
            message_id=400,
            discord_user_id=99,
            discord_interaction_id=501,
            level=DifficultyLevel.GUIDED,
        )
        assert selection.preference.level is DifficultyLevel.GUIDED
        assert await repository.difficulty_preferences(live_ref) == ((99, "guided", 1),)
        assert await repository.difficulty_preferences(refs[Environment.TEST]) == ()
        assert (await repository.difficulty_preference(
            refs[Environment.TEST], 99,
        )).level is DifficultyLevel.STANDARD
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_selection_is_private_idempotent_revisable_and_persistent(
    tmp_path: Path,
) -> None:
    database, repository, refs = await initialized_repository(
        tmp_path / "difficulty-selection.db"
    )
    ref = refs[Environment.TEST]
    ballot = await repository.open_difficulty_ballot(
        ref,
        guild_id=1,
        channel_id=20,
        message_id=400,
    )

    first = await repository.record_difficulty_selection(
        ref,
        guild_id=1,
        channel_id=20,
        message_id=400,
        discord_user_id=99,
        discord_interaction_id=501,
        level=DifficultyLevel.GUIDED,
    )
    duplicate = await repository.record_difficulty_selection(
        ref,
        guild_id=1,
        channel_id=20,
        message_id=400,
        discord_user_id=99,
        discord_interaction_id=501,
        level=DifficultyLevel.GUIDED,
    )
    same_value = await repository.record_difficulty_selection(
        ref,
        guild_id=1,
        channel_id=20,
        message_id=400,
        discord_user_id=99,
        discord_interaction_id=502,
        level=DifficultyLevel.GUIDED,
    )
    revised = await repository.record_difficulty_selection(
        ref,
        guild_id=1,
        channel_id=20,
        message_id=400,
        discord_user_id=99,
        discord_interaction_id=503,
        level=DifficultyLevel.EXPERT,
    )

    assert first.changed and not first.duplicate
    assert first.preference.revision == 1
    assert duplicate.duplicate and not duplicate.changed
    assert duplicate.preference == first.preference
    assert not same_value.changed and not same_value.duplicate
    assert revised.changed and revised.preference.revision == 2
    assert revised.preference.level is DifficultyLevel.EXPERT
    assert await repository.difficulty_ballot_response_count(ref, ballot.ballot_id) == 1
    assert await repository.count_rows(ref, DifficultySelectionEvent) == 2

    await database.dispose()

    reopened = Database(database_url(tmp_path / "difficulty-selection.db"))
    recovered = GameRepository(reopened)
    preference = await recovered.difficulty_preference(ref, 99)
    assert preference.level is DifficultyLevel.EXPERT
    assert preference.revision == 2
    await reopened.dispose()


@pytest.mark.asyncio
async def test_selector_requires_the_exact_open_hypha_message(
    tmp_path: Path,
) -> None:
    database, repository, refs = await initialized_repository(
        tmp_path / "difficulty-binding.db"
    )
    ref = refs[Environment.TEST]
    await repository.open_difficulty_ballot(
        ref,
        guild_id=1,
        channel_id=20,
        message_id=600,
    )

    for changed_scope in (
        {"guild_id": 2, "channel_id": 20, "message_id": 600},
        {"guild_id": 1, "channel_id": 21, "message_id": 600},
        {"guild_id": 1, "channel_id": 20, "message_id": 601},
    ):
        with pytest.raises(DifficultyBallotInactive):
            await repository.record_difficulty_selection(
                ref,
                **changed_scope,
                discord_user_id=99,
                discord_interaction_id=700 + changed_scope["message_id"],
                level=DifficultyLevel.GUIDED,
            )

    assert (await repository.difficulty_preference(ref, 99)).revision == 0
    await database.dispose()


@pytest.mark.asyncio
async def test_close_is_authoritative_and_new_selector_preserves_preference(
    tmp_path: Path,
) -> None:
    database, repository, refs = await initialized_repository(
        tmp_path / "difficulty-close.db"
    )
    ref = refs[Environment.TEST]
    await repository.open_difficulty_ballot(
        ref,
        guild_id=1,
        channel_id=20,
        message_id=800,
    )
    await repository.record_difficulty_selection(
        ref,
        guild_id=1,
        channel_id=20,
        message_id=800,
        discord_user_id=99,
        discord_interaction_id=801,
        level=DifficultyLevel.GUIDED,
    )

    with pytest.raises(DifficultyBallotConflict):
        await repository.open_difficulty_ballot(
            ref,
            guild_id=1,
            channel_id=20,
            message_id=802,
        )

    closed = await repository.close_difficulty_ballot(ref)
    assert closed.status == "closed"
    with pytest.raises(DifficultyBallotInactive):
        await repository.record_difficulty_selection(
            ref,
            guild_id=1,
            channel_id=20,
            message_id=800,
            discord_user_id=99,
            discord_interaction_id=803,
            level=DifficultyLevel.EXPERT,
        )

    reopened = await repository.open_difficulty_ballot(
        ref,
        guild_id=1,
        channel_id=20,
        message_id=804,
    )
    assert reopened.status == "open"
    assert (await repository.difficulty_preference(ref, 99)).level is DifficultyLevel.GUIDED
    await database.dispose()


@pytest.mark.asyncio
async def test_invalid_difficulty_never_mutates_preference(tmp_path: Path) -> None:
    database, repository, refs = await initialized_repository(
        tmp_path / "difficulty-invalid.db"
    )
    ref = refs[Environment.TEST]
    await repository.open_difficulty_ballot(
        ref,
        guild_id=1,
        channel_id=20,
        message_id=900,
    )
    with pytest.raises(ValueError, match="difficulty must be one of"):
        await repository.record_difficulty_selection(
            ref,
            guild_id=1,
            channel_id=20,
            message_id=900,
            discord_user_id=99,
            discord_interaction_id=901,
            level="nightmare",
        )
    assert (await repository.difficulty_preference(ref, 99)).revision == 0
    await database.dispose()
