from __future__ import annotations

from pathlib import Path

import pytest

from uniflora.content.v2 import V2InvestigationPack, load_investigation_pack
from uniflora.engine.v2 import (
    V2ApplicationError,
    V2AssignRoleCommand,
    V2OptimisticConcurrencyError,
    V2PersistentInvestigationService,
    V2ReleaseRoleCommand,
    V2SQLiteEventStore,
    V2SessionAlreadyExistsError,
)

FIXTURE_PATH = (
    Path(__file__).parent / "fixtures" / "v2" / "boundary_array_investigation" / "pack.yaml"
)


@pytest.fixture
def pack() -> V2InvestigationPack:
    return load_investigation_pack(FIXTURE_PATH)


def test_creates_and_restores_a_persisted_session(
    tmp_path: Path,
    pack: V2InvestigationPack,
) -> None:
    database = tmp_path / "events.sqlite3"

    with V2SQLiteEventStore(database) as store:
        service = V2PersistentInvestigationService(pack, store)
        created = service.create_session(
            "session",
            ["player_a", "player_b"],
        )

        assert created.accepted is True
        assert created.code == "session_created"
        assert created.event is not None
        assert created.session.sequence == 0
        assert store.latest_sequence("session") == 0

    with V2SQLiteEventStore(database) as reopened:
        restored = V2PersistentInvestigationService(
            pack,
            reopened,
        ).load_session("session")

    assert restored == created.session


def test_rejects_duplicate_session_creation(
    tmp_path: Path,
    pack: V2InvestigationPack,
) -> None:
    with V2SQLiteEventStore(tmp_path / "events.sqlite3") as store:
        service = V2PersistentInvestigationService(pack, store)
        service.create_session("session", ["player_a"])

        with pytest.raises(
            V2SessionAlreadyExistsError,
            match="already exists",
        ):
            service.create_session("session", ["player_b"])

        assert store.latest_sequence("session") == 0


def test_accepted_command_is_appended_and_restored(
    tmp_path: Path,
    pack: V2InvestigationPack,
) -> None:
    with V2SQLiteEventStore(tmp_path / "events.sqlite3") as store:
        service = V2PersistentInvestigationService(pack, store)
        service.create_session("session", ["player_a"])

        result = service.execute(
            "session",
            V2AssignRoleCommand(
                player_id="player_a",
                role_id="instrument_operator",
            ),
            expected_sequence=0,
        )

        assert result.accepted is True
        assert result.code == "role_assigned"
        assert result.event is not None
        assert result.session.sequence == 1
        assert store.latest_sequence("session") == 1
        assert service.load_session("session") == result.session


def test_rejected_command_does_not_append_an_event(
    tmp_path: Path,
    pack: V2InvestigationPack,
) -> None:
    with V2SQLiteEventStore(tmp_path / "events.sqlite3") as store:
        service = V2PersistentInvestigationService(pack, store)
        created = service.create_session("session", ["player_a"])

        result = service.execute(
            "session",
            V2ReleaseRoleCommand(player_id="player_a"),
            expected_sequence=0,
        )

        assert result.accepted is False
        assert result.code == "no_active_role"
        assert result.event is None
        assert result.session == created.session
        assert store.latest_sequence("session") == 0
        assert len(store.load_event_envelopes("session")) == 1


def test_stale_expected_sequence_is_rejected(
    tmp_path: Path,
    pack: V2InvestigationPack,
) -> None:
    database = tmp_path / "events.sqlite3"

    with V2SQLiteEventStore(database) as first_store:
        first = V2PersistentInvestigationService(pack, first_store)
        first.create_session("session", ["player_a"])

    with V2SQLiteEventStore(database) as second_store:
        second = V2PersistentInvestigationService(pack, second_store)
        second.execute(
            "session",
            V2AssignRoleCommand(
                player_id="player_a",
                role_id="instrument_operator",
            ),
            expected_sequence=0,
        )

    with V2SQLiteEventStore(database) as stale_store:
        stale = V2PersistentInvestigationService(pack, stale_store)

        with pytest.raises(
            V2OptimisticConcurrencyError,
            match="expected sequence 0, actual sequence 1",
        ):
            stale.execute(
                "session",
                V2ReleaseRoleCommand(player_id="player_a"),
                expected_sequence=0,
            )

        assert stale_store.latest_sequence("session") == 1


def test_reopened_service_continues_the_same_stream(
    tmp_path: Path,
    pack: V2InvestigationPack,
) -> None:
    database = tmp_path / "events.sqlite3"

    with V2SQLiteEventStore(database) as store:
        service = V2PersistentInvestigationService(pack, store)
        service.create_session("session", ["player_a"])
        assigned = service.execute(
            "session",
            V2AssignRoleCommand(
                player_id="player_a",
                role_id="instrument_operator",
            ),
            expected_sequence=0,
        )
        assert assigned.session.sequence == 1

    with V2SQLiteEventStore(database) as reopened:
        service = V2PersistentInvestigationService(pack, reopened)
        released = service.execute(
            "session",
            V2ReleaseRoleCommand(player_id="player_a"),
            expected_sequence=1,
        )

        assert released.accepted is True
        assert released.session.sequence == 2
        assert released.session.state.get_player("player_a").active_role_id is None


def test_saves_a_verified_snapshot_for_the_current_revision(
    tmp_path: Path,
    pack: V2InvestigationPack,
) -> None:
    database = tmp_path / "events.sqlite3"

    with V2SQLiteEventStore(database) as store:
        service = V2PersistentInvestigationService(pack, store)
        service.create_session("session", ["player_a"])
        result = service.execute(
            "session",
            V2AssignRoleCommand(
                player_id="player_a",
                role_id="instrument_operator",
            ),
            expected_sequence=0,
        )
        snapshot = service.save_snapshot(
            "session",
            expected_sequence=1,
        )

        assert snapshot.sequence == 1
        assert snapshot.state == result.session.state
        assert store.load_latest_snapshot("session") == snapshot

    with V2SQLiteEventStore(database) as reopened:
        restored = V2PersistentInvestigationService(
            pack,
            reopened,
        ).load_session("session")

    assert restored.state == snapshot.state
    assert restored.sequence == snapshot.sequence


def test_refuses_to_load_a_stream_from_another_pack(
    tmp_path: Path,
    pack: V2InvestigationPack,
) -> None:
    with V2SQLiteEventStore(tmp_path / "events.sqlite3") as store:
        V2PersistentInvestigationService(pack, store).create_session(
            "session",
            ["player_a"],
        )

        other_metadata = pack.pack.model_copy(update={"id": "other_pack"})
        other_pack = pack.model_copy(update={"pack": other_metadata})
        other_service = V2PersistentInvestigationService(other_pack, store)

        with pytest.raises(
            V2ApplicationError,
            match="stream belongs to pack",
        ):
            other_service.load_session("session")
