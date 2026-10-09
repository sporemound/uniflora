from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import secrets
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from uniflora import web_game
from uniflora.content.v2 import load_missing_interior_static_pack
from uniflora.v2_activity_projection import V2ActivityPublishError
from uniflora.v2_test_runtime import V2TestRuntime
from uniflora.voice_service import VoiceClip
from uniflora.web_game import WebGameApi, create_app


class FakeRuntime:
    def __init__(self) -> None:
        self.players: list[str] = []
        self.commands: list[tuple[str, str]] = []

    async def public_status(self, *, player_id: str):
        self.players.append(player_id)
        return SimpleNamespace(
            accepted=True, code="session", summary="Investigation open",
            details=("Review the current evidence.",), sequence=3,
        )

    async def execute_public(self, *, player_id: str, text: str):
        self.commands.append((player_id, text))
        return SimpleNamespace(
            accepted=True, code="accepted", summary="Recorded",
            details=(), sequence=4,
        )

    async def session(self):
        return SimpleNamespace(state=SimpleNamespace(
            current_position_id="network_orientation",
            get_player=lambda _: SimpleNamespace(
                active_role_id="evidence_investigator",
                current_location_id="boundary_array",
            ),
        ))

    async def available_public_commands(self, *, player_id: str):
        return (("inspect artifact", "Inspect artifact"),)

    async def close(self) -> None:
        pass


def signed_headers(
    secret: str, path: str, body: bytes, *, nonce: str | None = None
) -> dict[str, str]:
    timestamp = str(int(time.time()))
    nonce = nonce or secrets.token_hex(16)
    body_hash = hashlib.sha256(body).hexdigest()
    canonical = "\n".join(("POST", path, timestamp, nonce, body_hash))
    signature = hmac.new(secret.encode(), canonical.encode(), hashlib.sha256).hexdigest()
    return {
        "Content-Type": "application/json",
        "X-Game-Timestamp": timestamp,
        "X-Game-Nonce": nonce,
        "X-Game-Content-SHA256": body_hash,
        "X-Game-Signature": f"v1={signature}",
    }


def fake_request(path: str, body: bytes, headers: dict[str, str]):
    async def read() -> bytes:
        return body

    return SimpleNamespace(
        content_length=len(body), read=read, headers=headers, method="POST", path=path,
    )


@pytest.mark.asyncio
async def test_signed_python_voice_endpoint_returns_named_ogg() -> None:
    secret = "game-secret-" + "v" * 32
    path = "/internal/voice/synthesize"
    body = json.dumps({
        "environment": "live",
        "text": "The optical record remains open.",
        "filenameTitle": "Optical Record",
    }).encode()

    class FakeVoice:
        enabled = True

        async def synthesize(self, text: str) -> VoiceClip:
            assert text == "The optical record remains open."
            return VoiceClip(audio=b"OggSvoice", filename="optical-record.ogg")

    api = WebGameApi(
        FakeRuntime(), secret, voice=FakeVoice(),  # type: ignore[arg-type]
    )
    headers = signed_headers(secret, path, body)
    response = await api.synthesize_voice(fake_request(path, body, headers))

    assert response.status == 200
    assert response.body == b"OggSvoice"
    assert response.content_type == "audio/ogg"
    assert response.headers["Content-Disposition"] == (
        'inline; filename="optical-record.ogg"'
    )
    assert response.headers["Cache-Control"] == "private, no-store"

    with pytest.raises(web.HTTPConflict):
        await api.synthesize_voice(fake_request(path, body, headers))
    with pytest.raises(web.HTTPUnauthorized):
        await api.synthesize_voice(fake_request(path, body, {}))


@pytest.mark.asyncio
async def test_web_game_requires_signed_identity_and_rejects_replay() -> None:
    secret = "game-secret-" + "x" * 32
    runtime = FakeRuntime()
    api = WebGameApi(runtime, secret)  # type: ignore[arg-type]
    path = "/internal/game/status"
    body = json.dumps({
        "environment": "live", "playerId": "web:participant_" + "a" * 24,
    }).encode()
    headers = signed_headers(secret, path, body)
    response = await api.status(fake_request(path, body, headers))
    assert response.status == 200
    payload = json.loads(response.text)
    assert payload["player"]["roleId"] == "evidence_investigator"
    assert payload["suggestions"] == [
        {"command": "inspect artifact", "label": "Inspect artifact"}
    ]
    assert runtime.players == ["web:participant_" + "a" * 24]

    with pytest.raises(web.HTTPConflict):
        await api.status(fake_request(path, body, headers))
    assert runtime.players == ["web:participant_" + "a" * 24]

    with pytest.raises(web.HTTPUnauthorized):
        await api.status(fake_request(path, body.replace(b"a", b"b"), headers))
    assert len(runtime.players) == 1


@pytest.mark.asyncio
async def test_web_game_command_uses_signed_player_id() -> None:
    secret = "game-secret-" + "y" * 32
    runtime = FakeRuntime()
    api = WebGameApi(runtime, secret)  # type: ignore[arg-type]
    path = "/internal/game/command"
    body = json.dumps({
        "environment": "live",
        "playerId": "web:participant_" + "c" * 24,
        "text": "assign-role evidence_investigator",
    }).encode()
    response = await api.command(fake_request(path, body, signed_headers(secret, path, body)))
    assert response.status == 200
    assert runtime.commands == [
        ("web:participant_" + "c" * 24, "assign-role evidence_investigator")
    ]


@pytest.mark.asyncio
async def test_web_game_http_boundary_returns_json_and_rejects_unsigned_request() -> None:
    secret = "game-secret-" + "z" * 32
    runtime = FakeRuntime()
    path = "/internal/game/status"
    body = json.dumps({
        "environment": "live", "playerId": "web:participant_" + "e" * 24,
    }).encode()
    async with TestServer(create_app(WebGameApi(runtime, secret))) as server:
        async with TestClient(server) as client:
            unsigned = await client.post(path, data=body)
            assert unsigned.status == 401
            assert (await unsigned.json())["error"]
            signed = await client.post(
                path,
                data=body,
                headers=signed_headers(secret, path, body),
            )
            assert signed.status == 200
            assert (await signed.json())["player"]["roleId"] == "evidence_investigator"


@pytest.mark.asyncio
async def test_first_web_player_seeds_new_static_stream(tmp_path: Path) -> None:
    player_id = "web:participant_" + "d" * 24
    runtime = V2TestRuntime(
        tmp_path / "web-live.sqlite3",
        stream_id="web-live",
        initial_player_ids=(),
        pack=load_missing_interior_static_pack(),
    )
    try:
        status = await runtime.public_status(player_id=player_id)
        assert status.accepted
        session = await runtime.session()
        assert session.state.get_player(player_id) is not None
        assert session.state.pack_id == "missing_interior_static_roles"
        suggestions = await runtime.available_public_commands(player_id=player_id)
        assert any(command == "assign-role evidence_investigator" for command, _ in suggestions)
    finally:
        await runtime.close()


@pytest.mark.asyncio
async def test_startup_republishes_existing_stream_and_retries_without_player_request(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(web_game, "_PUBLISH_RETRY_INITIAL_SECONDS", 0.01)
    db_path = tmp_path / "committed-web-live.sqlite3"
    player_id = "web:participant_" + "9" * 24
    first_runtime = V2TestRuntime(
        db_path, stream_id="web-live", initial_player_ids=(),
        pack=load_missing_interior_static_pack(),
    )
    try:
        await first_runtime.public_status(player_id=player_id)
        committed_sequence = (await first_runtime.session()).sequence
    finally:
        await first_runtime.close()

    restarted_runtime = V2TestRuntime(
        db_path, stream_id="web-live", initial_player_ids=(),
        pack=load_missing_interior_static_pack(),
    )

    class StartupPublisher:
        def __init__(self) -> None:
            self.sequences: list[int] = []
            self.recovered = asyncio.Event()

        async def publish(self, _pack: object, session: SimpleNamespace) -> None:
            self.sequences.append(session.sequence)
            if len(self.sequences) == 1:
                raise V2ActivityPublishError("temporary outage", operation="publish")
            self.recovered.set()

    publisher = StartupPublisher()
    api = WebGameApi(
        restarted_runtime, "game-secret-" + "p" * 32, publisher=publisher,
    )  # type: ignore[arg-type]
    async with TestServer(create_app(api)):
        await asyncio.wait_for(publisher.recovered.wait(), timeout=1)
        assert publisher.sequences == [committed_sequence, committed_sequence]


@pytest.mark.asyncio
async def test_committed_command_retries_publication_without_another_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(web_game, "_PUBLISH_RETRY_INITIAL_SECONDS", 0.01)
    runtime = FakeRuntime()
    runtime.pack = object()
    runtime.revision = 1
    original_session = runtime.session

    async def current_session():
        session = await original_session()
        session.revision = runtime.revision
        return session

    runtime.session = current_session  # type: ignore[method-assign]

    class FlakyPublisher:
        def __init__(self) -> None:
            self.revisions: list[int] = []
            self.recovered = asyncio.Event()

        async def publish(self, _pack: object, session: SimpleNamespace) -> None:
            self.revisions.append(session.revision)
            if len(self.revisions) == 1:
                raise V2ActivityPublishError("temporary outage", operation="publish")
            self.recovered.set()

    publisher = FlakyPublisher()
    secret = "game-secret-" + "r" * 32
    api = WebGameApi(runtime, secret, publisher=publisher)  # type: ignore[arg-type]
    path = "/internal/game/command"
    body = json.dumps({
        "environment": "live", "playerId": "web:participant_" + "f" * 24,
        "text": "assign-role evidence_investigator",
    }).encode()
    try:
        response = await api.command(fake_request(path, body, signed_headers(secret, path, body)))
        assert json.loads(response.text)["projectionCurrent"] is False
        assert len(runtime.commands) == 1, "the committed action must not be replayed"
        runtime.revision = 2
        await asyncio.wait_for(publisher.recovered.wait(), timeout=1)
        assert publisher.revisions == [1, 2], "retry must publish the latest committed state"
    finally:
        await api.close()


@pytest.mark.asyncio
async def test_publication_timeout_is_retried(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(web_game, "_PUBLISH_TIMEOUT_SECONDS", 0.01)
    monkeypatch.setattr(web_game, "_PUBLISH_RETRY_INITIAL_SECONDS", 0.01)
    runtime = FakeRuntime()
    runtime.pack = object()

    class SlowPublisher:
        def __init__(self) -> None:
            self.calls = 0
            self.recovered = asyncio.Event()

        async def publish(self, _pack: object, _session: object) -> None:
            self.calls += 1
            if self.calls == 1:
                await asyncio.sleep(1)
            self.recovered.set()

    publisher = SlowPublisher()
    api = WebGameApi(runtime, "game-secret-" + "t" * 32, publisher=publisher)  # type: ignore[arg-type]
    try:
        assert await api._publish() is False
        await asyncio.wait_for(publisher.recovered.wait(), timeout=1)
        assert publisher.calls == 2
    finally:
        await api.close()


@pytest.mark.asyncio
async def test_publication_retry_backoff_is_capped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(web_game, "_PUBLISH_RETRY_INITIAL_SECONDS", 1.0)
    monkeypatch.setattr(web_game, "_PUBLISH_RETRY_MAX_SECONDS", 4.0)
    actual_sleep = asyncio.sleep
    delays: list[float] = []

    async def fast_recorded_sleep(delay: float) -> None:
        delays.append(delay)
        await actual_sleep(0)

    monkeypatch.setattr(web_game.asyncio, "sleep", fast_recorded_sleep)
    runtime = FakeRuntime()
    runtime.pack = object()

    class RecoveringPublisher:
        calls = 0

        def __init__(self) -> None:
            self.recovered = asyncio.Event()

        async def publish(self, _pack: object, _session: object) -> None:
            self.calls += 1
            if self.calls <= 4:
                raise V2ActivityPublishError("offline", operation="publish")
            self.recovered.set()

    publisher = RecoveringPublisher()
    api = WebGameApi(runtime, "game-secret-" + "b" * 32, publisher=publisher)  # type: ignore[arg-type]
    try:
        assert await api._publish() is False
        await asyncio.wait_for(publisher.recovered.wait(), timeout=1)
        assert delays[:4] == [1.0, 2.0, 4.0, 4.0]
    finally:
        await api.close()


@pytest.mark.asyncio
async def test_publication_retry_stops_on_shutdown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(web_game, "_PUBLISH_RETRY_INITIAL_SECONDS", 0.05)
    runtime = FakeRuntime()
    runtime.pack = object()

    class DownPublisher:
        calls = 0

        async def publish(self, _pack: object, _session: object) -> None:
            self.calls += 1
            raise V2ActivityPublishError("offline", operation="publish")

    publisher = DownPublisher()
    api = WebGameApi(runtime, "game-secret-" + "s" * 32, publisher=publisher)  # type: ignore[arg-type]
    assert await api._publish() is False
    await api.close()
    await asyncio.sleep(0.08)
    assert publisher.calls == 1, "shutdown must cancel the scheduled retry"
