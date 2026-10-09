from __future__ import annotations

from io import BytesIO
from types import SimpleNamespace
from urllib.request import Request

import pytest

from uniflora.activity_chat_relay import (
    ActivityChatClaim,
    ActivityChatRelay,
    ActivityChatRelayError,
)
from uniflora.gemini_chat import GeminiSpokenReply
from uniflora.voice_service import VoiceClip


class ReadOnlyRuntime:
    def __init__(self) -> None:
        self.session_reads = 0
        self.events_written = 0

    async def session(self):
        self.session_reads += 1
        return SimpleNamespace(state=SimpleNamespace(
            current_position_id="position_1",
            available_evidence_ids=frozenset({"optical_record"}),
            examined_evidence_ids=frozenset(),
            completed_action_ids=frozenset(),
        ))

    async def available_public_commands(self, **_kwargs: object):
        self.events_written += 1
        raise AssertionError("Shared chat must not join a player or load private actions")


class RecordingVoiceReply:
    def __init__(self) -> None:
        self.context = None

    async def reply(self, context):
        self.context = context
        return GeminiSpokenReply(
            text="The public optical record is open.",
            model="test-model",
            clip=VoiceClip(audio=b"OggSvoice", filename="hypha-sealed-stone.ogg"),
        )


def relay(runtime: ReadOnlyRuntime, reply: RecordingVoiceReply) -> ActivityChatRelay:
    return ActivityChatRelay(
        "https://activity.example", "test-secret", runtime, reply, "discord-test",
    )  # type: ignore[arg-type]


def test_signed_relay_uses_explicit_service_user_agent() -> None:
    instance = relay(ReadOnlyRuntime(), RecordingVoiceReply())
    requests: list[Request] = []

    class Response(BytesIO):
        status = 200

    def open_request(request: Request, *, timeout: int) -> Response:
        assert timeout == 15
        requests.append(request)
        return Response(b"null")

    instance._opener.open = open_request  # type: ignore[method-assign]
    assert instance._signed_json_request("/api/hypha/chat/claim", {}) is None
    assert requests[0].get_header("User-agent") == "TheMissingInterior-HyphaRelay/1.0"


@pytest.mark.asyncio
async def test_live_relay_claims_only_live_stream() -> None:
    instance = ActivityChatRelay(
        "https://activity.example", "test-secret", ReadOnlyRuntime(),
        RecordingVoiceReply(), "discord-live", environment="live",
    )
    calls: list[tuple[str, dict[str, object]]] = []

    def fake_request(path: str, payload: dict[str, object]) -> object:
        calls.append((path, payload))
        return None

    instance._signed_json_request = fake_request  # type: ignore[method-assign]
    assert await instance.claim() is None
    assert calls == [(
        "/api/hypha/chat/claim",
        {"environment": "live", "streamId": "discord-live"},
    )]


@pytest.mark.asyncio
async def test_claim_is_bound_to_actual_stream_and_signed_relay_scope() -> None:
    instance = relay(ReadOnlyRuntime(), RecordingVoiceReply())
    calls: list[tuple[str, dict[str, object]]] = []

    def fake_request(path: str, payload: dict[str, object]) -> object:
        calls.append((path, payload))
        return {
            "requestId": "request-one",
            "discordUserId": "111111111111111111",
            "environment": "test",
            "streamId": "discord-test",
            "privacyAlias": "Aster Fixture",
            "history": [],
            "message": "What is known?",
        }

    instance._signed_json_request = fake_request  # type: ignore[method-assign]
    claim = await instance.claim()
    assert claim is not None
    assert claim.stream_id == "discord-test"
    assert calls == [(
        "/api/hypha/chat/claim",
        {"environment": "test", "streamId": "discord-test"},
    )]

    def wrong_stream(_path: str, _payload: dict[str, object]) -> object:
        return {**fake_request("", {}), "streamId": "another-stream"}

    instance._signed_json_request = wrong_stream  # type: ignore[method-assign]
    with pytest.raises(ActivityChatRelayError):
        await instance.claim()


@pytest.mark.asyncio
async def test_shared_relay_uses_public_context_and_links_transcript_to_ogg() -> None:
    runtime = ReadOnlyRuntime()
    reply = RecordingVoiceReply()
    instance = relay(runtime, reply)
    claim = ActivityChatClaim(
        request_id="request-one",
        discord_user_id=111111111111111111,
        environment="test",
        stream_id="discord-test",
        privacy_alias="Aster Fixture",
        history=(("participant", "Aster Fixture saw the optical record"),),
        message="Aster Fixture asks about the optical record",
    )
    completed: list[tuple[ActivityChatClaim, bytes | None, str]] = []

    async def fake_claim() -> ActivityChatClaim:
        return claim

    async def fake_complete(
        accepted: ActivityChatClaim, *, audio: bytes | None, transcript_text: str,
    ) -> None:
        completed.append((accepted, audio, transcript_text))

    instance.claim = fake_claim  # type: ignore[method-assign]
    instance.complete = fake_complete  # type: ignore[method-assign]
    assert await instance.process_once() is True
    assert runtime.session_reads == 1
    assert runtime.events_written == 0
    assert reply.context.available_actions == ()
    assert reply.context.authorized_restricted_reports == ()
    assert "Aster Fixture" not in reply.context.player_message
    assert "Aster Fixture" not in reply.context.conversation_history[0].text
    assert completed == [(claim, b"OggSvoice", "The public optical record is open.")]


@pytest.mark.asyncio
async def test_albuquerque_request_transforms_relay_reply_before_completion() -> None:
    class TransformingReply(RecordingVoiceReply):
        async def reply(self, context, *, text_transform):
            self.context = context
            transformed = text_transform("Hello, GO.")
            return GeminiSpokenReply(
                text=transformed,
                model="test-model",
                clip=VoiceClip(audio=b"OggStransformed", filename="hypha.ogg"),
            )

    instance = relay(ReadOnlyRuntime(), TransformingReply())
    claim = ActivityChatClaim(
        request_id="request-albuquerque",
        discord_user_id=111111111111111111,
        environment="test",
        stream_id="discord-test",
        privacy_alias=None,
        history=(),
        message="Use Albuquerque mode for this reply",
        albuquerque_mode=True,
    )
    completed: list[tuple[bytes | None, str]] = []

    async def fake_claim() -> ActivityChatClaim:
        return claim

    async def fake_complete(
        _accepted: ActivityChatClaim, *, audio: bytes | None, transcript_text: str,
    ) -> None:
        completed.append((audio, transcript_text))

    instance.claim = fake_claim  # type: ignore[method-assign]
    instance.complete = fake_complete  # type: ignore[method-assign]
    assert await instance.process_once() is True
    assert completed == [
        (b"OggStransformed", "HeAlbuquerquelloAlbuquerque, GOAlbuquerque."),
    ]
