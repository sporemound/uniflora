from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pytest

from uniflora.config import Settings
from uniflora.content.loader import PuzzleRegistry
from uniflora.discord_adapter import build_bot, initial_routing
from uniflora.engine.core import DeterministicEngine
from uniflora.engine.position_one import PositionOneValidator
from uniflora.engine.position_zero import EnvironmentPositionValidator
from uniflora.game_service import GameService
from uniflora.health import HealthService
from uniflora.narration import FallbackNarrator
from uniflora.runtime import Environment, RoutingSnapshot, RuntimeSessions
from uniflora.storage.database import Database
from uniflora.storage.repository import GameRepository, MutationPlan


@dataclass
class FakeMessage:
    id: int
    pin_failures: int = 0
    pin_calls: int = 0

    async def pin(self, *, reason: str | None = None) -> None:
        assert reason is not None
        assert reason.startswith("The Missing Interior Position ")
        assert reason.endswith(" reference")
        self.pin_calls += 1
        if self.pin_failures:
            self.pin_failures -= 1
            raise RuntimeError("pin permission unavailable")


@dataclass
class FakeChannel:
    message: FakeMessage
    sends: list[dict[str, object]] = field(default_factory=list)
    fetches: list[int] = field(default_factory=list)

    async def send(
        self,
        content: str,
        *,
        file: object | None = None,
        files: list[object] | None = None,
    ) -> FakeMessage:
        attachments = files if files is not None else ([file] if file is not None else [])
        first = attachments[0]
        self.sends.append(
            {
                "content": content,
                "filename": first.filename,  # type: ignore[attr-defined]
                "description": first.description,  # type: ignore[attr-defined]
                "header": first.fp.read(8),  # type: ignore[attr-defined]
                "filenames": [item.filename for item in attachments],  # type: ignore[attr-defined]
                "descriptions": [item.description for item in attachments],  # type: ignore[attr-defined]
            }
        )
        return self.message

    async def fetch_message(self, message_id: int) -> FakeMessage:
        self.fetches.append(message_id)
        assert message_id == self.message.id
        return self.message


async def build_announcement_game(path: Path) -> tuple[Database, GameService]:
    database = Database(f"sqlite+aiosqlite:///{path.as_posix()}")
    await database.create_schema_for_tests()
    repository = GameRepository(database)
    _, refs = await repository.bootstrap(RoutingSnapshot(1, 10, 20, 30, frozenset({99})))
    registry = PuzzleRegistry.load_packaged()
    validator = EnvironmentPositionValidator(registry, enforce_cycles=False)
    game = GameService(
        repository,
        refs,
        registry,
        DeterministicEngine(repository, validator),
        FallbackNarrator(),
        validator,
    )
    await game.initialize()
    initializer = PositionOneValidator(registry.get(1))
    for environment, ref in refs.items():

        def planner(state: dict[str, object]) -> MutationPlan:
            after = dict(state)
            after["current_position"] = 1
            after["response_profile"] = "local_correlation"
            after["data"] = initializer.initialize_from_previous(registry.get(0).initial_state())
            return MutationPlan(
                event_type="test.position_one.opened", state_after=after, payload={}
            )

        await repository.mutate(
            ref,
            actor_id="system:setup",
            idempotency_key=f"test-position-one:{environment.value}",
            planner=planner,
        )
    return database, game


async def build_artifact_reveal_game(path: Path) -> tuple[Database, GameService]:
    database = Database(f"sqlite+aiosqlite:///{path.as_posix()}")
    await database.create_schema_for_tests()
    repository = GameRepository(database)
    _, refs = await repository.bootstrap(RoutingSnapshot(1, 10, 20, 30, frozenset({99})))
    registry = PuzzleRegistry.load_packaged()
    validator = EnvironmentPositionValidator(registry, enforce_cycles=False)
    game = GameService(
        repository,
        refs,
        registry,
        DeterministicEngine(repository, validator),
        FallbackNarrator(),
        validator,
    )
    await game.initialize()

    def planner(state: dict[str, object]) -> MutationPlan:
        after = dict(state)
        data = dict(after["data"])  # type: ignore[arg-type]
        counters = dict(data["counters"])  # type: ignore[arg-type]
        counters["repair"] = {"damaged_circulation": 1}
        data["counters"] = counters
        after["data"] = data
        return MutationPlan(event_type="test.route_tested", state_after=after, payload={})

    await repository.mutate(
        refs[Environment.LIVE],
        actor_id="system:setup",
        idempotency_key="test-route-reveal",
        planner=planner,
    )
    return database, game


def settings() -> Settings:
    return Settings(
        _env_file=None,
        discord_token="fake",
        discord_guild_id="1",
        live_puzzle_channel_id="10",
        test_puzzle_channel_id="20",
        mycotroph_role_id="30",
        admin_user_ids="99",
    )  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_chart_creates_automatic_announcement_without_presentation_block(
    tmp_path: Path,
) -> None:
    database, game = await build_artifact_reveal_game(tmp_path / "chart-fallback.db")
    ref = game.refs[Environment.LIVE]
    definition = game.registries[Environment.LIVE].get(3)

    def planner(state: dict[str, object]) -> MutationPlan:
        after = dict(state)
        after["current_position"] = 3
        after["response_profile"] = "reciprocity"
        after["data"] = definition.initial_state()
        return MutationPlan(event_type="test.position_three.opened", state_after=after, payload={})

    await game.repository.mutate(
        ref,
        actor_id="system:test",
        idempotency_key="test:position-three",
        planner=planner,
    )
    announcement = await game.pending_position_announcement(Environment.LIVE)

    assert announcement is not None
    assert announcement.position == 3
    assert announcement.image_filename == "position_3_cycle_flow_chart.png"
    assert "POSITION 3 — THE PROVISION WORKS" in announcement.introduction
    assert "cycle flow chart" in announcement.image_alt_text
    assert announcement.additional_images == ()
    assert await game.mark_position_announcement_delivered(Environment.LIVE, 3, 3030)
    assert await game.pending_position_pin(Environment.LIVE) == (3, 3030)
    await database.dispose()


@pytest.mark.asyncio
async def test_current_map_is_present_only_when_current_position_asset_exists(
    tmp_path: Path,
) -> None:
    position_one_database, position_one_game = await build_announcement_game(
        tmp_path / "map-position-one.db"
    )
    position_zero_database, position_zero_game = await build_artifact_reveal_game(
        tmp_path / "map-position-zero.db"
    )

    current = await position_one_game.current_map(Environment.LIVE)
    missing = await position_zero_game.current_map(Environment.LIVE)

    assert current is not None
    assert current.image_filename == "position_1_map.png"
    assert current.image_bytes.startswith(b"\x89PNG\r\n\x1a\n")
    assert "water routes" in current.image_alt_text
    assert "Shaded Planting Surface" in current.image_alt_text
    assert missing is None
    await position_one_database.dispose()
    await position_zero_database.dispose()


@pytest.mark.asyncio
async def test_current_cycle_chart_matches_current_position(tmp_path: Path) -> None:
    database, game = await build_announcement_game(tmp_path / "current-chart.db")

    chart = await game.current_cycle_chart(Environment.LIVE)

    assert chart is not None
    assert chart.image_filename == "position_1_cycle_flow_chart.png"
    assert chart.image_bytes.startswith(b"\x89PNG\r\n\x1a\n")
    assert "Position 1 cycle flow chart" in chart.image_alt_text
    await database.dispose()


@pytest.mark.asyncio
async def test_position_message_posts_image_and_intro_once_then_pins_it(tmp_path: Path) -> None:
    database, game = await build_announcement_game(tmp_path / "announcement.db")
    configured = settings()
    sessions = RuntimeSessions()
    bot = build_bot(
        configured,
        sessions,
        initial_routing(configured),
        HealthService(sessions, "127.0.0.1", 8080),
        game=game,
    )
    channel = FakeChannel(FakeMessage(1234))

    await bot._announce_current_position(Environment.TEST, channel)
    await bot._announce_current_position(Environment.TEST, channel)

    assert len(channel.sends) == 1
    sent = channel.sends[0]
    assert str(sent["content"]).startswith(
        "[TEST SURFACE]\n## POSITION 1 — THE INTERRUPTED CURRENT"
    )
    assert "Route 03 remains open." in str(sent["content"])
    assert sent["filename"] == "position_1_interrupted_current_atmosphere.png"
    assert "sepia botanical-field-guide panorama" in str(sent["description"])
    assert sent["filenames"] == [
        "position_1_interrupted_current_atmosphere.png",
        "position_1_cycle_flow_chart.png",
    ]
    assert len(sent["descriptions"]) == 2
    assert "cycle flow chart" in str(sent["descriptions"])
    assert sent["header"] == b"\x89PNG\r\n\x1a\n"
    assert channel.message.pin_calls == 1
    assert channel.fetches == []

    state = await game.repository.state(game.refs[Environment.TEST])
    assert state["data"]["announced_position_introductions"] == [1]
    assert state["data"]["position_introduction_deliveries"]["1"] == {
        "message_id": 1234,
        "content_version": "3.3.1",
        "pinned": True,
    }
    await bot.close()
    await database.dispose()


@pytest.mark.asyncio
async def test_newer_recorded_announcement_is_not_reposted_after_content_rollback(
    tmp_path: Path,
) -> None:
    database, game = await build_announcement_game(tmp_path / "content-rollback.db")
    ref = game.refs[Environment.LIVE]

    def planner(state: dict[str, object]) -> MutationPlan:
        after = dict(state)
        data = dict(after["data"])  # type: ignore[arg-type]
        data["announced_position_introductions"] = [1]
        data["position_introduction_deliveries"] = {
            "1": {
                "message_id": 3200,
                "content_version": "3.3.1",
                "pinned": False,
            }
        }
        after["data"] = data
        return MutationPlan(
            event_type="test.newer_announcement_recorded",
            state_after=after,
            payload={},
        )

    await game.repository.mutate(
        ref,
        actor_id="system:test",
        idempotency_key="test:newer-announcement",
        planner=planner,
    )

    assert await game.pending_position_announcement(Environment.LIVE) is None
    await database.dispose()


@pytest.mark.asyncio
async def test_missing_announcement_is_retired_without_reposting(tmp_path: Path) -> None:
    database, game = await build_announcement_game(tmp_path / "missing-announcement.db")
    assert await game.mark_position_announcement_delivered(Environment.LIVE, 1, 3300)

    assert await game.mark_position_announcement_missing(Environment.LIVE, 1, 3300)
    assert await game.pending_position_announcement(Environment.LIVE) is None
    assert await game.pending_position_pin(Environment.LIVE) is None
    state = await game.repository.state(game.refs[Environment.LIVE])
    assert state["data"]["position_introduction_deliveries"]["1"]["message_missing"] is True
    await database.dispose()


@pytest.mark.asyncio
async def test_failed_pin_retries_without_reposting_position_message(tmp_path: Path) -> None:
    database, game = await build_announcement_game(tmp_path / "pin-retry.db")
    configured = settings()
    sessions = RuntimeSessions()
    bot = build_bot(
        configured,
        sessions,
        initial_routing(configured),
        HealthService(sessions, "127.0.0.1", 8080),
        game=game,
    )
    channel = FakeChannel(FakeMessage(5678, pin_failures=1))

    await bot._announce_current_position(Environment.LIVE, channel)
    assert len(channel.sends) == 1
    assert not str(channel.sends[0]["content"]).startswith("[TEST SURFACE]")
    assert await game.pending_position_pin(Environment.LIVE) == (1, 5678)

    await bot._announce_current_position(Environment.LIVE, channel)
    assert len(channel.sends) == 1
    assert channel.fetches == [5678]
    assert channel.message.pin_calls == 2
    assert await game.pending_position_pin(Environment.LIVE) is None
    await bot.close()
    await database.dispose()


@pytest.mark.asyncio
async def test_successful_route_test_posts_atmospheric_artifact_once(tmp_path: Path) -> None:
    database, game = await build_artifact_reveal_game(tmp_path / "artifact-reveal.db")
    configured = settings()
    sessions = RuntimeSessions()
    bot = build_bot(
        configured,
        sessions,
        initial_routing(configured),
        HealthService(sessions, "127.0.0.1", 8080),
        game=game,
    )
    channel = FakeChannel(FakeMessage(9012))

    await bot._announce_current_position(Environment.LIVE, channel)
    await bot._announce_current_position(Environment.LIVE, channel)

    assert len(channel.sends) == 2
    sent = channel.sends[0]
    assert "Route 03 carries more than water" in str(sent["content"])
    assert "not a confirmed map" in str(sent["content"])
    assert sent["filename"] == "route_03_settlement_vista.png"
    assert "atmospheric illustrated panorama" in str(sent["description"])
    assert sent["header"] == b"\x89PNG\r\n\x1a\n"
    chart = channel.sends[1]
    assert chart["filename"] == "position_0_cycle_flow_chart.png"
    assert "POSITION 0 — THE DRY NETWORK" in str(chart["content"])
    assert channel.message.pin_calls == 1

    state = await game.repository.state(game.refs[Environment.LIVE])
    assert state["data"]["revealed_artifacts"] == ["route_03_settlement_vista"]
    assert state["data"]["artifact_reveal_deliveries"]["route_03_settlement_vista"] == {
        "message_id": 9012,
        "source_position": 0,
        "content_version": "1.4.0",
    }
    assert state["data"]["announced_position_introductions"] == [0]
    assert await game.pending_artifact_reveal(Environment.LIVE) is None
    await bot.close()
    await database.dispose()
