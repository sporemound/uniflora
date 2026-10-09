from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import re
import secrets
import time
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, build_opener

from uniflora.albuquerque_mode import transform_albuquerque_markdown
from uniflora.gemini_chat import GeminiVoiceReplyService, build_v2_chat_context
from uniflora.openai_privacy import DiscordPrivacyMetadata, ParticipantIdentity


class ActivityChatRelayError(RuntimeError):
    pass


_MAX_TRANSCRIPT_CHARACTERS = 4000
_MAX_ALBUQUERQUE_SOURCE_CHARACTERS = 300


def _transform_albuquerque_reply(text: str) -> str:
    """Shorten source prose if needed, then transform without splitting insertions.

    The shared chat database and completion endpoint both cap transcripts at
    4,000 characters. A 300-character source cannot exceed that limit even if
    every source character is a vowel (300 * 12 plus one ellipsis).
    """

    source = text
    rendered = transform_albuquerque_markdown(source)
    if len(rendered) <= _MAX_TRANSCRIPT_CHARACTERS:
        return rendered

    prefix = source[:_MAX_ALBUQUERQUE_SOURCE_CHARACTERS]
    sentence_ends = [
        match.end() for match in re.finditer(r"[.!?](?=\s|$)", prefix)
        if match.end() >= 80
    ]
    if sentence_ends:
        boundary = sentence_ends[-1]
    else:
        boundary = max(prefix.rfind(" "), prefix.rfind("\n"))
    if boundary < 80:
        # A single huge token is usually a URL or path; do not split it.
        prefix = "Please ask Hypha for a shorter reply."
    else:
        prefix = prefix[:boundary].rstrip()
    return transform_albuquerque_markdown(prefix + "…")


@dataclass(frozen=True, slots=True)
class ActivityChatClaim:
    request_id: str
    discord_user_id: int | str
    environment: str
    stream_id: str
    privacy_alias: str | None
    history: tuple[tuple[str, str], ...]
    message: str
    albuquerque_mode: bool = False


class ActivityChatRelay:
    """Poll private Activity chat work and render it through local sealed-stone Hypha."""

    def __init__(
        self,
        base_url: str,
        secret: str,
        runtime: Any,
        voice_reply: GeminiVoiceReplyService,
        stream_id: str,
        *,
        environment: str = "test",
        poll_seconds: float = 5.0,
    ) -> None:
        parsed = urlsplit(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("Activity chat relay requires an HTTP(S) origin")
        if parsed.scheme == "http" and (parsed.hostname or "").casefold() not in {
            "127.0.0.1",
            "localhost",
            "::1",
        }:
            raise ValueError("Activity chat relay requires HTTPS outside loopback")
        if not secret:
            raise ValueError("Activity chat relay secret must not be empty")
        if poll_seconds <= 0:
            raise ValueError("poll_seconds must be positive")
        if not stream_id or len(stream_id) > 128:
            raise ValueError("Activity chat relay requires a v2 stream ID")
        if environment not in {"test", "live"}:
            raise ValueError("Activity chat relay requires test or live environment")
        self._origin = f"{parsed.scheme}://{parsed.netloc}"
        self._secret = secret.encode("utf-8")
        self._runtime = runtime
        self._voice_reply = voice_reply
        self._stream_id = stream_id
        self._environment = environment
        self._poll_seconds = poll_seconds
        self._opener = build_opener()

    def _signed_json_request(
        self,
        path: str,
        payload: dict[str, object],
    ) -> object:
        body = json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        content_sha256 = hashlib.sha256(body).hexdigest()
        timestamp = int(time.time())
        nonce = secrets.token_hex(16)
        canonical = "\n".join(
            ("POST", path, str(timestamp), nonce, content_sha256)
        )
        signature = hmac.new(
            self._secret,
            canonical.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        request = Request(
            self._origin + path,
            data=body,
            method="POST",
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "User-Agent": "TheMissingInterior-HyphaRelay/1.0",
                "X-Hypha-Timestamp": str(timestamp),
                "X-Hypha-Nonce": nonce,
                "X-Hypha-Content-SHA256": content_sha256,
                "X-Hypha-Signature": f"v1={signature}",
            },
        )
        try:
            with self._opener.open(request, timeout=15) as response:  # noqa: S310
                raw = response.read(3 * 1024 * 1024 + 1)
                status = response.status
        except HTTPError as error:
            raw = error.read(4096)
            status = error.code
        if not 200 <= status < 300:
            detail = raw.decode("utf-8", errors="replace")[:1000]
            raise ActivityChatRelayError(
                f"Activity chat relay returned HTTP {status}: {detail}"
            )
        if not raw:
            return None
        try:
            return json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ActivityChatRelayError(
                "Activity chat relay returned invalid JSON"
            ) from exc

    async def claim(self) -> ActivityChatClaim | None:
        value = await asyncio.to_thread(
            self._signed_json_request,
            "/api/hypha/chat/claim",
            {"environment": self._environment, "streamId": self._stream_id},
        )
        if value is None:
            return None
        if not isinstance(value, dict):
            raise ActivityChatRelayError("Activity chat claim must be an object")
        request_id = str(value.get("requestId") or "")
        discord_user_raw = value.get("discordUserId")
        environment = str(value.get("environment") or "")
        stream_id = str(value.get("streamId") or "")
        privacy_alias = value.get("privacyAlias")
        history_raw = value.get("history")
        message = str(value.get("message") or "")
        albuquerque_mode = value.get("albuquerqueMode", False)
        if not isinstance(albuquerque_mode, bool):
            raise ActivityChatRelayError("Activity chat claim has an invalid presentation mode")
        if (
            isinstance(discord_user_raw, str)
            and re.fullmatch(r"web:participant_[a-f0-9]{24}", discord_user_raw)
        ):
            discord_user_id: int | str = discord_user_raw
        else:
            try:
                discord_user_id = int(str(discord_user_raw))
            except (TypeError, ValueError) as exc:
                raise ActivityChatRelayError(
                    "Activity chat claim has no usable participant identity"
                ) from exc
            if discord_user_id <= 0:
                raise ActivityChatRelayError(
                    "Activity chat claim has an invalid participant identity"
                )
        if (
            not request_id or not message or environment != self._environment
            or stream_id != self._stream_id
        ):
            raise ActivityChatRelayError("Activity chat claim is incomplete")
        if not isinstance(history_raw, list) or len(history_raw) > 8:
            raise ActivityChatRelayError("Activity chat claim history is invalid")
        history: list[tuple[str, str]] = []
        for item in history_raw:
            if not isinstance(item, dict):
                raise ActivityChatRelayError("Activity chat claim history is invalid")
            sender = item.get("senderType")
            text = item.get("text")
            if sender not in {"participant", "hypha"} or not isinstance(text, str):
                raise ActivityChatRelayError("Activity chat claim history is invalid")
            history.append((sender, text))
        return ActivityChatClaim(
            request_id=request_id,
            discord_user_id=discord_user_id,
            environment=environment,
            stream_id=stream_id,
            privacy_alias=privacy_alias if isinstance(privacy_alias, str) else None,
            history=tuple(history),
            message=message,
            albuquerque_mode=albuquerque_mode,
        )

    async def complete(
        self,
        claim: ActivityChatClaim,
        *,
        audio: bytes | None,
        transcript_text: str,
    ) -> None:
        failed = audio is None
        payload: dict[str, object] = {
            "failed": failed,
            "environment": claim.environment,
            "streamId": claim.stream_id,
            "transcriptText": transcript_text,
        }
        if audio is not None:
            payload["audioBase64"] = base64.b64encode(audio).decode("ascii")
        await asyncio.to_thread(
            self._signed_json_request,
            f"/api/hypha/chat/{claim.request_id}/complete",
            payload,
        )

    async def process_once(self) -> bool:
        claim = await self.claim()
        if claim is None:
            return False
        web_player = isinstance(claim.discord_user_id, str)
        metadata = DiscordPrivacyMetadata(
            current_participant=ParticipantIdentity(
                999999999999999999 if web_player else claim.discord_user_id,
                (claim.privacy_alias,) if claim.privacy_alias else (),
            ),
            sensitive_values=(claim.discord_user_id,) if web_player else (),
        )
        try:
            context = await build_v2_chat_context(
                self._runtime,
                player_id=(
                    claim.discord_user_id if web_player
                    else f"discord:{claim.discord_user_id}"
                ),
                player_message=claim.message,
                privacy_metadata=metadata,
                shared_public_only=True,
                shared_history=claim.history,
                environment=claim.environment,
            )
            result = (
                await self._voice_reply.reply(
                    context, text_transform=_transform_albuquerque_reply,
                )
                if claim.albuquerque_mode else await self._voice_reply.reply(context)
            )
            fallback = "Hypha could not render a response."
            await self.complete(
                claim,
                audio=result.clip.audio if result.clip is not None else None,
                transcript_text=result.text or (
                    _transform_albuquerque_reply(fallback)
                    if claim.albuquerque_mode else fallback
                ),
            )
        except Exception:
            failure = "Hypha could not render a response. No game state changed."
            await self.complete(
                claim,
                audio=None,
                transcript_text=(
                    _transform_albuquerque_reply(failure)
                    if claim.albuquerque_mode else failure
                ),
            )
        return True

    async def run(self, stop_event: asyncio.Event) -> None:
        while not stop_event.is_set():
            processed = False
            try:
                processed = await self.process_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                processed = False
            if processed:
                continue
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=self._poll_seconds)
            except TimeoutError:
                pass
