from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from uniflora.content.v2 import V2InvestigationPack, load_investigation_pack
from uniflora.engine.v2 import (
    V2AssignRoleCommand,
    V2OptimisticConcurrencyError,
    V2PersistenceError,
    V2ReleaseRoleCommand,
    V2SQLiteEventStore,
    V2StreamNotFoundError,
    create_snapshot_envelope,
    execute_command,
    initialize_event_stream,
    restore_snapshot_tail,
    seal_event_stream,
)

FIXTURE_PATH = (
    Path(__file__).parent / "fixtures" / "v2" / "boundary_array_investigation" / "pack.yaml"
)


@pytest.fixture
def pack() -> V2InvestigationPack:
    return load_investigation_pack(FIXTURE_PATH)


def _assigned_stream(pack: V2InvestigationPack, *, stream_id: str = "session"):
    stream = initialize_event_stream(
        pack,
        ["player_a", "player_b"],
        stream_id=stream_id,
    )
    result = execute_command(
        pack,
        stream,
        V2AssignRoleCommand(
            player_id="player_a",
            role_id="instrument_operator",
        ),
    )
    assert result.accepted is True
    return result.stream


def test_appends_and_loads_an_atomic_event_batch(
    tmp_path: Path,
    pack: V2InvestigationPack,
) -> None:
    envelopes = seal_event_stream(_assigned_stream(pack))

    with V2SQLiteEventStore(tmp_path / "events.sqlite3") as store:
        recorded = store.append_event_envelopes(
            envelopes,
            expected_sequence=-1,
        )

        assert recorded == envelopes
        assert store.latest_sequence("session") == 1
        assert store.load_event_envelopes("session") == envelopes


def test_stale_expected_sequence_is_rejected(
    tmp_path: Path,
    pack: V2InvestigationPack,
) -> None:
    envelopes = seal_event_stream(_assigned_stream(pack))
    database = tmp_path / "events.sqlite3"

    with V2SQLiteEventStore(database) as first:
        first.append_event_envelopes(
            envelopes[:1],
            expected_sequence=-1,
        )

    with V2SQLiteEventStore(database) as second:
        with pytest.raises(
            V2OptimisticConcurrencyError,
            match="expected sequence -1, actual sequence 0",
        ):
            second.append_event_envelopes(
                envelopes[1:],
                expected_sequence=-1,
            )

        assert second.latest_sequence("session") == 0


def test_invalid_batch_is_rolled_back_atomically(
    tmp_path: Path,
    pack: V2InvestigationPack,
) -> None:
    envelopes = seal_event_stream(_assigned_stream(pack))
    invalid_second = envelopes[1].__class__(
        event=envelopes[1].event.__class__(
            stream_id="session",
            sequence=2,
            player_id="player_a",
            role_id="instrument_operator",
        ),
        previous_hash=envelopes[1].previous_hash,
        event_hash=envelopes[1].event_hash,
    )

    with V2SQLiteEventStore(tmp_path / "events.sqlite3") as store:
        with pytest.raises(
            V2PersistenceError,
            match="expected appended event sequence 1, received 2",
        ):
            store.append_event_envelopes(
                (envelopes[0], invalid_second),
                expected_sequence=-1,
            )

        assert store.latest_sequence("session") is None
        assert store.load_event_envelopes("session") == ()


def test_snapshot_round_trip_survives_store_reopen(
    tmp_path: Path,
    pack: V2InvestigationPack,
) -> None:
    envelopes = seal_event_stream(_assigned_stream(pack))
    snapshot = create_snapshot_envelope(envelopes)
    database = tmp_path / "events.sqlite3"

    with V2SQLiteEventStore(database) as store:
        store.append_event_envelopes(envelopes, expected_sequence=-1)
        assert store.save_snapshot(snapshot, expected_sequence=1) is True
        assert store.save_snapshot(snapshot, expected_sequence=1) is False

    with V2SQLiteEventStore(database) as reopened:
        assert reopened.load_latest_snapshot("session") == snapshot


def test_restore_without_snapshot_replays_the_full_chain(
    tmp_path: Path,
    pack: V2InvestigationPack,
) -> None:
    stream = _assigned_stream(pack)
    envelopes = seal_event_stream(stream)

    with V2SQLiteEventStore(tmp_path / "events.sqlite3") as store:
        store.append_event_envelopes(envelopes, expected_sequence=-1)
        restored = store.restore("session")

    assert restored.snapshot is None
    assert restored.tail_envelopes == envelopes
    assert restored.state == stream.state
    assert restored.last_sequence == 1


def test_restore_uses_latest_snapshot_plus_event_tail(
    tmp_path: Path,
    pack: V2InvestigationPack,
) -> None:
    assigned = _assigned_stream(pack)
    assigned_envelopes = seal_event_stream(assigned)
    snapshot = create_snapshot_envelope(assigned_envelopes)
    released_result = execute_command(
        pack,
        assigned,
        V2ReleaseRoleCommand(player_id="player_a"),
    )
    assert released_result.accepted is True
    released = released_result.stream
    released_envelopes = seal_event_stream(released)

    with V2SQLiteEventStore(tmp_path / "events.sqlite3") as store:
        store.append_event_envelopes(
            assigned_envelopes,
            expected_sequence=-1,
        )
        store.save_snapshot(snapshot, expected_sequence=1)
        store.append_event_envelopes(
            released_envelopes[2:],
            expected_sequence=1,
        )
        restored = store.restore("session")

    assert restored.snapshot == snapshot
    assert restored.tail_envelopes == released_envelopes[2:]
    assert restored.state == released.state
    assert restored.last_sequence == 2


def test_restore_snapshot_tail_rejects_a_broken_chain(
    pack: V2InvestigationPack,
) -> None:
    assigned = _assigned_stream(pack)
    assigned_envelopes = seal_event_stream(assigned)
    snapshot = create_snapshot_envelope(assigned_envelopes)
    released = execute_command(
        pack,
        assigned,
        V2ReleaseRoleCommand(player_id="player_a"),
    ).stream
    tail = seal_event_stream(released)[2:]
    broken = tail[0].__class__(
        event=tail[0].event,
        previous_hash="0" * 64,
        event_hash=tail[0].event_hash,
    )

    with pytest.raises(V2PersistenceError, match="invalid previous hash"):
        restore_snapshot_tail(snapshot, (broken,))


def test_tampered_stored_event_is_rejected(
    tmp_path: Path,
    pack: V2InvestigationPack,
) -> None:
    envelopes = seal_event_stream(_assigned_stream(pack))
    database = tmp_path / "events.sqlite3"

    with V2SQLiteEventStore(database) as store:
        store.append_event_envelopes(envelopes, expected_sequence=-1)

    connection = sqlite3.connect(database)
    row = connection.execute(
        """
        SELECT envelope_json
        FROM v2_event_envelopes
        WHERE stream_id = ? AND sequence = 1
        """,
        ("session",),
    ).fetchone()
    assert row is not None
    record = json.loads(bytes(row[0]))
    record["event"]["payload"]["role_id"] = "protocol_auditor"
    connection.execute(
        """
        UPDATE v2_event_envelopes
        SET envelope_json = ?
        WHERE stream_id = ? AND sequence = 1
        """,
        (json.dumps(record).encode(), "session"),
    )
    connection.commit()
    connection.close()

    with V2SQLiteEventStore(database) as store:
        with pytest.raises(V2PersistenceError, match="stored event envelope"):
            store.restore("session")


def test_snapshot_save_uses_optimistic_revision_check(
    tmp_path: Path,
    pack: V2InvestigationPack,
) -> None:
    envelopes = seal_event_stream(_assigned_stream(pack))
    snapshot = create_snapshot_envelope(envelopes)

    with V2SQLiteEventStore(tmp_path / "events.sqlite3") as store:
        store.append_event_envelopes(envelopes, expected_sequence=-1)

        with pytest.raises(
            V2OptimisticConcurrencyError,
            match="expected sequence 0, actual sequence 1",
        ):
            store.save_snapshot(snapshot, expected_sequence=0)


def test_missing_stream_restore_is_explicit(tmp_path: Path) -> None:
    with V2SQLiteEventStore(tmp_path / "events.sqlite3") as store:
        with pytest.raises(V2StreamNotFoundError, match="does not exist"):
            store.restore("missing_session")
