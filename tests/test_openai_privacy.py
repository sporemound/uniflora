from __future__ import annotations

import json
import logging
from io import StringIO
from types import SimpleNamespace

import pytest

from uniflora.interpretation import (
    InterpretationContext,
    OpenAIResponsesProvider,
    StructuredInterpretation,
)
from uniflora.logging import JsonFormatter
from uniflora.narration import (
    NarrationContext,
    OpenAINarrationProvider,
    StructuredNarration,
)
from uniflora.openai_privacy import (
    DiscordPrivacyMetadata,
    ParticipantIdentity,
    PrivacyBoundaryError,
    sanitize_discord_text,
)
from uniflora.runtime import Environment

FIXTURE_USER_ID = 111111111111111111
FIXTURE_OTHER_USER_ID = 222222222222222222
FIXTURE_MESSAGE_ID = 333333333333333333
FIXTURE_CHANNEL_ID = 444444444444444444
FIXTURE_GUILD_ID = 555555555555555555


class RecordingResponses:
    def __init__(self) -> None:
        self.kwargs: dict[str, object] | None = None

    async def parse(self, **kwargs: object) -> object:
        self.kwargs = kwargs
        return SimpleNamespace(
            output_parsed=StructuredInterpretation.model_validate(
                {
                    "action": "observe",
                    "confidence": 0.99,
                    "evidence_fact_keys": (),
                    "attempted_rule_change": False,
                    "entity_id": "north",
                }
            ),
            usage=None,
        )


class RecordingClient:
    def __init__(self) -> None:
        self.responses = RecordingResponses()

    async def close(self) -> None:
        pass


class NarrationRecordingResponses(RecordingResponses):
    async def parse(self, **kwargs: object) -> object:
        self.kwargs = kwargs
        return SimpleNamespace(
            output_parsed=StructuredNarration(lead="boundary signal", closing=""),
            usage=None,
        )


class NarrationRecordingClient(RecordingClient):
    def __init__(self) -> None:
        self.responses = NarrationRecordingResponses()


def fixture_privacy_metadata() -> DiscordPrivacyMetadata:
    return DiscordPrivacyMetadata(
        current_participant=ParticipantIdentity(
            FIXTURE_USER_ID, ("aster_fixture", "Aster Fixture")
        ),
        referenced_participants=(
            ParticipantIdentity(
                FIXTURE_OTHER_USER_ID, ("bryn_fixture", "Bryn Fixture")
            ),
        ),
        sensitive_values=(
            str(FIXTURE_MESSAGE_ID),
            str(FIXTURE_CHANNEL_ID),
            str(FIXTURE_GUILD_ID),
            "2026-01-02T03:04:05+00:00",
            "https://cdn.discordapp.com/avatars/111/avatar.png",
        ),
    )


@pytest.mark.asyncio
async def test_outgoing_interpretation_payload_has_no_discord_identifiers() -> None:
    metadata = fixture_privacy_metadata()
    raw_fixture = (
        f"Aster Fixture asks <@{FIXTURE_OTHER_USER_ID}> to inspect north "
        f"in <#{FIXTURE_CHANNEL_ID}> at <t:1760000000:F>. "
        f"message {FIXTURE_MESSAGE_ID} "
        "https://cdn.discordapp.com/avatars/111/avatar.png"
    )
    sanitized = sanitize_discord_text(raw_fixture, metadata, limit=2000)
    client = RecordingClient()
    provider = OpenAIResponsesProvider(
        client, "test-model", max_output_tokens=100, network_authorized=True
    )
    await provider.interpret(
        InterpretationContext(
            environment=Environment.TEST,
            allowed_actions=("observe",),
            known_entities=(),
            confirmed_observations=(),
            current_player_message=sanitized,
            privacy_forbidden_values=metadata.forbidden_values(),
        )
    )
    assert client.responses.kwargs is not None
    outgoing = json.dumps(client.responses.kwargs, default=str)
    for forbidden in metadata.forbidden_values():
        assert forbidden.casefold() not in outgoing.casefold()
    assert "participant_1" in outgoing
    assert "participant_2" in outgoing
    assert "sanitized_local_context" not in outgoing
    assert client.responses.kwargs["store"] is False


@pytest.mark.asyncio
async def test_provider_without_explicit_transport_authorization_sends_nothing() -> None:
    client = RecordingClient()
    provider = OpenAIResponsesProvider(client, "test-model", max_output_tokens=100)
    with pytest.raises(PrivacyBoundaryError, match="explicitly authorized"):
        await provider.interpret(
            InterpretationContext(
                environment=Environment.TEST,
                allowed_actions=("observe",),
                known_entities=(),
                confirmed_observations=(),
                current_player_message="participant_1 inspects north",
            )
        )
    assert client.responses.kwargs is None


@pytest.mark.asyncio
async def test_narration_payload_does_not_send_the_local_confirmed_outcome() -> None:
    client = NarrationRecordingClient()
    provider = OpenAINarrationProvider(
        client, "test-model", max_output_tokens=100, network_authorized=True
    )
    await provider.narrate(
        NarrationContext(
            profile="surface_noise",
            event_type="observation.unlocked",
            narration_key="observation_unlocked",
            confirmed_outcome=f"Do not send {FIXTURE_MESSAGE_ID}.",
            position_completed=False,
            allowed_style_words=("boundary", "signal"),
        )
    )
    assert client.responses.kwargs is not None
    outgoing = json.dumps(client.responses.kwargs, default=str)
    assert str(FIXTURE_MESSAGE_ID) not in outgoing
    assert "confirmed_outcome" not in outgoing


@pytest.mark.asyncio
async def test_dry_run_displays_sanitized_payload_without_client(
    capsys: pytest.CaptureFixture[str],
) -> None:
    provider = OpenAIResponsesProvider(
        None, "test-model", max_output_tokens=100, dry_run=True
    )
    result = await provider.interpret(
        InterpretationContext(
            environment=Environment.TEST,
            allowed_actions=("observe",),
            known_entities=(),
            confirmed_observations=(),
            current_player_message="participant_1 inspects north",
        )
    )
    preview = capsys.readouterr().out
    assert not result.transmitted
    assert '"openai_dry_run": true' in preview
    assert "participant_1 inspects north" in preview
    assert '"store": false' in preview


def test_raw_participant_message_and_exception_do_not_appear_in_logs() -> None:
    raw_fixture = "Aster Fixture privately says the amber gate is open"
    stream = StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    logger = logging.getLogger("uniflora.tests.privacy")
    logger.handlers = [handler]
    logger.propagate = False
    logger.setLevel(logging.INFO)
    try:
        raise RuntimeError(raw_fixture)
    except RuntimeError:
        logger.exception(raw_fixture, extra={"alert": raw_fixture})
    rendered = stream.getvalue()
    assert raw_fixture not in rendered
    assert "Aster Fixture" not in rendered
    assert "RuntimeError" in rendered
