from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from uniflora.config import Settings
from uniflora.content.loader import PuzzleRegistry
from uniflora.engine.actions import ObserveAction
from uniflora.engine.core import DeterministicEngine
from uniflora.engine.position_zero import EnvironmentPositionValidator
from uniflora.game_service import GameService
from uniflora.narration import (
    FallbackNarrator,
    NarrationContext,
    NarrationGuard,
    NarrationProviderResult,
    NarrationService,
    NarrationUsage,
    OpenAINarrationProvider,
    StructuredNarration,
)
from uniflora.runtime import Environment, RoutingSnapshot, SessionMode
from uniflora.storage.database import Database
from uniflora.storage.models import ApiUsageRecord, NarrationHistory
from uniflora.storage.repository import GameRepository, SessionRef


def narration_settings(**changes: Any) -> Settings:
    values: dict[str, Any] = {
        "discord_token": "fake",
        "discord_guild_id": 1,
        "live_puzzle_channel_id": 10,
        "test_puzzle_channel_id": 20,
        "mycotroph_role_id": 30,
        "admin_user_ids": "99",
        "openai_api_key": "test-key",
        "openai_enabled": True,
        "openai_privacy_acknowledged": True,
        "openai_per_user_cooldown_seconds": 0,
        "openai_global_cooldown_seconds": 0,
        "openai_request_timeout_seconds": 0.1,
    }
    return Settings(_env_file=None, **(values | changes))  # type: ignore[arg-type]


class FakeNarrationProvider:
    model = "fake-narration-model"
    dry_run = False

    def __init__(self, *, unsafe: bool = False, failure: BaseException | None = None) -> None:
        self.unsafe = unsafe
        self.failure = failure
        self.contexts: list[NarrationContext] = []
        self.closed = False

    async def narrate(self, context: NarrationContext) -> NarrationProviderResult:
        self.contexts.append(context)
        if self.failure is not None:
            raise self.failure
        lead = (
            "invented progression"
            if self.unsafe
            else (
                "boundary signal retained"
                if context.profile == "surface_noise"
                else "the mycotrophs correlate this confirmed relation"
            )
        )
        return NarrationProviderResult(
            {
                "lead": lead,
                "closing": "shared public trace" if context.profile == "surface_noise" else "",
            },
            NarrationUsage(80, 10, 20),
        )

    async def close(self) -> None:
        self.closed = True


async def build_repository(
    path: Path,
) -> tuple[Database, GameRepository, dict[Environment, SessionRef]]:
    database = Database(f"sqlite+aiosqlite:///{path.as_posix()}")
    await database.create_schema_for_tests()
    repository = GameRepository(database)
    _, refs = await repository.bootstrap(RoutingSnapshot(1, 10, 20, 30, frozenset({99})))
    return database, repository, refs


def narration_context(**changes: Any) -> NarrationContext:
    values: dict[str, Any] = {
        "profile": "surface_noise",
        "event_type": "observation.unlocked",
        "narration_key": "observation_unlocked",
        "confirmed_outcome": "The northern store holds 12 confirmed units.",
        "position_completed": False,
        "allowed_style_words": (
            "boundary",
            "signal",
            "retained",
            "shared",
            "public",
            "trace",
        ),
    }
    return NarrationContext(**(values | changes))


def test_narration_guard_preserves_canonical_facts_exactly() -> None:
    context = narration_context()
    safe = StructuredNarration(
        lead="boundary signal retained",
        closing="shared public trace",
    )
    assert NarrationGuard.compose(safe, context) == (
        "boundary signal retained The northern store holds 12 confirmed units. shared public trace"
    )
    invented = safe.model_copy(update={"lead": "secret chamber detected"})
    assert NarrationGuard.compose(invented, context) is None
    changed_context = narration_context(confirmed_outcome="A different local outcome.")
    assert "A different local outcome." in (NarrationGuard.compose(safe, changed_context) or "")


def test_confirmed_fallbacks_are_varied_and_profile_specific() -> None:
    narrator = FallbackNarrator()
    surface = {
        narrator.render_confirmed_outcome(
            profile="surface_noise", event_id=f"event-{number}", outcome="Outcome retained."
        )
        for number in range(12)
    }
    local = narrator.render_confirmed_outcome(
        profile="local_correlation", event_id="event-1", outcome="Outcome retained."
    )
    assert len(surface) > 1
    assert all("Outcome retained." in item for item in surface)
    assert "mycotrophs" in local
    assert local not in surface


@pytest.mark.asyncio
async def test_valid_generation_is_bounded_recorded_and_environment_scoped(
    tmp_path: Path,
) -> None:
    database, repository, refs = await build_repository(tmp_path / "narration.db")
    provider = FakeNarrationProvider()
    service = NarrationService(narration_settings(), repository, FallbackNarrator(), provider)
    fact = "The northern store holds 12 confirmed units."
    test_text = await service.render(
        refs[Environment.TEST],
        participant_id="test:observer",
        profile="surface_noise",
        event_id="test-event",
        event_type="observation.unlocked",
        narration_key="observation_unlocked",
        public_data={"public_text": fact},
        permitted_public_facts=(fact,),
        position_completed=False,
    )
    live_text = await service.render(
        refs[Environment.LIVE],
        participant_id="discord:101",
        profile="local_correlation",
        event_id="live-event",
        event_type="observation.unlocked",
        narration_key="observation_unlocked",
        public_data={"public_text": "A separate live fact is confirmed."},
        permitted_public_facts=("A separate live fact is confirmed.",),
        position_completed=False,
    )
    assert fact in test_text and len(test_text) < 2000
    assert "mycotrophs" in live_text
    assert provider.contexts[0].profile == "surface_noise"
    assert provider.contexts[1].profile == "local_correlation"
    assert not hasattr(provider.contexts[1], "recent_public_context")
    assert await repository.count_rows(refs[Environment.TEST], NarrationHistory) == 1
    assert await repository.count_rows(refs[Environment.LIVE], NarrationHistory) == 1
    assert await repository.count_rows(refs[Environment.TEST], ApiUsageRecord) == 1
    assert await repository.count_rows(refs[Environment.LIVE], ApiUsageRecord) == 1
    await service.close()
    assert provider.closed
    await database.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "provider,generated_by",
    (
        (FakeNarrationProvider(unsafe=True), "fallback:guard"),
        (FakeNarrationProvider(failure=TimeoutError()), "fallback:timeout"),
    ),
)
async def test_invalid_or_timed_out_narration_falls_back_without_losing_outcome(
    tmp_path: Path, provider: FakeNarrationProvider, generated_by: str
) -> None:
    database, repository, refs = await build_repository(
        tmp_path / f"fallback-{generated_by.replace(':', '-')}.db"
    )
    service = NarrationService(narration_settings(), repository, FallbackNarrator(), provider)
    canonical = "A confirmed public observation remains unchanged."
    rendered = await service.render(
        refs[Environment.TEST],
        participant_id="test:observer",
        profile="surface_noise",
        event_id="event-fallback",
        event_type="observation.unlocked",
        narration_key="observation_unlocked",
        public_data={"public_text": canonical},
        permitted_public_facts=(canonical,),
        position_completed=False,
    )
    history = await repository.recent_narration(refs[Environment.TEST], limit=1)
    assert canonical in rendered
    assert "invented progression" not in rendered
    assert history[0]["generated_by"] == generated_by
    await database.dispose()


@pytest.mark.asyncio
async def test_disabled_or_over_budget_api_keeps_deterministic_narration(
    tmp_path: Path,
) -> None:
    database, repository, refs = await build_repository(tmp_path / "budget.db")
    provider = FakeNarrationProvider()
    disabled = NarrationService(
        narration_settings(openai_enabled=False), repository, FallbackNarrator(), provider
    )
    disabled_text = await disabled.render(
        refs[Environment.TEST],
        participant_id="test:observer",
        profile="surface_noise",
        event_id="disabled-event",
        event_type="summary.recorded",
        narration_key="accepted",
        public_data={"public_text": "The disabled path remains playable."},
        permitted_public_facts=(),
        position_completed=False,
    )
    assert "The disabled path remains playable." in disabled_text
    assert provider.contexts == []
    settings = narration_settings(
        openai_soft_daily_budget_usd=0.005,
        openai_hard_daily_budget_usd=0.01,
    )
    await repository.record_api_usage(
        refs[Environment.TEST],
        model="seed",
        purpose="interpretation",
        participant_id="test:observer",
        input_tokens=1,
        cached_input_tokens=0,
        output_tokens=1,
        estimated_cost=0.01,
    )
    service = NarrationService(settings, repository, FallbackNarrator(), provider)
    rendered = await service.render(
        refs[Environment.TEST],
        participant_id="test:observer",
        profile="surface_noise",
        event_id="budget-event",
        event_type="summary.recorded",
        narration_key="accepted",
        public_data={"public_text": "The public summary is confirmed."},
        permitted_public_facts=(),
        position_completed=False,
    )
    assert "The public summary is confirmed." in rendered
    assert provider.contexts == []
    assert (await repository.recent_narration(refs[Environment.TEST], limit=1))[0][
        "generated_by"
    ] == "fallback:budget"
    await database.dispose()


@pytest.mark.asyncio
async def test_game_narration_cannot_add_state_or_unlocks(tmp_path: Path) -> None:
    database, repository, refs = await build_repository(tmp_path / "state-authority.db")
    registry = PuzzleRegistry.load_packaged()
    fallback = FallbackNarrator()
    validator = EnvironmentPositionValidator(registry.get(0), enforce_cycles=False)
    provider = FakeNarrationProvider(unsafe=True)
    narration = NarrationService(narration_settings(), repository, fallback, provider)
    game = GameService(
        repository,
        refs,
        registry,
        DeterministicEngine(repository, validator),
        fallback,
        validator,
        narration,
    )
    await game.initialize()
    await repository.transition(
        refs[Environment.TEST], SessionMode.RUNNING, {SessionMode.LOCKED}, "discord:99"
    )
    await repository.select_test_identity(refs[Environment.TEST], "observer", 99)
    result = await game.act(
        Environment.TEST,
        99,
        ObserveAction(action="observe", entity_id="north"),
        "narrated-observation",
    )
    state = await repository.state(refs[Environment.TEST])
    assert result.accepted and "invented progression" not in result.text
    assert state["current_position"] == 0
    assert state["data"]["unlocked_observations"] == ["northern_usable_capacity"]
    assert len(state["data"]["confirmed_facts"]) == 1
    await database.dispose()


class FakeResponses:
    def __init__(self) -> None:
        self.kwargs: dict[str, object] = {}

    async def parse(self, **kwargs: object) -> object:
        self.kwargs = kwargs
        return SimpleNamespace(
            output_parsed=StructuredNarration(
                lead="boundary signal retained",
                closing="",
            ),
            usage=SimpleNamespace(
                input_tokens=40,
                output_tokens=8,
                input_tokens_details=SimpleNamespace(cached_tokens=7),
            ),
        )


class FakeOpenAIClient:
    def __init__(self) -> None:
        self.responses = FakeResponses()
        self.closed = False

    async def close(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_openai_narration_provider_uses_flat_structured_responses_output() -> None:
    client = FakeOpenAIClient()
    provider = OpenAINarrationProvider(
        client, "fake-model", max_output_tokens=99, network_authorized=True
    )
    result = await provider.narrate(
        narration_context(confirmed_outcome="Confirmed outcome.")
    )
    request = client.responses.kwargs
    assert request["text_format"] is StructuredNarration
    assert request["max_output_tokens"] == 99
    assert request["store"] is False
    assert "TRUSTED_PUBLIC_EVENT_DATA" in request["input"][1]["content"]  # type: ignore[index]
    assert result.usage == NarrationUsage(40, 7, 8)
    await provider.close()
    assert client.closed
