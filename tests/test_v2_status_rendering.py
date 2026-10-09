from __future__ import annotations

from uniflora.content.v2 import load_missing_interior_pack
from uniflora.engine.v2 import (
    V2BeginInvestigationCommand,
    V2SessionView,
    execute_command,
    initialize_event_stream,
    seal_event_stream,
)
from uniflora.engine.v2.rendering import render_session_view


PLAYER = "discord:1"


def test_player_status_is_compact_and_pack_driven() -> None:
    pack = load_missing_interior_pack()
    stream = initialize_event_stream(
        pack,
        (PLAYER,),
        stream_id="compact-status-test",
    )

    begun = execute_command(
        pack,
        stream,
        V2BeginInvestigationCommand(player_id=PLAYER),
    )

    assert begun.accepted
    envelopes = seal_event_stream(begun.stream)

    session = V2SessionView(
        stream_id=begun.stream.stream_id,
        state=begun.stream.state,
        sequence=begun.stream.state.revision,
        last_event_hash=envelopes[-1].event_hash,
    )

    rendered = render_session_view(
        session,
        pack=pack,
        player_id=PLAYER,
    )
    text = rendered.to_text()

    assert "**Position 1 \u2014 First Return**" in text
    assert "**Progress**" in text
    assert "Evidence 0/4" in text
    assert "**Your current function**" in text
    assert "**Next step**" in text
    assert "shared authoritative state" in text

    assert "Investigation stream" not in text
    assert "Available locations:" not in text
    assert "Available evidence:" not in text
    assert "Examined evidence:" not in text
    assert "Completed actions:" not in text
    assert "Player discord:" not in text
