from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from tests.test_gemini_config import settings
from uniflora.gemini_chat import GeminiGameChatProvider, GeminiVoiceReplyService
from uniflora.openai_chat import OpenAIGameChatProvider
from uniflora.web_game import create_app, web_chat_provider


def test_provider_defaults_preserve_disabled_chat() -> None:
    config = settings()
    assert config.hypha_chat_provider == "gemini"
    assert not config.feature_gemini_chat
    assert not config.feature_gemini_discord_chat
    assert not config.openai_enabled
    assert not config.openai_dry_run


def test_openai_chat_selection_keeps_gemini_disabled() -> None:
    config = settings(
        hypha_chat_provider="openai", feature_gemini_chat="true", openai_dry_run="true",
    )
    assert not config.gemini_enabled
    assert not config.gemini_dry_run
    assert config.openai_chat_model == "gpt-6-luna"
    assert config.openai_chat_reasoning_effort == "none"


def test_openai_chat_cannot_start_without_authorized_transport() -> None:
    with pytest.raises(ValidationError, match="OPENAI_ENABLED"):
        settings(hypha_chat_provider="openai", feature_gemini_chat="true")


@pytest.mark.parametrize("provider,expected", [
    ("openai", OpenAIGameChatProvider), ("gemini", GeminiGameChatProvider),
])
def test_web_dry_run_selects_only_requested_provider(monkeypatch, provider, expected) -> None:
    monkeypatch.setenv("HYPHA_CHAT_PROVIDER", provider)
    monkeypatch.setenv(f"{provider.upper()}_DRY_RUN", "true")
    result = web_chat_provider()
    assert isinstance(result, expected)
    assert result.client is None
    assert result.dry_run


def test_web_openai_does_not_fall_back_to_gemini_key(monkeypatch) -> None:
    monkeypatch.setenv("HYPHA_CHAT_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_DRY_RUN", "false")
    monkeypatch.setenv("OPENAI_PRIVACY_ACKNOWLEDGED", "true")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "unused-test-key")
    with pytest.raises(SystemExit, match="OPENAI API key"):
        web_chat_provider()


def test_web_openai_needs_privacy_acknowledgement(monkeypatch) -> None:
    monkeypatch.setenv("HYPHA_CHAT_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_DRY_RUN", "false")
    monkeypatch.setenv("OPENAI_API_KEY", "unused-test-key")
    monkeypatch.setenv("OPENAI_PRIVACY_ACKNOWLEDGED", "false")
    with pytest.raises(SystemExit, match="privacy approval"):
        web_chat_provider()


def test_web_unknown_provider_stops_before_client_creation(monkeypatch) -> None:
    monkeypatch.setenv("HYPHA_CHAT_PROVIDER", "typo")
    with pytest.raises(SystemExit, match="HYPHA_CHAT_PROVIDER"):
        web_chat_provider()


def test_web_openai_uses_only_selected_key_without_constructing_gemini(monkeypatch) -> None:
    monkeypatch.setenv("HYPHA_CHAT_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_DRY_RUN", "false")
    monkeypatch.setenv("OPENAI_API_KEY", "selected-test-key")
    monkeypatch.setenv("OPENAI_PRIVACY_ACKNOWLEDGED", "true")
    monkeypatch.setenv("GEMINI_API_KEY", "other-provider-test-key")
    calls: list[dict[str, object]] = []

    def client(**kwargs: object) -> object:
        calls.append(kwargs)
        return SimpleNamespace()

    def unwanted_client(**_kwargs: object) -> None:
        pytest.fail("Selecting OpenAI must not construct a Gemini client")

    monkeypatch.setattr("openai.AsyncOpenAI", client)
    monkeypatch.setattr("google.genai.Client", unwanted_client)
    result = web_chat_provider()
    assert isinstance(result, OpenAIGameChatProvider)
    assert result.network_authorized
    assert calls == [{"api_key": "selected-test-key", "timeout": 12.0, "max_retries": 0}]


@pytest.mark.parametrize("selected,expected", [
    ("openai", OpenAIGameChatProvider), ("gemini", GeminiGameChatProvider),
])
def test_discord_selector_preserves_message_intent_boundaries(selected, expected) -> None:
    from uniflora.discord_adapter import build_bot, initial_routing
    from uniflora.health import HealthService
    from uniflora.runtime import RuntimeSessions

    config = settings(
        feature_natural_language="false", feature_gemini_chat="true",
        hypha_chat_provider=selected, **{f"{selected}_dry_run": "true"},
    )
    sessions = RuntimeSessions()
    bot = build_bot(
        config, sessions, initial_routing(config),
        HealthService(sessions, "127.0.0.1", 8080),
    )
    assert bot.gemini_voice is not None
    assert isinstance(bot.gemini_voice.provider, expected)
    assert bot.gemini_voice.provider.client is None
    assert not bot.intents.messages
    assert not bot.intents.message_content


@pytest.mark.asyncio
async def test_web_cleanup_closes_selected_openai_client_and_runtime() -> None:
    client = SimpleNamespace(close=AsyncMock())
    provider = OpenAIGameChatProvider(
        client, "test-model", timeout_seconds=1, max_output_tokens=300,
        network_authorized=True,
    )
    reply = GeminiVoiceReplyService(provider, SimpleNamespace())

    async def relay_run(stop) -> None:
        await stop.wait()

    api = SimpleNamespace(
        status=AsyncMock(), command=AsyncMock(), synthesize_voice=AsyncMock(),
        publisher=None, close=AsyncMock(), runtime=SimpleNamespace(close=AsyncMock()),
    )
    app = create_app(api, chat_relay=SimpleNamespace(run=relay_run), chat_reply=reply)
    app.freeze()
    await app.startup()
    await app.cleanup()
    client.close.assert_awaited_once()
    api.close.assert_awaited_once()
    api.runtime.close.assert_awaited_once()
