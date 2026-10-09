from __future__ import annotations

import json
import re
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any


class PrivacyBoundaryError(ValueError):
    """Raised before transport when a payload contains Discord metadata."""


@dataclass(frozen=True, slots=True)
class ParticipantIdentity:
    discord_user_id: int
    names: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class DiscordPrivacyMetadata:
    """Request-local metadata used only to remove Discord identity from content."""

    current_participant: ParticipantIdentity
    referenced_participants: tuple[ParticipantIdentity, ...] = ()
    sensitive_values: tuple[str, ...] = ()

    def forbidden_values(self) -> tuple[str, ...]:
        values = list(self.sensitive_values)
        for participant in (self.current_participant, *self.referenced_participants):
            values.append(str(participant.discord_user_id))
            values.extend(participant.names)
        return tuple(value for value in values if value and value.strip())


_USER_MENTION = re.compile(r"<@!?(\d+)>")
_NON_USER_MENTION = re.compile(r"<(?:@&|#)\d+>")
_DISCORD_TIMESTAMP = re.compile(r"<t:\d+(?::[tTdDfFR])?>")
_CUSTOM_EMOJI = re.compile(r"<a?:[A-Za-z0-9_]+:\d+>")
_SNOWFLAKE = re.compile(r"(?<!\d)\d{17,20}(?!\d)")
_ISO_TIMESTAMP = re.compile(
    r"\b\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d{1,6})?)?(?:Z|[+-]\d{2}:\d{2})?\b",
    re.I,
)
_DISCORD_ASSET_URL = re.compile(
    r"https?://(?:cdn|media)\.discordapp\.(?:com|net)/\S+", re.I
)


def _replace_literal(value: str, secret: str, replacement: str) -> str:
    if not secret.strip():
        return value
    pattern = re.compile(rf"(?<!\w){re.escape(secret)}(?!\w)", re.I)
    return pattern.sub(replacement, value)


def sanitize_discord_text(
    value: str,
    metadata: DiscordPrivacyMetadata,
    *,
    limit: int,
) -> str:
    """Remove Discord metadata and replace people with request-local labels."""

    participants = (metadata.current_participant, *metadata.referenced_participants)
    labels: dict[str, str] = {}
    next_label = 1
    for participant in participants:
        key = str(participant.discord_user_id)
        if key not in labels:
            labels[key] = f"participant_{next_label}"
            next_label += 1

    def replace_user_mention(match: re.Match[str]) -> str:
        nonlocal next_label
        discord_id = match.group(1)
        label = labels.get(discord_id)
        if label is None:
            label = f"participant_{next_label}"
            labels[discord_id] = label
            next_label += 1
        return label

    sanitized = value.replace("\x00", " ")
    sanitized = _USER_MENTION.sub(replace_user_mention, sanitized)
    sanitized = _NON_USER_MENTION.sub(" ", sanitized)
    sanitized = _DISCORD_TIMESTAMP.sub(" ", sanitized)
    sanitized = _CUSTOM_EMOJI.sub(" ", sanitized)
    sanitized = _DISCORD_ASSET_URL.sub(" ", sanitized)

    for participant in participants:
        label = labels[str(participant.discord_user_id)]
        sanitized = _replace_literal(sanitized, str(participant.discord_user_id), label)
        for name in sorted(participant.names, key=len, reverse=True):
            sanitized = _replace_literal(sanitized, name, label)

    for secret in sorted(metadata.sensitive_values, key=len, reverse=True):
        sanitized = _replace_literal(sanitized, secret, " ")

    sanitized = _SNOWFLAKE.sub(" ", sanitized)
    sanitized = _ISO_TIMESTAMP.sub(" ", sanitized)
    sanitized = " ".join(sanitized.split())
    return sanitized[:limit]


def assert_discord_metadata_absent(
    payload: Mapping[str, Any] | Sequence[Any],
    *,
    forbidden_values: Sequence[str] = (),
) -> None:
    """Fail closed immediately before a request if Discord metadata remains."""

    serialized = json.dumps(payload, ensure_ascii=False, default=str)
    structural_patterns = (
        _USER_MENTION,
        _NON_USER_MENTION,
        _DISCORD_TIMESTAMP,
        _CUSTOM_EMOJI,
        _SNOWFLAKE,
        _ISO_TIMESTAMP,
        _DISCORD_ASSET_URL,
    )
    if any(pattern.search(serialized) for pattern in structural_patterns):
        raise PrivacyBoundaryError("outgoing payload contains Discord metadata")
    lowered = serialized.casefold()
    for forbidden in forbidden_values:
        normalized = forbidden.strip().casefold()
        if len(normalized) >= 2 and normalized in lowered:
            raise PrivacyBoundaryError("outgoing payload contains a forbidden Discord value")


def display_dry_run(purpose: str, payload: Mapping[str, Any]) -> None:
    """Write an explicit local preview without using the logging subsystem."""

    preview = dict(payload)
    text_format = preview.get("text_format")
    if isinstance(text_format, type):
        preview["text_format"] = text_format.__name__
    document = {"openai_dry_run": True, "purpose": purpose, "request": preview}
    sys.stdout.write(json.dumps(document, indent=2, ensure_ascii=False, default=str) + "\n")
    sys.stdout.flush()
