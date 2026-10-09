from __future__ import annotations

from types import SimpleNamespace

import pytest

from uniflora.activity_difficulty_sync import ActivityDifficultySync
from uniflora.runtime import Environment


@pytest.mark.asyncio
async def test_saved_choices_are_sent_to_their_own_activity_environment() -> None:
    live_ref = object()
    test_ref = object()

    async def difficulty_preferences(ref: object) -> tuple[tuple[int, str, int], ...]:
        return ((123456789012345678, "guided", 2),) if ref is live_ref else ()

    sync = ActivityDifficultySync(
        "https://activity.example",
        "shared-test-secret",
        SimpleNamespace(difficulty_preferences=difficulty_preferences),  # type: ignore[arg-type]
        {Environment.LIVE: live_ref, Environment.TEST: test_ref},  # type: ignore[arg-type]
    )
    requests: list[dict[str, object]] = []
    sync._post = requests.append  # type: ignore[method-assign]

    await sync.sync_once()

    assert requests == [
        {
            "environment": "live",
            "choices": [
                {"discordUserId": "123456789012345678", "level": "guided", "revision": 2}
            ],
        }
    ]
