from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Final


class DifficultyLevel(StrEnum):
    """A private presentation preference; never an authoritative rules switch."""

    GUIDED = "guided"
    STANDARD = "standard"
    EXPERT = "expert"


DIFFICULTY_POLL_ID: Final = "hypha-difficulty-v1"
DEFAULT_DIFFICULTY: Final = DifficultyLevel.STANDARD
MAX_DIFFICULTY_CHANGES_PER_BALLOT: Final = 24

DIFFICULTY_LABELS: Final = MappingProxyType(
    {
        DifficultyLevel.GUIDED: "Guided",
        DifficultyLevel.STANDARD: "Standard",
        DifficultyLevel.EXPERT: "Expert",
    }
)

DIFFICULTY_DESCRIPTIONS: Final = MappingProxyType(
    {
        DifficultyLevel.GUIDED: (
            "proactive next-step cues, definitions, and command reminders"
        ),
        DifficultyLevel.STANDARD: (
            "the current balanced presentation with normal phase guidance"
        ),
        DifficultyLevel.EXPERT: (
            "minimal automatic scaffolding; explicit help remains available on request"
        ),
    }
)

DIFFICULTY_POLL_TEXT: Final = """\
**Choose your personal investigation difficulty**

This controls only how much guidance Hypha shows to you:
• **Guided** — proactive next steps, definitions, and command reminders.
• **Standard** — balanced guidance (default).
• **Expert** — minimal automatic scaffolding.

Evidence, scientific constraints, review independence, access rules, action costs, and
position-completion requirements remain identical. Your choice is private, may be changed while
this selector is open, and is bound to the Discord account that clicks the button."""


@dataclass(frozen=True, slots=True)
class DifficultyPreference:
    poll_id: str
    level: DifficultyLevel
    revision: int


@dataclass(frozen=True, slots=True)
class DifficultyBallot:
    ballot_id: str
    poll_id: str
    environment: str
    guild_id: int
    channel_id: int
    message_id: int
    status: str
    revision: int


@dataclass(frozen=True, slots=True)
class DifficultySelectionResult:
    preference: DifficultyPreference
    changed: bool
    duplicate: bool


def parse_difficulty_level(value: str | DifficultyLevel) -> DifficultyLevel:
    if isinstance(value, DifficultyLevel):
        return value
    try:
        return DifficultyLevel(value.strip().casefold())
    except (AttributeError, ValueError) as exc:
        allowed = ", ".join(item.value for item in DifficultyLevel)
        raise ValueError(f"difficulty must be one of: {allowed}") from exc


def difficulty_confirmation(level: DifficultyLevel) -> str:
    label = DIFFICULTY_LABELS[level]
    return (
        f"Saved **{label}** for you. Hypha will use "
        f"{DIFFICULTY_DESCRIPTIONS[level]}. Shared game rules did not change."
    )


def guided_support_footer(*, v2: bool = False) -> str:
    if v2:
        return (
            "Guided support: use `/v2 status` to inspect persistent state and `/v2 guide` "
            "for the complete Position 1 sequence."
        )
    return (
        "Guided support: `/interior next` shows useful actions and "
        "`/interior accessibility` always shows explicit alternatives."
    )
