from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime

import pytest

from uniflora.content.v2 import V2InvestigationPack, load_missing_interior_pack
from uniflora.engine.v2 import (
    V2SessionView,
    initialize_event_stream,
    seal_event_stream,
)
from uniflora.v2_activity_projection import (
    V2ActivityHttpResponse,
    V2ActivityPublisher,
    V2ActivityPublishError,
    build_v2_activity_snapshot,
)

TEST_PLAYERS = ("discord:100000000000000001", "discord:100000000000000002")
ROOT_KEYS = {
    "schemaVersion",
    "source",
    "environment",
    "revision",
    "sequence",
    "stateHeadHash",
    "previousStateHeadHash",
    "positionId",
    "positionTitle",
    "focusLocationId",
    "casePhase",
    "updatedAt",
    "zuluTime",
    "facilityTime",
    "facilityTimezone",
    "metrics",
    "locations",
    "assignments",
    "latestPublication",
    "nextRequirement",
    "positions",
    "adaptivePresentation",
    "contentVersion",
    "evidence",
    "actions",
    "completionRoutes",
    "stochasticProcesses",
    "recentObservations",
    "campaignTracks",
    "strategicBoard",
    "strategicOutcomes",
    "campaignModifiers",
}
PUBLICATION = {
    "publicationId": "publication-test-1",
    "artifactId": "artifact-test-1",
    "title": "Boundary timing review",
    "institution": "Boundary Array",
    "finding": "The two public records preserve a timing offset.",
    "limitation": "Upper-atmosphere conditions remain unmeasured.",
    "status": "verified",
    "primaryAsset": {
        "filename": "scientific-plate.png",
        "contentType": "image/png",
        "byteLength": 321,
        "sha256": "a" * 64,
        "url": "/api/artifacts/test/artifact-test-1/scientific-plate.png",
    },
    "manifestUrl": "/api/artifacts/test/artifact-test-1/manifest.json",
}


def _session(
    pack: V2InvestigationPack,
    *,
    stream_id: str = "private-discord-instance-999999999999",
    player_ids: tuple[str, ...] = TEST_PLAYERS,
) -> V2SessionView:
    stream = initialize_event_stream(pack, player_ids, stream_id=stream_id)
    envelope = seal_event_stream(stream)[-1]
    return V2SessionView(
        stream_id=stream.stream_id,
        state=stream.state,
        sequence=envelope.event.sequence,
        last_event_hash=envelope.event_hash,
    )


@dataclass(frozen=True, slots=True)
class _Call:
    method: str
    url: str
    headers: dict[str, str]
    body: bytes | None
    thread_id: int


class _StubTransport:
    def __init__(
        self,
        current: Mapping[str, object],
        *,
        post_status: int = 201,
        delay: float = 0,
    ) -> None:
        self.current = dict(current)
        self.post_status = post_status
        self.delay = delay
        self.calls: list[_Call] = []
        self._lock = threading.Lock()

    def request(
        self,
        *,
        method: str,
        url: str,
        headers: Mapping[str, str],
        body: bytes | None,
    ) -> V2ActivityHttpResponse:
        if self.delay:
            time.sleep(self.delay)
        with self._lock:
            self.calls.append(
                _Call(
                    method=method,
                    url=url,
                    headers=dict(headers),
                    body=body,
                    thread_id=threading.get_ident(),
                )
            )
            if method == "GET":
                return V2ActivityHttpResponse(
                    status=200,
                    body=json.dumps(self.current).encode(),
                )
            if self.post_status != 201:
                return V2ActivityHttpResponse(
                    status=self.post_status,
                    body=b'{"error":"temporarily unavailable"}',
                )

            assert body is not None
            published = json.loads(body)
            self.current = published
            return V2ActivityHttpResponse(
                status=201,
                body=json.dumps(
                    {
                        "ok": True,
                        "environment": published["environment"],
                        "revision": published["revision"],
                        "stateHeadHash": published["stateHeadHash"],
                    }
                ).encode(),
            )

class _DuplicateHeadConflictTransport(_StubTransport):
    def __init__(
        self,
        current: Mapping[str, object],
        refreshed: Mapping[str, object],
    ) -> None:
        super().__init__(current, post_status=409)
        self._refreshed = dict(refreshed)
        self._get_count = 0

    def request(
        self,
        *,
        method: str,
        url: str,
        headers: Mapping[str, str],
        body: bytes | None,
    ) -> V2ActivityHttpResponse:
        if method == "GET":
            self._get_count += 1
            if self._get_count > 1:
                self.current = dict(self._refreshed)
        if method == "POST":
            with self._lock:
                self.calls.append(
                    _Call(
                        method=method,
                        url=url,
                        headers=dict(headers),
                        body=body,
                        thread_id=threading.get_ident(),
                    )
                )
                return V2ActivityHttpResponse(
                    status=409,
                    body=(
                        b'{"error":"state_chain_conflict","detail":"D1_ERROR: '
                        b'UNIQUE constraint failed: '
                        b'public_state_revisions.environment, '
                        b'public_state_revisions.state_head_hash"}'
                    ),
                )
        return super().request(method=method, url=url, headers=headers, body=body)


@pytest.fixture
def pack() -> V2InvestigationPack:
    return load_missing_interior_pack()


def test_projection_is_closed_canonical_and_sanitized(
    pack: V2InvestigationPack,
) -> None:
    session = _session(pack)
    snapshot = build_v2_activity_snapshot(
        pack,
        session,
        revision=1,
        previous_state_head_hash=None,
        updated_at=datetime(2026, 7, 25, 20, 15, tzinfo=UTC),
        latest_publication=PUBLICATION,
    )

    assert set(snapshot) == ROOT_KEYS
    assert snapshot["schemaVersion"] == "2.4.0"
    assert snapshot["contentVersion"] == pack.pack.content_version
    assert snapshot["adaptivePresentation"] == {
        "presentationId": "network_orientation_fixed_opening",
        "targetId": "network_orientation",
        "kind": "opening",
        "prose": pack.positions[0].fixed_opening.prologue,
        "guidance": list(pack.positions[0].fixed_opening.guidance),
        "requiredActionId": None,
        "optionalActionIds": [],
    }
    serialized = json.dumps(snapshot, sort_keys=True)
    assert '"band"' not in serialized
    assert "score_numerator" not in serialized
    assert "score_denominator" not in serialized
    assert snapshot["source"] == "hypha"
    assert snapshot["environment"] == "test"
    assert snapshot["positionId"] == "network_orientation"
    assert snapshot["positionTitle"] == "The Network Before the Event"
    assert snapshot["focusLocationId"] == "boundary_array"
    assert snapshot["updatedAt"] == "2026-07-25T20:15:00Z"
    assert snapshot["zuluTime"] == "20:15Z"
    assert snapshot["facilityTime"] == "13:15"
    assert snapshot["facilityTimezone"] == "Pacific"
    assert snapshot["latestPublication"] == PUBLICATION
    assert {
        item["id"]: item["mapCoordinates"]["label"]
        for item in snapshot["locations"]
    } == {
        "boundary_array": "Black Rock Sector, Nevada",
        "aeronautical_incident_center": "Allegheny Sector, West Virginia",
        "aerial_phenomena_archive": "Driftless Sector, Wisconsin",
        "holography_laboratory": "San Luis Sector, Colorado",
        "subsurface_resonance_station": "Cascadia Sector, Washington",
        "quantum_state_institute": "Adirondack Sector, New York",
    }
    assert all(
        item["mapCoordinates"]["basis"] == "WGS84 facility site"
        and item["mapCoordinates"]["precisionKm"] == 25
        for item in snapshot["locations"]
    )

    positions = snapshot["positions"]
    assert isinstance(positions, list)
    assert [
        (item["id"], item["ordinal"], item["title"], item["locationId"])
        for item in positions
    ] == [
        (
            "network_orientation",
            0,
            "The Network Before the Event",
            "boundary_array",
        ),
        ("boundary_event", 1, "First Return", "boundary_array"),
        (
            "aeronautical_incident",
            2,
            "The Track That Will Not Close",
            "aeronautical_incident_center",
        ),
        (
            "archive_convergence",
            3,
            "A Pattern Without a Common Cause",
            "aerial_phenomena_archive",
        ),
        (
            "holographic_reconstruction",
            4,
            "The Volume Defined by Its Absence",
            "holography_laboratory",
        ),
        (
            "subsurface_resonance",
            5,
            "A Mode Without a Source Point",
            "subsurface_resonance_station",
        ),
        (
            "quantum_state",
            6,
            "The View From the Missing Interior",
            "quantum_state_institute",
        ),
    ]
    assert positions[0]["progression"] == "available"
    assert positions[0]["consoleMode"] == "workspace"
    assert all(item["progression"] == "locked" for item in positions[1:])

    assignments = snapshot["assignments"]
    assert isinstance(assignments, list)
    assert [item["workingName"] for item in assignments] == [
    "Unassigned Investigator",
    "Unassigned Investigator",
]
    serialized = json.dumps(snapshot, sort_keys=True)
    assert "discord:100000000000000001" not in serialized
    assert "discord:100000000000000002" not in serialized
    assert session.stream_id not in serialized
    assert snapshot["nextRequirement"] == (
        "Draft an assessment from the examined source classes and recorded tests."
    )


def test_projection_ignores_private_players_and_projects_discord_roster(
    pack: V2InvestigationPack,
) -> None:
    session = _session(
        pack,
        player_ids=(
            "123456789012345678",
            "discord:100000000000000002",
        ),
    )

    snapshot = build_v2_activity_snapshot(
        pack,
        session,
        revision=1,
        previous_state_head_hash=None,
    )

    assert len(snapshot["assignments"]) == 1

    assignment = snapshot["assignments"][0]

    assert assignment["assignmentId"] == "public-assignment-1"
    assert assignment["workingName"] == "Unassigned Investigator"
    assert assignment["roleTitle"] == "Unassigned Investigator"
    assert assignment["station"] == "Unassigned Console"

    serialized = str(snapshot)

    assert "123456789012345678" not in serialized
    assert "discord:100000000000000002" not in serialized


async def test_publisher_signs_mock_chain_as_revision_one(
    pack: V2InvestigationPack,
) -> None:
    session = _session(pack)
    transport = _StubTransport(
        {
            "source": "mock",
            "environment": "test",
            "revision": 0,
            "stateHeadHash": "preview-head-must-not-be-chained",
            "latestPublication": PUBLICATION,
        }
    )
    timestamp = 1_722_114_000
    nonce = "test-nonce-abcdefghijklmnop"
    secret = "shared-test-secret"
    publisher = V2ActivityPublisher(
        "https://activity.example.test",
        secret,
        transport=transport,
        clock=lambda: timestamp,
        nonce_factory=lambda: nonce,
    )
    main_thread_id = threading.get_ident()

    result = await publisher.publish(
        pack,
        session,
        updated_at=datetime(2026, 7, 25, 20, 15, tzinfo=UTC),
    )

    assert result.published is True
    assert result.revision == 1
    assert result.snapshot["previousStateHeadHash"] is None
    assert result.snapshot["latestPublication"] is None
    assert [call.method for call in transport.calls] == ["GET", "POST"]
    assert all(call.thread_id != main_thread_id for call in transport.calls)

    request = transport.calls[1]
    assert request.url == "https://activity.example.test/api/hypha/state"
    assert request.body is not None
    content_sha256 = hashlib.sha256(request.body).hexdigest()
    canonical = "\n".join(
        (
            "POST",
            "/api/hypha/state",
            str(timestamp),
            nonce,
            content_sha256,
        )
    )
    expected_signature = hmac.new(
        secret.encode(),
        canonical.encode(),
        hashlib.sha256,
    ).hexdigest()
    assert request.headers["X-Hypha-Timestamp"] == str(timestamp)
    assert request.headers["X-Hypha-Nonce"] == nonce
    assert request.headers["X-Hypha-Content-SHA256"] == content_sha256
    assert request.headers["X-Hypha-Signature"] == f"v1={expected_signature}"


async def test_publisher_increments_chain_and_carries_publication(
    pack: V2InvestigationPack,
) -> None:
    previous_session = _session(pack, stream_id="previous-test-stream")
    current = build_v2_activity_snapshot(
        pack,
        previous_session,
        revision=7,
        previous_state_head_hash="older-head",
        latest_publication=PUBLICATION,
    )
    next_session = _session(pack, stream_id="next-test-stream")
    transport = _StubTransport(current)
    publisher = V2ActivityPublisher(
        "https://activity.example.test/",
        "shared-test-secret",
        transport=transport,
    )

    result = await publisher.publish(pack, next_session)

    assert result.revision == 8
    assert result.snapshot["previousStateHeadHash"] == previous_session.last_event_hash
    assert result.snapshot["latestPublication"] == PUBLICATION


async def test_publisher_skips_identical_event_head(
    pack: V2InvestigationPack,
) -> None:
    session = _session(pack)
    current = build_v2_activity_snapshot(
        pack,
        session,
        revision=4,
        previous_state_head_hash="older-head",
    )
    transport = _StubTransport(current)
    publisher = V2ActivityPublisher(
        "https://activity.example.test",
        "shared-test-secret",
        transport=transport,
    )

    result = await publisher.publish(pack, session)

    assert result.skipped is True
    assert result.revision == 4
    assert [call.method for call in transport.calls] == ["GET"]


async def test_publisher_treats_duplicate_head_conflict_as_skip(
    pack: V2InvestigationPack,
) -> None:
    previous_session = _session(pack, stream_id="previous-test-stream")
    current = build_v2_activity_snapshot(
        pack,
        previous_session,
        revision=7,
        previous_state_head_hash="older-head",
    )
    session = _session(pack, stream_id="next-test-stream")
    refreshed = build_v2_activity_snapshot(
        pack,
        session,
        revision=8,
        previous_state_head_hash=previous_session.last_event_hash,
    )
    transport = _DuplicateHeadConflictTransport(current, refreshed)
    publisher = V2ActivityPublisher(
        "https://activity.example.test",
        "shared-test-secret",
        transport=transport,
    )

    result = await publisher.publish(pack, session)

    assert result.skipped is True
    assert result.revision == 8
    assert result.state_head_hash == session.last_event_hash
    assert [call.method for call in transport.calls] == ["GET", "POST", "GET"]


async def test_publisher_treats_duplicate_head_conflict_with_stale_refresh_as_skip(
    pack: V2InvestigationPack,
) -> None:
    previous_session = _session(pack, stream_id="previous-test-stream")
    current = build_v2_activity_snapshot(
        pack,
        previous_session,
        revision=7,
        previous_state_head_hash="older-head",
    )
    session = _session(pack, stream_id="next-test-stream")
    transport = _DuplicateHeadConflictTransport(current, current)
    publisher = V2ActivityPublisher(
        "https://activity.example.test",
        "shared-test-secret",
        transport=transport,
    )

    result = await publisher.publish(pack, session)

    assert result.skipped is True
    assert result.revision == 8
    assert result.state_head_hash == session.last_event_hash
    assert result.snapshot["stateHeadHash"] == session.last_event_hash
    assert [call.method for call in transport.calls] == ["GET", "POST", "GET"]

async def test_publisher_serializes_concurrent_refreshes(
    pack: V2InvestigationPack,
) -> None:
    session = _session(pack)
    transport = _StubTransport(
        {"source": "mock", "environment": "test"},
        delay=0.01,
    )
    publisher = V2ActivityPublisher(
        "https://activity.example.test",
        "shared-test-secret",
        transport=transport,
    )

    results = await asyncio.gather(
        publisher.publish(pack, session),
        publisher.publish(pack, session),
    )

    assert sum(result.published for result in results) == 1
    assert sum(result.skipped for result in results) == 1
    assert [call.method for call in transport.calls] == ["GET", "POST", "GET"]


async def test_publish_failure_is_typed_for_stale_projection_reporting(
    pack: V2InvestigationPack,
) -> None:
    session = _session(pack)
    transport = _StubTransport(
        {"source": "mock", "environment": "test"},
        post_status=503,
    )
    publisher = V2ActivityPublisher(
        "https://activity.example.test",
        "shared-test-secret",
        transport=transport,
    )

    with pytest.raises(V2ActivityPublishError) as captured:
        await publisher.publish(pack, session)

    assert captured.value.operation == "state publish"
    assert captured.value.status == 503
    assert session.state.revision == 0


def test_publisher_requires_https_outside_loopback() -> None:
    with pytest.raises(ValueError, match="HTTPS"):
        V2ActivityPublisher("http://activity.example.test", "secret")

    assert V2ActivityPublisher("http://127.0.0.1:5173", "secret")


@pytest.mark.asyncio
async def test_live_projection_uses_separate_public_state_scope(
    pack: V2InvestigationPack,
) -> None:
    transport = _StubTransport({"source": "mock", "environment": "live"})
    publisher = V2ActivityPublisher(
        "https://activity.example.test", "shared-test-secret",
        environment="live", transport=transport,
    )
    result = await publisher.publish(pack, _session(pack, stream_id="discord-live"))
    assert result.snapshot["environment"] == "live"
    assert transport.calls[0].url.endswith("/api/public-state?environment=live")
    assert transport.calls[1].body is not None
    assert json.loads(transport.calls[1].body)["environment"] == "live"


@pytest.mark.asyncio
async def test_live_projection_bootstraps_after_missing_public_state(
    pack: V2InvestigationPack,
) -> None:
    class MissingLiveTransport(_StubTransport):
        def request(self, *, method, url, headers, body):  # type: ignore[no-untyped-def]
            if method == "GET" and not self.calls:
                self.calls.append(_Call(method, url, dict(headers), body, threading.get_ident()))
                return V2ActivityHttpResponse(
                    status=404, body=b'{"error":"state_unavailable"}',
                )
            return super().request(method=method, url=url, headers=headers, body=body)

    transport = MissingLiveTransport({"source": "mock", "environment": "live"})
    publisher = V2ActivityPublisher(
        "https://activity.example.test", "shared-test-secret",
        environment="live", transport=transport,
    )
    result = await publisher.publish(pack, _session(pack, stream_id="discord-live"))
    assert result.published is True
    assert result.revision == 1
