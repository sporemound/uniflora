from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import SecretStr

from uniflora.gemini_chat import (
    ClearanceGrant,
    GeminiChatContext,
    GeminiGameChatProvider,
    PublicChatFact,
    RestrictedChatReport,
    SharedChatTurn,
)
from uniflora.openai_chat import OpenAIGameChatProvider
from uniflora.openai_privacy import PrivacyBoundaryError


def context(**updates: object) -> GeminiChatContext:
    value = GeminiChatContext(
        position_id="position_1",
        public_summary="The first return is under review.",
        public_facts=(PublicChatFact(fact_key="examined", text="The return was examined."),),
        clearance=(ClearanceGrant(domain="receiver", level=2),),
        authorized_restricted_reports=(RestrictedChatReport(
            report_id="calibration", domain="receiver", clearance_level=2,
            text="A calibration discrepancy remains unresolved.",
        ),),
        available_actions=("compare_source_timing",),
        conversation_history=(
            SharedChatTurn(sender_type="participant", text="What did we find?"),
            SharedChatTurn(sender_type="hypha", text="The public record is incomplete."),
        ),
        player_message="What conflicts with the public record?",
    )
    return value.model_copy(update=updates)


def provider(**options: object) -> OpenAIGameChatProvider:
    client = SimpleNamespace(
        responses=SimpleNamespace(create=AsyncMock(return_value=SimpleNamespace(
            status="completed", output_text="**The return** remains __unresolved__.",
        ))),
        close=AsyncMock(),
    )
    return OpenAIGameChatProvider(
        client, "test-model", timeout_seconds=0.1, max_output_tokens=300,
        network_authorized=True, **options,
    )


@pytest.mark.asyncio
async def test_openai_keeps_authorized_facts_separate_from_untrusted_conversation() -> None:
    chat = provider()
    result = await chat.reply(context())
    request = chat.client.responses.create.call_args.kwargs

    assert result.text == "The return remains unresolved."
    assert result.model == "test-model"
    assert result.transmitted is True
    assert request["store"] is False
    assert request["reasoning"] == {"effort": "none"}
    assert request["max_output_tokens"] == 300
    assert request["instructions"].startswith(GeminiGameChatProvider.SYSTEM_INSTRUCTIONS)
    assert "calibration discrepancy" in request["instructions"]
    assert "compare_source_timing" in request["instructions"]
    assert "The public record is incomplete." not in request["instructions"]
    assert request["input"][0]["role"] == "user"
    assert "The public record is incomplete." in request["input"][0]["content"]
    assert "What conflicts" in request["input"][0]["content"]
    assert not {"tools", "previous_response_id", "conversation", "temperature"} & request.keys()


@pytest.mark.asyncio
async def test_postprocessing_instructions_preserve_plain_spoken_text() -> None:
    chat = provider()
    await chat.reply(context(), plain_text_for_postprocessing=True)
    instructions = chat.client.responses.create.call_args.kwargs["instructions"]
    assert GeminiGameChatProvider.POSTPROCESSED_PRESENTATION_INSTRUCTIONS in instructions


@pytest.mark.asyncio
async def test_reply_privacy_guard_blocks_before_network() -> None:
    chat = provider()
    with pytest.raises(PrivacyBoundaryError):
        await chat.reply(context(player_message="Hello <@111111111111111111>"))
    chat.client.responses.create.assert_not_awaited()


@pytest.mark.asyncio
async def test_reply_privacy_guard_blocks_private_model_output() -> None:
    chat = provider()
    chat.client.responses.create.return_value.output_text = "Aster Fixture knows."
    with pytest.raises(PrivacyBoundaryError):
        await chat.reply(context(privacy_forbidden_values=("Aster Fixture",)))


@pytest.mark.asyncio
async def test_dry_run_displays_preview_without_transport(capsys: pytest.CaptureFixture[str]) -> None:
    chat = provider(dry_run=True)
    result = await chat.reply(context())
    assert result.transmitted is False
    assert result.text == ""
    preview = json.loads(capsys.readouterr().out)
    assert preview["openai_dry_run"] is True
    assert preview["purpose"] == "game_chat"
    assert await chat.audio_title(context(), "Safe reply") is None
    chat.client.responses.create.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["reply", "audio_title"])
async def test_network_requires_explicit_authorization(method: str) -> None:
    chat = provider()
    chat.network_authorized = False
    with pytest.raises(PrivacyBoundaryError, match="explicitly authorized"):
        if method == "reply":
            await chat.reply(context())
        else:
            await chat.audio_title(context(), "Safe reply")
    chat.client.responses.create.assert_not_awaited()


@pytest.mark.asyncio
async def test_audio_title_uses_only_exchange_context_and_small_nonreasoning_budget() -> None:
    chat = provider(reasoning_effort="low")
    chat.client.responses.create.return_value.output_text = "Optical Record"
    assert await chat.audio_title(context(), "The optical record remains open.") == "Optical Record"
    request = chat.client.responses.create.call_args.kwargs
    assert request["store"] is False
    assert request["reasoning"] == {"effort": "none"}
    assert request["max_output_tokens"] == 24
    assert "The optical record remains open." in str(request["input"])
    assert "The public record is incomplete." in str(request["input"])
    assert "calibration discrepancy" not in str(request["input"])


@pytest.mark.asyncio
@pytest.mark.parametrize("location", ["request", "response"])
async def test_audio_title_privacy_checks_input_and_output(location: str) -> None:
    chat = provider()
    chat.client.responses.create.return_value.output_text = (
        "Aster Fixture" if location == "response" else "Optical Record"
    )
    reply = "Aster Fixture" if location == "request" else "Safe reply"
    with pytest.raises(PrivacyBoundaryError):
        await chat.audio_title(context(privacy_forbidden_values=("Aster Fixture",)), reply)
    assert chat.client.responses.create.await_count == (location == "response")


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["incomplete", "failed", "in_progress", None])
async def test_partial_or_failed_responses_are_not_delivered(status: str | None) -> None:
    chat = provider()
    chat.client.responses.create.return_value.status = status
    with pytest.raises(RuntimeError, match="did not complete"):
        await chat.reply(context())


@pytest.mark.asyncio
async def test_empty_reply_is_rejected() -> None:
    chat = provider()
    chat.client.responses.create.return_value.output_text = "   "
    with pytest.raises(RuntimeError, match="no chat text"):
        await chat.reply(context())
    assert await chat.audio_title(context(), "Safe reply") is None


@pytest.mark.asyncio
async def test_timeout_cancels_transport() -> None:
    chat = provider()
    cancelled = asyncio.Event()

    async def slow_request(**_kwargs: object) -> object:
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    chat.client.responses.create.side_effect = slow_request
    chat.timeout_seconds = 0.001
    with pytest.raises(TimeoutError):
        await chat.reply(context())
    assert cancelled.is_set()


@pytest.mark.asyncio
async def test_transport_error_is_not_retried() -> None:
    chat = provider()
    chat.client.responses.create.side_effect = RuntimeError("transport unavailable")
    with pytest.raises(RuntimeError, match="transport unavailable"):
        await chat.reply(context())
    assert chat.client.responses.create.await_count == 1


@pytest.mark.asyncio
async def test_close_awaits_openai_client_shutdown() -> None:
    chat = provider()
    await chat.close()
    chat.client.close.assert_awaited_once()
    chat.client = None
    await chat.close()


def settings(**updates: object) -> SimpleNamespace:
    return SimpleNamespace(**({
        "openai_chat_model": "test-model",
        "openai_chat_max_output_tokens": 300,
        "openai_chat_reasoning_effort": "none",
        "openai_request_timeout_seconds": 12.0,
        "openai_dry_run": False,
        "openai_enabled": False,
        "openai_privacy_acknowledged": False,
        "openai_api_key": None,
    } | updates))


def test_from_settings_dry_run_requires_no_key() -> None:
    chat = OpenAIGameChatProvider.from_settings(settings(openai_dry_run=True))
    assert chat.client is None
    assert chat.dry_run is True
    assert chat.network_authorized is False


@pytest.mark.parametrize("overrides", [
    {},
    {"openai_enabled": True},
    {"openai_enabled": True, "openai_privacy_acknowledged": True},
    {"openai_enabled": True, "openai_privacy_acknowledged": True,
     "openai_api_key": SecretStr(" ")},
])
def test_from_settings_fails_closed_without_full_transport_configuration(
    overrides: dict[str, object],
) -> None:
    with pytest.raises(PrivacyBoundaryError):
        OpenAIGameChatProvider.from_settings(settings(**overrides))


def test_from_settings_constructs_async_sdk_without_automatic_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, object]] = []

    def client(**kwargs: object) -> object:
        calls.append(kwargs)
        return SimpleNamespace()

    monkeypatch.setattr("openai.AsyncOpenAI", client)
    chat = OpenAIGameChatProvider.from_settings(settings(
        openai_enabled=True, openai_privacy_acknowledged=True,
        openai_api_key=SecretStr("test-key"),
    ))
    assert chat.network_authorized is True
    assert calls == [{"api_key": "test-key", "timeout": 12.0, "max_retries": 0}]
