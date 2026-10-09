from __future__ import annotations

import re
import shlex
from dataclasses import dataclass
from typing import Literal

from uniflora.engine.v2.analysis_persistence import (
    V2AnalysisArtifactNotFoundError,
    V2AnalysisJobNotFoundError,
    V2AnalysisJobStatus,
    V2AnalysisPersistenceError,
)
from uniflora.engine.v2.analysis_presentation import (
    V2AnalysisPresentationService,
    V2RenderedAnalysisResponse,
    render_analysis_artifact,
    render_analysis_status,
)

_IDENTIFIER_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,255}\Z")


class V2AnalysisCommandParseError(ValueError):
    """Raised when explicit analysis command text is invalid."""

    def __init__(self, code: str, message: str, *, usage: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.usage = usage


@dataclass(frozen=True, slots=True)
class V2AnalysisCommandHelp:
    name: str
    usage: str
    description: str


ANALYSIS_COMMAND_HELP: tuple[V2AnalysisCommandHelp, ...] = (
    V2AnalysisCommandHelp(
        name="analysis-status",
        usage="analysis-status <job_id>",
        description="Read the persisted status of one analysis job.",
    ),
    V2AnalysisCommandHelp(
        name="analysis-artifact",
        usage="analysis-artifact <artifact_id>",
        description="Read one completed analysis artifact by artifact ID.",
    ),
    V2AnalysisCommandHelp(
        name="analysis-artifact-for-job",
        usage="analysis-artifact-for-job <job_id>",
        description="Read the completed artifact associated with an analysis job.",
    ),
)

_HELP_BY_NAME = {item.name: item for item in ANALYSIS_COMMAND_HELP}


@dataclass(frozen=True, slots=True)
class V2GetAnalysisStatusCommand:
    job_id: str


@dataclass(frozen=True, slots=True)
class V2GetAnalysisArtifactCommand:
    artifact_id: str


@dataclass(frozen=True, slots=True)
class V2GetAnalysisArtifactForJobCommand:
    job_id: str


V2AnalysisReadCommand = (
    V2GetAnalysisStatusCommand | V2GetAnalysisArtifactCommand | V2GetAnalysisArtifactForJobCommand
)


@dataclass(frozen=True, slots=True)
class V2AnalysisTransportResponse:
    kind: Literal["analysis_status", "analysis_artifact", "analysis_error"]
    accepted: bool
    code: str
    summary: str
    details: tuple[str, ...] = ()
    job_id: str | None = None
    artifact_id: str | None = None

    def to_text(self) -> str:
        return "\n".join((self.summary, *self.details))


def _tokenize(text: str) -> list[str]:
    normalized = text.strip()
    if not normalized:
        raise V2AnalysisCommandParseError(
            "empty_analysis_command",
            "No analysis command was provided.",
        )

    try:
        tokens = shlex.split(normalized, posix=True)
    except ValueError as exc:
        raise V2AnalysisCommandParseError(
            "invalid_analysis_quoting",
            f"Analysis command quoting is invalid: {exc}",
        ) from exc

    if not tokens:
        raise V2AnalysisCommandParseError(
            "empty_analysis_command",
            "No analysis command was provided.",
        )

    if tokens[0].startswith("/"):
        tokens[0] = tokens[0][1:]

    if tokens[0].casefold() == "v2":
        tokens = tokens[1:]
        if not tokens:
            raise V2AnalysisCommandParseError(
                "empty_analysis_command",
                "No analysis command followed the v2 prefix.",
            )

    return tokens


def _parse_identifier(value: str, *, label: str, usage: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise V2AnalysisCommandParseError(
            "missing_analysis_identifier",
            f"The {label} must not be blank.",
            usage=usage,
        )
    if _IDENTIFIER_PATTERN.fullmatch(normalized) is None:
        raise V2AnalysisCommandParseError(
            "invalid_analysis_identifier",
            (
                f"The {label} must begin with an ASCII letter or digit and may "
                "contain only letters, digits, periods, underscores, colons, "
                "or hyphens."
            ),
            usage=usage,
        )
    return normalized


def parse_analysis_command(text: str) -> V2AnalysisReadCommand:
    """Parse a strict, read-only analysis transport command."""

    tokens = _tokenize(text)
    command_name = tokens[0].casefold().replace("_", "-")
    help_item = _HELP_BY_NAME.get(command_name)
    if help_item is None:
        known = ", ".join(item.name for item in ANALYSIS_COMMAND_HELP)
        raise V2AnalysisCommandParseError(
            "unknown_analysis_command",
            f"Unknown analysis command {tokens[0]!r}. Known commands: {known}.",
        )

    arguments = tokens[1:]
    if len(arguments) != 1:
        raise V2AnalysisCommandParseError(
            "invalid_analysis_arguments",
            (f"Command {command_name!r} expects 1 argument; received {len(arguments)}."),
            usage=help_item.usage,
        )

    if command_name == "analysis-status":
        return V2GetAnalysisStatusCommand(
            job_id=_parse_identifier(
                arguments[0],
                label="analysis job ID",
                usage=help_item.usage,
            )
        )
    if command_name == "analysis-artifact":
        return V2GetAnalysisArtifactCommand(
            artifact_id=_parse_identifier(
                arguments[0],
                label="analysis artifact ID",
                usage=help_item.usage,
            )
        )
    return V2GetAnalysisArtifactForJobCommand(
        job_id=_parse_identifier(
            arguments[0],
            label="analysis job ID",
            usage=help_item.usage,
        )
    )


def _success_response(
    rendered: V2RenderedAnalysisResponse,
) -> V2AnalysisTransportResponse:
    return V2AnalysisTransportResponse(
        kind=rendered.kind,
        accepted=True,
        code=rendered.code,
        summary=rendered.summary,
        details=rendered.details,
        job_id=rendered.job_id,
        artifact_id=rendered.artifact_id,
    )


def _parse_error_response(
    error: V2AnalysisCommandParseError,
) -> V2AnalysisTransportResponse:
    details = (f"Usage: {error.usage}",) if error.usage else ()
    return V2AnalysisTransportResponse(
        kind="analysis_error",
        accepted=False,
        code=error.code,
        summary=f"Analysis command not accepted: {error.message}",
        details=details,
    )


def _not_found_response(
    *,
    code: str,
    summary: str,
    job_id: str | None = None,
    artifact_id: str | None = None,
) -> V2AnalysisTransportResponse:
    return V2AnalysisTransportResponse(
        kind="analysis_error",
        accepted=False,
        code=code,
        summary=summary,
        job_id=job_id,
        artifact_id=artifact_id,
    )


class V2AnalysisTextCommandAdapter:
    """Read-only text adapter for analysis status and artifact presentation."""

    def __init__(self, service: V2AnalysisPresentationService) -> None:
        self._service = service

    def execute(self, text: str) -> V2AnalysisTransportResponse:
        try:
            command = parse_analysis_command(text)
        except V2AnalysisCommandParseError as exc:
            return _parse_error_response(exc)

        try:
            if isinstance(command, V2GetAnalysisStatusCommand):
                return _success_response(
                    render_analysis_status(self._service.get_status(command.job_id))
                )

            if isinstance(command, V2GetAnalysisArtifactCommand):
                return _success_response(
                    render_analysis_artifact(self._service.get_artifact(command.artifact_id))
                )

            artifact = self._service.get_artifact_for_job(command.job_id)
            if artifact is not None:
                return _success_response(render_analysis_artifact(artifact))

            status = self._service.get_status(command.job_id)
            if status.status is V2AnalysisJobStatus.FAILED:
                details = (
                    f"Status: {status.status.value}",
                    *((f"Error: {status.error}",) if status.error else ()),
                )
                return V2AnalysisTransportResponse(
                    kind="analysis_error",
                    accepted=False,
                    code="analysis_artifact_unavailable",
                    summary=(f"Analysis job {command.job_id!r} failed without an artifact."),
                    details=details,
                    job_id=command.job_id,
                )

            return V2AnalysisTransportResponse(
                kind="analysis_error",
                accepted=False,
                code="analysis_artifact_pending",
                summary=(f"Analysis job {command.job_id!r} has no completed artifact yet."),
                details=(
                    f"Status: {status.status.value}",
                    f"Attempts: {status.attempt_count}",
                ),
                job_id=command.job_id,
            )
        except V2AnalysisJobNotFoundError:
            job_id = getattr(command, "job_id", None)
            return _not_found_response(
                code="analysis_job_not_found",
                summary=f"Analysis job {job_id!r} was not found.",
                job_id=job_id,
            )
        except V2AnalysisArtifactNotFoundError:
            artifact_id = getattr(command, "artifact_id", None)
            return _not_found_response(
                code="analysis_artifact_not_found",
                summary=f"Analysis artifact {artifact_id!r} was not found.",
                artifact_id=artifact_id,
            )
        except V2AnalysisPersistenceError:
            return V2AnalysisTransportResponse(
                kind="analysis_error",
                accepted=False,
                code="analysis_storage_error",
                summary="Analysis records could not be read safely.",
            )
