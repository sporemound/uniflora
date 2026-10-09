from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from uniflora.albuquerque_mode import transform_albuquerque_markdown
from uniflora.gemini_chat import (
    ClearanceGrant,
    GeminiChatContext,
    GeminiGameChatProvider,
    GeminiVoiceReplyService,
    PublicChatFact,
    RestrictedChatReport,
    SharedChatTurn,
    build_v2_chat_context,
)
from uniflora.openai_privacy import (
    DiscordPrivacyMetadata,
    ParticipantIdentity,
    PrivacyBoundaryError,
)
from uniflora.voice_service import VoiceClip, VoiceSynthesisError, contextual_voice_filename


class RecordingInteractions:
    def __init__(self) -> None:
        self.kwargs: dict[str, object] | None = None

    async def create(self, **kwargs: object) -> object:
        self.kwargs = kwargs
        return SimpleNamespace(output_text="The receiver record remains internally inconsistent.")


class RecordingAsyncClient:
    def __init__(self) -> None:
        self.interactions = RecordingInteractions()
        self.closed = False

    async def aclose(self) -> None:
        self.closed = True


class RecordingClient:
    def __init__(self) -> None:
        self.aio = RecordingAsyncClient()
        self.closed = False

    def close(self) -> None:
        self.closed = True


def context() -> GeminiChatContext:
    return GeminiChatContext(
        position_id="position_1",
        public_summary="The first return is under review.",
        public_facts=(
            PublicChatFact(fact_key="radio_return_examined", text="The radio return was examined."),
        ),
        clearance=(ClearanceGrant(domain="receiver", level=2),),
        authorized_restricted_reports=(
            RestrictedChatReport(
                report_id="receiver_internal_1",
                domain="receiver",
                clearance_level=2,
                text="A calibration discrepancy remains unresolved.",
            ),
        ),
        available_actions=("compare_source_timing", "test_atmospheric_propagation"),
        conversation_history=(
            SharedChatTurn(sender_type="participant", text="What did we find?"),
            SharedChatTurn(sender_type="hypha", text="The public record is incomplete."),
        ),
        player_message="participant_1 asks what conflicts with the public record",
    )


@pytest.mark.asyncio
async def test_gemini_chat_is_read_only_and_stateless() -> None:
    client = RecordingClient()
    provider = GeminiGameChatProvider(
        client,
        "test-model",
        timeout_seconds=5,
        max_output_tokens=300,
        temperature=0.6,
        network_authorized=True,
    )

    result = await provider.reply(context())

    assert "inconsistent" in result.text
    assert client.aio.interactions.kwargs is not None
    request = client.aio.interactions.kwargs
    assert request["store"] is False
    assert "tools" not in request
    assert "compare_source_timing" in str(request["system_instruction"])
    assert "calibration discrepancy" in str(request["system_instruction"])
    assert "The public record is incomplete." in str(request["input"])
    assert "The public record is incomplete." not in str(request["system_instruction"])


@pytest.mark.asyncio
async def test_gemini_names_voice_clip_from_exchange_context() -> None:
    client = RecordingClient()

    async def named_reply(**kwargs: object) -> object:
        client.aio.interactions.kwargs = kwargs
        return SimpleNamespace(output_text="Optical Record")

    client.aio.interactions.create = named_reply  # type: ignore[method-assign]
    provider = GeminiGameChatProvider(
        client, "test-model", timeout_seconds=5,
        max_output_tokens=300, temperature=0.6, network_authorized=True,
    )
    title = await provider.audio_title(context(), "The optical record is still open.")

    assert title == "Optical Record"
    request = client.aio.interactions.kwargs
    assert request is not None
    assert request["store"] is False
    assert "The optical record is still open." in str(request["input"])
    assert "The public record is incomplete." in str(request["input"])
    assert "authorized_restricted_reports" not in str(request["input"])


@pytest.mark.asyncio
async def test_gemini_audio_title_rejects_private_identity() -> None:
    client = RecordingClient()

    async def unsafe_title(**_kwargs: object) -> object:
        return SimpleNamespace(output_text="Aster Fixture")

    client.aio.interactions.create = unsafe_title  # type: ignore[method-assign]
    provider = GeminiGameChatProvider(
        client, "test-model", timeout_seconds=5,
        max_output_tokens=300, temperature=0.6, network_authorized=True,
    )
    safe_context = context().model_copy(
        update={"privacy_forbidden_values": ("Aster Fixture",)},
    )

    with pytest.raises(PrivacyBoundaryError):
        await provider.audio_title(safe_context, "The optical record remains open.")


@pytest.mark.asyncio
async def test_gemini_reply_does_not_speak_markdown_emphasis() -> None:
    client = RecordingClient()

    async def formatted_reply(**_kwargs: object) -> object:
        return SimpleNamespace(output_text="**The radio return** is __unresolved__. 2**3 is eight.")

    client.aio.interactions.create = formatted_reply  # type: ignore[method-assign]
    provider = GeminiGameChatProvider(
        client, "test-model", timeout_seconds=5,
        max_output_tokens=300, temperature=0.6, network_authorized=True,
    )
    voice = RecordingVoice()

    result = await GeminiVoiceReplyService(provider, voice).reply(context())

    expected = "The radio return is unresolved. 2**3 is eight."
    assert result.text == expected
    assert voice.texts == [expected]


@pytest.mark.asyncio
async def test_gemini_chat_blocks_forbidden_discord_metadata_before_transport() -> None:
    client = RecordingClient()
    provider = GeminiGameChatProvider(
        client,
        "test-model",
        timeout_seconds=5,
        max_output_tokens=300,
        temperature=0.6,
        network_authorized=True,
    )
    forbidden = "111111111111111111"
    unsafe = context().model_copy(
        update={
            "player_message": f"participant {forbidden} asks for the receiver report",
            "privacy_forbidden_values": (forbidden,),
        }
    )

    with pytest.raises(PrivacyBoundaryError):
        await provider.reply(unsafe)

    assert client.aio.interactions.kwargs is None


@pytest.mark.asyncio
async def test_gemini_chat_rejects_metadata_in_generated_reply() -> None:
    client = RecordingClient()
    async def unsafe_reply(**_kwargs: object) -> object:
        return SimpleNamespace(output_text="Contact 111111111111111111")
    client.aio.interactions.create = unsafe_reply  # type: ignore[method-assign]
    provider = GeminiGameChatProvider(
        client, "test-model", timeout_seconds=5,
        max_output_tokens=300, temperature=0.6, network_authorized=True,
    )
    with pytest.raises(PrivacyBoundaryError):
        await provider.reply(context())


@pytest.mark.asyncio
async def test_gemini_chat_requires_explicit_network_authorization() -> None:
    client = RecordingClient()
    provider = GeminiGameChatProvider(
        client,
        "test-model",
        timeout_seconds=5,
        max_output_tokens=300,
        temperature=0.6,
    )

    with pytest.raises(PrivacyBoundaryError, match="explicitly authorized"):
        await provider.reply(context())


@pytest.mark.asyncio
async def test_gemini_chat_dry_run_sends_nothing(
    capsys: pytest.CaptureFixture[str],
) -> None:
    provider = GeminiGameChatProvider(
        None,
        "test-model",
        timeout_seconds=5,
        max_output_tokens=300,
        temperature=0.6,
        dry_run=True,
    )

    result = await provider.reply(context())
    document = json.loads(capsys.readouterr().out)

    assert not result.transmitted
    assert document["gemini_dry_run"] is True
    assert document["request"]["store"] is False


class FakeGeminiProvider:
    model = "fake-gemini"

    def __init__(self, text: str = "Receiver discrepancy remains unresolved.") -> None:
        self.text = text
        self.title = "Receiver Discrepancy"
        self.contexts: list[GeminiChatContext] = []
        self.postprocessing_flags: list[bool] = []
        self.title_replies: list[str] = []
        self.closed = False

    async def reply(
        self,
        value: GeminiChatContext,
        *,
        plain_text_for_postprocessing: bool = False,
    ):
        from uniflora.gemini_chat import GeminiChatResult

        self.contexts.append(value)
        self.postprocessing_flags.append(plain_text_for_postprocessing)
        return GeminiChatResult(self.text, self.model)

    async def audio_title(self, _context: GeminiChatContext, reply_text: str) -> str:
        self.title_replies.append(reply_text)
        return self.title

    async def close(self) -> None:
        self.closed = True


class RecordingVoice:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.texts: list[str] = []

    async def synthesize(self, text: str) -> VoiceClip:
        self.texts.append(text)
        if self.fail:
            raise VoiceSynthesisError("voice unavailable")
        return VoiceClip(audio=b"sealed-stone", filename=contextual_voice_filename(text))


@pytest.mark.asyncio
async def test_gemini_voice_reply_uses_only_existing_espeak_renderer() -> None:
    provider = FakeGeminiProvider("The timing record remains unresolved.")
    voice = RecordingVoice()
    service = GeminiVoiceReplyService(provider, voice)  # type: ignore[arg-type]

    result = await service.reply(context())

    assert result.text == "The timing record remains unresolved."
    assert result.clip is not None
    assert result.clip.audio == b"sealed-stone"
    assert result.clip.filename == "receiver-discrepancy.ogg"
    assert voice.texts == ["The timing record remains unresolved."]
    assert provider.title_replies == ["The timing record remains unresolved."]


@pytest.mark.asyncio
async def test_albuquerque_reply_transforms_transcript_before_voice() -> None:
    provider = FakeGeminiProvider("Hello, GO.")
    voice = RecordingVoice()
    service = GeminiVoiceReplyService(provider, voice)  # type: ignore[arg-type]

    result = await service.reply(
        context(), text_transform=transform_albuquerque_markdown,
    )

    assert result.text == transform_albuquerque_markdown("Hello, GO.")
    assert voice.texts == [result.text]
    assert provider.postprocessing_flags == [True]
    assert provider.title_replies == ["Hello, GO."]


@pytest.mark.asyncio
async def test_gemini_voice_reply_keeps_text_fallback_if_espeak_fails() -> None:
    provider = FakeGeminiProvider("The timing record remains unresolved.")
    voice = RecordingVoice(fail=True)
    service = GeminiVoiceReplyService(provider, voice)  # type: ignore[arg-type]

    result = await service.reply(context())

    assert result.text == "The timing record remains unresolved."
    assert result.clip is None
    assert provider.title_replies == []


@pytest.mark.asyncio
async def test_gemini_title_failure_keeps_spoken_reply() -> None:
    provider = FakeGeminiProvider("The signal is under review.")
    voice = RecordingVoice()

    async def unavailable_title(_context: GeminiChatContext, _text: str) -> str:
        raise TimeoutError("title request timed out")

    provider.audio_title = unavailable_title  # type: ignore[method-assign]
    result = await GeminiVoiceReplyService(
        provider, voice,  # type: ignore[arg-type]
    ).reply(context())

    assert result.clip is not None
    assert result.clip.filename == "signal-review.ogg"
    assert voice.texts == ["The signal is under review."]


@pytest.mark.asyncio
async def test_gemini_voice_reply_never_speaks_private_identity() -> None:
    provider = FakeGeminiProvider("Hello, Aster Fixture.")
    voice = RecordingVoice()
    service = GeminiVoiceReplyService(provider, voice)  # type: ignore[arg-type]
    unsafe = context().model_copy(update={"privacy_forbidden_values": ("Aster Fixture",)})
    with pytest.raises(PrivacyBoundaryError):
        await service.reply(unsafe)
    assert voice.texts == []


@pytest.mark.asyncio
async def test_v2_context_builder_does_not_join_unknown_player() -> None:
    class State:
        current_position_id = "position_1"
        available_evidence_ids = frozenset({"optical_record"})
        examined_evidence_ids = frozenset()
        completed_action_ids = frozenset()

        def get_player(self, _player_id: str):
            return None

    class Runtime:
        def __init__(self) -> None:
            self.commands_called = False

        async def session(self):
            return SimpleNamespace(state=State())

        async def available_public_commands(self, **_kwargs: object):
            self.commands_called = True
            return (("examine-evidence optical_record", "Inspect"),)

    runtime = Runtime()
    metadata = DiscordPrivacyMetadata(
        current_participant=ParticipantIdentity(
            111111111111111111,
            ("Aster Fixture",),
        )
    )

    built = await build_v2_chat_context(
        runtime,
        player_id="discord:111111111111111111",
        player_message="Aster Fixture asks what is available",
        privacy_metadata=metadata,
    )

    assert runtime.commands_called is False
    assert built.available_actions == ()
    assert "Aster Fixture" not in built.player_message
    assert "participant_1" in built.player_message


@pytest.mark.asyncio
async def test_v2_context_builder_exposes_only_current_legal_actions_for_existing_player() -> None:
    class State:
        current_position_id = "position_1"
        available_evidence_ids = frozenset({"optical_record", "radio_return"})
        examined_evidence_ids = frozenset({"optical_record"})
        completed_action_ids = frozenset({"inspect_optical_record"})

        def get_player(self, player_id: str):
            return object() if player_id == "discord:111111111111111111" else None

    class Runtime:
        async def session(self):
            return SimpleNamespace(state=State())

        async def available_public_commands(self, **_kwargs: object):
            return (
                ("compare-source-timing", "Compare timing"),
                ("test-atmospheric-propagation", "Test atmosphere"),
            )

    metadata = DiscordPrivacyMetadata(
        current_participant=ParticipantIdentity(111111111111111111)
    )
    built = await build_v2_chat_context(
        Runtime(),
        player_id="discord:111111111111111111",
        player_message="What can I do next?",
        privacy_metadata=metadata,
    )

    assert built.available_actions == (
        "compare-source-timing",
        "test-atmospheric-propagation",
    )
    assert "optical_record" in built.public_summary
    assert "inspect_optical_record" in built.public_summary


@pytest.mark.asyncio
async def test_shared_v2_context_never_loads_player_private_actions() -> None:
    class State:
        current_position_id = "position_1"
        available_evidence_ids = frozenset({"optical_record"})
        examined_evidence_ids = frozenset()
        completed_action_ids = frozenset()

        def get_player(self, _player_id: str):
            raise AssertionError("Shared chat must not inspect a player's private record")

    class Runtime:
        def __init__(self) -> None:
            self.events_written = 0

        async def session(self):
            return SimpleNamespace(state=State())

        async def available_public_commands(self, **_kwargs: object):
            self.events_written += 1
            raise AssertionError("Shared chat must not invoke participant commands")

    runtime = Runtime()
    metadata = DiscordPrivacyMetadata(
        current_participant=ParticipantIdentity(111111111111111111, ("Aster Fixture",))
    )
    built = await build_v2_chat_context(
        runtime, player_id="discord:111111111111111111",
        player_message="Aster Fixture asks about the optical record",
        privacy_metadata=metadata, shared_public_only=True,
    )
    assert built.available_actions == ()
    assert built.clearance == ()
    assert built.authorized_restricted_reports == ()
    assert built.conversation_history == ()
    assert runtime.events_written == 0
    assert "Aster Fixture" not in built.player_message


@pytest.mark.asyncio
async def test_live_shared_chat_uses_public_activity_guidance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class State:
        current_position_id = "boundary_event"

        def get_player(self, _player_id: str):
            raise AssertionError("Shared chat must not inspect private player state")

    class Runtime:
        pack = object()

        async def session(self):
            return SimpleNamespace(state=State())

        async def available_public_commands(self, **_kwargs: object):
            raise AssertionError("Shared chat must not invoke participant commands")

        async def available_public_roles(self):
            return (("field_observer", "Field Observer — examines optical record"),)

    def public_snapshot(_pack: object, _session: object, **kwargs: object):
        assert kwargs["environment"] == "live"
        return {
            "positionTitle": "First Return",
            "casePhase": "investigation",
            "adaptivePresentation": {
                "prose": "The array retained two independent records.",
                "guidance": ["Start with the optical record."],
            },
            "nextRequirement": (
                "Examine Saturated Optical Array Record. "
                "Use `examine-evidence optical_record`."
            ),
            "evidence": [
                {
                    "id": "optical_record", "name": "Saturated Optical Array Record",
                    "status": "available",
                },
                {"id": "secret_record", "name": "Secret Record", "status": "locked"},
            ],
            "actions": [
                {
                    "id": "compare_timing", "title": "Compare timing",
                    "description": "Compare the public records.", "status": "available",
                    "command": "perform-action compare_timing", "requiredRoleIds": [],
                },
                {
                    "id": "secret_action", "title": "Secret action",
                    "description": "Restricted description.", "status": "locked",
                    "command": None, "requiredRoleIds": [],
                },
            ],
            "completionRoutes": [{
                "id": "timing_review", "title": "Timing review",
                "description": "Compare independent records.",
                "status": "available", "progress": "0 of 2 records examined",
            }],
        }

    monkeypatch.setattr("uniflora.gemini_chat.build_v2_activity_snapshot", public_snapshot)
    built = await build_v2_chat_context(
        Runtime(),
        player_id="discord:111111111111111111",
        player_message="what are the first steps to begin this activity?",
        privacy_metadata=DiscordPrivacyMetadata(
            current_participant=ParticipantIdentity(111111111111111111),
        ),
        shared_public_only=True,
        environment="live",
    )

    assert "Saturated Optical Array Record" in built.public_summary
    facts = " ".join(fact.text for fact in built.public_facts)
    assert "Saturated Optical Array Record" in facts
    assert "Compare the public records" in facts
    assert "Start with the optical record" in facts
    assert "Compare independent records" in facts
    assert "/v2-live command" in facts
    assert "/v2-live role" in facts
    assert "public title" in facts
    assert "Field Observer" in facts
    assert "Secret Record" not in facts
    assert "Restricted description" not in facts
    assert built.available_actions == ()
    assert built.authorized_restricted_reports == ()
