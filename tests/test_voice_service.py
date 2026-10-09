from __future__ import annotations

import asyncio
from collections.abc import Sequence
from pathlib import Path
from types import SimpleNamespace

import pytest

from uniflora.voice_service import (
    EspeakVoiceService,
    VoiceProcessResult,
    VoiceSynthesisBusyError,
    VoiceSynthesisError,
    VoiceTextTooLongError,
    VoiceUnavailableError,
    _run_local_process,
    contextual_voice_filename,
    model_voice_filename,
)


def write_test_file(path: str, contents: bytes) -> None:
    Path(path).write_bytes(contents)


def read_test_text(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("The public optical record is open.", "optical-record.ogg"),
        ("The signal is strong.", "signal-strong.ogg"),
        ("No words are lost.", "words-lost.ogg"),
        ("caAlbuquerquet", "cat-reply.ogg"),
        ("../The station doors reopened!", "station-doors.ogg"),
    ],
)
def test_contextual_voice_filename_uses_two_safe_words(
    text: str, expected: str,
) -> None:
    assert contextual_voice_filename(text) == expected


def test_model_voice_filename_rejects_unsafe_or_generic_titles() -> None:
    assert model_voice_filename("Optical Record") == "optical-record.ogg"
    assert model_voice_filename("Sealed Stone") is None
    assert model_voice_filename("../../private") is None
    assert model_voice_filename("three word title") is None


class FakeVoiceRunner:
    def __init__(self) -> None:
        self.calls: list[tuple[Path, tuple[str, ...], float]] = []
        self.spoken_texts: list[str] = []

    async def __call__(
        self,
        program: Path,
        arguments: Sequence[str],
        timeout_seconds: float,
    ) -> VoiceProcessResult:
        args = tuple(arguments)
        self.calls.append((program, args, timeout_seconds))
        if "-f" in args:
            self.spoken_texts.append(read_test_text(args[args.index("-f") + 1]))
        if "-w" in args:
            write_test_file(args[args.index("-w") + 1], b"test-wave")
        elif args and args[-1].endswith(".ogg"):
            write_test_file(args[-1], b"test-ogg")
        return VoiceProcessResult(stdout=b"ok")


def voice_service(
    tmp_path: Path,
    runner: FakeVoiceRunner,
    **changes: object,
) -> EspeakVoiceService:
    espeak_path = tmp_path / "espeak-ng"
    ffmpeg_path = tmp_path / "ffmpeg"
    espeak_path.touch()
    ffmpeg_path.touch()
    options: dict[str, object] = {
        "espeak_path": espeak_path,
        "espeak_data_root": None,
        "ffmpeg_path": ffmpeg_path,
        "process_runner": runner,
    }
    options.update(changes)
    return EspeakVoiceService(**options)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_health_probe_renders_through_both_tools_and_is_cached(
    tmp_path: Path,
) -> None:
    runner = FakeVoiceRunner()
    service = voice_service(tmp_path, runner)

    first = await service.probe_health()
    second = await service.probe_health()

    assert first.ready is True
    assert second is first
    assert len(runner.calls) == 2
    assert "-w" in runner.calls[0][1]
    assert runner.spoken_texts == ["Hypha voice health probe."]
    assert runner.calls[1][1][-1].endswith(".ogg")
    assert all(call[2] == 45.0 for call in runner.calls)


@pytest.mark.asyncio
async def test_failed_health_probe_makes_voice_optional_and_unavailable(
    tmp_path: Path,
) -> None:
    async def failing_runner(
        _program: Path,
        _arguments: Sequence[str],
        _timeout_seconds: float,
    ) -> VoiceProcessResult:
        raise VoiceSynthesisError("probe failed")

    espeak_path = tmp_path / "espeak-ng"
    ffmpeg_path = tmp_path / "ffmpeg"
    espeak_path.touch()
    ffmpeg_path.touch()
    service = EspeakVoiceService(
        espeak_path=espeak_path,
        espeak_data_root=None,
        ffmpeg_path=ffmpeg_path,
        process_runner=failing_runner,
    )

    health = await service.probe_health()
    assert health.ready is False
    assert health.detail == "probe failed"

    with pytest.raises(VoiceUnavailableError, match="probe failed"):
        await service.synthesize("The complete text remains available.")


@pytest.mark.asyncio
async def test_synthesis_never_silently_truncates(tmp_path: Path) -> None:
    runner = FakeVoiceRunner()
    service = voice_service(tmp_path, runner, max_characters=10)

    with pytest.raises(VoiceTextTooLongError, match="No text was truncated"):
        await service.synthesize("12345678901")

    assert runner.calls == []


@pytest.mark.asyncio
async def test_synthesis_uses_full_normalized_text_and_bounded_cache(
    tmp_path: Path,
) -> None:
    runner = FakeVoiceRunner()
    service = voice_service(tmp_path, runner, cache_max_entries=1)

    first = await service.synthesize("No   words\nare lost.")
    cached = await service.synthesize("No words are lost.")

    assert first.audio == b"test-ogg"
    assert first.filename == "words-lost.ogg"
    assert cached is first
    assert runner.spoken_texts.count("No words are lost.") == 1

    await service.synthesize("A different line.")
    await service.synthesize("No words are lost.")
    assert runner.spoken_texts.count("No words are lost.") == 2
    assert runner.spoken_texts.count("A different line.") == 1


@pytest.mark.asyncio
async def test_bounded_queue_rejects_excess_work(tmp_path: Path) -> None:
    started = asyncio.Event()
    release = asyncio.Event()

    class BlockingRunner(FakeVoiceRunner):
        async def __call__(
            self,
            program: Path,
            arguments: Sequence[str],
            timeout_seconds: float,
        ) -> VoiceProcessResult:
            args = tuple(arguments)
            speech = (
                read_test_text(args[args.index("-f") + 1])
                if "-f" in args
                else None
            )
            if "-w" in args and speech != "Hypha voice health probe.":
                started.set()
                await release.wait()
            return await super().__call__(program, args, timeout_seconds)

    runner = BlockingRunner()
    service = voice_service(
        tmp_path,
        runner,
        max_pending_requests=0,
        queue_timeout_seconds=0.02,
    )
    await service.probe_health()
    active = asyncio.create_task(service.synthesize("first"))
    await started.wait()

    with pytest.raises(VoiceSynthesisBusyError, match="queue is full"):
        await service.synthesize("second")

    release.set()
    assert (await active).audio == b"test-ogg"


@pytest.mark.asyncio
async def test_process_timeout_kills_child_without_real_binary(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    class HangingProcess:
        returncode = 0

        def __init__(self) -> None:
            self.killed = False
            self.wait_forever = asyncio.Event()

        async def communicate(self) -> tuple[bytes, bytes]:
            if self.killed:
                return b"", b""
            await self.wait_forever.wait()
            return b"", b""

        def kill(self) -> None:
            self.killed = True

    process = HangingProcess()

    async def create_process(*_args: object, **_kwargs: object) -> HangingProcess:
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", create_process)

    with pytest.raises(VoiceSynthesisError, match="timed out"):
        await _run_local_process(tmp_path / "unused", ("--version",), 0.01)
    assert process.killed is True


def test_from_settings_resolves_packaged_windows_tools_without_executing_them(
    tmp_path: Path,
) -> None:
    tools = tmp_path / "Tools"
    tools.mkdir()
    (tools / "espeak-ng-data").mkdir()
    (tools / "espeak-ng.exe").touch()
    (tools / "ffmpeg.exe").touch()
    runner = FakeVoiceRunner()
    settings = SimpleNamespace(
        hypha_voice_enabled=True,
        hypha_voice_espeak_command=None,
        hypha_voice_espeak_data_root=None,
        hypha_voice_ffmpeg_command=None,
        hypha_voice_max_characters=5000,
        hypha_voice_process_timeout_seconds=20.0,
        hypha_voice_queue_timeout_seconds=2.0,
        hypha_voice_max_concurrent_requests=1,
        hypha_voice_max_pending_requests=1,
        hypha_voice_cache_enabled=False,
        hypha_voice_cache_max_entries=0,
    )

    service = EspeakVoiceService.from_settings(
        settings,  # type: ignore[arg-type]
        packaged_tools_root=tools,
        process_runner=runner,
    )

    assert service.espeak_path == (tools / "espeak-ng.exe").resolve()
    assert service.ffmpeg_path == (tools / "ffmpeg.exe").resolve()
    assert service.espeak_data_root == tools.resolve()
    assert service.max_characters == 5000
    assert service.cache_enabled is False
