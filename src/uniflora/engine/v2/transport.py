from __future__ import annotations

from uniflora.engine.v2.application import V2PersistentInvestigationService
from uniflora.engine.v2.parsing import V2CommandParseError, parse_user_command
from uniflora.engine.v2.rendering import (
    V2RenderedResponse,
    render_application_result,
    render_parse_error,
    render_session_view,
)


class V2TextCommandAdapter:
    """Strict text adapter with no Discord or natural-language dependency."""

    def __init__(self, service: V2PersistentInvestigationService) -> None:
        self._service = service

    def execute(
        self,
        stream_id: str,
        *,
        player_id: str,
        text: str,
        expected_sequence: int,
    ) -> V2RenderedResponse:
        try:
            command = parse_user_command(text, player_id=player_id)
        except V2CommandParseError as exc:
            return render_parse_error(exc)

        before = self._service.load_session(stream_id)
        result = self._service.execute(
            stream_id,
            command,
            expected_sequence=expected_sequence,
        )
        return render_application_result(
            result,
            pack=self._service.pack,
            command=command,
            previous_state=before.state,
        )

    def render_session(self, stream_id: str) -> V2RenderedResponse:
        return render_session_view(self._service.load_session(stream_id))
