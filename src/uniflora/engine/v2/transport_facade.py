from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal, TypeAlias

from uniflora.engine.v2.analysis_transport import (
    V2AnalysisTextCommandAdapter,
    V2AnalysisTransportResponse,
)
from uniflora.engine.v2.rendering import V2RenderedResponse
from uniflora.engine.v2.transport import V2TextCommandAdapter

V2TransportRoute: TypeAlias = Literal["investigation", "analysis"]
V2TransportPayload: TypeAlias = V2RenderedResponse | V2AnalysisTransportResponse

_COMMAND_TOKEN_PATTERN = re.compile(r"\S+")
_ANALYSIS_NAMESPACE = "analysis-"


@dataclass(frozen=True, slots=True)
class V2TransportResponse:
    """One transport-neutral envelope for investigation and analysis reads."""

    route: V2TransportRoute
    payload: V2TransportPayload

    @property
    def kind(self) -> str:
        return self.payload.kind

    @property
    def accepted(self) -> bool:
        return self.payload.accepted

    @property
    def code(self) -> str:
        return self.payload.code

    @property
    def summary(self) -> str:
        return self.payload.summary

    @property
    def details(self) -> tuple[str, ...]:
        return self.payload.details

    @property
    def stream_id(self) -> str | None:
        return getattr(self.payload, "stream_id", None)

    @property
    def sequence(self) -> int | None:
        return getattr(self.payload, "sequence", None)

    @property
    def job_id(self) -> str | None:
        return getattr(self.payload, "job_id", None)

    @property
    def artifact_id(self) -> str | None:
        return getattr(self.payload, "artifact_id", None)

    def to_text(self) -> str:
        return self.payload.to_text()


# A descriptive alias for callers that prefer to name the facade boundary.
V2TransportFacadeResponse = V2TransportResponse


def classify_transport_command(text: str) -> V2TransportRoute:
    """Classify only the explicit command namespace; do not parse arguments."""

    tokens = _COMMAND_TOKEN_PATTERN.findall(text.strip())
    if not tokens:
        return "investigation"

    command_index = 0
    first = tokens[0]
    if first.startswith("/"):
        first = first[1:]

    if first.casefold() == "v2":
        command_index = 1
        if len(tokens) <= command_index:
            return "investigation"
        first = tokens[command_index]

    if first.startswith("/"):
        first = first[1:]

    normalized = first.casefold().replace("_", "-")
    if normalized.startswith(_ANALYSIS_NAMESPACE):
        return "analysis"
    return "investigation"


def _analysis_unavailable_response() -> V2AnalysisTransportResponse:
    return V2AnalysisTransportResponse(
        kind="analysis_error",
        accepted=False,
        code="analysis_unavailable",
        summary="Analysis records are not configured for this transport.",
        details=(
            "Investigation commands remain available.",
            "Scientific analysis is performed only by a separately configured worker.",
        ),
    )


class V2TransportFacade:
    """Route strict v2 text commands without depending on Discord or a worker.

    Investigation commands use the persistent investigation adapter. Commands in
    the reserved ``analysis-*`` namespace use the optional, read-only analysis
    presentation adapter. The facade never claims or executes analysis jobs.
    """

    def __init__(
        self,
        investigation_adapter: V2TextCommandAdapter,
        analysis_adapter: V2AnalysisTextCommandAdapter | None = None,
    ) -> None:
        self._investigation_adapter = investigation_adapter
        self._analysis_adapter = analysis_adapter

    @property
    def analysis_available(self) -> bool:
        return self._analysis_adapter is not None

    def execute(
        self,
        stream_id: str,
        *,
        player_id: str,
        text: str,
        expected_sequence: int,
    ) -> V2TransportResponse:
        route = classify_transport_command(text)

        if route == "analysis":
            if self._analysis_adapter is None:
                payload: V2TransportPayload = _analysis_unavailable_response()
            else:
                payload = self._analysis_adapter.execute(text)
            return V2TransportResponse(route=route, payload=payload)

        payload = self._investigation_adapter.execute(
            stream_id,
            player_id=player_id,
            text=text,
            expected_sequence=expected_sequence,
        )
        return V2TransportResponse(route=route, payload=payload)

    def render_session(self, stream_id: str) -> V2TransportResponse:
        return V2TransportResponse(
            route="investigation",
            payload=self._investigation_adapter.render_session(stream_id),
        )
