from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from dataclasses import asdict, dataclass
from importlib.resources import files
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field

from uniflora.alerts import DiagnosticAlertSink
from uniflora.config import Settings
from uniflora.openai_privacy import (
    PrivacyBoundaryError,
    assert_discord_metadata_absent,
    display_dry_run,
)
from uniflora.storage.repository import GameRepository, SessionRef

logger = logging.getLogger(__name__)


class NarrationTemplateError(ValueError):
    pass


class FallbackNarrator:
    """Renders only pre-authored text; it cannot add facts or mutate state."""

    def __init__(self, templates: dict[str, dict[str, list[str]]] | None = None) -> None:
        if templates is None:
            resource = files("uniflora.content").joinpath("fallback_narration.json")
            templates = json.loads(resource.read_text(encoding="utf-8"))
        self.templates = templates

    def render(
        self,
        *,
        profile: str,
        narration_key: str,
        event_id: str,
        public_data: dict[str, Any] | None = None,
    ) -> str:
        del public_data  # Phase 2 templates contain no dynamic fact placeholders.
        profile_templates = self.templates.get(profile)
        if profile_templates is None:
            raise NarrationTemplateError(f"unknown response profile: {profile}")
        variants = profile_templates.get(narration_key)
        if not variants:
            variants = profile_templates.get("invalid_action")
        if not variants:
            raise NarrationTemplateError(
                f"profile {profile!r} lacks narration key {narration_key!r} and fallback"
            )
        digest = hashlib.sha256(f"{profile}:{narration_key}:{event_id}".encode()).digest()
        return variants[int.from_bytes(digest[:4], "big") % len(variants)]

    def render_confirmed_outcome(self, *, profile: str, event_id: str, outcome: str) -> str:
        variants = {
            "surface_noise": (
                "boundary signal retained:",
                "shared surface records:",
                "public fragment resolves:",
            ),
            "local_correlation": (
                "The mycotrophs correlate this confirmed outcome:",
                "The shared public relation now records:",
                "The mycotrophs retain this contribution together:",
            ),
            "conditional_memory": (
                "The current conditional record now states:",
                "The mycotrophs retain this outcome with its expiry conditions:",
                "The shared circulation record now distinguishes:",
            ),
            "plural_translation": (
                "The sourced public concordance now records:",
                "The mycotrophs preserve this record with its difference:",
                "The shared translation retains:",
            ),
        }
        options = variants.get(profile)
        if options is None:
            raise NarrationTemplateError(f"unknown response profile: {profile}")
        digest = hashlib.sha256(f"confirmed:{profile}:{event_id}".encode()).digest()
        return f"{options[int.from_bytes(digest[:4], 'big') % len(options)]} {outcome}"


class NarrationModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class StructuredNarration(NarrationModel):
    lead: str = Field(max_length=120)
    closing: str = Field(max_length=120)


@dataclass(frozen=True, slots=True)
class NarrationContext:
    profile: str
    event_type: str
    narration_key: str
    confirmed_outcome: str
    position_completed: bool
    allowed_style_words: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class NarrationUsage:
    input_tokens: int = 0
    cached_input_tokens: int = 0
    output_tokens: int = 0


@dataclass(frozen=True, slots=True)
class NarrationProviderResult:
    output: object
    usage: NarrationUsage = NarrationUsage()
    transmitted: bool = True


class NarrationProvider(Protocol):
    model: str
    dry_run: bool

    async def narrate(self, context: NarrationContext) -> NarrationProviderResult: ...

    async def close(self) -> None: ...


_COMMON_STYLE_WORDS = {
    "a",
    "an",
    "and",
    "as",
    "at",
    "confirmed",
    "in",
    "is",
    "of",
    "on",
    "public",
    "shared",
    "the",
    "this",
    "through",
    "together",
    "within",
}
_PROFILE_STYLE_WORDS = {
    "surface_noise": _COMMON_STYLE_WORDS
    | {
        "boundary",
        "fragment",
        "fragments",
        "interface",
        "relation",
        "retained",
        "signal",
        "signals",
        "surface",
        "trace",
    },
    "local_correlation": _COMMON_STYLE_WORDS
    | {
        "act",
        "acts",
        "contribution",
        "correlate",
        "correlation",
        "mycotroph",
        "mycotrophs",
        "pattern",
        "record",
        "recorded",
        "relation",
        "relations",
    },
    "conditional_memory": _COMMON_STYLE_WORDS
    | {
        "circulation",
        "condition",
        "conditional",
        "current",
        "delivery",
        "expires",
        "forecast",
        "maintained",
        "mycotroph",
        "mycotrophs",
        "projected",
        "reassessed",
        "record",
        "source",
    },
    "plural_translation": _COMMON_STYLE_WORDS
    | {
        "concordance",
        "delivered",
        "difference",
        "mycotroph",
        "mycotrophs",
        "plural",
        "preserve",
        "provenance",
        "record",
        "retained",
        "sent",
        "sourced",
        "translation",
    },
}
_WORDS = re.compile(r"[A-Za-z]+")


class NarrationGuard:
    @classmethod
    def compose(cls, output: StructuredNarration, context: NarrationContext) -> str | None:
        allowed = set(context.allowed_style_words)
        if not cls._wrapper_is_safe(output.lead, allowed) or not cls._wrapper_is_safe(
            output.closing, allowed
        ):
            return None
        parts = [output.lead.strip(), context.confirmed_outcome.strip()]
        parts.append(output.closing.strip())
        rendered = " ".join(part for part in parts if part)
        if len(rendered) > 1900 or "@everyone" in rendered or "@here" in rendered:
            return None
        return rendered

    @staticmethod
    def _wrapper_is_safe(value: str, allowed: set[str]) -> bool:
        if any(character.isdigit() for character in value):
            return False
        if any(marker in value.casefold() for marker in ("http://", "https://", "@", "`")):
            return False
        return all(word.casefold() in allowed for word in _WORDS.findall(value))


class NarrationService:
    def __init__(
        self,
        settings: Settings,
        repository: GameRepository,
        fallback: FallbackNarrator,
        provider: NarrationProvider | None,
        alerts: DiagnosticAlertSink | None = None,
    ) -> None:
        self.settings = settings
        self.repository = repository
        self.fallback = fallback
        self.provider = provider
        self.alerts = alerts

    async def render(
        self,
        ref: SessionRef,
        *,
        participant_id: str,
        profile: str,
        event_id: str,
        event_type: str,
        narration_key: str,
        public_data: dict[str, Any],
        permitted_public_facts: tuple[str, ...],
        position_completed: bool,
    ) -> str:
        canonical = public_data.get("public_text")
        if canonical:
            canonical_text = str(canonical)
            fallback_text = self.fallback.render_confirmed_outcome(
                profile=profile, event_id=event_id, outcome=canonical_text
            )
        else:
            canonical_text = self.fallback.render(
                profile=profile,
                narration_key=narration_key,
                event_id=event_id,
                public_data=public_data,
            )
            fallback_text = canonical_text
        control = await self.repository.runtime_control(ref)
        if (
            not self.settings.feature_gpt_narration
            or not control["feature_flags"].get("gpt_narration", True)
            or control["fallback_mode"]
        ):
            await self._record(ref, event_id, profile, fallback_text, "fallback:mode")
            return fallback_text
        if self.provider is not None:
            self.provider.model = str(
                control["narration_model"] or self.settings.openai_narration_model
            )
        if (
            not (self.settings.openai_enabled or self.settings.openai_dry_run)
            or self.provider is None
        ):
            await self._record(ref, event_id, profile, fallback_text, "fallback")
            return fallback_text
        totals = await self.repository.api_usage_totals(ref)
        budgets = self._effective_budgets(control)
        if (
            totals["daily_cost"] >= budgets["hard_daily"]
            or totals["monthly_cost"] >= budgets["hard_monthly"]
        ):
            await self._record(ref, event_id, profile, fallback_text, "fallback:budget")
            return fallback_text
        acquired = await self.repository.acquire_api_cooldowns(
            ref,
            participant_id,
            purpose="narration",
            per_user_seconds=self.settings.openai_per_user_cooldown_seconds,
            global_seconds=self.settings.openai_global_cooldown_seconds,
        )
        if not acquired:
            await self._record(ref, event_id, profile, fallback_text, "fallback:cooldown")
            return fallback_text
        context = await self._context(
            ref,
            profile=profile,
            event_type=event_type,
            narration_key=narration_key,
            canonical_text=canonical_text,
            permitted_public_facts=permitted_public_facts,
            position_completed=position_completed,
        )
        if context is None:
            await self._record(ref, event_id, profile, fallback_text, "fallback:context")
            return fallback_text
        selected_model = self.provider.model
        try:
            result = await asyncio.wait_for(
                self.provider.narrate(context),
                timeout=self.settings.openai_request_timeout_seconds,
            )
        except TimeoutError:
            await self._record_provider_failure(ref)
            logger.warning(
                "OpenAI narration timed out",
                extra={"environment": ref.environment.value, "purpose": "narration"},
            )
            await self._record(ref, event_id, profile, fallback_text, "fallback:timeout")
            return fallback_text
        except Exception:
            await self._record_provider_failure(ref)
            logger.warning(
                "OpenAI narration failed",
                extra={"environment": ref.environment.value, "purpose": "narration"},
            )
            await self._record(ref, event_id, profile, fallback_text, "fallback:error")
            return fallback_text
        if not result.transmitted:
            await self._record(ref, event_id, profile, fallback_text, "fallback:dry-run")
            return fallback_text
        cost = self._estimated_cost(result.usage)
        await self.repository.record_api_usage(
            ref,
            model=selected_model,
            purpose="narration",
            participant_id=None,
            input_tokens=result.usage.input_tokens,
            cached_input_tokens=result.usage.cached_input_tokens,
            output_tokens=result.usage.output_tokens,
            estimated_cost=cost,
        )
        try:
            structured = StructuredNarration.model_validate(result.output)
        except Exception:
            structured = None
        rendered = NarrationGuard.compose(structured, context) if structured else None
        if rendered is None:
            await self._record_provider_failure(ref)
            await self._record(ref, event_id, profile, fallback_text, "fallback:guard")
            return fallback_text
        await self.repository.record_api_result(
            ref,
            success=True,
            failure_threshold=self.settings.api_failure_fallback_threshold,
        )
        if (
            totals["daily_cost"] + cost >= budgets["soft_daily"]
            or totals["monthly_cost"] + cost >= budgets["soft_monthly"]
        ):
            logger.warning(
                "OpenAI soft budget threshold reached",
                extra={"environment": ref.environment.value, "purpose": "narration"},
            )
            if self.alerts is not None and await self.repository.acquire_api_cooldowns(
                ref,
                "system:budget-alert",
                purpose="budget-alert",
                per_user_seconds=0,
                global_seconds=3600,
            ):
                await self.alerts.alert(
                    ref.environment, "API usage reached a configured soft budget threshold."
                )
        await self._record(ref, event_id, profile, rendered, "openai")
        return rendered

    async def close(self) -> None:
        if self.provider is not None:
            await self.provider.close()

    async def _context(
        self,
        ref: SessionRef,
        *,
        profile: str,
        event_type: str,
        narration_key: str,
        canonical_text: str,
        permitted_public_facts: tuple[str, ...],
        position_completed: bool,
    ) -> NarrationContext | None:
        del ref, permitted_public_facts
        allowed = _PROFILE_STYLE_WORDS.get(profile)
        if allowed is None:
            return None
        context = NarrationContext(
            profile=profile,
            event_type=event_type,
            narration_key=narration_key,
            confirmed_outcome=canonical_text,
            position_completed=position_completed,
            allowed_style_words=tuple(sorted(allowed)),
        )
        return (
            context
            if self._context_size(context) <= self.settings.openai_max_prompt_tokens * 4
            else None
        )

    @staticmethod
    def _context_size(context: NarrationContext) -> int:
        return len(json.dumps(asdict(context), ensure_ascii=True, separators=(",", ":")))

    def _estimated_cost(self, usage: NarrationUsage) -> float:
        cached = min(usage.input_tokens, usage.cached_input_tokens)
        uncached = max(0, usage.input_tokens - cached)
        total = (
            uncached * self.settings.openai_narration_input_usd_per_million
            + cached * self.settings.openai_narration_cached_input_usd_per_million
            + usage.output_tokens * self.settings.openai_narration_output_usd_per_million
        )
        return total / 1_000_000

    def _effective_budgets(self, control: dict[str, Any]) -> dict[str, float]:
        overrides = control["budget_overrides"]
        return {
            "soft_daily": float(
                overrides.get("soft_daily", self.settings.openai_soft_daily_budget_usd)
            ),
            "hard_daily": float(
                overrides.get("hard_daily", self.settings.openai_hard_daily_budget_usd)
            ),
            "soft_monthly": float(
                overrides.get("soft_monthly", self.settings.openai_soft_monthly_budget_usd)
            ),
            "hard_monthly": float(
                overrides.get("hard_monthly", self.settings.openai_hard_monthly_budget_usd)
            ),
        }

    async def _record_provider_failure(self, ref: SessionRef) -> None:
        activated = await self.repository.record_api_result(
            ref,
            success=False,
            failure_threshold=self.settings.api_failure_fallback_threshold,
        )
        if activated and self.alerts is not None:
            await self.alerts.alert(
                ref.environment,
                "Automatic deterministic fallback activated after repeated API failures.",
            )

    async def _record(
        self,
        ref: SessionRef,
        event_id: str,
        profile: str,
        text: str,
        generated_by: str,
    ) -> None:
        try:
            await self.repository.record_narration(
                ref,
                event_id=event_id,
                profile=profile,
                public_text=text,
                generated_by=generated_by,
            )
        except Exception:
            logger.exception(
                "narration history write failed",
                extra={"environment": ref.environment.value, "purpose": "narration"},
            )


class OpenAINarrationProvider:
    SYSTEM_INSTRUCTIONS = """Return only a restrained lead and closing for a confirmed Discord
game event. They may use only allowed_style_words and punctuation; they may not contain numbers,
names, facts, clues, negation, private knowledge, or claims about real people. Never infer
progression. Keep both fields brief."""

    def __init__(
        self,
        client: Any | None,
        model: str,
        *,
        max_output_tokens: int,
        dry_run: bool = False,
        network_authorized: bool = False,
    ) -> None:
        self.client = client
        self.model = model
        self.max_output_tokens = max_output_tokens
        self.dry_run = dry_run
        self.network_authorized = network_authorized

    @classmethod
    def from_settings(cls, settings: Settings) -> OpenAINarrationProvider:
        from openai import AsyncOpenAI

        if settings.openai_dry_run:
            return cls(
                None,
                settings.openai_narration_model,
                max_output_tokens=settings.openai_max_output_tokens,
                dry_run=True,
            )
        if not settings.openai_enabled or not settings.openai_privacy_acknowledged:
            raise PrivacyBoundaryError("OpenAI network transport is not privacy-authorized")
        if (
            settings.openai_api_key is None
            or not settings.openai_api_key.get_secret_value().strip()
        ):
            raise PrivacyBoundaryError("OpenAI network transport has no API key")
        return cls(
            AsyncOpenAI(
                api_key=settings.openai_api_key.get_secret_value(),
                base_url="https://api.openai.com/v1",
                timeout=settings.openai_request_timeout_seconds,
                max_retries=0,
            ),
            settings.openai_narration_model,
            max_output_tokens=settings.openai_max_output_tokens,
            network_authorized=True,
        )

    async def narrate(self, context: NarrationContext) -> NarrationProviderResult:
        payload = {
            "profile": context.profile,
            "event_type": context.event_type,
            "narration_key": context.narration_key,
            "position_completed": context.position_completed,
            "allowed_style_words": context.allowed_style_words,
        }
        request: dict[str, Any] = {
            "model": self.model,
            "input": [
                {"role": "system", "content": self.SYSTEM_INSTRUCTIONS},
                {
                    "role": "user",
                    "content": "TRUSTED_PUBLIC_EVENT_DATA:\n"
                    + json.dumps(payload, separators=(",", ":"), ensure_ascii=True),
                },
            ],
            "text_format": StructuredNarration,
            "max_output_tokens": self.max_output_tokens,
            "store": False,
        }
        assert_discord_metadata_absent(request)
        if self.dry_run:
            display_dry_run("narration", request)
            return NarrationProviderResult(output=None, transmitted=False)
        if not self.network_authorized:
            raise PrivacyBoundaryError("OpenAI API transport was not explicitly authorized")
        if self.client is None:
            raise PrivacyBoundaryError("OpenAI API client is unavailable")
        response = await self.client.responses.parse(**request)
        usage = getattr(response, "usage", None)
        details = getattr(usage, "input_tokens_details", None)
        return NarrationProviderResult(
            output=getattr(response, "output_parsed", None),
            usage=NarrationUsage(
                input_tokens=int(getattr(usage, "input_tokens", 0) or 0),
                cached_input_tokens=int(getattr(details, "cached_tokens", 0) or 0),
                output_tokens=int(getattr(usage, "output_tokens", 0) or 0),
            ),
        )

    async def close(self) -> None:
        if self.client is not None:
            await self.client.close()
