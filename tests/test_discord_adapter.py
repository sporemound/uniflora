from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import discord
import pytest
from discord import app_commands

from uniflora.config import Settings
from uniflora.content.loader import PuzzleRegistry
from uniflora.difficulty import (
    DifficultyLevel,
    DifficultyPreference,
    DifficultySelectionResult,
)
from uniflora.discord_adapter import (
    AprsFiSettings,
    DifficultyPollView,
    SettlementInterventionView,
    _ufo_report_event_date_label,
    build_bot,
    initial_routing,
)
from uniflora.engine.actions import (
    AuditAction,
    BeginStackAction,
    # existing imports...
    ConfirmReconstructionAction,
    ContainAction,
    DocumentAction,
    InoculateAction,
    InspectAction,
    ProposeCirculationAction,
    ProposeMemoryArchiveAction,
    ProposeProductionReformAction,
    ProposeReciprocityAction,
    ProposeRemediationProtocolAction,
    RedesignAction,
    ReduceAction,
    RefuseAction,
    ReplaceAction,
    RestAction,
    SampleAction,
    SeparateAction,
    SlowAction,
    SummarizeAction,
)
from uniflora.engine.core import EngineOutcome
from uniflora.external_feeds.aprsfi.errors import AprsFiConfigurationError
from uniflora.external_ufo_reports import ExternalUfoReport
from uniflora.game_service import GameService, PositionImage, PublicResult
from uniflora.health import HealthService
from uniflora.narration import FallbackNarrator
from uniflora.runtime import Environment, RuntimeSessions
from uniflora.storage.repository import SessionRef


def _settings() -> Settings:
    return Settings(
        _env_file=None,
        discord_token="fake",
        discord_guild_id="1",
        live_puzzle_channel_id="10",
        test_puzzle_channel_id="20",
        mycotroph_role_id="30",
        admin_user_ids="99",
    )  # type: ignore[arg-type]


def _build_test_bot() -> Any:
    settings = _settings()
    sessions = RuntimeSessions()
    return build_bot(
        settings,
        sessions,
        initial_routing(settings),
        HealthService(sessions, "127.0.0.1", 8080),
    )


def test_live_v2_commands_are_registered_only_with_live_runtime() -> None:
    assert _build_test_bot().tree.get_command("v2-live") is None
    settings = _settings()
    sessions = RuntimeSessions()
    bot = build_bot(
        settings,
        sessions,
        initial_routing(settings),
        HealthService(sessions, "127.0.0.1", 8080),
        v2_live_runtime=SimpleNamespace(),  # type: ignore[arg-type]
    )
    group = bot.tree.get_command("v2-live")
    assert isinstance(group, app_commands.Group)
    assert {item.name for item in group.commands} >= {
        "status", "begin", "command", "role", "guide", "ask", "difficulty",
    }


@pytest.mark.asyncio
async def test_live_role_assigns_through_live_runtime() -> None:
    settings = _settings()
    calls: list[tuple[str, str, str | None, str | None]] = []
    messages: list[str] = []

    class Runtime:
        async def session(self):
            return SimpleNamespace(
                state=SimpleNamespace(completed_position_ids={"network_orientation"}),
            )

        async def assign_public_role(self, **kwargs: str | None):
            calls.append((
                str(kwargs["player_id"]), str(kwargs["role_id"]),
                kwargs["display_name"], kwargs["description"],
            ))
            return SimpleNamespace(accepted=True, to_text=lambda: "Role assigned")

        async def available_public_roles(self, current: str = ""):
            assert current == "field"
            return (("field_observer", "Field Observer — examines optical record"),)

    sessions = RuntimeSessions()
    bot = build_bot(
        settings, sessions, initial_routing(settings),
        HealthService(sessions, "127.0.0.1", 8080),
        v2_live_runtime=Runtime(),  # type: ignore[arg-type]
    )
    group = bot.tree.get_command("v2-live")
    assert isinstance(group, app_commands.Group)
    role_command = group.get_command("role")
    assert role_command is not None
    async def standard(*_args: object, **_kwargs: object) -> DifficultyLevel:
        return DifficultyLevel.STANDARD
    bot._difficulty_for = standard  # type: ignore[method-assign]

    class Response:
        async def defer(self, **_kwargs: object) -> None:
            pass

        def is_done(self) -> bool:
            return True

    class Followup:
        async def send(self, content: str, **_kwargs: object) -> None:
            messages.append(content)

    interaction = SimpleNamespace(
        guild_id=1, channel_id=10,
        user=SimpleNamespace(id=99, roles=()),
        response=Response(), followup=Followup(),
    )
    await role_command.callback(
        interaction, role="field_observer", name="Field Analyst",
        description="Review the optical record",
    )

    assert calls == [(
        "discord:99", "field_observer", "Field Analyst", "Review the optical record",
    )]
    assert any("Role assigned" in message for message in messages)

    payload = role_command.to_dict(bot.tree)
    role_option = next(item for item in payload["options"] if item["name"] == "role")
    assert role_option["autocomplete"] is True



def test_ufo_report_event_date_label_does_not_invent_time() -> None:
    report = ExternalUfoReport(
        report_id="618999",
        source_key="ufosint",
        source_name="UFOSINT Explorer",
        source_page_url="https://ufosint.com/",
        source_url=None,
        authorization_mode="api",
        observed_at=datetime(2026, 7, 28, tzinfo=UTC),
        indexed_at=datetime(2026, 7, 28, 6, tzinfo=UTC),
        latitude=45.0,
        longitude=-122.0,
        title="Light observation near Portland, Oregon, United States",
        location_name="Portland, Oregon, United States",
        coordinate_precision="city",
        summary="UFOSINT indexed a quality-screened sighting.",
        status="unverified",
        quality_score=88,
    )

    label = _ufo_report_event_date_label(report)

    assert label == (
        "2026-07-28\n"
        "UFOSINT provides an event date, not an authoritative event time."
    )
    assert "00:00" not in label

def test_aprsfi_disabled_does_not_load_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("UNIFLORA_APRSFI_ENABLED", raising=False)

    def unexpected_load(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise AssertionError("disabled APRS.fi must not load settings")

    monkeypatch.setattr(AprsFiSettings, "from_environment", unexpected_load)

    bot = _build_test_bot()

    assert bot._aprsfi_service is None


@pytest.mark.parametrize("enabled", ("1", "true", "TRUE", "yes", "on"))
def test_aprsfi_enabled_fails_closed_when_settings_are_invalid(
    monkeypatch: pytest.MonkeyPatch,
    enabled: str,
) -> None:
    monkeypatch.setenv("UNIFLORA_APRSFI_ENABLED", enabled)

    def invalid_settings(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise AprsFiConfigurationError("missing APRS.fi credentials")

    monkeypatch.setattr(AprsFiSettings, "from_environment", invalid_settings)

    with pytest.raises(AprsFiConfigurationError, match="missing APRS.fi credentials"):
        _build_test_bot()


@pytest.mark.asyncio
async def test_rejected_action_does_not_retry_position_announcement() -> None:
    bot = _build_test_bot()
    announcements: list[Environment] = []

    async def authorize(interaction: object) -> Environment:
        del interaction
        return Environment.LIVE

    async def send(*args: object, **kwargs: object) -> None:
        del args, kwargs

    async def announce(environment: Environment, channel: object) -> None:
        del channel
        announcements.append(environment)

    class RejectedGame:
        async def act(self, *args: object, **kwargs: object) -> object:
            del args, kwargs
            return SimpleNamespace(accepted=False, text="That move is unavailable.")

        async def has_active_settlement_event(self, environment: Environment) -> bool:
            del environment
            return False

    bot._authorize_player = authorize
    bot._send = send
    bot._announce_current_position = announce
    bot.game = RejectedGame()
    interaction = SimpleNamespace(
        id=123,
        user=SimpleNamespace(id=7),
        channel=object(),
    )

    await bot._perform_action(
        interaction,
        InspectAction(action="inspect", target_entity_id="relay"),
    )

    assert announcements == []

@pytest.mark.asyncio
async def test_position_zero_confirm_command_wires_proposal_id() -> None:
    bot = _build_test_bot()
    root = bot.tree.get_command("interior")
    assert isinstance(root, app_commands.Group)

    actions = root.get_command("act")
    assert isinstance(actions, app_commands.Group)

    confirm = actions.get_command("confirm")
    assert confirm is not None
    assert {parameter.name for parameter in confirm.parameters} == {"proposal_id"}

    captured: list[Any] = []

    async def capture(_interaction: object, action: Any) -> None:
        captured.append(action)

    bot._perform_action = capture

    await confirm.callback(
        SimpleNamespace(),
        proposal_id="p-test-confirmation",
    )

    assert len(captured) == 1
    assert isinstance(captured[0], ConfirmReconstructionAction)
    assert captured[0].model_dump() == {
        "action": "confirm_reconstruction",
        "proposal_id": "p-test-confirmation",
    }

@pytest.mark.asyncio
async def test_summarize_defers_once_and_attaches_chart_to_first_followup() -> None:
    bot = _build_test_bot()
    deferrals: list[bool] = []
    sends: list[tuple[str, dict[str, Any]]] = []

    async def authorize(interaction: object) -> Environment:
        del interaction
        return Environment.TEST

    async def defer() -> None:
        deferrals.append(True)

    async def send(content: str, **kwargs: Any) -> None:
        sends.append((content, kwargs))

    class SummaryGame:
        async def act(self, *args: object, **kwargs: object) -> PublicResult:
            del args, kwargs
            return PublicResult(
                True,
                "Committed public summary.",
                "event-1",
                attachment=PositionImage(
                    image_filename="missing-interior-position-1-cycle-1.png",
                    image_alt_text="Position 1 summary chart",
                    image_bytes=b"\x89PNG\r\n\x1a\nfixture",
                ),
                phase_footer="_Current phase: **Orientation** · Position 1 · Cycle 1_",
            )

        async def has_active_settlement_event(self, environment: Environment) -> bool:
            del environment
            return False

    bot._authorize_player = authorize  # type: ignore[method-assign]
    bot.game = SummaryGame()  # type: ignore[assignment]
    interaction = SimpleNamespace(
        id=101,
        user=SimpleNamespace(id=7),
        response=SimpleNamespace(defer=defer),
        followup=SimpleNamespace(send=send),
        channel=None,
    )

    await bot._perform_action(
        interaction,
        SummarizeAction(action="summarize"),
    )

    assert deferrals == [True]
    assert len(sends) == 1

    content, options = sends[0]

    assert "Committed public summary." in content
    assert "Current phase" in content
    assert "files" in options

    filenames = [attachment.filename for attachment in options["files"]]

    assert "missing-interior-position-1-cycle-1.png" in filenames
    


def test_required_commands_are_registered() -> None:
    bot = _build_test_bot()
    assert bot.intents.message_content
    group = bot.tree.get_command("interior")
    assert group is not None
    names = {command.name for command in group.commands}
    assert names == {
        "pause",
        "resume",
        "position",
        "next",
        "map",
        "chart",
        "recall",
        "accessibility",
        "act",
        "works",
        "propose",
        "test",
        "ops",
        "exterior",
        "live-readiness",
        "start-live",
        "rollback",
        "retry-event",
        "invalidate",
        "intervene",
        "debug-state",
        "export",
        "set-model",
        "set-api-budget",
        "fallback-mode",
    }
    actions = group.get_command("act")
    assert actions is not None
    assert {command.name for command in actions.commands} == {
        "awaken",
        "orient",
        "observe",
        "connect",
        "offer",
        "request-support",
        "summarize",
        "sustain",
        "relay",
        "mitigate",
        "calculate",
        "branch",
        "compare",
        "clarify",
        "classify",
        "relay-record",
        "annotate",
        "reconstruct",
        "confirm",
        "stack-open",
        "stack-react",
        "stack-resolve",
        "kicker",
        "trigger",
    }
    position_zero_propose = actions.get_command("reconstruct")
    assert position_zero_propose is not None
    parameters = {item.name: item for item in position_zero_propose.parameters}
    assert {choice.value for choice in parameters["pathway_action"].choices} == {
        "repair",
        "account",
    }
    assert {choice.value for choice in parameters["maintenance"].choices} == {
        "monitor",
        "reassess",
        "check",
        "review",
        "measure",
        "revisit",
        "maintain",
    }
    assert "no sentence is needed" in parameters["maintenance"].description
    proposals = group.get_command("propose")
    assert proposals is not None
    assert {command.name for command in proposals.commands} == {
        "circulation",
        "circulation-stack",
        "translation",
        "translation-stack",
        "reciprocity",
        "remediation",
        "memory",
        "reconstruction",
    }
    for command_name in ("circulation", "circulation-stack"):
        command = proposals.get_command(command_name)
        assert command is not None
        circulation_parameters = {item.name: item for item in command.parameters}
        assert set(circulation_parameters) == {
            "source_amount",
            "delivered_amount",
            "revision_trigger",
            "support_source",
            "support_amount",
        }
        assert {
            "maintenance",
            "reassessment",
            "branch_condition",
            "branch_action",
        }.isdisjoint(circulation_parameters)
        revision_trigger = circulation_parameters["revision_trigger"]
        assert revision_trigger.required
        assert [(choice.name, choice.value) for choice in revision_trigger.choices] == [
            ("Nursery demand or Veil output changes", "change")
        ]
        assert "revision condition" in revision_trigger.description
        assert "Blank" in circulation_parameters["support_source"].description
    works = group.get_command("works")
    assert works is not None
    assert {command.name for command in works.commands} == {
        "inspect",
        "sample",
        "separate",
        "inoculate",
        "slow",
        "contain",
        "rest",
        "replace",
        "refuse",
        "reduce",
        "redesign",
        "document",
        "audit",
    }
    test = group.get_command("test")
    assert test is not None
    assert {command.name for command in test.commands} == {
        "status",
        "settlement-event",
        "start",
        "pause",
        "resume",
        "as",
        "list-identities",
        "create-identity",
        "remove-identity",
        "reset",
        "reset-position",
        "force-observation",
        "debug-state",
        "copy-live-content",
        "checkpoint",
        "rollback",
        "export",
        "import",
        "clear-history",
        "force-event",
        "set-position",
        "set-profile",
        "gpt-on",
        "gpt-off",
    }
    ops = group.get_command("ops")
    assert ops is not None
    assert {command.name for command in ops.commands} == {
        "setup",
        "status",
        "set-live-channel",
        "set-test-channel",
        "set-role",
        "set-diagnostic-channel",
        "feature",
        "cycle-close",
        "validate-content",
    }
    v2 = bot.tree.get_command("v2")
    assert v2 is not None
    assert {command.name for command in v2.commands} == {
        "status",
        "command",
        "guide",
        "difficulty",
    }
    v2_command = v2.get_command("command")
    assert v2_command is not None
    identity = {item.name: item for item in v2_command.parameters}["identity"]
    assert {choice.value for choice in identity.choices} == {
        "investigator-a",
        "reviewer-b",
    }


def test_v2_only_bot_does_not_enable_privileged_message_content_intent() -> None:
    settings = _settings().model_copy(
        update={
            "feature_natural_language": False,
            "v2_test_enabled": True,
        }
    )
    sessions = RuntimeSessions()

    bot = build_bot(
        settings,
        sessions,
        initial_routing(settings),
        HealthService(sessions, "127.0.0.1", 8080),
        v2_test_runtime=SimpleNamespace(),  # type: ignore[arg-type]
    )

    assert not bot.intents.messages
    assert not bot.intents.message_content


@pytest.mark.parametrize("discord_chat_enabled", [False, True])
def test_activity_gemini_chat_requests_message_content_only_for_discord_chat(
    discord_chat_enabled: bool,
) -> None:
    settings = _settings().model_copy(
        update={
            "feature_natural_language": False,
            "feature_gemini_chat": True,
            "feature_gemini_discord_chat": discord_chat_enabled,
            "gemini_dry_run": True,
            "v2_test_enabled": True,
        }
    )
    sessions = RuntimeSessions()
    bot = build_bot(
        settings,
        sessions,
        initial_routing(settings),
        HealthService(sessions, "127.0.0.1", 8080),
        v2_test_runtime=SimpleNamespace(),  # type: ignore[arg-type]
    )

    assert bot.gemini_voice is not None
    assert bot.intents.messages is discord_chat_enabled
    assert bot.intents.message_content is discord_chat_enabled


@pytest.mark.asyncio
async def test_v2_command_uses_fixed_identity_and_isolated_sender() -> None:
    bot = _build_test_bot()
    v2 = bot.tree.get_command("v2")
    assert isinstance(v2, app_commands.Group)
    command = v2.get_command("command")
    assert command is not None

    calls: list[tuple[str, str]] = []
    sends: list[tuple[str, str | None]] = []

    class Runtime:
        async def execute(self, *, identity: str, text: str) -> object:
                calls.append((identity, text))
                return SimpleNamespace(
                    accepted=True,
                    code="role_assigned",
                    to_text=lambda: "Accepted: role assigned.",
                )

    async def authorize(*args: object, **kwargs: object) -> Environment:
        del args, kwargs
        return Environment.TEST

    async def send(
        interaction: object,
        message: str,
        *,
        identity: str | None = None,
    ) -> None:
        del interaction
        sends.append((message, identity))

    bot.v2_test_runtime = Runtime()  # type: ignore[assignment]
    bot._authorize_admin = authorize  # type: ignore[method-assign]
    bot._send_v2_test = send  # type: ignore[method-assign]

    await command.callback(
        SimpleNamespace(),
        identity=app_commands.Choice(
            name="Investigator A (simulated)",
            value="investigator-a",
        ),
        text="assign-role field_observer",
    )

    assert calls == [("investigator-a", "assign-role field_observer")]
    assert sends == [
        ("Accepted: role assigned.\nResult code: `role_assigned`", "investigator-a")
    ]


def test_entity_parameters_expose_autocomplete() -> None:
    bot = _build_test_bot()
    root = bot.tree.get_command("interior")
    assert isinstance(root, app_commands.Group)

    actions = root.get_command("act")
    works = root.get_command("works")
    proposals = root.get_command("propose")
    assert isinstance(actions, app_commands.Group)
    assert isinstance(works, app_commands.Group)
    assert isinstance(proposals, app_commands.Group)

    observe = actions.get_command("observe")
    sample = works.get_command("sample")
    remediation = proposals.get_command("remediation")
    assert observe is not None and sample is not None and remediation is not None
    assert {item.name: item for item in observe.parameters}["entity"].autocomplete
    sample_parameters = {item.name: item for item in sample.parameters}
    assert sample_parameters["source"].autocomplete
    assert sample_parameters["comparison"].autocomplete
    assert sample_parameters["measure"].autocomplete
    remediation_parameters = {item.name: item for item in remediation.parameters}
    assert remediation_parameters["treatment_bed"].autocomplete
    assert remediation_parameters["spent_substrate_destination"].autocomplete
    assert remediation_parameters["contaminant_class"].autocomplete
    assert remediation_parameters["fungal_culture"].autocomplete
    assert remediation_parameters["flow_rate_condition"].autocomplete


def test_settlement_intervention_view_exposes_costs_without_command_discovery() -> None:
    view = SettlementInterventionView(_build_test_bot())
    assert {item.label for item in view.children} == {
        "Brace (+strain)",
        "Divert (+burden)",
        "Release (-escalation, -capacity)",
    }
    assert all(item.custom_id for item in view.children)


def test_difficulty_poll_view_is_persistent_single_choice_ui() -> None:
    view = DifficultyPollView(_build_test_bot())
    assert view.timeout is None
    assert {item.label for item in view.children} == {
        "Guided",
        "Standard",
        "Expert",
    }
    assert {item.custom_id for item in view.children} == {
        "interior:difficulty:guided",
        "interior:difficulty:standard",
        "interior:difficulty:expert",
    }
    assert all(not item.disabled for item in view.children)

    disabled = DifficultyPollView(_build_test_bot(), disabled=True)
    assert all(item.disabled for item in disabled.children)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("environment", "channel_id"),
    ((Environment.TEST, 20), (Environment.LIVE, 10)),
)
async def test_difficulty_button_binds_the_clicking_user_and_replies_privately(
    environment: Environment, channel_id: int,
) -> None:
    bot = _build_test_bot()
    captured: dict[str, Any] = {}
    sends: list[tuple[str, dict[str, Any]]] = []

    async def authorize(*args: object, **kwargs: object) -> Environment:
        del args, kwargs
        return environment

    class Repository:
        async def record_difficulty_selection(
            self,
            ref: SessionRef,
            **kwargs: Any,
        ) -> DifficultySelectionResult:
            captured["ref"] = ref
            captured.update(kwargs)
            return DifficultySelectionResult(
                preference=DifficultyPreference(
                    poll_id="hypha-difficulty-v1",
                    level=DifficultyLevel.GUIDED,
                    revision=1,
                ),
                changed=True,
                duplicate=False,
            )

    async def send_message(message: str, **kwargs: Any) -> None:
        sends.append((message, kwargs))

    bot._authorize_difficulty_selection = authorize  # type: ignore[method-assign]
    bot.repository = Repository()  # type: ignore[assignment]
    bot.session_refs = {
        environment: SessionRef(f"{environment.value}-session", environment),
    }
    interaction = SimpleNamespace(
        id=700,
        guild_id=1,
        channel_id=channel_id,
        user=SimpleNamespace(id=77),
        message=SimpleNamespace(id=600),
        response=SimpleNamespace(send_message=send_message),
    )

    await bot._record_difficulty_selection(
        interaction,
        DifficultyLevel.GUIDED,
    )

    assert captured["discord_user_id"] == 77
    assert captured["discord_interaction_id"] == 700
    assert captured["message_id"] == 600
    assert captured["guild_id"] == 1
    assert captured["channel_id"] == channel_id
    assert captured["ref"] == SessionRef(f"{environment.value}-session", environment)
    assert len(sends) == 1
    assert sends[0][1]["ephemeral"] is True
    assert isinstance(sends[0][1]["allowed_mentions"], discord.AllowedMentions)


@pytest.mark.asyncio
async def test_difficulty_changes_guidance_without_changing_the_result() -> None:
    bot = _build_test_bot()

    class Game:
        async def current_phase_footer(self, environment: Environment) -> str:
            assert environment is Environment.TEST
            return "Phase: investigation"

    bot.game = Game()  # type: ignore[assignment]
    result = "Accepted: the evidence record is unchanged."

    standard = await bot._with_phase_footer(
        result,
        Environment.TEST,
        DifficultyLevel.STANDARD,
    )
    guided = await bot._with_phase_footer(
        result,
        Environment.TEST,
        DifficultyLevel.GUIDED,
    )
    expert = await bot._with_phase_footer(
        result,
        Environment.TEST,
        DifficultyLevel.EXPERT,
    )

    assert standard == f"{result}\n\nPhase: investigation"
    assert guided.startswith(standard)
    assert "/interior next" in guided
    assert expert == result


@pytest.mark.asyncio
async def test_expert_v2_transport_is_compact_but_preserves_result_identity() -> None:
    bot = _build_test_bot()

    async def expert(*args: object, **kwargs: object) -> DifficultyLevel:
        del args, kwargs
        return DifficultyLevel.EXPERT

    bot._difficulty_for = expert  # type: ignore[method-assign]
    response = SimpleNamespace(
        summary="Accepted: role assigned.",
        sequence=12,
        code="role_assigned",
        to_text=lambda: "Accepted: role assigned.\nVerbose guidance.",
    )

    rendered = await bot._render_v2_transport_response(
        SimpleNamespace(),
        response,
    )

    assert rendered == (
        "Accepted: role assigned.\n"
        "Sequence: 12\n"
        "Result code: `role_assigned`"
    )
    assert "Verbose guidance" not in rendered


def test_settlement_intervention_view_uses_event_specific_labels() -> None:
    view = SettlementInterventionView(
        _build_test_bot(),
        {
            "brace": "Stitch the seam (+strain)",
            "divert": "Channel the runoff (+burden)",
            "release": "Dry one span (-escalation, -capacity)",
        },
    )
    assert {item.label for item in view.children} == {
        "Stitch the seam (+strain)",
        "Channel the runoff (+burden)",
        "Dry one span (-escalation, -capacity)",
    }


def test_command_tree_serializes_within_discord_option_limits() -> None:
    bot = _build_test_bot()
    root = bot.tree.get_command("interior")
    assert isinstance(root, app_commands.Group)

    def assert_limits(command: app_commands.Command[Any, ..., Any] | app_commands.Group) -> None:
        if isinstance(command, app_commands.Group):
            assert len(command.commands) <= 25
            for child in command.commands:
                assert_limits(child)
            return
        assert len(command.parameters) <= 25

    assert_limits(root)
    payload = root.to_dict(bot.tree)
    assert len(payload["options"]) == len(root.commands)
    assert len(payload["options"]) <= 25

    def command_size(value: dict[str, Any]) -> int:
        total = len(value.get("name", "")) + len(value.get("description", ""))
        for localizations in ("name_localizations", "description_localizations"):
            total += sum(len(text) for text in (value.get(localizations) or {}).values())
        for choice in value.get("choices", []):
            total += len(choice.get("name", "")) + len(str(choice.get("value", "")))
            total += sum(len(text) for text in (choice.get("name_localizations") or {}).values())
        return total + sum(command_size(option) for option in value.get("options", []))

    assert command_size(payload) <= 7_900

    proposals = root.get_command("propose")
    assert isinstance(proposals, app_commands.Group)
    expected_parameter_counts = {
        "reciprocity": 10,
        "remediation": 16,
        "memory": 9,
        "reconstruction": 17,
    }
    assert {
        name: len(proposals.get_command(name).parameters)  # type: ignore[union-attr]
        for name in expected_parameter_counts
    } == expected_parameter_counts


@pytest.mark.asyncio
async def test_works_commands_wire_all_typed_action_fields() -> None:
    bot = _build_test_bot()
    root = bot.tree.get_command("interior")
    assert isinstance(root, app_commands.Group)
    works = root.get_command("works")
    assert isinstance(works, app_commands.Group)
    captured: list[Any] = []

    async def capture(_interaction: object, action: Any) -> None:
        captured.append(action)

    bot._perform_action = capture
    cases = (
        (
            "inspect",
            {"target": "line"},
            InspectAction(action="inspect", target_entity_id="line"),
        ),
        (
            "sample",
            {"source": "upstream", "comparison": "downstream", "measure": "load"},
            SampleAction(
                action="sample",
                source_entity_id="upstream",
                comparison_entity_id="downstream",
                measure="load",
            ),
        ),
        (
            "separate",
            {
                "source": "line",
                "clean_target": "clean",
                "contaminated_target": "containment",
            },
            SeparateAction(
                action="separate",
                source_entity_id="line",
                clean_target_entity_id="clean",
                contaminated_target_entity_id="containment",
            ),
        ),
        (
            "inoculate",
            {"target": "bed", "culture": "culture", "substrate": "straw"},
            InoculateAction(
                action="inoculate",
                target_entity_id="bed",
                culture_id="culture",
                substrate="straw",
            ),
        ),
        (
            "slow",
            {"target": "flow", "condition": "when load rises"},
            SlowAction(action="slow", target_entity_id="flow", condition="when load rises"),
        ),
        (
            "contain",
            {"target": "substrate", "destination": "vault", "condition": "when spent"},
            ContainAction(
                action="contain",
                target_entity_id="substrate",
                destination_entity_id="vault",
                condition="when spent",
            ),
        ),
        (
            "rest",
            {"target": "bed", "reassessment": "sample after one cycle"},
            RestAction(
                action="rest",
                target_entity_id="bed",
                reassessment="sample after one cycle",
            ),
        ),
        (
            "replace",
            {"target": "bed", "destination": "vault", "replacement": "fresh straw"},
            ReplaceAction(
                action="replace",
                target_entity_id="bed",
                destination_entity_id="vault",
                replacement="fresh straw",
            ),
        ),
        (
            "refuse",
            {"target": "flow", "basis": "above the public limit"},
            RefuseAction(action="refuse", target_entity_id="flow", basis="above the public limit"),
        ),
        (
            "reduce",
            {"target": "line", "measure": "throughput", "amount": 3.5, "condition": "now"},
            ReduceAction(
                action="reduce",
                target_entity_id="line",
                measure="throughput",
                amount=3.5,
                condition="now",
            ),
        ),
        (
            "redesign",
            {"target": "line", "change": "closed loop", "public_need": "clean water"},
            RedesignAction(
                action="redesign",
                target_entity_id="line",
                change="closed loop",
                public_need="clean water",
            ),
        ),
        (
            "document",
            {"subject": "claim", "record_type": "revision", "reference": "ledger v2"},
            DocumentAction(
                action="document",
                subject_entity_id="claim",
                record_type="revision",
                text="ledger v2",
            ),
        ),
        (
            "audit",
            {"target": "line", "claim": "safe", "comparison": "sample series"},
            AuditAction(
                action="audit",
                target_entity_id="line",
                claim="safe",
                comparison="sample series",
            ),
        ),
    )

    for name, kwargs, expected in cases:
        command = works.get_command(name)
        assert command is not None
        await command.callback(SimpleNamespace(), **kwargs)
        actual = captured.pop()
        assert type(actual) is type(expected)
        assert actual.model_dump() == expected.model_dump()


def _arc_proposal_cases() -> tuple[tuple[str, dict[str, Any], Any, str], ...]:
    reciprocity = {
        "producer": "mill",
        "public_benefit": "clean water",
        "local_burden": "worker exposure",
        "source_reduction_action": "reduce inputs",
        "material_disclosure": "publish materials",
        "maintenance_obligation": "weekly maintenance",
        "containment_plan": "sealed vault",
        "worker_protection": "stop-work authority",
        "shutdown_condition": "shutdown above limit",
    }
    remediation = {
        "source_discharge": "outfall",
        "contaminant_class": "organic dye residue",
        "production_reduction_action": "reduce production",
        "treatment_bed": "bed-a",
        "fungal_culture": "culture-a",
        "flow_rate_condition": "slow above threshold",
        "moisture_condition": "hold at target",
        "monitoring_method": "paired samples",
        "upstream_sample": "sample-up",
        "downstream_sample": "sample-down",
        "evidence_requirement": "three clean samples",
        "saturation_limit": 4,
        "spent_substrate_destination": "sealed-vault",
        "maintenance_condition": "inspect every cycle",
        "shutdown_condition": "shutdown on breakthrough",
    }
    memory = {
        "original_claim": "treatment always works",
        "later_revision": "treatment has limits",
        "physical_evidence": "sample archive",
        "affected_observation": "downstream reading",
        "uncertainty": "seasonal variance",
        "correction": "publish bounded claim",
        "unresolved_conflict": "winter result differs",
        "handling_requirement": "retain all versions",
    }
    reconstruction = {
        "production_line": "line-a",
        "current_output": 12.0,
        "revised_output": 7.0,
        "public_need_served": "essential goods",
        "water_cap": 5.0,
        "waste_reduction": "reduce waste at source",
        "worker_transition": "protect livelihoods during transition",
        "ownership_or_governance": "public governance board",
        "remediation_obligation": "fund remediation",
        "clean_flow_plan": "separate clean flow",
        "spent_substrate_plan": "contain spent substrate",
        "monitoring": "continuous monitoring",
        "maintenance": "scheduled maintenance",
        "historical_records": "preserve historical records",
        "reassessment": "seasonal reassessment",
        "shutdown_threshold": "shutdown at threshold",
    }
    return (
        (
            "reciprocity",
            reciprocity,
            ProposeReciprocityAction(action="propose_reciprocity", **reciprocity),
            "reciprocity",
        ),
        (
            "remediation",
            remediation,
            ProposeRemediationProtocolAction(action="propose_remediation_protocol", **remediation),
            "remediation_protocol",
        ),
        (
            "memory",
            memory,
            ProposeMemoryArchiveAction(action="propose_memory_archive", **memory),
            "memory_archive",
        ),
        (
            "reconstruction",
            reconstruction,
            ProposeProductionReformAction(action="propose_production_reform", **reconstruction),
            "reconstruction",
        ),
    )


@pytest.mark.asyncio
async def test_circulation_proposals_expand_revision_choice_for_direct_and_stack() -> None:
    bot = _build_test_bot()
    root = bot.tree.get_command("interior")
    assert isinstance(root, app_commands.Group)
    proposals = root.get_command("propose")
    assert isinstance(proposals, app_commands.Group)
    captured: list[Any] = []

    async def capture(_interaction: object, action: Any) -> None:
        captured.append(action)

    bot._perform_action = capture
    kwargs = {
        "source_amount": 8.0,
        "delivered_amount": 6.0,
        "revision_trigger": app_commands.Choice(
            name="Nursery demand or Veil output changes",
            value="change",
        ),
        "support_source": "",
        "support_amount": 0.0,
    }
    expected_fields = {
        "maintenance": "maintain the Condensation Veil collection surface",
        "reassessment": "reassess Nursery demand and Veil output before the next cycle",
        "branch_condition": "if Nursery demand or Veil output changes",
        "branch_action": ("revise delivery to the confirmed need and release unused condensation"),
    }

    direct_command = proposals.get_command("circulation")
    assert direct_command is not None
    await direct_command.callback(SimpleNamespace(), **kwargs)
    direct = captured.pop()
    assert isinstance(direct, ProposeCirculationAction)
    assert (
        direct.model_dump()
        == ProposeCirculationAction(
            action="propose_circulation",
            source_entity_id="condensation_veil",
            recipient_entity_id="pale_nursery",
            resource_id="water",
            source_amount=8,
            pathway_entity_id="route_07",
            relay_entity_id="central_relay",
            delivered_amount=6,
            support_source_entity_id="",
            support_amount=0,
            **expected_fields,
        ).model_dump()
    )

    stack_command = proposals.get_command("circulation-stack")
    assert stack_command is not None
    await stack_command.callback(SimpleNamespace(), **kwargs)
    stack = captured.pop()
    assert isinstance(stack, BeginStackAction)
    assert stack.proposal == {
        "kind": "circulation",
        "source_entity_id": "condensation_veil",
        "recipient_entity_id": "pale_nursery",
        "resource_id": "water",
        "source_amount": 8.0,
        "pathway_entity_id": "route_07",
        "relay_entity_id": "central_relay",
        "delivered_amount": 6.0,
        "support_source_entity_id": "",
        "support_amount": 0.0,
        **expected_fields,
    }


@pytest.mark.asyncio
async def test_arc_proposals_wire_direct_and_stack_actions() -> None:
    bot = _build_test_bot()
    root = bot.tree.get_command("interior")
    assert isinstance(root, app_commands.Group)
    proposals = root.get_command("propose")
    assert isinstance(proposals, app_commands.Group)
    captured: list[Any] = []

    async def capture(_interaction: object, action: Any) -> None:
        captured.append(action)

    bot._perform_action = capture
    for name, kwargs, expected_direct, kind in _arc_proposal_cases():
        command = proposals.get_command(name)
        assert command is not None

        await command.callback(SimpleNamespace(), **kwargs)
        direct = captured.pop()
        assert type(direct) is type(expected_direct)
        assert direct.model_dump() == expected_direct.model_dump()

        await command.callback(SimpleNamespace(), **kwargs, open_stack=True)
        stack = captured.pop()
        expected_stack = BeginStackAction(action="begin_stack", proposal={"kind": kind, **kwargs})
        assert isinstance(stack, BeginStackAction)
        assert stack.model_dump() == expected_stack.model_dump()


class _MessageSink:
    def __init__(self, *, done: bool = False) -> None:
        self.messages: list[str] = []
        self._done = done

    def is_done(self) -> bool:
        return self._done

    async def send(self, message: str, **kwargs: object) -> None:
        del kwargs
        self.messages.append(message)
        self._done = True

    async def send_message(self, message: str, **kwargs: object) -> None:
        await self.send(message, **kwargs)


@pytest.mark.asyncio
async def test_send_appends_current_phase_footer() -> None:
    bot = _build_test_bot()

    class PhaseGame:
        async def current_phase_footer(self, environment: Environment) -> str:
            assert environment is Environment.TEST
            return "_Current phase: **Coordination** · Position 5 · Cycle 2_"

    bot.game = PhaseGame()
    response = _MessageSink()
    interaction = SimpleNamespace(
    id=123456789,
    response=response,
    followup=_MessageSink(),
)

    await bot._send(interaction, "Action accepted.", Environment.TEST)

    assert response.messages == [
        "[TEST SURFACE]\nAction accepted.\n\n"
        "_Current phase: **Coordination** · Position 5 · Cycle 2_"
    ]


@pytest.mark.asyncio
async def test_optional_reply_voice_is_built_only_after_text_delivery() -> None:
    bot = _build_test_bot()
    bot.settings.hypha_voice_reply_attachments_enabled = True
    response = _MessageSink()
    followup = _MessageSink()
    interaction = SimpleNamespace(
        id=123456791,
        response=response,
        followup=followup,
    )

    async def build_voice_after_text(
        text: str,
        environment: Environment,
        *,
        source_message_id: int,
    ) -> object:
        assert text == "Action accepted."
        assert environment is Environment.TEST
        assert source_message_id == interaction.id
        assert response.messages == ["[TEST SURFACE]\nAction accepted."]
        return object()

    bot._build_voice_file = build_voice_after_text

    await bot._send(interaction, "Action accepted.", Environment.TEST)

    assert followup.messages == [
        "Optional Hypha narration of the text response above."
    ]


@pytest.mark.asyncio
async def test_send_paginates_every_discord_message_to_2000_characters() -> None:
    bot = _build_test_bot()
    response = _MessageSink()
    followup = _MessageSink()
    interaction = SimpleNamespace(
    id=123456790,
    response=response,
    followup=followup,
)
    message = "x" * 4500

    await bot._send(interaction, message, Environment.TEST)

    chunks = [*response.messages, *followup.messages]
    marker = "[TEST SURFACE]\n"
    assert len(response.messages) == 1
    assert len(followup.messages) == 2
    assert all(len(chunk) <= 2000 for chunk in chunks)
    assert all(chunk.startswith(marker) for chunk in chunks)
    assert "".join(chunk.removeprefix(marker) for chunk in chunks) == message
    assert bot._discord_chunks("x" * 2000) == ["x" * 2000]


class _StateRepository:
    def __init__(self, states: dict[SessionRef, dict[str, Any]]) -> None:
        self.states = states

    async def state(self, ref: SessionRef) -> dict[str, Any]:
        return self.states[ref]

    async def resolve_participant(self, ref: SessionRef, discord_user_id: int) -> str:
        del ref
        return f"discord:{discord_user_id}"


@pytest.mark.asyncio
async def test_entity_choices_are_scoped_to_position_and_search_aliases() -> None:
    registry = PuzzleRegistry.load_packaged()
    refs = {
        Environment.LIVE: SessionRef("live", Environment.LIVE),
        Environment.TEST: SessionRef("test", Environment.TEST),
    }
    test_data = registry.get(5).initial_state()
    test_data["unlocked_observations"] = ["original_limited_works_claim"]
    repository = _StateRepository(
        {
            refs[Environment.LIVE]: {
                "current_position": 6,
                "data": registry.get(6).initial_state(),
            },
            refs[Environment.TEST]: {
                "current_position": 5,
                "data": test_data,
            },
        }
    )
    game = GameService(
        repository,  # type: ignore[arg-type]
        refs,
        registry,
        SimpleNamespace(),  # type: ignore[arg-type]
        FallbackNarrator(),
    )

    choices = await game.entity_choices(Environment.TEST, "record wall")

    assert choices == [("Assurance Archive — assurance_archive", "assurance_archive")]
    assert "public_memory_archive" not in {
        value for _, value in await game.entity_choices(Environment.TEST)
    }


@pytest.mark.asyncio
async def test_entity_choices_do_not_reveal_unobserved_position_entities() -> None:
    registry = PuzzleRegistry.load_packaged()
    ref = SessionRef("test", Environment.TEST)
    data = registry.get(1).initial_state()
    repository = _StateRepository({ref: {"current_position": 1, "data": data}})
    game = GameService(
        repository,  # type: ignore[arg-type]
        {Environment.TEST: ref},
        registry,
        SimpleNamespace(),  # type: ignore[arg-type]
        FallbackNarrator(),
    )

    assert await game.entity_choices(Environment.TEST) == []

    data["unlocked_observations"] = ["condensation_shared_output"]
    assert await game.entity_choices(Environment.TEST) == [
        ("Condensation Veil — condensation_veil", "condensation_veil")
    ]


@pytest.mark.asyncio
async def test_observation_choices_expose_map_cues_without_entity_spoilers() -> None:
    registry = PuzzleRegistry.load_packaged()
    ref = SessionRef("test", Environment.TEST)
    data = registry.get(1).initial_state()
    repository = _StateRepository({ref: {"current_position": 1, "data": data}})
    game = GameService(
        repository,  # type: ignore[arg-type]
        {Environment.TEST: ref},
        registry,
        SimpleNamespace(),  # type: ignore[arg-type]
        FallbackNarrator(),
    )

    choices = await game.observable_entity_choices(Environment.TEST)

    assert (
        "Inspect: Shaded Planting Surface",
        "Shaded Planting Surface",
    ) in choices
    assert not any("Pale Nursery" in label or value == "pale_nursery" for label, value in choices)
    assert not any("Route 11" in label or value == "route_11" for label, value in choices)
    assert not any(
        "Upper Allocation" in label or value == "production_intake_channel"
        for label, value in choices
    )

    data["unlocked_observations"] = ["nursery_projected_need"]
    identified = await game.observable_entity_choices(Environment.TEST)
    assert ("Pale Nursery — pale_nursery", "pale_nursery") in identified
    assert not any(label == "Inspect: Shaded Planting Surface" for label, _ in identified)


@pytest.mark.asyncio
async def test_next_names_the_remaining_inspectable_nursery_cue() -> None:
    registry = PuzzleRegistry.load_packaged()
    ref = SessionRef("test", Environment.TEST)
    data = registry.get(1).initial_state()
    data["unlocked_observations"] = [
        "northern_inherited_burden",
        "eastern_relay_limit",
        "central_relay_no_storage",
        "archive_coherence_cost",
        "condensation_shared_output",
        "veil_requires_maintenance",
        "route_07_loss",
        "first_bloom_basin_dry",
    ]
    repository = _StateRepository({ref: {"current_position": 1, "data": data}})
    game = GameService(
        repository,  # type: ignore[arg-type]
        {Environment.TEST: ref},
        registry,
        SimpleNamespace(),  # type: ignore[arg-type]
        FallbackNarrator(),
    )

    guidance = await game.next_steps(Environment.TEST, 7)

    assert "Inspect `Shaded Planting Surface`" in guidance
    assert "/interior act observe" in guidance


@pytest.mark.asyncio
@pytest.mark.legacy_content
@pytest.mark.parametrize(
    ("position", "choice_method", "first_label"),
    (
        (0, "observable_entity_choices", "Inspect: northern reserve"),
        (1, "observable_entity_choices", "Inspect: Edge of Shared Workers' Court"),
        (2, "observable_entity_choices", "Inspect: Circulation Ledger — SENT"),
        (3, "inspectable_entity_choices", "Inspect: Provision Works"),
        (4, "inspectable_entity_choices", "Inspect: Provision Works"),
        (5, "inspectable_entity_choices", "Inspect: Layered assurance record wall"),
        (6, "inspectable_entity_choices", "Inspect: Works output and quota board"),
    ),
)
async def test_every_position_has_spoiler_safe_initial_discovery_choices(
    position: int, choice_method: str, first_label: str
) -> None:
    registry = PuzzleRegistry.load_packaged()
    ref = SessionRef("test", Environment.TEST)
    data = registry.get(position).initial_state()
    repository = _StateRepository({ref: {"current_position": position, "data": data}})
    game = GameService(
        repository,  # type: ignore[arg-type]
        {Environment.TEST: ref},
        registry,
        SimpleNamespace(),  # type: ignore[arg-type]
        FallbackNarrator(),
    )

    choices = await getattr(game, choice_method)(Environment.TEST)

    assert choices
    assert choices[0][0] == first_label
    assert all(label.startswith("Inspect: ") for label, _ in choices)
    aliases = registry.get(position).entity_aliases()
    assert all(value.casefold() in aliases for _, value in choices)
    assert await game.entity_choices(Environment.TEST) == []
    if position >= 3:
        assert await game.observable_entity_choices(Environment.TEST) == choices


@pytest.mark.asyncio
async def test_discovery_choices_appear_only_after_their_public_prerequisites() -> None:
    registry = PuzzleRegistry.load_packaged()
    ref = SessionRef("test", Environment.TEST)

    async def choices(position: int, data: dict[str, Any]) -> list[tuple[str, str]]:
        repository = _StateRepository({ref: {"current_position": position, "data": data}})
        game = GameService(
            repository,  # type: ignore[arg-type]
            {Environment.TEST: ref},
            registry,
            SimpleNamespace(),  # type: ignore[arg-type]
            FallbackNarrator(),
        )
        method = (
            game.observable_entity_choices if position <= 2 else game.inspectable_entity_choices
        )
        return await method(Environment.TEST)

    position_two = registry.get(2).initial_state()
    opening_two = await choices(2, position_two)
    assert not any("Metered upper branch" in label for label, _ in opening_two)
    position_two["unlocked_observations"] = [
        "source_sent_measurement",
        "intake_delivered_measurement",
        "survey_retained_measurement",
        "stage_term_mapping",
        "records_have_distinct_provenance",
        "retention_minor_report",
    ]
    assert any(
        label == "Inspect: Metered upper branch — destination not recorded"
        for label, _ in await choices(2, position_two)
    )

    position_four = registry.get(4).initial_state()
    opening_four = await choices(4, position_four)
    assert not any("Characterized Warm Return" in label for label, _ in opening_four)
    assert not any("Culture Archive" in label for label, _ in opening_four)
    position_four["unlocked_observations"] = ["production_exceeds_capacity"]
    assert any(
        label == "Inspect: Characterized Warm Return"
        for label, _ in await choices(4, position_four)
    )
    position_four["unlocked_observations"].append("characterized_return_class")
    assert any(label == "Inspect: Culture Archive" for label, _ in await choices(4, position_four))

    position_six = registry.get(6).initial_state()
    assert not any(
        "Open reconstruction table" in label for label, _ in await choices(6, position_six)
    )
    position_six["unlocked_observations"] = [
        "unnecessary_output_quota",
        "distant_surplus_control",
    ]
    assert any(
        label == "Inspect: Open reconstruction table" for label, _ in await choices(6, position_six)
    )


@pytest.mark.legacy_content
@pytest.mark.parametrize(
    ("position", "expected_cue"),
    (
        (2, "Circulation Ledger — SENT"),
        (3, "A visibly altered return water channel with a warmer surface and a sealed margin"),
        (4, "Clear-Flow Branch"),
        (5, "Layered assurance record wall"),
    ),
)
async def test_public_map_alt_text_names_its_inspectable_cues(
    position: int,
    expected_cue: str,
) -> None:
    registry = PuzzleRegistry.load_packaged()
    ref = SessionRef("test", Environment.TEST)
    repository = _StateRepository(
        {ref: {"current_position": position, "data": registry.get(position).initial_state()}}
    )
    game = GameService(
        repository,  # type: ignore[arg-type]
        {Environment.TEST: ref},
        registry,
        SimpleNamespace(),  # type: ignore[arg-type]
        FallbackNarrator(),
    )

    current_map = await game.current_map(Environment.TEST)

    assert current_map is not None
    assert expected_cue in current_map.image_alt_text
    if position == 2:
            assert "Provision Works" not in current_map.image_alt_text
    assert "Warm visibly altered return flow" not in current_map.image_alt_text


@pytest.mark.asyncio
async def test_configured_text_fields_offer_position_specific_values() -> None:
    registry = PuzzleRegistry.load_packaged()
    ref = SessionRef("test", Environment.TEST)
    repository = _StateRepository(
        {ref: {"current_position": 4, "data": registry.get(4).initial_state()}}
    )
    game = GameService(
        repository,  # type: ignore[arg-type]
        {Environment.TEST: ref},
        registry,
        SimpleNamespace(),  # type: ignore[arg-type]
        FallbackNarrator(),
    )

    measures = await game.configured_choices(Environment.TEST, "sample_measure")
    assert ("Documented Material Class", "documented_material_class") in measures
    assert ("Visible Clarity", "visible_clarity") in measures
    assert await game.configured_choices(Environment.TEST, "reduction_measure", "shutdown") == [
        ("Trigger Public Shutdown", "trigger_public_shutdown")
    ]
    assert await game.configured_choices(Environment.TEST, "culture") == [
        ("Archive white-rot culture", "archive_white_rot_culture")
    ]


@pytest.mark.asyncio
async def test_trigger_choices_label_ineligible_participants_instead_of_hiding() -> None:
    registry = PuzzleRegistry.load_packaged()
    refs = {
        Environment.LIVE: SessionRef("live", Environment.LIVE),
        Environment.TEST: SessionRef("test", Environment.TEST),
    }
    data = registry.get(0).initial_state()
    data["triggered_reactions"] = [
        {
            "trigger_id": "t-0f3291b5d50b",
            "kind": "inspect_capacity",
            "observation_id": "northern_usable_capacity",
            "source_participant_id": "discord:99",
            "consumed": False,
        },
        {
            "trigger_id": "t-cf2d2d01e3c8",
            "kind": "test_route",
            "pathway_id": "damaged_circulation",
            "excluded_participant_ids": ["discord:7"],
            "consumed": False,
        },
        {
            "trigger_id": "old-consumed",
            "kind": "risk_check",
            "consumed": True,
        },
    ]
    repository = _StateRepository(
        {
            refs[Environment.LIVE]: {"current_position": 0, "data": data},
            refs[Environment.TEST]: {"current_position": 0, "data": data},
        }
    )
    game = GameService(
        repository,  # type: ignore[arg-type]
        refs,
        registry,
        SimpleNamespace(),  # type: ignore[arg-type]
        FallbackNarrator(),
    )

    assert await game.trigger_choices(Environment.TEST, 7) == [
        ("Inspect capacity northern reservoir", "inspect-capacity-northern-reservoir"),
        (
            "Another participant required — Test route damaged circulation",
            "test-route-damaged-circulation",
        ),
    ]
    recalled = await game.recall(Environment.TEST)
    assert "Use `/interior act trigger trigger_id:inspect-capacity-northern-reservoir`" in recalled
    assert "trigger_id:test-route-damaged-circulation`" in recalled


@pytest.mark.asyncio
async def test_rejected_cycle_feedback_uses_readable_trigger_alias() -> None:
    registry = PuzzleRegistry.load_packaged()
    refs = {
        Environment.LIVE: SessionRef("live", Environment.LIVE),
        Environment.TEST: SessionRef("test", Environment.TEST),
    }
    data = registry.get(0).initial_state()
    data["triggered_reactions"] = [
        {
            "trigger_id": "t-0f3291b5d50b",
            "kind": "inspect_capacity",
            "observation_id": "northern_usable_capacity",
            "consumed": False,
        }
    ]
    repository = _StateRepository(
        {
            refs[Environment.LIVE]: {"current_position": 0, "data": data},
            refs[Environment.TEST]: {"current_position": 0, "data": data},
        }
    )
    game = GameService(
        repository,  # type: ignore[arg-type]
        refs,
        registry,
        SimpleNamespace(),  # type: ignore[arg-type]
        FallbackNarrator(),
    )

    result = await game.render_outcome(
        refs[Environment.TEST],
        "discord:7",
        EngineOutcome(
            False,
            "cycle_action_spent",
            public_data={"feedback": ("Use `/interior act trigger trigger_id:t-0f3291b5d50b`.")},
        ),
    )

    assert "trigger_id:inspect-capacity-northern-reservoir" in result.text
    assert "t-0f3291b5d50b" not in result.text
    assert "Recorded: No state change" in result.text
    assert "Cost: None" in result.text
    assert "Cycle effect:" in result.text
    assert "Available next:" in result.text
    assert "Waiting on:" in result.text


@pytest.mark.asyncio
async def test_summarize_response_offers_interior_next() -> None:
    registry = PuzzleRegistry.load_packaged()
    ref = SessionRef("test", Environment.TEST)
    repository = _StateRepository(
        {ref: {"current_position": 0, "data": registry.get(0).initial_state()}}
    )
    game = GameService(
        repository,  # type: ignore[arg-type]
        {Environment.TEST: ref},
        registry,
        SimpleNamespace(),  # type: ignore[arg-type]
        FallbackNarrator(),
    )

    result = await game.render_outcome(
        ref,
        "discord:7",
        EngineOutcome(
            True,
            "accepted",
            public_data={"public_text": "The confirmed record is summarized."},
            event_type="summary.recorded",
        ),
        action=SummarizeAction(action="summarize"),
    )

    assert "Available next:" in result.text
    assert "See your personalized options (free): `/interior next`" in result.text


@pytest.mark.asyncio
async def test_game_service_positions_and_position_3_to_6_pending_recall_are_scoped() -> None:
    registry = PuzzleRegistry.load_packaged()
    refs = {
        Environment.LIVE: SessionRef("live", Environment.LIVE),
        Environment.TEST: SessionRef("test", Environment.TEST),
    }

    def state(position: int, proposal: dict[str, Any] | None = None) -> dict[str, Any]:
        data = registry.get(position).initial_state()
        if proposal is not None:
            data["proposals"] = {proposal["proposal_id"]: proposal}
        return {"current_position": position, "data": data}

    repository = _StateRepository(
        {
            refs[Environment.LIVE]: state(6),
            refs[Environment.TEST]: state(3),
        }
    )
    game = GameService(
        repository,  # type: ignore[arg-type]
        refs,
        registry,
        SimpleNamespace(),  # type: ignore[arg-type]
        FallbackNarrator(),
    )

    assert "Position 6 — Reconstruction" in await game.position(Environment.LIVE)
    assert "Position 3 — The Provision Works" in await game.position(Environment.TEST)

    summaries = (
        (3, "reciprocity", "producer obligations preserve public benefit and local burden"),
        (
            4,
            "remediation_protocol",
            "source reduction, compatibility, evidence, containment, and shutdown cycle",
        ),
        (5, "memory_archive", "versioned claim, evidence, correction, and unresolved conflict"),
        (6, "reconstruction", "production reform 12 → 7 with public governance"),
    )
    for position, kind, expected in summaries:
        proposal = {
            "proposal_id": f"p{position}",
            "kind": kind,
            "status": "pending",
            "current_output": 12,
            "revised_output": 7,
        }
        repository.states[refs[Environment.TEST]] = state(position, proposal)
        recalled = await game.recall(Environment.TEST)
        assert f"`p{position}` ({kind}): {expected}" in recalled
        assert repository.states[refs[Environment.LIVE]]["current_position"] == 6
