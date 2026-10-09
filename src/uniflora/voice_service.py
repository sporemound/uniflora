from __future__ import annotations

import asyncio
import hashlib
import os
import re
import shutil
import subprocess
import tempfile
import unicodedata
from collections import OrderedDict
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from uniflora.config import Settings


SEALED_STONE_FILTER = (
    "highpass=f=90,"
    "lowpass=f=3200,"
    "equalizer=f=220:t=q:w=1.2:g=4,"
    "aecho=0.75:0.42:45|95|170:0.24|0.15|0.08,"
    "volume=0.88,"
    "alimiter=limit=0.92"
)

_FILENAME_STOP_WORDS = frozenset({
    "a", "about", "an", "and", "are", "as", "at", "be", "by", "can", "do",
    "for", "from", "has", "have", "hypha", "i", "in", "is", "it", "its",
    "my", "no", "of", "on", "or", "our", "reply", "s", "so", "the", "their",
    "there", "these", "this", "to", "under", "was", "were", "will", "with", "you",
    "your", "public",
})


def contextual_voice_filename(text: str) -> str:
    """Give an eSpeak clip two safe words from its spoken subject."""

    # Albuquerque Mode inserts this marker after vowels for presentation only.
    # Recover the underlying words before choosing a file title.
    source = re.sub(r"(?<=[AEIOUaeiou])Albuquerque", "", text)
    ascii_text = unicodedata.normalize("NFKD", source).encode(
        "ascii", "ignore"
    ).decode("ascii")
    words = re.findall(r"[a-z0-9]+", ascii_text.casefold())
    selected: list[str] = []
    for word in words:
        if word in _FILENAME_STOP_WORDS or word in selected:
            continue
        selected.append(word[:24])
        if len(selected) == 2:
            break
    if not selected:
        selected.append("spoken")
    if len(selected) == 1:
        selected.append("reply")
    return f"{selected[0]}-{selected[1]}.ogg"


def model_voice_filename(title: str) -> str | None:
    """Accept only a safe, two-word title supplied by the dialogue model."""

    words = " ".join(title.strip().strip("\"'").split())
    match = re.fullmatch(r"([A-Za-z0-9]{1,24}) ([A-Za-z0-9]{1,24})", words)
    if match is None:
        return None
    first, second = (word.casefold() for word in match.groups())
    if (first, second) == ("sealed", "stone"):
        return None
    return f"{first}-{second}.ogg"


class VoiceSynthesisError(RuntimeError):
    """Base class for optional voice-rendering failures."""


class VoiceUnavailableError(VoiceSynthesisError):
    """The configured local voice toolchain is disabled or unavailable."""


class VoiceSynthesisBusyError(VoiceSynthesisError):
    """The bounded local voice queue cannot accept work in time."""


class VoiceTextTooLongError(VoiceSynthesisError):
    """A narration exceeds the configured, explicit safety bound."""


@dataclass(frozen=True, slots=True)
class VoiceClip:
    audio: bytes
    filename: str


@dataclass(frozen=True, slots=True)
class VoiceHealth:
    """Result of actually invoking both local voice binaries."""

    enabled: bool
    ready: bool
    espeak_path: Path | None
    ffmpeg_path: Path | None
    detail: str


@dataclass(frozen=True, slots=True)
class VoiceProcessResult:
    stdout: bytes = b""
    stderr: bytes = b""


VoiceProcessRunner = Callable[
    [Path, Sequence[str], float],
    Awaitable[VoiceProcessResult],
]


def _path_candidate(value: str | Path | None) -> Path | None:
    if value is None:
        return None

    raw = str(value).strip()
    if not raw:
        return None

    candidate = Path(raw).expanduser()
    if candidate.is_file():
        return candidate.resolve()

    discovered = shutil.which(raw)
    if discovered:
        return Path(discovered).resolve()

    return None


def _discover_command(
    configured: str | Path | None,
    *,
    packaged_candidates: Sequence[Path],
    path_commands: Sequence[str],
) -> Path | None:
    if configured is not None and str(configured).strip():
        return _path_candidate(configured)

    for candidate in packaged_candidates:
        resolved = _path_candidate(candidate)
        if resolved is not None:
            return resolved

    for command in path_commands:
        resolved = _path_candidate(command)
        if resolved is not None:
            return resolved

    return None


async def _run_local_process(
    program: Path,
    arguments: Sequence[str],
    timeout_seconds: float,
) -> VoiceProcessResult:
    creationflags = (
        subprocess.CREATE_NO_WINDOW
        if os.name == "nt" and hasattr(subprocess, "CREATE_NO_WINDOW")
        else 0
    )

    try:
        process = await asyncio.create_subprocess_exec(
            str(program),
            *arguments,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            creationflags=creationflags,
        )
    except OSError as exc:
        raise VoiceSynthesisError(f"Could not start {program}: {exc}") from exc

    try:
        stdout, stderr = await asyncio.wait_for(
            process.communicate(),
            timeout=timeout_seconds,
        )
    except TimeoutError as exc:
        try:
            process.kill()
        except ProcessLookupError:
            pass
        try:
            await asyncio.wait_for(
                process.communicate(),
                timeout=min(timeout_seconds, 5.0),
            )
        except TimeoutError:
            pass
        raise VoiceSynthesisError(f"{program.name} timed out.") from exc
    except asyncio.CancelledError:
        try:
            process.kill()
        except ProcessLookupError:
            pass
        try:
            await asyncio.wait_for(
                process.communicate(),
                timeout=min(timeout_seconds, 5.0),
            )
        except TimeoutError:
            pass
        raise

    if process.returncode != 0:
        detail = (
            stderr.decode("utf-8", errors="replace")
            or stdout.decode("utf-8", errors="replace")
        )[-1500:]
        raise VoiceSynthesisError(
            f"{program.name} exited with code {process.returncode}: {detail}"
        )

    return VoiceProcessResult(stdout=stdout, stderr=stderr)


class EspeakVoiceService:
    """Bounded, local-only Hypha speech synthesis.

    Audio remains an optional presentation surface. Errors are deliberately
    surfaced to the caller so text delivery can continue without audio.
    """

    def __init__(
        self,
        *,
        espeak_path: Path | str | None,
        espeak_data_root: Path | str | None,
        ffmpeg_path: Path | str | None,
        enabled: bool = True,
        max_characters: int = 6000,
        process_timeout_seconds: float = 45.0,
        queue_timeout_seconds: float = 3.0,
        max_concurrent_requests: int = 1,
        max_pending_requests: int = 2,
        cache_enabled: bool = True,
        cache_max_entries: int = 32,
        process_runner: VoiceProcessRunner | None = None,
        timeout_seconds: float | None = None,
    ) -> None:
        if timeout_seconds is not None:
            process_timeout_seconds = timeout_seconds
        if max_characters < 1:
            raise ValueError("max_characters must be positive")
        if process_timeout_seconds <= 0:
            raise ValueError("process_timeout_seconds must be positive")
        if queue_timeout_seconds <= 0:
            raise ValueError("queue_timeout_seconds must be positive")
        if max_concurrent_requests < 1:
            raise ValueError("max_concurrent_requests must be positive")
        if max_pending_requests < 0:
            raise ValueError("max_pending_requests cannot be negative")
        if cache_max_entries < 0:
            raise ValueError("cache_max_entries cannot be negative")

        self.enabled = enabled
        self.espeak_path = _path_candidate(espeak_path)
        self.ffmpeg_path = _path_candidate(ffmpeg_path)
        self.espeak_data_root = self._resolve_data_root(espeak_data_root)
        self.max_characters = max_characters
        self.process_timeout_seconds = process_timeout_seconds
        # Retained as a read-only compatibility alias for older integrations.
        self.timeout_seconds = process_timeout_seconds
        self.queue_timeout_seconds = queue_timeout_seconds
        self.max_concurrent_requests = max_concurrent_requests
        self.max_pending_requests = max_pending_requests
        self.cache_enabled = cache_enabled
        self.cache_max_entries = cache_max_entries
        self._process_runner = process_runner or _run_local_process
        self._capacity = asyncio.BoundedSemaphore(
            max_concurrent_requests + max_pending_requests
        )
        self._workers = asyncio.BoundedSemaphore(max_concurrent_requests)
        self._health_lock = asyncio.Lock()
        self._cache_lock = asyncio.Lock()
        self._health: VoiceHealth | None = None
        self._cache: OrderedDict[str, VoiceClip] = OrderedDict()

    @classmethod
    def from_settings(
        cls,
        settings: Settings,
        *,
        packaged_tools_root: Path | None = None,
        process_runner: VoiceProcessRunner | None = None,
    ) -> EspeakVoiceService:
        """Resolve a native toolchain from settings, the package, then PATH.

        A configured command is authoritative: an invalid explicit value does
        not silently fall through to another binary.
        """

        tools_root = (
            packaged_tools_root
            if packaged_tools_root is not None
            else Path(__file__).resolve().parents[1] / "Tools"
        )
        packaged_espeak = (
            (tools_root / "espeak-ng.exe", tools_root / "espeak-ng")
            if os.name == "nt"
            else (tools_root / "espeak-ng",)
        )
        packaged_ffmpeg = (
            (tools_root / "ffmpeg.exe", tools_root / "ffmpeg")
            if os.name == "nt"
            else (tools_root / "ffmpeg",)
        )
        espeak_path = _discover_command(
            settings.hypha_voice_espeak_command,
            packaged_candidates=packaged_espeak,
            path_commands=("espeak-ng", "espeak"),
        )
        ffmpeg_path = _discover_command(
            settings.hypha_voice_ffmpeg_command,
            packaged_candidates=packaged_ffmpeg,
            path_commands=("ffmpeg", "ffmpeg.exe"),
        )

        configured_data_root = settings.hypha_voice_espeak_data_root
        if configured_data_root is not None:
            data_root: Path | str | None = configured_data_root
        elif (
            espeak_path is not None
            and espeak_path.parent == tools_root.resolve()
            and (tools_root / "espeak-ng-data").is_dir()
        ):
            data_root = tools_root
        else:
            # System eSpeak installations discover their own data directory.
            data_root = None

        return cls(
            enabled=settings.hypha_voice_enabled,
            espeak_path=espeak_path,
            espeak_data_root=data_root,
            ffmpeg_path=ffmpeg_path,
            max_characters=settings.hypha_voice_max_characters,
            process_timeout_seconds=settings.hypha_voice_process_timeout_seconds,
            queue_timeout_seconds=settings.hypha_voice_queue_timeout_seconds,
            max_concurrent_requests=settings.hypha_voice_max_concurrent_requests,
            max_pending_requests=settings.hypha_voice_max_pending_requests,
            cache_enabled=settings.hypha_voice_cache_enabled,
            cache_max_entries=settings.hypha_voice_cache_max_entries,
            process_runner=process_runner,
        )

    @staticmethod
    def _resolve_data_root(value: Path | str | None) -> Path | None:
        if value is None or not str(value).strip():
            return None

        root = Path(value).expanduser()
        if root.name == "espeak-ng-data":
            root = root.parent
        try:
            return root.resolve()
        except OSError:
            return root.absolute()

    @property
    def available(self) -> bool:
        if not self.enabled:
            return False
        if self.espeak_path is None or self.ffmpeg_path is None:
            return False
        if not self.espeak_path.is_file() or not self.ffmpeg_path.is_file():
            return False
        return self.espeak_data_root is None or (
            self.espeak_data_root / "espeak-ng-data"
        ).is_dir()

    def eligible(self, text: str) -> bool:
        lowered = text.casefold()
        blocked = (
            "natural-language surface is unavailable",
            "interpretation failed",
            "interpretation timed out",
            "fallback mode is active",
            "interpretation is disabled",
            "api budget cap is active",
            "interpretation surface is cooling",
        )

        return (
            self.available
            and bool(text.strip())
            and len(" ".join(text.split())) <= self.max_characters
            and not any(phrase in lowered for phrase in blocked)
        )

    async def probe_health(self, *, force: bool = False) -> VoiceHealth:
        """Render a short clip through the complete local voice pipeline."""

        async with self._health_lock:
            if self._health is not None and not force:
                return self._health

            if not self.enabled:
                result = VoiceHealth(
                    enabled=False,
                    ready=False,
                    espeak_path=self.espeak_path,
                    ffmpeg_path=self.ffmpeg_path,
                    detail="Hypha voice is disabled.",
                )
            elif not self.available:
                missing: list[str] = []
                if self.espeak_path is None or not self.espeak_path.is_file():
                    missing.append("eSpeak NG")
                if self.ffmpeg_path is None or not self.ffmpeg_path.is_file():
                    missing.append("FFmpeg")
                if self.espeak_data_root is not None and not (
                    self.espeak_data_root / "espeak-ng-data"
                ).is_dir():
                    missing.append("eSpeak NG data")
                result = VoiceHealth(
                    enabled=True,
                    ready=False,
                    espeak_path=self.espeak_path,
                    ffmpeg_path=self.ffmpeg_path,
                    detail=f"Unavailable local dependency: {', '.join(missing)}.",
                )
            else:
                assert self.espeak_path is not None
                assert self.ffmpeg_path is not None
                try:
                    await self._synthesize_uncached("Hypha voice health probe.")
                except (OSError, VoiceSynthesisError) as exc:
                    result = VoiceHealth(
                        enabled=True,
                        ready=False,
                        espeak_path=self.espeak_path,
                        ffmpeg_path=self.ffmpeg_path,
                        detail=str(exc),
                    )
                else:
                    result = VoiceHealth(
                        enabled=True,
                        ready=True,
                        espeak_path=self.espeak_path,
                        ffmpeg_path=self.ffmpeg_path,
                        detail="The eSpeak NG and FFmpeg rendering probe succeeded.",
                    )

            self._health = result
            return result

    async def synthesize(self, text: str) -> VoiceClip:
        speech = " ".join(text.split())
        if not speech:
            raise VoiceSynthesisError("Speech text is empty.")
        if len(speech) > self.max_characters:
            raise VoiceTextTooLongError(
                "Speech text has "
                f"{len(speech)} characters; the configured limit is "
                f"{self.max_characters}. No text was truncated."
            )
        if not self.enabled:
            raise VoiceUnavailableError("Hypha voice is disabled.")

        cache_key = hashlib.sha256(speech.encode("utf-8")).hexdigest()
        cached = await self._cache_get(cache_key)
        if cached is not None:
            return cached

        await self._acquire_or_busy(self._capacity, "Voice request queue is full.")
        try:
            await self._acquire_or_busy(
                self._workers,
                "Voice request waited too long for a synthesis worker.",
            )
            try:
                health = await self.probe_health()
                if not health.ready:
                    raise VoiceUnavailableError(health.detail)
                clip = await self._synthesize_uncached(speech)
            finally:
                self._workers.release()
        finally:
            self._capacity.release()

        await self._cache_put(cache_key, clip)
        return clip

    async def _acquire_or_busy(
        self,
        semaphore: asyncio.BoundedSemaphore,
        message: str,
    ) -> None:
        try:
            await asyncio.wait_for(
                semaphore.acquire(),
                timeout=self.queue_timeout_seconds,
            )
        except TimeoutError as exc:
            raise VoiceSynthesisBusyError(message) from exc

    async def _synthesize_uncached(self, speech: str) -> VoiceClip:
        assert self.espeak_path is not None
        assert self.ffmpeg_path is not None

        with tempfile.TemporaryDirectory(prefix="hypha-voice-") as directory:
            root = Path(directory)
            speech_path = root / "speech.txt"
            raw_path = root / "raw.wav"
            final_path = root / contextual_voice_filename(speech)
            await asyncio.to_thread(
                speech_path.write_text,
                speech,
                encoding="utf-8",
            )

            espeak_arguments: list[str] = []
            if self.espeak_data_root is not None:
                espeak_arguments.append(f"--path={self.espeak_data_root}")
            espeak_arguments.extend(
                (
                    "-v",
                    "en-us",
                    "-s",
                    "118",
                    "-p",
                    "28",
                    "-a",
                    "125",
                    "-f",
                    str(speech_path),
                    "-w",
                    str(raw_path),
                )
            )
            await self._process_runner(
                self.espeak_path,
                tuple(espeak_arguments),
                self.process_timeout_seconds,
            )

            if not raw_path.is_file():
                raise VoiceSynthesisError(
                    "eSpeak did not create the intermediate WAV."
                )

            await self._process_runner(
                self.ffmpeg_path,
                (
                    "-y",
                    "-loglevel",
                    "error",
                    "-i",
                    str(raw_path),
                    "-af",
                    SEALED_STONE_FILTER,
                    "-ac",
                    "1",
                    "-ar",
                    "48000",
                    "-c:a",
                    "libopus",
                    "-b:a",
                    "32k",
                    str(final_path),
                ),
                self.process_timeout_seconds,
            )

            if not final_path.is_file():
                raise VoiceSynthesisError("FFmpeg did not create the final OGG.")

            return VoiceClip(audio=final_path.read_bytes(), filename=final_path.name)

    async def _cache_get(self, key: str) -> VoiceClip | None:
        if not self.cache_enabled or self.cache_max_entries == 0:
            return None
        async with self._cache_lock:
            clip = self._cache.get(key)
            if clip is not None:
                self._cache.move_to_end(key)
            return clip

    async def _cache_put(self, key: str, clip: VoiceClip) -> None:
        if not self.cache_enabled or self.cache_max_entries == 0:
            return
        async with self._cache_lock:
            self._cache[key] = clip
            self._cache.move_to_end(key)
            while len(self._cache) > self.cache_max_entries:
                self._cache.popitem(last=False)
