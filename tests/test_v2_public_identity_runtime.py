from __future__ import annotations

import asyncio
from pathlib import Path

from uniflora.v2_test_runtime import V2TestRuntime


def test_public_discord_identities_join_shared_stream(tmp_path: Path) -> None:
    async def scenario() -> None:
        database = tmp_path / "public.sqlite3"
        runtime = V2TestRuntime(database, stream_id="public-release")

        begun = await runtime.execute_public(
            player_id="discord:111",
            text="begin-investigation",
        )
        assert begun.accepted
        assert begun.code == "investigation_begun"

        first = await runtime.assign_public_role(
            player_id="discord:111",
            role_id="field_observer",
            display_name="Optical Records Examiner",
        )
        second = await runtime.assign_public_role(
            player_id="discord:222",
            role_id="protocol_auditor",
            display_name="Independent Reviewer",
        )
        assert first.accepted
        assert second.accepted

        status = await runtime.public_status()
        rendered = status.to_text()
        assert "Player discord:111" in rendered
        assert "Player discord:222" in rendered
        assert "test:investigator-a" not in rendered
        assert "test:reviewer-b" not in rendered

        await runtime.close()

        reopened = V2TestRuntime(database, stream_id="public-release")
        restored = await reopened.public_status()
        assert "Player discord:111" in restored.to_text()
        assert "Player discord:222" in restored.to_text()
        await reopened.close()

    asyncio.run(scenario())


def test_boundary_event_role_choices_are_current_position_only(tmp_path: Path) -> None:
    async def scenario() -> None:
        runtime = V2TestRuntime(tmp_path / "roles.sqlite3", stream_id="roles")
        begun = await runtime.execute_public(
            player_id="discord:111",
            text="begin-investigation",
        )
        assert begun.accepted

        roles = await runtime.available_public_roles()
        assert tuple(role_id for role_id, _ in roles) == (
            "field_observer",
            "instrument_operator",
            "atmospheric_analyst",
            "signal_correlator",
            "protocol_auditor",
        )
        await runtime.close()

    asyncio.run(scenario())
